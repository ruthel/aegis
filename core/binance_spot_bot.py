import time
import json
import ccxt
import os
import threading
from queue import Queue
from datetime import datetime
from core.websocket_manager import WebSocketManager
from core.notification_manager import NotificationManager
from core.technical_indicators import SignalGenerator
from core.earn_manager import BinanceEarnManager
from core.balance_manager import BalanceManager
from utils.advanced_risk_manager import AdvancedRiskManager, TrailingStopManager, CorrelationManager
from utils.multi_timeframe_analyzer import MultiTimeframeAnalyzer
from utils.safety_manager import SafetyManager
from utils.stuck_position_manager import StuckPositionManager
from utils.crypto_scorer import CryptoScorer
from utils.decision_display import DecisionDisplay
import logging

# Import des mixins
from core.bot_trading import TradingMixin
from core.bot_strategies import StrategiesMixin
from core.bot_sync import SyncMixin
from core.bot_analysis import AnalysisMixin
from core.bot_display import DisplayMixin

class BinanceSpotBot(TradingMixin, StrategiesMixin, SyncMixin, AnalysisMixin, DisplayMixin):
    """Bot de trading Binance Spot avec stratégies avancées"""
    
    def __init__(self, api_key, api_secret, testnet=True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        
        # Affichage simplifié
        self.max_retries = 3
        self.retry_delay = 5
        self.state_file = 'data/bot_state.json'
        self.min_amounts = {}
        self.price_cache = {}
        self.cache_timeout = 0.5
        
        # Configuration
        self.paper_trading = os.getenv('PAPER_TRADING', 'True') == 'True'
        self.paper_balance = float(os.getenv('PAPER_BALANCE', '1000'))
        self.max_daily_loss = float(os.getenv('MAX_DAILY_LOSS', '100'))
        self.stop_loss_percent = float(os.getenv('STOP_LOSS_PERCENT', '5'))
        self.notify_trades = os.getenv('NOTIFY_TRADES', 'True') == 'True'
        self.save_logs = os.getenv('SAVE_LOGS', 'True') == 'True'
        
        # Frais
        self.trading_fee = float(os.getenv('TRADING_FEE_PERCENT', '0.1')) / 100
        self.min_profit_threshold = float(os.getenv('MIN_PROFIT_THRESHOLD', '0.3')) / 100
        
        # Stats
        self.daily_pnl = 0
        self.total_trades = 0
        self.winning_trades = 0
        
        self.setup_logging()
        
        # Notifications
        if self.notify_trades:
            self.notifier = NotificationManager()
            self.notifier.set_bot(self)
            self.status_interval = int(os.getenv('TELEGRAM_STATUS_INTERVAL', '300'))
            self.last_status_time = 0
        
        # WebSocket
        self.websocket = WebSocketManager()
        self.websocket.set_bot_callback(self.on_realtime_signal)
        self.websocket.set_balance_callback(self.on_balance_update)
        self.websocket.start()
        
        # Trading temps réel
        self.realtime_trading = os.getenv('REALTIME_TRADING', 'False') == 'True'
        self.last_analysis = {}
        
        # Ordres
        self.order_type = os.getenv('ORDER_TYPE', 'adaptive')
        self.pending_orders = {}
        self.order_timeout = 86400
        
        # Générateur signaux
        self.signal_generator = SignalGenerator()
        
        # Gestionnaires
        self.risk_manager = AdvancedRiskManager()
        self.trailing_stop = TrailingStopManager(float(os.getenv('TRAILING_STOP_PERCENT', '3')))
        self.correlation_manager = CorrelationManager()
        self.multi_tf_analyzer = MultiTimeframeAnalyzer()
        self.safety_manager = SafetyManager(
            max_daily_trades=int(os.getenv('MAX_DAILY_TRADES', '50')),
            max_daily_loss=self.max_daily_loss,
            emergency_stop_loss=float(os.getenv('EMERGENCY_STOP_LOSS', '500'))
        )
        self.earn_manager = BinanceEarnManager(self)
        self.stuck_manager = StuckPositionManager(
            max_loss_percent=float(os.getenv('MAX_STUCK_LOSS', '15')),
            stuck_threshold_hours=int(os.getenv('STUCK_THRESHOLD_HOURS', '24'))
        )
        self.crypto_scorer = CryptoScorer(
            min_score=int(os.getenv('MIN_CRYPTO_SCORE', '50')),
            max_tradeable=int(os.getenv('MAX_TRADEABLE_CRYPTOS', '2'))
        )
        self.decision_display = DecisionDisplay(
            show_decisions=os.getenv('SHOW_DECISIONS', 'True') == 'True',
            show_details=os.getenv('SHOW_DECISION_DETAILS', 'True') == 'True'
        )
        
        # Cache
        self.analysis_cache = {}
        self.analysis_cache_timeout = 5
        self.price_change_threshold = 0.001
        
        # Gestionnaire de balance centralisé
        self.balance_manager = BalanceManager(self)
        
        os.makedirs('data', exist_ok=True)
        
        # Affichage async
        self.display_queue = Queue(maxsize=100)
        
        if not self.paper_trading:
            self.connect()
        self.load_state()
        
        # Initialiser l'affichage async
        self.start_async_display()
        
        # Sync initiale
        if not self.paper_trading:
            try:
                # Vérifier et transférer les fonds de financement
                self.balance_manager.auto_transfer_funding_to_spot()
                
                self.sync_positions_from_exchange()
                self.earn_manager.sync_earn_positions_from_api()
                self.websocket.start_user_data_stream(self)
            except Exception as e:
                print(f"⚠️ Erreur sync initiale: {e}")
    

    
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
                self.connect()
                self.exchange.fetch_balance()
                return True
            except Exception as e:
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                else:
                    print(f"❌ Échec reconnexion: {e}")
        return False
    
    def safe_request(self, func, *args, **kwargs):
        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if attempt < self.max_retries - 1:
                    if self.reconnect():
                        continue
                    time.sleep(self.retry_delay)
                else:
                    print(f"❌ Erreur API: {e}")
                    raise e
    
    def load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    self.state = json.load(f)
            except Exception as e:
                print(f"⚠️ Erreur chargement: {e}")
                self.state = {'positions': [], 'last_update': None}
        else:
            self.state = {'positions': [], 'last_update': None}
    
    def save_state(self):
        try:
            if 'positions' in self.state:
                seen_orders = set()
                unique_positions = []
                for pos in self.state['positions']:
                    order_id = pos.get('order_id')
                    if order_id and order_id in seen_orders:
                        continue
                    if order_id:
                        seen_orders.add(order_id)
                    unique_positions.append(pos)
                unique_positions.sort(key=lambda x: x.get('timestamp', ''))
                self.state['positions'] = unique_positions
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
                    min_costs = {'BTC/USDT': 5, 'ETH/USDT': 10, 'SOL/USDT': 8, 'BNB/USDT': 12}
                    self.min_amounts[symbol] = {'min_amount': 0.001, 'min_cost': min_costs.get(symbol, 10)}
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
                shortage = cost - self.paper_balance
                if self.earn_manager.withdraw_from_flexible(shortage):
                    print(f"💰 Retrait Earn: {shortage:.2f} USDT pour trade")
                    return True
                return False
        else:
            balance = self.balance_manager.get_balance()
            if symbol.endswith('/USDT'):
                available = balance.get('USDT', {}).get('free', 0)
                if cost > available:
                    shortage = cost - available
                    if self.earn_manager.withdraw_from_flexible(shortage):
                        print(f"💰 Retrait Earn: {shortage:.2f} USDT pour trade")
                        return True
                    return False
        return True
    
    def get_price(self, symbol, force_refresh=False):
        cache_key = f"price_{symbol}"
        now = time.time()
        if not force_refresh and self.websocket.is_connected():
            ws_price = self.websocket.get_price(symbol)
            if ws_price is not None:
                self.price_cache[cache_key] = {'price': ws_price, 'timestamp': now}
                return ws_price
        if not force_refresh and cache_key in self.price_cache:
            cached_data = self.price_cache[cache_key]
            cache_age = now - cached_data['timestamp']
            if cache_age < self.cache_timeout:
                return cached_data['price']
            elif cache_age > 5:
                print(f"⚠️ Prix {symbol} obsolète ({cache_age:.1f}s)")
        try:
            if self.paper_trading:
                price = 50000 if 'BTC' in symbol else 3000 if 'ETH' in symbol else 150
            else:
                ticker = self.safe_request(self.exchange.fetch_ticker, symbol)
                price = ticker['last']
            self.price_cache[cache_key] = {'price': price, 'timestamp': now}
            return price
        except Exception as e:
            print(f"Erreur récupération prix {symbol}: {e}")
            if cache_key in self.price_cache:
                return self.price_cache[cache_key]['price']
            raise e
    
    def get_klines(self, symbol, count=50):
        if self.websocket.is_connected():
            klines = self.websocket.get_klines(symbol, count)
            if len(klines) >= count:
                return klines
        try:
            if self.paper_trading:
                klines = []
                base_price = 50000 if 'BTC' in symbol else 3000
                for i in range(count):
                    price = base_price + (i * 10)
                    klines.append({
                        'timestamp': int(time.time() - (count - i) * 60) * 1000,
                        'open': price, 'high': price + 50, 'low': price - 50,
                        'close': price + 25, 'volume': 100
                    })
                return klines
            else:
                ohlcv = self.safe_request(self.exchange.fetch_ohlcv, symbol, '1m', limit=count)
                return [{'timestamp': c[0], 'open': c[1], 'high': c[2], 'low': c[3], 'close': c[4], 'volume': c[5]} for c in ohlcv]
        except Exception as e:
            print(f"Erreur récupération klines {symbol}: {e}")
            return []
    
    def execute_strategy(self, symbol, strategy_type, amount):
        try:
            price = self.get_price(symbol)
            balance = self.balance_manager.get_balance()
            usdt_balance = balance.get('USDT', {}).get('free', 0)
            base_currency = symbol.split('/')[0]
            crypto_balance = balance.get(base_currency, {}).get('free', 0)
            min_limits = self.get_min_amount(symbol)
            min_cost = min_limits['min_cost']
            
            # Utiliser le minimum de la paire au lieu du TRADE_AMOUNT statique
            trade_amount = min_cost
            
            can_buy = usdt_balance >= min_cost
            crypto_value = crypto_balance * price
            can_sell = crypto_value >= min_cost
            if not can_buy and not can_sell:
                return
            if not self.paper_trading:
                ticker = self.safe_request(self.exchange.fetch_ticker, symbol)
                change_24h = ticker.get('percentage') or 0
            else:
                change_24h = 2.5
            analysis = self.get_cached_analysis(symbol, price)
            vol_display = analysis.get('volatility', 2.0)
            self.show_strategy_execution(symbol, price, change_24h, vol_display)
            if strategy_type == 'intelligent':
                self.intelligent_strategy(symbol, trade_amount, price)
            elif strategy_type == 'adaptive':
                self.adaptive_strategy(symbol, trade_amount, price)
            elif strategy_type == 'scalping':
                self.scalping_strategy(symbol, trade_amount, price)
            elif strategy_type == 'dca':
                self.dca_strategy(symbol, trade_amount, price)
        except Exception as e:
            print(f"❌ Erreur stratégie {symbol}: {e}")
    
    def on_balance_update(self, data):
        """Délègue au gestionnaire de balance centralisé"""
        try:
            print(f"⚡ Dépôt/Retrait détecté - Sync instantanée...")
            self.balance_manager.force_balance_sync()
        except Exception as e:
            print(f"⚠️ Erreur sync: {e}")
    
    def force_balance_sync(self):
        """Force la synchronisation des balances"""
        return self.balance_manager.force_balance_sync()
    
    def test_api_connection(self):
        """Test la connexion API et affiche les infos de compte"""
        try:
            print("🔍 Test connexion API...")
            
            # Test 1: Info compte
            account = self.safe_request(self.exchange.fetch_account)
            print(f"✅ Compte connecté: {account.get('info', {}).get('accountType', 'N/A')}")
            
            # Test 2: Balance SPOT
            balance = self.safe_request(self.exchange.fetch_balance)
            usdt_spot = balance.get('USDT', {}).get('free', 0)
            print(f"💰 Balance SPOT USDT: {usdt_spot:.2f}")
            
            # Test 3: Balance FUNDING (financement)
            try:
                funding_balance = self.balance_manager.get_funding_balance()
                usdt_funding = funding_balance.get('USDT', {}).get('free', 0)
                print(f"🏦 Balance FUNDING USDT: {usdt_funding:.2f}")
                
                if usdt_funding > 0.01 and usdt_spot < 1:
                    print(f"⚠️ Fonds détectés en FUNDING ! Transfert recommandé")
            except:
                print("⚠️ Impossible de vérifier le portefeuille de financement")
            
            # Test 4: Permissions
            permissions = account.get('info', {}).get('permissions', [])
            print(f"🔑 Permissions: {', '.join(permissions)}")
            
            return True
            
        except Exception as e:
            print(f"❌ Erreur test API: {e}")
            return False
    
    def on_realtime_signal(self, symbol, price):
        if not self.realtime_trading:
            return
        now = time.time()
        last_time = self.last_analysis.get(symbol, 0)
        if now - last_time < 0.1:
            return
        self.last_analysis[symbol] = now
        try:
            formatted_symbol = f"{symbol[:-4]}/{symbol[-4:]}"
            strategy_type = os.getenv('STRATEGY_TYPE', 'scalping')
            # Utiliser le minimum de la paire
            trade_amount = self.get_min_amount(formatted_symbol)['min_cost']
            if strategy_type == 'intelligent':
                self.realtime_intelligent(formatted_symbol, trade_amount, price)
            elif strategy_type == 'adaptive':
                self.realtime_adaptive(formatted_symbol, trade_amount, price)
            elif strategy_type == 'scalping':
                self.realtime_scalping(formatted_symbol, trade_amount, price)
        except Exception as e:
            print(f"❌ Erreur signal temps réel {symbol}: {e}")
    
    def ensure_trading_balance(self, trade_amount):
        """S'assure qu'il y a assez de fonds pour trader"""
        return self.balance_manager.ensure_trading_balance(trade_amount)
    
    def check_and_recover_stuck_positions(self):
        balance = self.balance_manager.get_balance()
        for pair in os.getenv('TRADING_PAIRS', 'BTCUSDT,ETHUSDT').split(','):
            symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
            base_currency = symbol.split('/')[0]
            current_holding = balance.get(base_currency, {}).get('free', 0)
            if current_holding <= 0.00001:
                continue
            position_value = current_holding * self.get_price(symbol)
            min_trade_value = self.get_min_amount(symbol)['min_cost']
            if position_value < min_trade_value:
                continue
            buy_positions = [p for p in self.state['positions'] if p['symbol'] == symbol and p['side'] == 'buy']
            if not buy_positions:
                continue
            buy_price = self.get_real_buy_price(symbol)
            if not buy_price:
                continue
            buy_time = datetime.fromisoformat(buy_positions[-1]['timestamp']).timestamp()
            current_price = self.get_price(symbol)
            is_stuck, loss_percent = self.stuck_manager.check_stuck_position(symbol, current_price, buy_price, buy_time)
            if is_stuck:
                self.stuck_manager.execute_recovery(self, symbol, current_price)
    
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
        check_interval = int(os.getenv('CHECK_INTERVAL', '60'))
        backtesting = os.getenv('BACKTEST_ENABLED', 'False') == 'True'
        balance = self.balance_manager.get_balance()
        active_positions = 0
        for pair in trading_pairs:
            symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
            base_currency = symbol.split('/')[0]
            free = balance.get(base_currency, {}).get('free', 0)
            locked = balance.get(base_currency, {}).get('used', 0)
            total = free + locked
            if total > 0.00001:
                position_value = total * self.get_price(symbol)
                if position_value >= self.get_min_amount(symbol)['min_cost']:
                    active_positions += 1
        
        self.show_header(trading_pairs, strategy_type, 0, active_positions)
        if backtesting:
            self.run_backtest()
            return
        if self.notify_trades:
            mode = "PAPER" if self.paper_trading else "LIVE"
            self.notifier.notify(f"🤖 Bot démarré - {mode}")
        try:
            while True:
                self.show_performance()
                self.show_spot_balances(trading_pairs)
                self.earn_manager.show_earn_performance()
                self.show_realtime_prices(trading_pairs)
                print()
                # Prévisions de vente
                sell_predictions = []
                for pair in trading_pairs:
                    symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
                    sell_pred = self.predict_next_sell_execution(symbol)
                    if sell_pred:
                        sell_predictions.append((symbol, sell_pred))
                self.show_sell_predictions(sell_predictions)
                
                # Prévisions d'achat
                buy_predictions = []
                for pair in trading_pairs:
                    symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
                    prediction = self.predict_next_buy_opportunity(symbol)
                    crypto = symbol.split('/')[0]
                    if prediction and prediction['status'] in ['READY', 'WAITING']:
                        buy_predictions.append((crypto, prediction))
                self.show_buy_predictions(buy_predictions)
                self.check_and_recover_stuck_positions()
                
                # Vérifier le portefeuille de financement périodiquement
                funding_interval = int(os.getenv('FUNDING_CHECK_INTERVAL', '300'))
                if hasattr(self, 'last_funding_check'):
                    if time.time() - self.last_funding_check > funding_interval:
                        self.balance_manager.auto_transfer_funding_to_spot()
                        self.last_funding_check = time.time()
                else:
                    self.last_funding_check = time.time()
                
                # Vérifier avec le minimum requis
                min_required = min(self.get_min_amount(p if '/' in p else f"{p[:3]}/{p[3:]}")['min_cost'] for p in trading_pairs)
                self.ensure_trading_balance(min_required)
                self.earn_manager.auto_allocate_idle_funds()
                self.sync_positions_from_exchange()
                # Rafraîchir les balances selon configuration
                from config import FORCE_BALANCE_REFRESH
                balance = self.balance_manager.get_balance(force_refresh=FORCE_BALANCE_REFRESH)
                
                # Sync périodique supplémentaire toutes les 30 secondes
                if hasattr(self, 'last_balance_sync'):
                    if time.time() - self.last_balance_sync > 30:
                        balance = self.balance_manager.get_balance(force_refresh=True)
                        self.last_balance_sync = time.time()
                else:
                    self.last_balance_sync = time.time()
                usdt_available = balance.get('USDT', {}).get('free', 0)
                tradable_pairs = []
                for pair in trading_pairs:
                    symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
                    base_currency = symbol.split('/')[0]
                    crypto_free = balance.get(base_currency, {}).get('free', 0)
                    crypto_locked = balance.get(base_currency, {}).get('used', 0)
                    min_cost = self.get_min_amount(symbol)['min_cost']
                    price = self.get_price(symbol)
                    can_buy = usdt_available >= min_cost
                    can_sell = (crypto_free * price) >= min_cost and crypto_locked == 0
                    if can_buy or can_sell:
                        tradable_pairs.append(symbol)

                self.show_tradable_pairs(tradable_pairs, usdt_available)
                if tradable_pairs:
                    for symbol in tradable_pairs:
                        self.execute_strategy(symbol, strategy_type, 0)  # amount sera calculé dynamiquement
                if usdt_available >= min_required:
                    stuck_positions = self.stuck_manager.stuck_positions
                    best_cryptos = self.crypto_scorer.rank_cryptos(self, trading_pairs, stuck_positions)
                    self.show_top_cryptos(best_cryptos)
                    if best_cryptos:
                        for symbol in best_cryptos:
                            if symbol not in tradable_pairs:
                                self.execute_strategy(symbol, strategy_type, 0)  # amount sera calculé dynamiquement
                if self.notify_trades:
                    current_time = time.time()
                    if current_time - self.last_status_time >= self.status_interval:
                        self.notifier.send_status_update()
                        self.last_status_time = current_time
                time.sleep(check_interval)
        except KeyboardInterrupt:
            print("\n🛑 Arrêt du bot...")
            if self.notify_trades:
                self.notifier.notify("🛑 Bot arrêté")
            if hasattr(self, 'websocket'):
                self.websocket.stop()
            self.save_state()
        except Exception as e:
            print(f"\n⚠️ Erreur bot: {e}")
            self.show_debug_commands()
            raise e
