import time
import os
import threading
from collections import deque
from datetime import datetime
from queue import Queue
import websocket
from core.ml_live_logger import MLLiveLogger
from utils.currency import get_trading_pairs, normalize_symbol as normalize_pair

websocket.enableTrace(False)

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
            symbols = get_trading_pairs()
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
        self.last_connected_ts = 0.0
        self.connected_since_ts = 0.0
        self.last_message_ts = 0.0
        self.last_market_data_ts = 0.0
        self.last_heartbeat_ts = 0.0
        self.last_disconnect_ts = 0.0
        self.last_disconnect_reason = None
        self.last_close_code = None
        self._rate_limited_until = 0.0
        self._next_reconnect_ts = 0.0
        self._reconnect_state_lock = threading.Lock()
        self._reconnect_pending = False
        self._reconnect_thread = None
        self._reconnect_history = deque(maxlen=50)
        self.is_ws_connected = False
        self.listen_key = None
        self.exchange_client = None  # Référence au client exchange
        self.tick_counts = {symbol: 0 for symbol in self.symbols}
        self.last_tick_ts = {}
        self.last_analysis_ts = {}
        self.market_meta = {}
        self._last_bad_tick_log = {}
        self.live_logger = MLLiveLogger(data_dir='data', sqlite_file=os.getenv('ML_LIVE_SQLITE_FILE', 'data/aegis_db.sqlite3'))
        self.trading_mode = 'paper' if os.getenv('PAPER_TRADING', 'True').lower() == 'true' else 'live'
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
                now = time.time()
                self._maybe_mark_connection_stable(now)
                self.write_live_status()

                # Kraken peut garder une connexion parfaitement saine avec des
                # heartbeats même quand aucun trade/ticker utile n'arrive. Le
                # watchdog surveille donc TOUT message WebSocket, pas seulement
                # les ticks de marché.
                if self.is_ws_connected:
                    last_activity = float(self.last_message_ts or self.last_connected_ts or 0.0)
                    stale_timeout = max(30.0, float(os.getenv('WS_STALE_TIMEOUT_SECONDS', '120')))
                    age = (now - last_activity) if last_activity > 0 else 0.0
                    if age > stale_timeout:
                        reason = f'watchdog_stale_{age:.0f}s'
                        self.last_disconnect_reason = reason
                        self.last_disconnect_ts = now
                        print(
                            f"⚠️ Watchdog WS: aucun message Kraken depuis {age:.0f}s "
                            f"(seuil {stale_timeout:.0f}s) — reconnexion contrôlée"
                        )
                        self.is_ws_connected = False
                        current_ws = self.ws
                        try:
                            if current_ws:
                                current_ws.close()
                        except Exception:
                            pass
                        # on_close() déclenche normalement la reconnexion. Cet
                        # appel de secours couvre le cas où close() ne rappelle
                        # pas le callback; le verrou empêche les doublons.
                        self._schedule_reconnect(reason)

                time.sleep(max(1.0, float(os.getenv('WS_WATCHDOG_INTERVAL_SECONDS', '5'))))

        _th.Thread(target=_hb, daemon=True).start()

    def _start_worker(self):
        """Démarre le worker thread pour analyses asynchrones"""
        import queue
        def worker():
            while self.running:
                try:
                    symbol, price = self.analysis_queue.get(timeout=1)
                    if hasattr(self, 'bot_callback') and self.bot_callback:
                        self.bot_callback(symbol, price)
                except queue.Empty:
                    pass
                except Exception as e:
                    print(f"⚠️ Erreur worker WebSocket: {e}")
        
        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()
        
    def connect(self):
        """Établit une connexion WebSocket Kraken sans créer de doublon."""
        if not self.running:
            return False
        if self.is_connected():
            return True
        try:
            self._connect_kraken()
            return True
        except Exception as e:
            self.last_disconnect_reason = f'connect_error:{e}'
            self.last_disconnect_ts = time.time()
            print(f"Erreur connexion WebSocket: {e}")
            self._schedule_reconnect('connect_error')
            return False

    def _connect_kraken(self):
        """Connexion WebSocket Kraken"""
        if os.getenv('WS_CONNECTION_DEBUG', 'false').lower() == 'true':
            print(f"WS Kraken: connexion wss://ws.kraken.com avec {self.symbols}")
        url = "wss://ws.kraken.com"

        ws_app = websocket.WebSocketApp(
            url,
            on_message=self.on_message_kraken,
            on_error=self.on_error,
            on_close=self.on_close,
            on_open=self._on_open_kraken
        )
        self.ws = ws_app

        self.ws_thread = threading.Thread(
            target=ws_app.run_forever,
            kwargs={'ping_interval': 30, 'ping_timeout': 10}
        )
        self.ws_thread.daemon = True
        self.ws_thread.start()

    def _on_open_kraken(self, ws):
        """Souscription aux channels Kraken à l'ouverture."""
        import json as std_json
        if ws is not self.ws:
            return
        now = time.time()
        self.is_ws_connected = True
        self.last_connected_ts = now
        self.connected_since_ts = now
        self.last_message_ts = now
        self._next_reconnect_ts = 0.0
        if os.getenv('WS_CONNECTION_DEBUG', 'false').lower() == 'true':
            print(
                f"WS Kraken: connexion ouverte, souscription... "
                f"(tentatives consécutives={self.reconnect_attempts})"
            )

        # Convertir symboles en format Kraken
        pairs = [normalize_pair(s) for s in self.symbols]

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
        """Traite les messages WebSocket Kraken et suit toute activité reçue."""
        if ws is not self.ws:
            return
        now = time.time()
        self.last_message_ts = now
        try:
            data = JSON_LOADS(message)

            # Les heartbeats prouvent que la connexion est vivante même en
            # l'absence de tick de marché.
            if isinstance(data, dict):
                event = data.get('event', '')
                if event == 'heartbeat':
                    self.last_heartbeat_ts = now
                error_message = str(data.get('errorMessage') or '').strip()
                if error_message:
                    self.last_disconnect_reason = f'kraken:{error_message}'
                    if self._looks_rate_limited(error_message):
                        self._rate_limited_until = max(
                            self._rate_limited_until,
                            now + max(30.0, float(os.getenv('WS_RATE_LIMIT_BACKOFF_SECONDS', '120')))
                        )
                if event not in ('heartbeat', 'systemStatus', 'subscriptionStatus'):
                    print(f"[WS SYS] {event} pair={data.get('pair','')} status={data.get('status','')} err={error_message}", flush=True)
                return

            if not isinstance(data, list) or len(data) < 4:
                return

            self.last_market_data_ts = now

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
                high_24h = float(ticker_data['h'][1]) if ticker_data.get('h') and len(ticker_data['h']) > 1 else None
                low_24h = float(ticker_data['l'][1]) if ticker_data.get('l') and len(ticker_data['l']) > 1 else None
                self.market_meta[symbol] = {
                    **self.market_meta.get(symbol, {}),
                    'bid': bid,
                    'ask': ask,
                    'spread': (ask - bid) if bid and ask else None,
                    'spread_percent': ((ask - bid) / self.prices.get(symbol, 1) * 100) if bid and ask else None,
                    'volume_24h': volume_24h,
                    'high_24h': high_24h,
                    'low_24h': low_24h,
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
        """Callback générique à l'ouverture de la connexion."""
        if ws is not self.ws:
            return
        now = time.time()
        self.is_ws_connected = True
        self.last_connected_ts = now
        self.connected_since_ts = now
        self.last_message_ts = now
    
    def _process_price_update(self, symbol, current_price):
        """Logique commune de filtrage et dispatch des prix"""
        symbol = self._normalize_symbol(symbol)
        try:
            current_price = float(current_price)
            meta = self.market_meta.get(symbol, {}) if isinstance(self.market_meta, dict) else {}
            bid = float(meta.get('bid') or 0.0)
            ask = float(meta.get('ask') or 0.0)
            if bid > 0 and ask > 0:
                lower = bid * 0.80
                upper = ask * 1.20
                if current_price < lower or current_price > upper:
                    now_bad = time.time()
                    if now_bad - self._last_bad_tick_log.get(symbol, 0) > 60:
                        self._last_bad_tick_log[symbol] = now_bad
                        print(
                            f"⚠️ Tick WS ignoré {symbol}: prix {current_price:.8f} hors bid/ask "
                            f"({bid:.8f}/{ask:.8f})"
                        )
                    return
        except Exception:
            return
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
        """Écrit une télémétrie WebSocket légère pour le ui."""
        try:
            status = {
                'timestamp': datetime.now().isoformat(),
                'exchange': os.getenv('EXCHANGE', 'kraken').lower(),
                'connected': self.is_connected(),
                'running': self.running,
                'mode': self.trading_mode,
                'trading_mode': self.trading_mode,
                'connection_mode': 'websocket' if self.is_connected() else 'rest_fallback',
                'reconnect_attempts': self.reconnect_attempts,
                'reconnect_pending': self._reconnect_pending,
                'last_message': datetime.fromtimestamp(self.last_message_ts).isoformat() if self.last_message_ts else None,
                'last_message_age_seconds': round(time.time() - self.last_message_ts, 2) if self.last_message_ts else None,
                'last_market_data': datetime.fromtimestamp(self.last_market_data_ts).isoformat() if self.last_market_data_ts else None,
                'last_heartbeat': datetime.fromtimestamp(self.last_heartbeat_ts).isoformat() if self.last_heartbeat_ts else None,
                'last_disconnect_reason': self.last_disconnect_reason,
                'last_close_code': self.last_close_code,
                'next_reconnect_in_seconds': max(0.0, round(self._next_reconnect_ts - time.time(), 2)) if self._next_reconnect_ts else 0.0,
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

            self.live_logger.save_live_status(status)
        except Exception:
            pass
    

    
    def set_bot_callback(self, callback):
        """Définit le callback pour le bot"""
        self.bot_callback = callback
    
    def set_balance_callback(self, callback):
        """Définit le callback pour les changements de solde"""
        self.balance_callback = callback
    
    @staticmethod
    def _looks_rate_limited(message):
        text = str(message or '').lower()
        return any(token in text for token in (
            'rate limit',
            'rate-limit',
            'exceeded msg rate',
            'too many requests',
            'too many connections',
            'connection rate',
        ))

    def _maybe_mark_connection_stable(self, now=None):
        now = float(now or time.time())
        if not self.is_ws_connected or not self.connected_since_ts:
            return False
        stable_seconds = max(30.0, float(os.getenv('WS_STABLE_CONNECTION_SECONDS', '180')))
        if self.reconnect_attempts > 0 and (now - self.connected_since_ts) >= stable_seconds:
            self.reconnect_attempts = 0
            self._reconnect_history.clear()
            self._rate_limited_until = 0.0
            if os.getenv('WS_CONNECTION_DEBUG', 'false').lower() == 'true':
                print(f"✅ WS Kraken stable depuis {stable_seconds:.0f}s — backoff réinitialisé")
            return True
        return False

    def on_error(self, ws, error):
        """Enregistre les erreurs du socket courant sans lancer une seconde reconnexion."""
        if ws is not self.ws:
            return
        message = str(error)
        now = time.time()
        self.last_disconnect_reason = f'error:{message}'
        self.last_disconnect_ts = now
        if self._looks_rate_limited(message):
            self._rate_limited_until = max(
                self._rate_limited_until,
                now + max(30.0, float(os.getenv('WS_RATE_LIMIT_BACKOFF_SECONDS', '120')))
            )
        if 'ping/pong timed out' not in message.lower():
            print(f"WS erreur: {message}")
        self.is_ws_connected = False
        try:
            if ws:
                ws.close()
        except Exception:
            pass
        if self.running:
            self._schedule_reconnect(f'error:{message}')

    def on_close(self, ws, close_status_code, close_msg):
        """Gère une fermeture et délègue à un unique contrôleur de reconnexion."""
        if ws is not self.ws:
            return
        self.is_ws_connected = False
        self.last_disconnect_ts = time.time()
        self.last_close_code = close_status_code
        reason = str(close_msg or self.last_disconnect_reason or 'closed')
        self.last_disconnect_reason = reason
        if self.running:
            self._schedule_reconnect(f'close:{close_status_code}:{reason}')

    def _compute_reconnect_delay(self, now=None):
        now = float(now or time.time())
        base_delay = max(1.0, float(os.getenv('WS_RECONNECT_BASE_SECONDS', '2')))
        max_delay = max(base_delay, float(os.getenv('WS_RECONNECT_MAX_SECONDS', '120')))
        delay = min(max_delay, base_delay * (2 ** max(0, self.reconnect_attempts - 1)))

        window_seconds = max(60.0, float(os.getenv('WS_CIRCUIT_WINDOW_SECONDS', '600')))
        threshold = max(2, int(os.getenv('WS_CIRCUIT_RECONNECTS', '5')))
        recent = [ts for ts in self._reconnect_history if now - ts <= window_seconds]
        if len(recent) >= threshold:
            delay = max(
                delay,
                max(30.0, float(os.getenv('WS_CIRCUIT_BACKOFF_SECONDS', '120')))
            )
        if self._rate_limited_until > now:
            delay = max(delay, self._rate_limited_until - now)
        return min(max_delay, delay) if self._rate_limited_until <= now else delay

    def _schedule_reconnect(self, reason='unknown'):
        if not self.running:
            return False
        with self._reconnect_state_lock:
            if self._reconnect_pending:
                return False
            self._reconnect_pending = True
            self.last_disconnect_reason = str(reason or 'unknown')
            thread = threading.Thread(
                target=self._reconnect_worker,
                args=(self.last_disconnect_reason,),
                daemon=True,
                name='aegis-ws-reconnect',
            )
            self._reconnect_thread = thread
            thread.start()
            return True

    def _reconnect_worker(self, reason):
        connect_timeout = max(3.0, float(os.getenv('WS_CONNECT_TIMEOUT_SECONDS', '15')))
        try:
            while self.running and not self.is_connected():
                self.is_ws_connected = False
                self.reconnect_attempts += 1
                now = time.time()
                self._reconnect_history.append(now)
                delay = self._compute_reconnect_delay(now)
                self._next_reconnect_ts = now + delay

                downtime = now - self.last_connected_ts if self.last_connected_ts else 0.0
                print(
                    f"⚠️ WS reconnexion dans {delay:.0f}s "
                    f"(tentative {self.reconnect_attempts}, raison={reason}, "
                    f"indisponible={downtime:.0f}s)"
                )

                deadline = time.time() + delay
                while self.running and time.time() < deadline:
                    time.sleep(min(0.5, max(0.0, deadline - time.time())))
                if not self.running:
                    return

                # Ne jamais précharger toutes les paires REST à chaque reconnexion:
                # les caches existants restent valides et TradingBot a son fallback REST.
                self.connect()

                open_deadline = time.time() + connect_timeout
                while self.running and time.time() < open_deadline:
                    if self.is_connected():
                        self._next_reconnect_ts = 0.0
                        return
                    thread = getattr(self, 'ws_thread', None)
                    if thread is not None and not thread.is_alive():
                        break
                    time.sleep(0.25)

                reason = 'connect_timeout'
                current_ws = self.ws
                try:
                    if current_ws:
                        current_ws.close()
                except Exception:
                    pass
        finally:
            self._next_reconnect_ts = 0.0
            with self._reconnect_state_lock:
                self._reconnect_pending = False
            # Une fermeture peut se produire exactement entre la dernière
            # vérification et la libération du verrou.
            if self.running and not self.is_connected():
                self._schedule_reconnect(reason)

    def reconnect(self):
        """API historique: planifie désormais une reconnexion sérialisée."""
        return self._schedule_reconnect('manual')
                
    def get_connection_status(self):
        """Retourne le statut actuel de la connexion WebSocket"""
        now = time.time()
        downtime = 0.0
        if not self.is_ws_connected:
            downtime = max(0.0, now - self.last_connected_ts)
        return {
            'connected': self.is_ws_connected,
            'last_connected': self.last_connected_ts,
            'connected_since': self.connected_since_ts,
            'last_message': self.last_message_ts,
            'last_message_age_seconds': round(now - self.last_message_ts, 2) if self.last_message_ts else None,
            'last_market_data': self.last_market_data_ts,
            'last_heartbeat': self.last_heartbeat_ts,
            'last_disconnect_reason': self.last_disconnect_reason,
            'last_close_code': self.last_close_code,
            'reconnect_attempts': self.reconnect_attempts,
            'reconnect_pending': self._reconnect_pending,
            'next_reconnect_in_seconds': max(0.0, round(self._next_reconnect_ts - now, 2)) if self._next_reconnect_ts else 0.0,
            'downtime_seconds': downtime
        }
    
    def get_price(self, symbol):
        """Récupère le prix en temps réel"""
        ws_symbol = symbol.replace('/', '')
        return self.prices.get(ws_symbol, None)
    
    def get_ticker(self, symbol):
        """Récupère le ticker Kraken WebSocket avec bid/ask réels."""
        ws_symbol = self._normalize_symbol(symbol)
        current_price = self.get_price(ws_symbol)
        meta = self.market_meta.get(ws_symbol, {}) if isinstance(self.market_meta, dict) else {}
        if current_price:
            bid = meta.get('bid')
            ask = meta.get('ask')
            return {
                'last': current_price,
                'bid': float(bid) if bid is not None else None,
                'ask': float(ask) if ask is not None else None,
                'spread': meta.get('spread'),
                'spread_percent': meta.get('spread_percent'),
                'percentage': 0,
                'symbol': symbol
            }
        return None
    
    def preload_klines(self, exchange, timeframe='1m', count=100):
        """Charge l'historique REST au demarrage pour eviter d'attendre le WS"""
        if not exchange:
            return
        import os as _os
        from concurrent.futures import ThreadPoolExecutor
        exchange_name = _os.getenv('EXCHANGE', 'kraken').lower()
        
        def fetch_symbol(symbol):
            try:
                ccxt_symbol = normalize_pair(symbol)
                ohlcv = exchange.fetch_ohlcv(ccxt_symbol, timeframe, limit=count)
                candles = [
                    {'timestamp': c[0], 'open': c[1], 'high': c[2], 'low': c[3], 'close': c[4], 'volume': c[5]}
                    for c in ohlcv if c[4]
                ]
                if candles:
                    self.klines[symbol] = deque(candles, maxlen=100)
                    self.prices[symbol] = candles[-1]['close']
            except Exception as e:
                if os.getenv('WS_PRELOAD_DEBUG', 'false').lower() == 'true':
                    print(f'WS preload erreur {symbol}: {e}')
        
        with ThreadPoolExecutor(max_workers=len(self.symbols)) as executor:
            executor.map(fetch_symbol, self.symbols)

    def get_klines(self, symbol, count=50, timeframe='1m'):
        """Récupère uniquement les bougies correspondant réellement au cache WebSocket.

        Le flux Kraken maintient actuellement des OHLC 1 minute. Pour tout autre
        timeframe, retourner une liste vide force TradingBot.get_klines() à utiliser
        Kraken REST avec le timeframe demandé, au lieu de réutiliser par erreur du 1m.
        """
        if str(timeframe or '1m').lower() != '1m':
            return []
        ws_symbol = self._normalize_symbol(symbol)
        klines = list(self.klines.get(ws_symbol, []))
        return klines[-count:] if len(klines) >= count else klines
    
    def is_connected(self):
        """Vérifie transport + fraîcheur générale du flux WebSocket."""
        ws_thread_alive = getattr(self, 'ws_thread', None) and self.ws_thread.is_alive()
        base_connected = bool(
            self.running and self.is_ws_connected and self.ws is not None and ws_thread_alive
        )
        if not base_connected:
            return False
        last_message = float(getattr(self, 'last_message_ts', 0.0) or 0.0)
        if last_message > 0:
            stale_timeout = max(30.0, float(os.getenv('WS_STALE_TIMEOUT_SECONDS', '120')))
            if time.time() - last_message > stale_timeout:
                return False
        return True
    
    def stop(self):
        """Arrête la connexion WebSocket"""
        self.running = False
        self.write_live_status()
        if self.ws:
            self.ws.close()
        if self.ws_user:
            self.ws_user.close()
        if getattr(self, 'live_logger', None):
            self.live_logger.close()
