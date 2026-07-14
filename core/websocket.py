import time
import os
import threading
from collections import deque
from datetime import datetime
from queue import Queue
import websocket

try:
    import orjson as json
    JSON_LOADS = lambda x: json.loads(x)
    JSON_DUMPS = lambda x: json.dumps(x)
except ImportError:
    import json
    JSON_LOADS = json.loads
    JSON_DUMPS = lambda x: json.dumps(x).encode('utf-8')


class WebSocketManager:
    def __init__(self, symbols=None):
        if symbols is None:
            symbols = os.getenv('TRADING_PAIRS', 'BTCUSD,ETHUSD,SOLUSD').split(',')
        self.symbols = [self._normalize_symbol(symbol) for symbol in symbols if symbol.strip()]
        self.prices = {}
        self.last_prices = {}
        self.last_analysis_count = {symbol: 0 for symbol in self.symbols}
        self.klines = {symbol: deque(maxlen=100) for symbol in self.symbols}
        self.ws = None
        self.ws_user = None
        self.running = False
        self.reconnect_attempts = 0
        self.max_reconnect = 5
        self.balance_callback = None
        self.listen_key = None
        self.exchange_client = None  # Référence au client exchange
        self.tick_counts = {symbol: 0 for symbol in self.symbols}
        self.last_tick_ts = {}
        self.last_analysis_ts = {}
        self.market_meta = {}
        self.live_status_file = os.getenv('LIVE_STATUS_FILE', 'data/live_status.json')
        self.live_status_interval = float(os.getenv('LIVE_STATUS_INTERVAL_SECONDS', '1'))
        self._last_live_status_write = 0
        
        # Queue asynchrone pour callbacks non-bloquants
        self.analysis_queue = Queue(maxsize=100)
        self.worker_thread = None
        
        # Pré-allocation mémoire pour candles
        self._candle_template = {
            'timestamp': 0, 'open': 0.0, 'high': 0.0,
            'low': 0.0, 'close': 0.0, 'volume': 0.0
        }

    def _normalize_symbol(self, symbol):
        return str(symbol).strip().replace('/', '').upper()

    def set_exchange_client(self, client):
        """Configure le client exchange pour adapter le WebSocket"""
        self.exchange_client = client
        
    def start(self):
        """Démarre la connexion WebSocket"""
        self.running = True
        self._start_worker()
        self._start_heartbeat()
        self.connect()

    def _start_heartbeat(self):
        import threading as _th
        def _hb():
            while self.running:
                self.write_live_status()
                time.sleep(1)
        _th.Thread(target=_hb, daemon=True).start()

    def _start_worker(self):
        """Démarre le worker thread pour analyses asynchrones"""
        def worker():
            while self.running:
                try:
                    symbol, price = self.analysis_queue.get(timeout=1)
                    if hasattr(self, 'bot_callback') and self.bot_callback:
                        self.bot_callback(symbol, price)
                except:
                    pass
        
        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()
        
    def connect(self):
        """Établit la connexion WebSocket selon l'exchange configuré"""
        try:
            exchange_name = os.getenv('EXCHANGE', 'binance').lower()

            if exchange_name == 'kraken':
                self._connect_kraken()
            else:
                self._connect_binance()

        except Exception as e:
            print(f"Erreur connexion WebSocket: {e}")
            self.reconnect()

    def _connect_binance(self):
        """Connexion WebSocket Binance"""
        streams = [f"{symbol.lower()}@kline_1m" for symbol in self.symbols]
        url = f"wss://stream.binance.com:9443/ws/{'/'.join(streams)}"

        self.ws = websocket.WebSocketApp(
            url,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
            on_open=self.on_open
        )

        self.ws_thread = threading.Thread(target=self.ws.run_forever)
        self.ws_thread.daemon = True
        self.ws_thread.start()

    def _connect_kraken(self):
        """Connexion WebSocket Kraken"""
        print(f"WS Kraken: connexion wss://ws.kraken.com avec {self.symbols}")
        url = "wss://ws.kraken.com"

        self.ws = websocket.WebSocketApp(
            url,
            on_message=self.on_message_kraken,
            on_error=self.on_error,
            on_close=self.on_close,
            on_open=self._on_open_kraken
        )

        self.ws_thread = threading.Thread(
            target=self.ws.run_forever,
            kwargs={'ping_interval': 30, 'ping_timeout': 10}
        )
        self.ws_thread.daemon = True
        self.ws_thread.start()

    def _on_open_kraken(self, ws):
        """Souscription aux channels Kraken à l'ouverture"""
        import json as std_json
        self.reconnect_attempts = 0
        print("WS Kraken: connexion ouverte, souscription...")

        # Convertir symboles en format Kraken
        pairs = []
        for s in self.symbols:
            base = s.replace('USD', '')
            pairs.append(f"{base}/USD")

        # Souscrire au ticker
        subscribe_msg = std_json.dumps({
            "event": "subscribe",
            "pair": pairs,
            "subscription": {"name": "ticker"}
        })
        ws.send(subscribe_msg)

        # Souscrire aux trades (prix temps reel) et OHLC 1min (klines)
        ws.send(std_json.dumps({"event": "subscribe", "pair": pairs, "subscription": {"name": "trade"}}))
        ws.send(std_json.dumps({"event": "subscribe", "pair": pairs, "subscription": {"name": "ohlc", "interval": 1}}))

    def on_message_kraken(self, ws, message):
        """Traite les messages WebSocket Kraken"""
        try:
            data = JSON_LOADS(message)

            # Ignorer les messages système
            if isinstance(data, dict):
                event = data.get('event', '')
                if event not in ('heartbeat', 'systemStatus', 'subscriptionStatus'):
                    print(f"[WS SYS] {event} pair={data.get('pair','')} status={data.get('status','')} err={data.get('errorMessage','')}", flush=True)
                return

            if not isinstance(data, list) or len(data) < 4:
                return

            channel = data[-2]
            pair = data[-1]

            # Convertir paire Kraken vers format interne
            symbol = pair.replace('XBT', 'BTC').replace('/', '')
            # Normaliser: BTCUSD reste BTCUSD

            if 'trade' in channel:
                # Chaque trade execute = prix temps reel le plus frais
                for trade in data[1]:
                    current_price = float(trade[0])
                self.prices[symbol] = current_price
                self.market_meta.setdefault(symbol, {})['source'] = 'trade'
                self._process_price_update(symbol, current_price)

            elif 'ticker' in channel:
                ticker_data = data[1]
                bid = float(ticker_data['b'][0]) if ticker_data.get('b') else None
                ask = float(ticker_data['a'][0]) if ticker_data.get('a') else None
                volume_24h = float(ticker_data['v'][1]) if ticker_data.get('v') and len(ticker_data['v']) > 1 else None
                self.market_meta[symbol] = {
                    **self.market_meta.get(symbol, {}),
                    'bid': bid,
                    'ask': ask,
                    'spread': (ask - bid) if bid and ask else None,
                    'spread_percent': ((ask - bid) / self.prices.get(symbol, 1) * 100) if bid and ask else None,
                    'volume_24h': volume_24h,
                }
                # ticker met a jour le prix seulement si pas de trade recus
                if self.market_meta.get(symbol, {}).get('source') != 'trade':
                    current_price = float(ticker_data['c'][0])
                    self.prices[symbol] = current_price
                    self._process_price_update(symbol, current_price)

            elif 'ohlc' in channel:
                ohlc_data = data[1]
                current_price = float(ohlc_data[5])  # close
                # ohlc ne met PAS a jour self.prices (trade/ticker sont plus frais)

                # Stocker kline
                candle = self._candle_template.copy()
                candle.update({
                    'timestamp': int(float(ohlc_data[0]) * 1000),
                    'open': float(ohlc_data[2]),
                    'high': float(ohlc_data[3]),
                    'low': float(ohlc_data[4]),
                    'close': current_price,
                    'volume': float(ohlc_data[7])
                })
                if symbol in self.klines:
                    kl = self.klines[symbol]
                    if kl and kl[-1]['timestamp'] == candle['timestamp']:
                        kl[-1] = candle
                    else:
                        kl.append(candle)
                self.market_meta[symbol] = {
                    **self.market_meta.get(symbol, {}),
                    'candle_open': candle['open'],
                    'candle_high': candle['high'],
                    'candle_low': candle['low'],
                    'candle_volume': candle['volume'],
                    'candle_timestamp': candle['timestamp'],
                }

        except Exception as e:
            print(f"[WS ERROR] {e}", flush=True)
    
    def on_open(self, ws):
        """Callback à l'ouverture de la connexion"""
        self.reconnect_attempts = 0
    
    def on_message(self, ws, message):
        """Traite les messages Binance (optimisé)"""
        try:
            data = JSON_LOADS(message)

            if 'k' in data:
                kline = data['k']
                symbol = kline['s']
                current_price = float(kline['c'])

                self.prices[symbol] = current_price
                self.market_meta[symbol] = {
                    'source': 'kline',
                    'candle_open': float(kline['o']),
                    'candle_high': float(kline['h']),
                    'candle_low': float(kline['l']),
                    'candle_volume': float(kline['v']),
                    'candle_closed': bool(kline['x']),
                    'candle_timestamp': kline['t'],
                }
                self._process_price_update(symbol, current_price)

                # Kline fermée : sauvegarde
                if kline['x']:
                    candle = self._candle_template.copy()
                    candle.update({
                        'timestamp': kline['t'],
                        'open': float(kline['o']),
                        'high': float(kline['h']),
                        'low': float(kline['l']),
                        'close': current_price,
                        'volume': float(kline['v'])
                    })
                    self.klines[symbol].append(candle)

        except:
            pass

    def _process_price_update(self, symbol, current_price):
        """Logique commune de filtrage et dispatch des prix"""
        symbol = self._normalize_symbol(symbol)
        should_analyze = False
        last_price = self.last_prices.get(symbol, 0)
        now = time.time()
        self.tick_counts[symbol] = self.tick_counts.get(symbol, 0) + 1
        self.last_tick_ts[symbol] = now

        if last_price == 0:
            should_analyze = True
        else:
            self.last_analysis_count[symbol] = self.last_analysis_count.get(symbol, 0) + 1
            variation = abs((current_price - last_price) / last_price)
            if variation >= 0.0005 or self.last_analysis_count.get(symbol, 0) >= 10:
                should_analyze = True
                self.last_analysis_count[symbol] = 0

        if should_analyze:
            self.last_prices[symbol] = current_price
            self.last_analysis_ts[symbol] = now
            try:
                self.analysis_queue.put_nowait((symbol, current_price))
            except:
                pass
        self._write_live_status_throttled()

    def _write_live_status_throttled(self):
        now = time.time()
        if now - self._last_live_status_write < self.live_status_interval:
            return
        self._last_live_status_write = now
        self.write_live_status()

    def write_live_status(self):
        """Écrit une télémétrie WebSocket légère pour le dashboard."""
        try:
            status = {
                'timestamp': datetime.now().isoformat(),
                'exchange': os.getenv('EXCHANGE', 'binance').lower(),
                'connected': self.is_connected(),
                'running': self.running,
                'mode': 'websocket' if self.is_connected() else 'rest_fallback',
                'reconnect_attempts': self.reconnect_attempts,
                'queue_size': self.analysis_queue.qsize(),
                'queue_maxsize': self.analysis_queue.maxsize,
                'worker_alive': bool(self.worker_thread and self.worker_thread.is_alive()),
                'ws_thread_alive': bool(getattr(self, 'ws_thread', None) and self.ws_thread.is_alive()),
                'subscribed_symbols': [symbol.replace('/', '') for symbol in self.symbols],
                'symbols': {}
            }
            now = time.time()
            for symbol in sorted(set(self.symbols) | {k for k in self.prices.keys() if not k.endswith('_logged')}):
                ws_symbol = symbol.replace('/', '')
                price = self.prices.get(ws_symbol)
                last_tick = self.last_tick_ts.get(ws_symbol)
                last_analysis = self.last_analysis_ts.get(ws_symbol)
                analysis_price = self.last_prices.get(ws_symbol)
                price_change_since_analysis = None
                if price is not None and analysis_price:
                    price_change_since_analysis = ((price - analysis_price) / analysis_price) * 100
                meta = self.market_meta.get(ws_symbol, {})
                status['symbols'][ws_symbol] = {
                    'price': price,
                    'tick_count': self.tick_counts.get(ws_symbol, 0),
                    'kline_count': len(self.klines.get(ws_symbol, [])),
                    'analysis_trigger_countdown': self.last_analysis_count.get(ws_symbol, 0),
                    'price_change_since_analysis_percent': price_change_since_analysis,
                    'last_tick': datetime.fromtimestamp(last_tick).isoformat() if last_tick else None,
                    'last_tick_age_seconds': round(now - last_tick, 2) if last_tick else None,
                    'last_analysis': datetime.fromtimestamp(last_analysis).isoformat() if last_analysis else None,
                    'last_analysis_age_seconds': round(now - last_analysis, 2) if last_analysis else None,
                    **meta,
                }

            directory = os.path.dirname(self.live_status_file)
            if directory:
                os.makedirs(directory, exist_ok=True)
            temp_file = f"{self.live_status_file}.tmp"
            with open(temp_file, 'wb') as f:
                f.write(JSON_DUMPS(status))
            os.replace(temp_file, self.live_status_file)
        except Exception:
            pass
    

    
    def set_bot_callback(self, callback):
        """Définit le callback pour le bot"""
        self.bot_callback = callback
    
    def set_balance_callback(self, callback):
        """Définit le callback pour les changements de solde"""
        self.balance_callback = callback
    
    def on_error(self, ws, error):
        """Gere les erreurs WebSocket"""
        print(f"WS erreur: {error}")
    
    def on_close(self, ws, close_status_code, close_msg):
        """Gère la fermeture de connexion (silencieux)"""
        if self.running:
            self.reconnect()
    
    def _preload_after_reconnect(self):
        """Recharge les klines apres reconnexion si exchange disponible"""
        if self.exchange_client:
            self.preload_klines(self.exchange_client)

    def reconnect(self):
        """Reconnexion automatique (silencieux)"""
        if self.reconnect_attempts < self.max_reconnect:
            self.reconnect_attempts += 1
            time.sleep(2 ** self.reconnect_attempts)  # Backoff exponentiel
            self.connect()
            self._preload_after_reconnect()
        else:
            print("❌ WebSocket déconnecté - Mode REST")
            self.reconnect_attempts = 0
            time.sleep(30)
            if self.running:
                self.connect()
                self._preload_after_reconnect()
    
    def get_price(self, symbol):
        """Récupère le prix en temps réel"""
        ws_symbol = symbol.replace('/', '')
        return self.prices.get(ws_symbol, None)
    
    def get_ticker(self, symbol):
        """Récupère les données ticker depuis WebSocket"""
        current_price = self.get_price(symbol)
        if current_price:
            return {
                'last': current_price,
                'percentage': 0,
                'symbol': symbol
            }
        return None
    
    def preload_klines(self, exchange, timeframe='1m', count=100):
        """Charge l'historique REST au demarrage pour eviter d'attendre le WS"""
        import os as _os
        exchange_name = _os.getenv('EXCHANGE', 'binance').lower()
        for symbol in self.symbols:
            try:
                # Convertir format interne (BTCUSD) vers format CCXT (BTC/USD)
                # BTCUSD->BTC/USD, ETHUSD->ETH/USD (enlever suffixe USD)
                if symbol.endswith('USD'):
                    base = symbol[:-3]
                else:
                    base = symbol
                ccxt_symbol = f'{base}/USD'
                ohlcv = exchange.fetch_ohlcv(ccxt_symbol, timeframe, limit=count)
                candles = [
                    {'timestamp': c[0], 'open': c[1], 'high': c[2], 'low': c[3], 'close': c[4], 'volume': c[5]}
                    for c in ohlcv if c[4]
                ]
                if candles:
                    self.klines[symbol] = deque(candles, maxlen=100)
                    self.prices[symbol] = candles[-1]['close']
                    print(f'WS preload: {symbol} {len(candles)} bougies @ {candles[-1]["close"]}')
            except Exception as e:
                print(f'WS preload erreur {symbol}: {e}')

    def get_klines(self, symbol, count=50):
        """Récupère les dernières bougies"""
        ws_symbol = symbol.replace('/', '')
        klines = list(self.klines.get(ws_symbol, []))
        return klines[-count:] if len(klines) >= count else klines
    
    def is_connected(self):
        """Vérifie si WebSocket est connecté"""
        ws_thread_alive = getattr(self, 'ws_thread', None) and self.ws_thread.is_alive()
        return bool(self.running and self.ws is not None and ws_thread_alive)
    
    def stop(self):
        """Arrête la connexion WebSocket"""
        self.running = False
        self.write_live_status()
        if self.ws:
            self.ws.close()
        if self.ws_user:
            self.ws_user.close()
