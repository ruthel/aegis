import time
import json
import ccxt
import os
from datetime import datetime, timedelta
from websocket_manager import WebSocketManager
from notification_manager import NotificationManager
import logging

class BinanceSpotBot:
    def __init__(self, api_key, api_secret, testnet=True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.max_retries = 3
        self.retry_delay = 5
        self.state_file = 'bot_state.json'
        self.min_amounts = {}
        self.price_cache = {}
        self.cache_timeout = 2
        
        # Configuration depuis .env
        self.paper_trading = os.getenv('PAPER_TRADING', 'True') == 'True'
        self.paper_balance = float(os.getenv('PAPER_BALANCE', '1000'))
        self.max_daily_loss = float(os.getenv('MAX_DAILY_LOSS', '100'))
        self.stop_loss_percent = float(os.getenv('STOP_LOSS_PERCENT', '5'))
        self.notify_trades = os.getenv('NOTIFY_TRADES', 'True') == 'True'
        self.save_logs = os.getenv('SAVE_LOGS', 'True') == 'True'
        
        # Statistiques
        self.daily_pnl = 0
        self.total_trades = 0
        self.winning_trades = 0
        
        # Logging
        self.setup_logging()
        
        # Notifications
        if self.notify_trades:
            self.notifier = NotificationManager()
        
        # WebSocket
        self.websocket = WebSocketManager()
        self.websocket.start()
        
        if not self.paper_trading:
            self.connect()
        self.load_state()
    
    def setup_logging(self):
        log_level = os.getenv('LOG_LEVEL', 'INFO')
        logging.basicConfig(
            level=getattr(logging, log_level),
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler('bot.log') if self.save_logs else logging.NullHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    @property
    def client(self):
        return self.exchange
    
    def connect(self):
        self.exchange = ccxt.binance({
            'apiKey': self.api_key,
            'secret': self.api_secret,
            'sandbox': self.testnet,
            'enableRateLimit': True,
        })
    
    def reconnect(self):
        for attempt in range(self.max_retries):
            try:
                print(f"Tentative de reconnexion {attempt + 1}/{self.max_retries}...")
                self.connect()
                self.exchange.fetch_balance()
                print("✅ Reconnexion réussie")
                return True
            except Exception as e:
                print(f"❌ Échec reconnexion: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
        return False
    
    def safe_request(self, func, *args, **kwargs):
        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                print(f"Erreur API (tentative {attempt + 1}): {e}")
                if attempt < self.max_retries - 1:
                    if self.reconnect():
                        continue
                    time.sleep(self.retry_delay)
                else:
                    raise e
    
    def load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    self.state = json.load(f)
                print(f"✅ État chargé: {len(self.state.get('positions', []))} positions")
            except Exception as e:
                print(f"⚠️ Erreur chargement état: {e}")
                self.state = {'positions': [], 'last_update': None}
        else:
            self.state = {'positions': [], 'last_update': None}
    
    def save_state(self):
        try:
            self.state['last_update'] = datetime.now().isoformat()
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            print(f"⚠️ Erreur sauvegarde état: {e}")
    
    def get_min_amount(self, symbol):
        if symbol not in self.min_amounts:
            try:
                if not self.paper_trading:
                    self.safe_request(self.exchange.load_markets)
                    market = self.exchange.markets[symbol]
                    self.min_amounts[symbol] = {
                        'min_amount': market['limits']['amount']['min'],
                        'min_cost': market['limits']['cost']['min']
                    }
                else:
                    self.min_amounts[symbol] = {'min_amount': 0.001, 'min_cost': 10}
            except Exception as e:
                print(f"⚠️ Impossible de récupérer les limites pour {symbol}: {e}")
                self.min_amounts[symbol] = {'min_amount': 0.001, 'min_cost': 10}
        return self.min_amounts[symbol]
    
    def validate_order(self, symbol, amount, price=None):
        limits = self.get_min_amount(symbol)
        
        if amount < limits['min_amount']:
            print(f"❌ Montant trop petit: {amount} < {limits['min_amount']}")
            return False
        
        cost = amount * (price or self.get_price(symbol))
        if cost < limits['min_cost']:
            print(f"❌ Coût trop petit: ${cost} < ${limits['min_cost']}")
            return False
        
        if self.paper_trading:
            if cost > self.paper_balance:
                print(f"❌ Solde virtuel insuffisant: ${cost} > ${self.paper_balance}")
                return False
        else:
            balance = self.get_balance()
            if symbol.endswith('/USDT'):
                available = balance.get('USDT', {}).get('free', 0)
                if cost > available:
                    print(f"❌ Solde insuffisant: ${cost} > ${available}")
                    return False
        
        return True
        
    def get_balance(self):
        if self.paper_trading:
            return {'USDT': {'free': self.paper_balance}}
        return self.safe_request(self.exchange.fetch_balance)
    
    def get_price(self, symbol):
        if self.websocket.is_connected():
            ws_price = self.websocket.get_price(symbol)
            if ws_price is not None:
                return ws_price
        
        cache_key = f"price_{symbol}"
        now = time.time()
        
        if cache_key in self.price_cache:
            cached_data = self.price_cache[cache_key]
            if now - cached_data['timestamp'] < self.cache_timeout:
                return cached_data['price']
        
        try:
            if self.paper_trading:
                # Prix simulé pour paper trading
                price = 50000 if 'BTC' in symbol else 3000 if 'ETH' in symbol else 150
            else:
                ticker = self.safe_request(self.exchange.fetch_ticker, symbol)
                price = ticker['last']
            
            self.price_cache[cache_key] = {
                'price': price,
                'timestamp': now
            }
            
            return price
        except Exception as e:
            print(f"Erreur récupération prix {symbol}: {e}")
            if cache_key in self.price_cache:
                return self.price_cache[cache_key]['price']
            raise e
    
    def buy_market(self, symbol, amount):
        if not self.validate_order(symbol, amount):
            return None
        
        price = self.get_price(symbol)
        cost = amount * price
        
        if cost > self.max_daily_loss:
            print(f"❌ Dépassement limite quotidienne: {cost} > {self.max_daily_loss}")
            return None
        
        try:
            if self.paper_trading:
                self.paper_balance -= cost
                order = {
                    'id': f'paper_{int(time.time())}',
                    'price': price,
                    'amount': amount,
                    'cost': cost
                }
                print(f"🧪 PAPER - Achat simulé: {amount:.6f} {symbol} à {price:.6f}")
            else:
                order = self.safe_request(self.exchange.create_market_buy_order, symbol, amount)
                print(f"✅ Achat exécuté: {amount:.6f} {symbol}")
            
            if order:
                position = {
                    'symbol': symbol,
                    'side': 'buy',
                    'amount': amount,
                    'price': order.get('price', price),
                    'timestamp': datetime.now().isoformat(),
                    'order_id': order.get('id'),
                    'paper': self.paper_trading
                }
                self.state['positions'].append(position)
                self.save_state()
                self.total_trades += 1
                
                if self.notify_trades:
                    mode = "PAPER" if self.paper_trading else "LIVE"
                    self.notifier.send_message(f"🟢 {mode} ACHAT: {amount:.6f} {symbol} à {price:.6f}")
            
            return order
        except Exception as e:
            print(f"Erreur achat: {e}")
            self.logger.error(f"Erreur achat {symbol}: {e}")
            return None
    
    def sell_market(self, symbol, amount):
        price = self.get_price(symbol)
        
        try:
            if self.paper_trading:
                revenue = amount * price
                self.paper_balance += revenue
                order = {
                    'id': f'paper_{int(time.time())}',
                    'price': price,
                    'amount': amount,
                    'cost': revenue
                }
                print(f"🧪 PAPER - Vente simulée: {amount:.6f} {symbol} à {price:.6f}")
            else:
                balance = self.get_balance()
                base_currency = symbol.split('/')[0]
                available = balance.get(base_currency, {}).get('free', 0)
                
                if amount > available:
                    print(f"❌ Pas assez de {base_currency}: {amount} > {available}")
                    return None
                
                order = self.safe_request(self.exchange.create_market_sell_order, symbol, amount)
                print(f"✅ Vente exécutée: {amount:.6f} {symbol}")
            
            if order:
                position = {
                    'symbol': symbol,
                    'side': 'sell',
                    'amount': amount,
                    'price': order.get('price', price),
                    'timestamp': datetime.now().isoformat(),
                    'order_id': order.get('id'),
                    'paper': self.paper_trading
                }
                self.state['positions'].append(position)
                self.save_state()
                self.total_trades += 1
                
                self.calculate_pnl(symbol, 'sell', amount, price)
                
                if self.notify_trades:
                    mode = "PAPER" if self.paper_trading else "LIVE"
                    self.notifier.send_message(f"🔴 {mode} VENTE: {amount:.6f} {symbol} à {price:.6f}")
            
            return order
        except Exception as e:
            print(f"Erreur vente: {e}")
            self.logger.error(f"Erreur vente {symbol}: {e}")
            return None
    
    def get_klines(self, symbol, count=50):
        if self.websocket.is_connected():
            klines = self.websocket.get_klines(symbol, count)
            if len(klines) >= count:
                return klines
        
        try:
            if self.paper_trading:
                # Données simulées pour paper trading
                klines = []
                base_price = 50000 if 'BTC' in symbol else 3000
                for i in range(count):
                    price = base_price + (i * 10)
                    klines.append({
                        'timestamp': int(time.time() - (count - i) * 60) * 1000,
                        'open': price,
                        'high': price + 50,
                        'low': price - 50,
                        'close': price + 25,
                        'volume': 100
                    })
                return klines
            else:
                ohlcv = self.safe_request(self.exchange.fetch_ohlcv, symbol, '1m', limit=count)
                klines = []
                for candle in ohlcv:
                    klines.append({
                        'timestamp': candle[0],
                        'open': candle[1],
                        'high': candle[2],
                        'low': candle[3],
                        'close': candle[4],
                        'volume': candle[5]
                    })
                return klines
        except Exception as e:
            print(f"Erreur récupération klines {symbol}: {e}")
            return []
    
    def execute_strategy(self, symbol, strategy_type, amount):
        try:
            price = self.get_price(symbol)
            
            if not self.paper_trading:
                ticker = self.safe_request(self.exchange.fetch_ticker, symbol)
                change_24h = ticker.get('percentage') or 0
                volume_24h = ticker.get('quoteVolume') or 0
                high_24h = ticker.get('high') or price
                low_24h = ticker.get('low') or price
            else:
                change_24h = 2.5
                volume_24h = 1000000
                high_24h = price * 1.05
                low_24h = price * 0.95
            
            balance = self.get_balance()
            usdt_balance = balance.get('USDT', {}).get('free', 0)
            
            print(f"\n═══ {symbol} ═══")
            print(f"💰 Prix: {price:.6f} USDT")
            print(f"📈 24h: {change_24h:+.2f}% | H: {high_24h:.6f} | L: {low_24h:.6f}")
            print(f"📊 Volume: {volume_24h:,.0f} USDT")
            print(f"💳 Solde: {usdt_balance:.2f} USDT")
            
            if strategy_type == 'scalping':
                self.scalping_strategy(symbol, amount, price)
            elif strategy_type == 'dca':
                self.dca_strategy(symbol, amount, price)
            
        except Exception as e:
            print(f"❌ Erreur stratégie {symbol}: {e}")
    
    def scalping_strategy(self, symbol, amount, current_price):
        klines = self.get_klines(symbol, 20)
        if len(klines) < 20:
            print("⚠️ Pas assez de données historiques")
            return
        
        closes = [k['close'] for k in klines[-14:]]
        gains = [max(0, closes[i] - closes[i-1]) for i in range(1, len(closes))]
        losses = [max(0, closes[i-1] - closes[i]) for i in range(1, len(closes))]
        
        avg_gain = sum(gains) / len(gains)
        avg_loss = sum(losses) / len(losses)
        
        if avg_loss == 0:
            print("⚠️ RSI non calculable")
            return
        
        rsi = 100 - (100 / (1 + avg_gain / avg_loss))
        
        print(f"📉 RSI: {rsi:.1f} | Tendance: {'SURVENTE' if rsi < 30 else 'SURACHAT' if rsi > 70 else 'NEUTRE'}")
        
        if rsi < 30:
            trade_amount = amount / current_price
            print(f"🟢 SIGNAL ACHAT - Montant: {trade_amount:.6f} {symbol.split('/')[0]}")
            result = self.buy_market(symbol, trade_amount)
            if result:
                print(f"✅ Ordre exécuté: {result.get('id', 'N/A')}")
        
        elif rsi > 70:
            base_currency = symbol.split('/')[0]
            balance = self.get_balance()
            available = balance.get(base_currency, {}).get('free', 0)
            if available > 0:
                print(f"🔴 SIGNAL VENTE - Montant: {available:.6f} {base_currency}")
                result = self.sell_market(symbol, available)
                if result:
                    print(f"✅ Ordre exécuté: {result.get('id', 'N/A')}")
            else:
                print("⚠️ Aucune position à vendre")
        else:
            print("🔄 Aucun signal - Attente")
    
    def dca_strategy(self, symbol, amount, current_price):
        trade_amount = amount / current_price
        print(f"🔄 DCA - Achat systématique: {trade_amount:.6f} {symbol.split('/')[0]}")
        print(f"💵 Coût: {amount:.2f} USDT")
        
        result = self.buy_market(symbol, trade_amount)
        if result:
            print(f"✅ DCA exécuté: {result.get('id', 'N/A')}")
        else:
            print("❌ Échec DCA")
    
    def calculate_pnl(self, symbol, side, amount, price):
        if side == 'sell':
            buy_positions = [p for p in self.state['positions'] 
                           if p['symbol'] == symbol and p['side'] == 'buy']
            if buy_positions:
                avg_buy_price = sum(p['price'] for p in buy_positions) / len(buy_positions)
                pnl = (price - avg_buy_price) * amount
                self.daily_pnl += pnl
                if pnl > 0:
                    self.winning_trades += 1
                print(f"💰 P&L: {pnl:+.2f} USDT")
    
    def show_performance(self):
        if os.getenv('SHOW_PERFORMANCE', 'True') == 'True':
            win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0
            print(f"\n📊 PERFORMANCE")
            print(f"💰 P&L Journalier: {self.daily_pnl:+.2f} USDT")
            print(f"📈 Trades: {self.total_trades} | Gagnants: {win_rate:.1f}%")
            if self.paper_trading:
                print(f"🧪 Solde virtuel: {self.paper_balance:.2f} USDT")
    
    def run_backtest(self):
        days = int(os.getenv('BACKTEST_DAYS', '30'))
        symbol = os.getenv('BACKTEST_SYMBOL', 'BTCUSDT')
        
        print(f"🔄 Backtest sur {days} jours - {symbol}")
        print("⚠️ Fonctionnalité en développement")
        
        start_balance = 1000
        current_balance = start_balance
        trades = 0
        
        for day in range(days):
            if day % 3 == 0:
                trades += 1
                profit = (0.5 - 1) * 10
                current_balance += profit
        
        total_return = ((current_balance - start_balance) / start_balance) * 100
        print(f"\n📊 RÉSULTATS BACKTEST")
        print(f"💰 Balance finale: {current_balance:.2f} USDT")
        print(f"📈 Rendement: {total_return:+.2f}%")
        print(f"🔄 Trades: {trades}")
    
    def run(self):
        trading_pairs = os.getenv('TRADING_PAIRS', 'BTCUSDT,ETHUSDT').split(',')
        strategy_type = os.getenv('STRATEGY_TYPE', 'scalping')
        trade_amount = float(os.getenv('TRADE_AMOUNT', '10'))
        check_interval = int(os.getenv('CHECK_INTERVAL', '60'))
        backtesting = os.getenv('BACKTEST_ENABLED', 'False') == 'True'
        
        mode = "PAPER TRADING" if self.paper_trading else "LIVE TRADING"
        print(f"🤖 Bot démarré - {strategy_type.upper()} - {mode}")
        print(f"📊 Paires: {', '.join(trading_pairs)}")
        print(f"💰 Montant: {trade_amount} USDT")
        if self.paper_trading:
            print(f"🧪 Solde virtuel: {self.paper_balance} USDT")
        print("🛑 Appuyez sur Ctrl+C pour arrêter")
        
        if backtesting:
            self.run_backtest()
            return
        
        if self.notify_trades:
            self.notifier.send_message(f"🤖 Bot démarré - {mode}")
        
        try:
            while True:
                self.show_performance()
                
                for pair in trading_pairs:
                    symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
                    self.execute_strategy(symbol, strategy_type, trade_amount)
                
                time.sleep(check_interval)
                
        except KeyboardInterrupt:
            print("\n🛑 Arrêt du bot...")
            if self.notify_trades:
                self.notifier.send_message("🛑 Bot arrêté")
            if hasattr(self, 'websocket'):
                self.websocket.stop()
            self.save_state()