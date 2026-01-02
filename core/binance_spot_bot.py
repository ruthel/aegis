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
from utils.flash_crash_detector import FlashCrashDetector
from utils.macro_event_monitor import MacroEventMonitor
from utils.contagion_detector import ContagionDetector
from utils.multi_exchange_fallback import MultiExchangeFallback
from utils.manipulation_detector import ManipulationDetector
from utils.news_monitor import NewsMonitor
from utils.multi_timeframe_analyzer import MultiTimeframeAnalyzer
from utils.safety_manager import SafetyManager
from utils.stuck_position_manager import StuckPositionManager
from utils.crypto_scorer import CryptoScorer
from utils.decision_display import DecisionDisplay
from utils.support_resistance_analyzer import SupportResistanceAnalyzer
from utils.stablecoin_monitor import StablecoinMonitor
from utils.pattern_recognition import PatternRecognition
from utils.slippage_calculator import SlippageCalculator
from utils.liquidity_checker import LiquidityChecker
from utils.volatility_calculator import VolatilityCalculator
from utils.market_calculator import MarketCalculator
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
        
        # Trading temps réel (TOUJOURS activé par défaut)
        self.realtime_trading = True
        self.last_analysis = {}
        
        # Détection tendance cumulative
        self.cumulative_tracker = {}  # {symbol: {'direction': 1/-1, 'count': 0, 'start_price': 0}}
        
        # Ordres
        self.pending_orders = {}
        self.order_timeout = 86400
        
        # Générateur signaux
        self.signal_generator = SignalGenerator()
        
        # Gestionnaires (nommage cohérent)
        self.advanced_risk_manager = AdvancedRiskManager()
        self.trailing_stop_manager = TrailingStopManager(float(os.getenv('TRAILING_STOP_PERCENT', '3')))
        self.correlation_manager = CorrelationManager()
        
        # NOUVEAUX DÉTECTEURS CRITIQUES
        self.flash_crash_detector = FlashCrashDetector()
        self.macro_monitor = MacroEventMonitor()
        self.contagion_detector = ContagionDetector()
        self.multi_exchange_fallback = MultiExchangeFallback()
        self.manipulation_detector = ManipulationDetector()
        self.news_monitor = NewsMonitor()
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
        self.decision_display = DecisionDisplay()
        self.sr_analyzer = SupportResistanceAnalyzer()
        self.stablecoin_monitor = StablecoinMonitor()
        self.pattern_recognition = PatternRecognition()
        self.slippage_calculator = SlippageCalculator()
        self.liquidity_checker = LiquidityChecker()
        self.volatility_calculator = VolatilityCalculator()
        self.market_calculator = MarketCalculator()
        
        self.price_change_threshold = 0.002  # 0.2% au lieu de 0.1%
        
        # Gestionnaire de balance centralisé
        self.balance_manager = BalanceManager(self)
        
        os.makedirs('data', exist_ok=True)
        
        # Affichage async
        self.display_queue = Queue(maxsize=100)
        
        # Toujours connecter pour éviter les erreurs, même en paper trading
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
        
        # Initialiser le mode PRO si activé
        if os.getenv('USE_SIMPLE_STRATEGY', 'False') == 'True':
            self.init_pro_mode()
    
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
                    min_costs = {'BTC/USDT': 15, 'ETH/USDT': 10, 'SOL/USDT': 8, 'BNB/USDT': 12}
                    min_amounts = {'BTC/USDT': 0.00015, 'ETH/USDT': 0.003, 'SOL/USDT': 0.04, 'BNB/USDT': 0.01}
                    self.min_amounts[symbol] = {
                        'min_amount': min_amounts.get(symbol, 0.001), 
                        'min_cost': min_costs.get(symbol, 10)
                    }
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
                print(f"⚠️ Paper trading: Fonds insuffisants {cost:.2f} > {self.paper_balance:.2f}")
                return False
            print(f"🧠 Paper trading: Validation OK - Coût {cost:.2f} USDT")
            return True
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
        # WebSocket temps réel - AUCUN cache
        if self.websocket.is_connected():
            ws_price = self.websocket.get_price(symbol)
            if ws_price is not None:
                return ws_price
        
        # TOUJOURS utiliser les vraies données Binance (même en paper trading)
        try:
            ticker = self.safe_request(self.exchange.fetch_ticker, symbol)
            return ticker['last']
        except Exception as e:
            print(f"❌ Erreur prix {symbol}: {e}")
            # Fallback seulement en cas d'erreur critique
            if self.paper_trading:
                fallback_prices = {'BTC': 50000, 'ETH': 3000, 'SOL': 100, 'BNB': 300}
                crypto = symbol.split('/')[0]
                return fallback_prices.get(crypto, 100)
            raise e
    
    def get_ticker(self, symbol):
        """Récupère ticker avec WebSocket prioritaire et fallback REST API - VRAIES DONNÉES"""
        # WebSocket temps réel prioritaire
        if self.websocket.is_connected():
            ws_ticker = self.websocket.get_ticker(symbol)
            if ws_ticker is not None:
                return ws_ticker
        
        # TOUJOURS utiliser les vraies données Binance (même en paper trading)
        try:
            return self.safe_request(self.exchange.fetch_ticker, symbol)
        except Exception as e:
            print(f"❌ Erreur ticker {symbol}: {e}")
            # Fallback seulement en cas d'erreur critique
            current_price = self.get_price(symbol)
            return {'last': current_price, 'percentage': 0, 'symbol': symbol}
    
    def get_klines(self, symbol, count=50, timeframe=None):
        """Récupère les klines avec timeframe configurable - VRAIES DONNÉES"""
        # Utiliser le timeframe spécifié ou celui par défaut depuis .env
        if timeframe is None:
            timeframe = os.getenv('MAIN_TIMEFRAME', '15m')
        
        if self.websocket.is_connected():
            klines = self.websocket.get_klines(symbol, count)
            if len(klines) >= count:
                return klines
        
        # TOUJOURS utiliser les vraies données Binance (même en paper trading)
        try:
            ohlcv = self.safe_request(self.exchange.fetch_ohlcv, symbol, timeframe, limit=count)
            return [{'timestamp': c[0], 'open': c[1], 'high': c[2], 'low': c[3], 'close': c[4], 'volume': c[5]} for c in ohlcv]
        except Exception as e:
            print(f"Erreur récupération klines {symbol}: {e}")
            # Fallback seulement en cas d'erreur critique
            if self.paper_trading:
                klines = []
                base_price = 50000 if 'BTC' in symbol else 3000
                interval_minutes = self._timeframe_to_minutes(timeframe)
                for i in range(count):
                    price = base_price + (i * 10)
                    klines.append({
                        'timestamp': int(time.time() - (count - i) * interval_minutes * 60) * 1000,
                        'open': price, 'high': price + 50, 'low': price - 50,
                        'close': price + 25, 'volume': 100
                    })
                return klines
            return []
    
    def _timeframe_to_minutes(self, timeframe):
        """Convertit un timeframe en minutes"""
        timeframe_map = {
            '1m': 1, '3m': 3, '5m': 5, '15m': 15, '30m': 30,
            '1h': 60, '2h': 120, '4h': 240, '6h': 360, '8h': 480, '12h': 720,
            '1d': 1440, '3d': 4320, '1w': 10080, '1M': 43200
        }
        return timeframe_map.get(timeframe, 15)
    
    def execute_strategy(self, symbol, strategy_type, amount):
        print(f"🔄 DEBUG: execute_strategy appelée pour {symbol}, type={strategy_type}")
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
                print(f"❌ {symbol}: Ni achat ni vente possible")
                return
            # Utiliser get_ticker avec WebSocket prioritaire et fallback REST API
            ticker = self.get_ticker(symbol)
            change_24h = ticker.get('percentage', 0)
            analysis = self.get_cached_analysis(symbol, price)
            vol_display = analysis.get('volatility', 2.0)
            self.show_strategy_execution(symbol, price, change_24h, vol_display)
            
            print(f"🎯 {symbol}: Appel de {strategy_type}_strategy")
            print(f"🚀 NOUVEAU CODE ACTIF - VERSION MISE À JOUR!")
            print(f"🔍 DEBUG: strategy_type='{strategy_type}', type={type(strategy_type)}")
            if strategy_type == 'intelligent':
                print(f"🔍 {symbol}: Tentative appel intelligent_strategy")
                if hasattr(self, 'intelligent_strategy'):
                    print(f"✅ {symbol}: intelligent_strategy existe - APPEL EN COURS...")
                    try:
                        result = self.intelligent_strategy(symbol, trade_amount, price)
                        print(f"✅ {symbol}: intelligent_strategy terminée, résultat: {result}")
                    except Exception as e:
                        print(f"❌ {symbol}: ERREUR dans intelligent_strategy: {e}")
                        import traceback
                        traceback.print_exc()
                else:
                    print(f"❌ {symbol}: intelligent_strategy n'existe pas!")
            elif strategy_type == 'adaptive':
                print(f"🔄 {symbol}: Appel adaptive_strategy")
                self.adaptive_strategy(symbol, trade_amount, price)
            elif strategy_type == 'scalping':
                print(f"🔄 {symbol}: Appel scalping_strategy")
                self.scalping_strategy(symbol, trade_amount, price)
            elif strategy_type == 'dca':
                print(f"🔄 {symbol}: Appel dca_strategy")
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
    
    def track_cumulative_trend(self, symbol, current_price):
        """Détecte les tendances cumulatives (ex: 6x -0.1% = -0.6%)"""
        if symbol not in self.cumulative_tracker:
            self.cumulative_tracker[symbol] = {
                'start_price': current_price,
                'last_price': current_price,
                'direction': 0,
                'count': 0,
                'cumulative_change': 0
            }
            return False
        
        tracker = self.cumulative_tracker[symbol]
        price_change = (current_price - tracker['last_price']) / tracker['last_price']
        
        # Déterminer direction (-1 baisse, +1 hausse)
        if abs(price_change) < 0.0005:  # Ignore variations < 0.05%
            return False
        
        current_direction = 1 if price_change > 0 else -1
        
        # Si même direction, incrémenter compteur
        if current_direction == tracker['direction']:
            tracker['count'] += 1
            tracker['cumulative_change'] += price_change
        else:
            # Changement de direction, reset
            tracker['direction'] = current_direction
            tracker['count'] = 1
            tracker['start_price'] = tracker['last_price']
            tracker['cumulative_change'] = price_change
        
        tracker['last_price'] = current_price
        
        # Alerte si 4+ variations consécutives dans même direction
        if tracker['count'] >= 4:
            total_change_pct = abs(tracker['cumulative_change']) * 100
            if total_change_pct >= 0.3:  # Cumul ≥ 0.3%
                direction_text = "baisse" if tracker['direction'] < 0 else "hausse"
                print(f"📊 {symbol}: Tendance cumulative détectée! {tracker['count']}x {direction_text} = {total_change_pct:.2f}%")
                # Reset après alerte
                tracker['count'] = 0
                tracker['start_price'] = current_price
                tracker['cumulative_change'] = 0
                return True
        
        return False
    
    def on_realtime_signal(self, symbol, price):
        if not self.realtime_trading:
            return
        
        formatted_symbol = f"{symbol[:-4]}/{symbol[-4:]}"
        
        # Détecter tendance cumulative
        cumulative_trend = self.track_cumulative_trend(formatted_symbol, price)
        
        now = time.time()
        last_time = self.last_analysis.get(formatted_symbol, 0)
        
        # Si tendance cumulative détectée, forcer analyse immédiate
        if cumulative_trend:
            print(f"⚡ Analyse forcée suite à tendance cumulative {formatted_symbol}")
        elif now - last_time < 0.1:
            return
        
        self.last_analysis[formatted_symbol] = now
        try:
            strategy_type = os.getenv('STRATEGY_TYPE', 'intelligent')
            trade_amount = self.get_min_amount(formatted_symbol)['min_cost']
            
            # MODE PRO : Utiliser directement la stratégie PRO
            if hasattr(self, 'intelligent_strategy_pro') and os.getenv('USE_SIMPLE_STRATEGY', 'False') == 'True':
                self.intelligent_strategy_pro(formatted_symbol, trade_amount, price)
            elif strategy_type == 'intelligent':
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
    
    def run(self):
        trading_pairs = os.getenv('TRADING_PAIRS', 'BTCUSDT,ETHUSDT').split(',')
        strategy_type = os.getenv('STRATEGY_TYPE', 'intelligent')
        check_interval = int(os.getenv('CHECK_INTERVAL', '60'))

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

        if self.notify_trades:
            mode = "PAPER" if self.paper_trading else "LIVE"
            self.notifier.notify(f"🤖 Bot démarré - {mode}")
        try:
            while True:
                self.show_performance()
                self.show_spot_balances(trading_pairs)
                self.earn_manager.show_earn_performance()
                self.show_realtime_prices(trading_pairs)
                self.show_protection_status()  # Afficher statuts protection
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
                
                # Vérifier exécution ordres limite paper trading
                self.check_paper_limit_orders()
                
                # Vérifier avec le minimum requis
                min_required = min(self.get_min_amount(p if '/' in p else f"{p[:3]}/{p[3:]}")['min_cost'] for p in trading_pairs)
                self.ensure_trading_balance(min_required)
                self.earn_manager.tirelire_auto_manage()
                self.sync_positions_from_exchange()
                self.detect_order_modifications()
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
                
                # Vérifier optimisation positions existantes (toujours, pas seulement si fonds insuffisants)
                optimized_any = False
                for pair in trading_pairs:
                    symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
                    base_currency = symbol.split('/')[0]
                    free_holding = balance.get(base_currency, {}).get('free', 0)
                    locked_holding = balance.get(base_currency, {}).get('used', 0)
                    total_holding = free_holding + locked_holding
                    
                    # Optimiser si position existe (libre ou verrouillée)
                    if total_holding > 0.00001:
                        position_value = total_holding * self.get_price(symbol)
                        min_cost = self.get_min_amount(symbol)['min_cost']
                        if position_value >= min_cost:
                            if self.optimize_existing_position(symbol):
                                optimized_any = True
                                break  # Une optimisation à la fois
                
                if optimized_any:
                    print(f"🔄 Position optimisée - Nouvelle analyse dans 10s")
                    time.sleep(10)
                    continue
                
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
    
    def show_protection_status(self):
        """Affiche le statut de toutes les protections actives"""
        import time
        protections = []
        
        # 1. Macro Events
        if hasattr(self, 'macro_monitor') and not self.macro_monitor.can_trade():
            if hasattr(self.macro_monitor, 'risk_off_start') and self.macro_monitor.risk_off_start:
                remaining = (self.macro_monitor.risk_off_duration - 
                           (time.time() - self.macro_monitor.risk_off_start)) / 3600
                if remaining > 0:
                    protections.append(f"🚫 RISK-OFF ({remaining:.1f}h)")
        
        # 2. Multi-Exchange
        if hasattr(self, 'multi_exchange_fallback'):
            exchange_status = self.multi_exchange_fallback.get_status_message()
            if exchange_status:
                protections.append(exchange_status)
        
        # 3. Protections par symbole
        trading_pairs = os.getenv('TRADING_PAIRS', 'BTCUSDT,ETHUSDT').split(',')
        for pair in trading_pairs[:2]:  # Max 2 symboles
            symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
            crypto = symbol.split('/')[0]
            
            # Manipulation
            if hasattr(self, 'manipulation_detector'):
                manip_status = self.manipulation_detector.get_manipulation_status(symbol)
                if manip_status:
                    protections.append(f"{crypto}: {manip_status}")
            
        # 4. Liquidity
        if hasattr(self, 'liquidity_checker'):
            liquidity_status = self.liquidity_checker.get_status_message(symbol)
            if liquidity_status:
                protections.append(f"{crypto}: {liquidity_status}")
        
        # Afficher seulement si protections actives
        if protections:
            print(f"🛡️ PROTECTIONS: {' | '.join(protections[:3])}")  # Max 3
    
    def show_debug_commands(self):
        """Affiche les commandes de debug"""
        print("\n🔧 COMMANDES DEBUG:")
        print("  bot.force_balance_sync()  # Forcer sync balances")
        print("  bot.balance_manager.get_balance(True)  # Rafraîchir balances")
    
    def init_pro_mode(self):
        """Initialise le mode PRO avec niveaux fixes et scaling"""
        try:
            from utils.fixed_levels_manager import FixedLevelsManager
            from utils.multi_position_manager import MultiPositionManager
            
            self.fixed_levels = FixedLevelsManager()
            self.multi_position = MultiPositionManager()
            
            # Sauvegarder méthode originale
            if hasattr(self, 'intelligent_strategy'):
                self.intelligent_strategy_original = self.intelligent_strategy
            
            # Remplacer par version pro
            self.intelligent_strategy = self.intelligent_strategy_pro
            
            print("🚀 MODE PRO ACTIVÉ - Niveaux fixes + Scaling")
            print(f"   🎯 Niveaux BTC: {os.getenv('BTC_LEVELS', 'Non défini')}")
            print(f"   🎯 Niveaux SOL: {os.getenv('SOL_LEVELS', 'Non défini')}")
            print(f"   📊 Max positions: {os.getenv('MAX_POSITIONS_PER_CRYPTO', '4')}")
            print(f"   ⚡ Mode agressif: {os.getenv('AGGRESSIVE_MODE', 'False')}")
            
        except Exception as e:
            print(f"⚠️ Erreur initialisation mode PRO: {e}")
    
    def init_pro_methods(self):
        """Initialise les méthodes pro"""
        if not hasattr(self, 'fixed_levels'):
            return
            
        # Sauvegarder méthode originale
        if hasattr(self, 'intelligent_strategy'):
            self.intelligent_strategy_original = self.intelligent_strategy
        
        # Remplacer par version pro
        self.intelligent_strategy = self.intelligent_strategy_pro
    
    def can_open_new_position_pro(self, symbol):
        """Vérifie si on peut ouvrir une nouvelle position (mode pro)"""
        import os  # Import local
        if not os.getenv('ALLOW_MULTIPLE_POSITIONS', 'False') == 'True':
            # Mode classique : 1 position max
            existing_positions = [p for p in self.state.get('positions', []) 
                                if p['symbol'] == symbol and p['side'] == 'buy']
            return len(existing_positions) == 0
        
        # Mode scaling : plusieurs positions autorisées
        max_positions = int(os.getenv('MAX_POSITIONS_PER_CRYPTO', '4'))
        existing_positions = [p for p in self.state.get('positions', []) 
                            if p['symbol'] == symbol and p['side'] == 'buy']
        
        return len(existing_positions) < max_positions
    
    def get_fixed_level_buy_signal(self, symbol, current_price):
        """Vérifie les niveaux fixes pour signal d'achat"""
        import os  # Import local
        if not hasattr(self, 'fixed_levels'):
            return False, None
            
        # Charger niveaux depuis .env
        crypto = symbol.split('/')[0]
        levels_key = f"{crypto}_LEVELS"
        levels_str = os.getenv(levels_key, '')
        
        if not levels_str:
            return False, None
            
        levels = [float(level) for level in levels_str.split(',')]
        
        # Vérifier si prix proche d'un niveau (±1.5%)
        for level in levels:
            distance_pct = abs(current_price - level) / level * 100
            if distance_pct <= 1.5 and current_price <= level * 1.015:  # Tolérance 1.5%
                return True, level
                
        return False, None
    
    def calculate_scaled_amount_pro(self, symbol, base_amount, current_price):
        """Calcule le montant selon le scaling pro"""
        import os  # Import local
        if not os.getenv('POSITION_SIZE_SCALING', 'False') == 'True':
            return base_amount
            
        # Compter positions existantes
        existing_positions = [p for p in self.state.get('positions', []) 
                            if p['symbol'] == symbol and p['side'] == 'buy']
        position_count = len(existing_positions)
        
        # Multipliers progressifs : 1x, 1.5x, 2x, 3x
        multipliers = [1.0, 1.5, 2.0, 3.0]
        multiplier = multipliers[min(position_count, len(multipliers)-1)]
        
        return base_amount * multiplier
    
    def should_scale_in_pro(self, symbol, current_price):
        """Détermine si on doit ajouter une position (scale in)"""
        import os  # Import local
        if not os.getenv('POSITION_SCALING', 'False') == 'True':
            return False, None
            
        # Récupérer dernière position
        buy_positions = [p for p in self.state.get('positions', []) 
                        if p['symbol'] == symbol and p['side'] == 'buy']
        
        if not buy_positions:
            return True, None  # Première position
            
        # Trier par timestamp et prendre le plus récent
        buy_positions.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        last_buy_price = buy_positions[0].get('price')
        
        if not last_buy_price:
            return False, None
            
        # Calculer la baisse depuis le dernier achat
        price_drop_pct = (last_buy_price - current_price) / last_buy_price * 100
        
        # Seuils de scaling : -2%, -4%, -6%
        scale_thresholds = [2.0, 4.0, 6.0]
        position_count = len(buy_positions)
        
        if position_count < len(scale_thresholds):
            required_drop = scale_thresholds[position_count]
            return price_drop_pct >= required_drop, last_buy_price
            
        return False, None
    
    def intelligent_strategy_pro(self, symbol, amount, current_price):
        """Version pro de intelligent_strategy avec niveaux fixes et scaling"""
        import os  # Import local pour éviter les erreurs
        
        # 1. Vérifier si on peut ouvrir une nouvelle position
        if not self.can_open_new_position_pro(symbol):
            return
        
        # 2. Mode agressif : ignorer la plupart des protections
        if os.getenv('AGGRESSIVE_MODE', 'False') == 'True':
            # Ignorer marché latéral et patterns
            pass
        else:
            # Mode conservateur : vérifications normales
            if not self.safety_manager.can_trade():
                return
        
        # 3. Vérifier niveaux fixes
        should_buy_level, level = self.get_fixed_level_buy_signal(symbol, current_price)
        buy_reason = None
        
        if should_buy_level:
            buy_reason = f"Niveau fixe: {level}"
        else:
            # 4. Vérifier scaling
            should_scale, last_price = self.should_scale_in_pro(symbol, current_price)
            if should_scale and last_price:
                buy_reason = f"Scaling depuis {last_price:.2f}"
            elif should_scale:
                buy_reason = "Première position"
        
        # 5. Signal technique simple (confidence réduite)
        if not buy_reason:
            min_confidence = int(os.getenv('MIN_CONFIDENCE', '50'))
            analysis = self.get_cached_analysis(symbol, current_price)
            global_signal = analysis['global_signal']
            
            if (global_signal['action'] in ['BUY', 'STRONG_BUY'] and 
                global_signal['confidence'] >= min_confidence):
                buy_reason = f"Signal technique {global_signal['confidence']:.0f}%"
        
        # 6. Exécuter achat si conditions remplies
        if buy_reason:
            # Calculer montant selon scaling
            base_amount = float(os.getenv('TRADE_AMOUNT', '5'))
            scaled_amount = self.calculate_scaled_amount_pro(symbol, base_amount, current_price)
            
            # Vérifier fonds disponibles
            balance = self.balance_manager.get_balance()
            usdt_available = balance.get('USDT', {}).get('free', 0)
            
            if self.paper_trading:
                usdt_available = self.paper_balance
            
            # Limiter au disponible
            final_amount = min(scaled_amount, usdt_available * 0.8)  # 80% max du disponible
            # Minimum spécial pour BTC (réduit à 15 USDT)
            if symbol == 'BTC/USDT':
                final_amount = max(final_amount, 15.0)  # 15 USDT minimum pour BTC
            else:
                final_amount = max(final_amount, self.get_min_amount(symbol)['min_cost'])
            
            trade_amount = final_amount / current_price
            
            # Vérifier que la quantité respecte les limites
            min_limits = self.get_min_amount(symbol)
            if trade_amount < min_limits['min_amount']:
                trade_amount = min_limits['min_amount']
                final_amount = trade_amount * current_price
                print(f"   ⚠️ Ajustement quantité: {trade_amount:.6f} {crypto}")
            
            # Affichage pro
            crypto = symbol.split('/')[0]
            existing_positions = [p for p in self.state.get('positions', []) 
                                if p['symbol'] == symbol and p['side'] == 'buy']
            position_count = len(existing_positions)
            
            print(f"🚀 ACHAT PRO {crypto}: {final_amount:.1f} USDT (Position #{position_count + 1})")
            print(f"   💡 Raison: {buy_reason}")
            print(f"   💰 Prix: {current_price:.2f}")
            print(f"   📊 Quantité: {trade_amount:.6f} {crypto}")
            
            # Exécuter l'achat
            result = self.buy_market(symbol, trade_amount)
            
            if result:
                print(f"✅ Achat PRO exécuté avec succès")
                # Ajouter trailing stop
                if hasattr(self, 'trailing_stop_manager'):
                    self.trailing_stop_manager.add_position(symbol, current_price)
            else:
                print(f"❌ Échec de l'achat PRO")
        else:
            # Mode debug : afficher pourquoi pas d'achat
            if os.getenv('DEBUG_PRO', 'False') == 'True':
                crypto = symbol.split('/')[0]
                print(f"⏸️ {crypto}: Aucune condition d'achat remplie")