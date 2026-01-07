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
from core.double_investment_manager import DoubleInvestmentManager
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
from utils.timing_optimizer import TimingOptimizer
from utils.position_sizing_calculator import PositionSizingCalculator
from utils.dynamic_levels_manager import DynamicLevelsManager
from utils.capital_manager import CapitalManager
from utils.crypto_detector import CryptoDetector
from utils.dust_manager import DustManager
from utils.dynamic_fees_manager import DynamicFeesManager
from utils.adaptive_thresholds_manager import AdaptiveThresholdsManager
import logging

# Import des mixins
from core.bot_trading import TradingMixin
from core.bot_strategies import StrategiesMixin
from core.bot_sync import SyncMixin
from core.bot_analysis import AnalysisMixin
from core.bot_display import DisplayMixin

class BinanceSpotBot(TradingMixin, StrategiesMixin, SyncMixin, AnalysisMixin, DisplayMixin):
    """Bot de trading Binance Spot avec stratégies avancées"""
    
    def __init__(self, api_key, api_secret, testnet=False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        
        # Affichage simplifié
        self.max_retries = 3
        self.retry_delay = 5
        self.min_amounts = {}
        
        # Configuration des fichiers selon le mode
        self.paper_trading = os.getenv('PAPER_TRADING', 'True') == 'True'
        if self.paper_trading:
            self.state_file = 'data/paper_bot_state.json'
        else:
            self.state_file = 'data/bot_state.json'
        self.paper_balance = float(os.getenv('PAPER_BALANCE', '1000'))
        self.max_daily_loss = float(os.getenv('MAX_DAILY_LOSS', '100'))
        self.stop_loss_percent = float(os.getenv('STOP_LOSS_PERCENT', '5'))
        self.notify_trades = os.getenv('NOTIFY_TRADES', 'True') == 'True'
        self.save_logs = os.getenv('SAVE_LOGS', 'True') == 'True'
        
        # Frais dynamiques (remplace frais statiques)
        self.trading_fee = 0.001  # Fallback seulement
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
        self.last_dynamic_notifications = {}  # Éviter notifications consécutives identiques
        
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
        self.double_investment_manager = DoubleInvestmentManager(self)
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
        
        # PHASE 1 - Gestionnaire de niveaux dynamiques
        self.dynamic_levels = DynamicLevelsManager(self)
        
        # PHASE 2 - Optimiseurs QUAND et COMBIEN
        self.timing_optimizer = TimingOptimizer(self)
        self.position_sizer = PositionSizingCalculator(self)
        
        self.price_change_threshold = 0.002  # 0.2% au lieu de 0.1%
        
        # Gestionnaire de balance centralisé
        self.balance_manager = BalanceManager(self)
        
        # Gestionnaire de capital automatique
        self.capital_manager = CapitalManager(self)
        
        # Détecteur de cryptos automatique
        self.crypto_detector = CryptoDetector(self)
        
        # Gestionnaire de dust (valeurs très petites)
        self.dust_manager = DustManager(self)
        
        # GESTIONNAIRES PROFESSIONNELS NIVEAU INSTITUTIONNEL
        self.dynamic_fees = DynamicFeesManager(self)
        self.adaptive_thresholds = AdaptiveThresholdsManager(self)
        
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
        
        # Ajustement automatique selon le capital
        self.capital_manager.auto_adjust_bot()
        print()  # Ligne vide après l'analyse du capital
        
        # Gestion automatique Double Investment
        if hasattr(self, 'double_investment_manager'):
            # Test d'intégration
            if self.double_investment_manager.test_integration():
                self.double_investment_manager.auto_manage_positions()
        
        # Notification de démarrage
        if self.notify_trades and hasattr(self, 'notifier'):
            mode = "PAPER" if self.paper_trading else "LIVE"
            self.notifier.notify(f"🤖 Bot démarré - {mode}")
            # Envoyer status initial
            self.notifier.send_status_update()
    
    def manage_double_investment_cycle(self):
        """Gère le cycle Double Investment (appelé périodiquement)"""
        try:
            if hasattr(self, 'double_investment_manager') and self.double_investment_manager.enabled:
                # Vérifier les expirations
                self.double_investment_manager.check_expirations()
                
                # Gérer les nouvelles positions si nécessaire
                self.double_investment_manager.auto_manage_positions()
                
        except Exception as e:
            print(f"⚠️ Erreur cycle Double Investment: {e}")
    
    def setup_logging(self):
        import logging
        
        class ConnectionErrorFilter(logging.Filter):
            def filter(self, record):
                msg = str(record.getMessage())
                # Filtrer tous les messages de connexion WebSocket
                if any(keyword in msg.lower() for keyword in [
                    "winerror 10054", "connexion existante", "websocket", 
                    "user data stream", "reconnexion", "connection reset"
                ]):
                    return False  # Supprimer complètement ces messages
                return True
        
        log_level = os.getenv('LOG_LEVEL', 'INFO')
        logging.basicConfig(
            level=getattr(logging, log_level),
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler('bot.log') if self.save_logs else logging.NullHandler()
            ]
        )
        
        # Ajouter le filtre personnalisé
        connection_filter = ConnectionErrorFilter()
        for handler in logging.getLogger().handlers:
            handler.addFilter(connection_filter)
            
        self.logger = logging.getLogger(__name__)
    
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
                    print(f"❌ Reconnexion échouée après {self.max_retries} tentatives")
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
                    if hasattr(self.exchange, 'markets') and self.exchange.markets:
                        market = self.exchange.markets.get(symbol)
                        if market and market.get('limits'):
                            limits = market['limits']
                            amount_limits = limits.get('amount', {})
                            cost_limits = limits.get('cost', {})
                            self.min_amounts[symbol] = {
                                'min_amount': amount_limits.get('min', 0.001),
                                'min_cost': cost_limits.get('min', 1.0)
                            }
                        else:
                            raise Exception("Market data unavailable")
                    else:
                        raise Exception("Markets not loaded")
                else:
                    min_costs = {'BTC/USDT': 15, 'ETH/USDT': 10, 'SOL/USDT': 8, 'BNB/USDT': 12}
                    min_amounts = {'BTC/USDT': 0.00015, 'ETH/USDT': 0.003, 'SOL/USDT': 0.04, 'BNB/USDT': 0.01}
                    self.min_amounts[symbol] = {
                        'min_amount': min_amounts.get(symbol, 0.001), 
                        'min_cost': min_costs.get(symbol, 10)
                    }
            except Exception as e:
                # Fallback avec minimums du marché (pas API)
                fallback_minimums = {
                    'BTC/USDT': {'min_amount': 0.00001, 'min_cost': 15.0},
                    'ETH/USDT': {'min_amount': 0.0001, 'min_cost': 10.0},
                    'SOL/USDT': {'min_amount': 0.01, 'min_cost': 8.0},
                    'BNB/USDT': {'min_amount': 0.001, 'min_cost': 12.0},
                    'ADA/USDT': {'min_amount': 1.0, 'min_cost': 5.0},
                    'DOT/USDT': {'min_amount': 0.1, 'min_cost': 6.0},
                    'MATIC/USDT': {'min_amount': 1.0, 'min_cost': 3.0},
                    'AVAX/USDT': {'min_amount': 0.01, 'min_cost': 7.0}
                }
                self.min_amounts[symbol] = fallback_minimums.get(symbol, {'min_amount': 0.001, 'min_cost': 1.0})
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
        """Récupère les klines avec timeframe adaptatif - VRAIES DONNÉES"""
        # Timeframe adaptatif au lieu de statique
        if timeframe is None:
            try:
                from utils.timeframe_manager import TimeframeManager
                timeframe = TimeframeManager.get_main_timeframe(symbol, 'intelligent', self)
            except:
                timeframe = os.getenv('MAIN_TIMEFRAME', '15m')  # Fallback
        
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
    
    def on_balance_update(self, data):
        """Délègue au gestionnaire de balance centralisé"""
        try:
            print(f"⚡ Dépôt/Retrait détecté - Sync instantanée...")
            self.balance_manager.force_balance_sync()
        except Exception as e:
            print(f"⚠️ Erreur sync: {e}")
    
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
                
                # Envoyer notification Telegram
                if self.notify_trades and hasattr(self, 'notifier'):
                    self.notifier.notify_cumulative_trend(symbol, tracker['direction'], tracker['count'], total_change_pct)
                
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
            trade_amount = self.get_min_amount(formatted_symbol)['min_cost']
            
            # Utiliser la stratégie intelligente
            self.intelligent_strategy(formatted_symbol, trade_amount, price)
            
        except Exception as e:
            print(f"❌ Erreur signal temps réel {symbol}: {e}")
    
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
    
    def check_and_recover_stuck_positions_filtered(self, tradable_pairs):
        """Vérifie les positions bloquées seulement pour les cryptos tradables"""
        balance = self.balance_manager.get_balance()
        for symbol in tradable_pairs:
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

        # Obtenir cryptos tradables via le système de scoring
        balance = self.balance_manager.get_balance()
        stuck_positions = []
        tradable_pairs = self.crypto_scorer.rank_cryptos(self, trading_pairs, stuck_positions)
        
        # Compter positions actives seulement pour cryptos tradables
        active_positions = 0
        for symbol in tradable_pairs:
            base_currency = symbol.split('/')[0]
            free = balance.get(base_currency, {}).get('free', 0)
            locked = balance.get(base_currency, {}).get('used', 0)
            total = free + locked
            if total > 0.00001:
                position_value = total * self.get_price(symbol)
                if position_value >= self.get_min_amount(symbol)['min_cost']:
                    active_positions += 1
        
        self.show_header(tradable_pairs, "intelligent", 0, active_positions)

        try:
            while True:
                self.show_performance()
                
                # Obtenir balance et cryptos tradables via le système de scoring
                balance = self.balance_manager.get_balance()
                usdt_available = balance.get('USDT', {}).get('free', 0)
                
                # Utiliser le crypto scorer pour filtrer les cryptos tradables
                stuck_positions = []
                tradable_pairs = self.crypto_scorer.rank_cryptos(self, trading_pairs, stuck_positions)
                
                # NOUVEAU: Calculer intervalle adaptatif multi-pairs
                check_interval = self.get_optimal_check_interval(tradable_pairs)
                
                # Affichage avec intervalle dynamique
                if tradable_pairs:
                    # Afficher intervalle adaptatif
                    volatilities = [self.get_pair_volatility(symbol) for symbol in tradable_pairs[:2]]
                    vol_display = ", ".join([f"{tradable_pairs[i].split('/')[0]}:{vol:.1f}" for i, vol in enumerate(volatilities)])
                    print(f"🔄 Intervalle: {check_interval}s ({vol_display})")
                    
                    self.show_spot_balances(tradable_pairs)
                    self.earn_manager.show_earn_performance()
                    self.show_realtime_prices(tradable_pairs)
                    self.show_protection_status(tradable_pairs)
                    # NOUVEAU: Afficher métriques professionnelles
                    self.show_professional_metrics()
                else:
                    self.earn_manager.show_earn_performance()
                    print("⚠️ Aucune crypto tradable - Attente...")
                
                # Afficher niveaux dynamiques seulement pour cryptos tradables
                if tradable_pairs:
                    self.show_dynamic_levels(tradable_pairs[:2])  # Top 2 cryptos tradables
                
                print()
                # Prévisions de vente seulement pour cryptos tradables
                sell_predictions = []
                for symbol in tradable_pairs:
                    sell_pred = self.predict_next_sell_execution(symbol)
                    if sell_pred:
                        sell_predictions.append((symbol, sell_pred))
                self.show_sell_predictions(sell_predictions)
                
                # Prévisions d'achat seulement pour cryptos tradables
                buy_predictions = []
                for symbol in tradable_pairs:
                    prediction = self.predict_next_buy_opportunity(symbol)
                    crypto = symbol.split('/')[0]
                    if prediction and prediction['status'] in ['READY', 'WAITING']:
                        buy_predictions.append((crypto, prediction))
                self.show_buy_predictions(buy_predictions)
                
                # Vérifier positions bloquées seulement pour cryptos tradables
                if tradable_pairs:
                    self.check_and_recover_stuck_positions_filtered(tradable_pairs)
                
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
                
                # Vérifier avec le minimum requis (seulement cryptos tradables)
                min_required = min(self.get_min_amount(symbol)['min_cost'] for symbol in tradable_pairs) if tradable_pairs else 10
                self.balance_manager.ensure_trading_balance(min_required)
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
                
                self.show_tradable_pairs(tradable_pairs, usdt_available)
                
                # Vérifier optimisation positions existantes seulement pour cryptos tradables
                optimized_any = False
                for symbol in tradable_pairs:
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
                
                # Envoyer status périodique Telegram
                if self.notify_trades and hasattr(self, 'notifier'):
                    self.notifier.send_status_update()
                
                # NOUVEAU: Optimisations quotidiennes automatiques
                self.run_daily_optimizations()
                
                # Plus besoin de vérifier manuellement - timer automatique
                time.sleep(check_interval)
        except KeyboardInterrupt:
            print("\n🛑 Arrêt du bot...")
            if self.notify_trades:
                self.notifier.notify("🛑 Bot arrêté")
                self.notifier.stop_hourly_notifications()
            if hasattr(self, 'websocket'):
                self.websocket.stop()
            self.save_state()
        except Exception as e:
            print(f"\n⚠️ Erreur bot: {e}")
            raise e
    
    def show_protection_status(self, tradable_pairs):
        """Affiche le statut de toutes les protections actives pour les cryptos tradables"""
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
        
        # 3. Protections par symbole (seulement cryptos tradables)
        for symbol in tradable_pairs[:2]:  # Max 2 symboles tradables
            crypto = symbol.split('/')[0]
            
            # Manipulation
            if hasattr(self, 'manipulation_detector'):
                manip_status = self.manipulation_detector.get_manipulation_status(symbol)
                if manip_status:
                    protections.append(f"{crypto}: {manip_status}")
            
            # Liquidity
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
        print("  bot.balance_manager.force_balance_sync()  # Forcer sync balances")
        print("  bot.balance_manager.get_balance(True)  # Rafraîchir balances")
        print("  bot.dynamic_levels.display_levels('BTC/USDT')  # Niveaux dynamiques")
        print("  bot.exchange.fetch_balance()  # Test API direct")
    
    def show_dynamic_levels(self, tradable_pairs):
        """Affiche les niveaux dynamiques pour les cryptos tradables uniquement"""
        try:
            # Utiliser directement la liste des cryptos tradables passée en paramètre
            for symbol in tradable_pairs:
                current_price = self.get_price(symbol)
                entry_opportunities = self.dynamic_levels.get_entry_levels(symbol, current_price)
                
                if entry_opportunities:
                    crypto = symbol.split('/')[0]
                    best_entry = entry_opportunities[0]
                    print(f"📊 {crypto}: Meilleur niveau {best_entry['price']:.2f} ({best_entry['type']}) - {best_entry['distance']:.1f}%")
                    
                    # Envoyer notification si niveau très proche (< 2%) et pas déjà envoyée
                    if abs(best_entry['distance']) < 2.0 and self.notify_trades and hasattr(self, 'notifier'):
                        notification_key = f"{symbol}_{best_entry['type']}_{best_entry['price']:.2f}"
                        last_notification = self.last_dynamic_notifications.get(notification_key)
                        
                        # Envoyer seulement si pas de notification identique récente (5 min)
                        if not last_notification or (time.time() - last_notification) > 300:
                            self.notifier.notify_dynamic_level(symbol, best_entry['type'], best_entry['price'], best_entry['distance'])
                            self.last_dynamic_notifications[notification_key] = time.time()
        except Exception as e:
            print(f"⚠️ Erreur affichage niveaux dynamiques: {e}")
    
    def intelligent_strategy(self, symbol, amount, current_price):
        """Stratégie intelligente - Niveaux dynamiques + Filtres SMC + Timing + Position Sizing + SEUILS PROFESSIONNELS"""
        # 1. Vérifier position existante
        if not self.can_open_position(symbol):
            return
        
        # 2. Filtre HTF adaptatif (inclut déjà discount zone et stop hunt)
        if not self.check_htf_bias(symbol):
            return
        
        # 3. NOUVEAU: Vérifier avec seuils professionnels adaptatifs
        try:
            analysis = self.get_cached_analysis(symbol, current_price)
            volatility = analysis.get('volatility', 2.0)
            
            # Seuil adaptatif au lieu du seuil statique
            adaptive_threshold = self.adaptive_thresholds.get_adaptive_confidence_threshold(symbol, volatility)
            global_signal = analysis['global_signal']
            
            # Vérifier signal avec seuil adaptatif
            if not (global_signal['action'] in ['BUY', 'STRONG_BUY'] and 
                   global_signal['confidence'] >= adaptive_threshold):
                crypto = symbol.split('/')[0]
                print(f"❌ {crypto}: Signal {global_signal['confidence']:.0f}% < Seuil adaptatif {adaptive_threshold:.0f}%")
                return
            
            print(f"✅ Signal validé avec seuil adaptatif: {global_signal['confidence']:.0f}% ≥ {adaptive_threshold:.0f}%")
            
        except Exception as e:
            # Fallback méthode classique
            should_buy, reason = self.get_entry_signal(symbol, current_price)
            if not should_buy:
                return
        
        # 4. Optimiser le timing (QUAND)
        signal_strength = self.get_signal_strength(symbol, current_price)
        timing_data = self.timing_optimizer.get_optimal_timing(symbol, signal_strength)
        
        if timing_data['action'] not in ['BUY_NOW', 'BUY_READY']:
            crypto = symbol.split('/')[0]
            print()
            print(f"⏳ {crypto}: Timing non optimal ({timing_data['score']:.2f}) - {timing_data['action']}")
            return
        
        # 5. Calculer position sizing optimal (COMBIEN)
        account_balance = self.get_account_balance()
        position_data = self.position_sizer.calculate_position_size(symbol, signal_strength, account_balance)
        
        # 6. NOUVEAU: Optimiser type d'ordre pour frais
        try:
            optimal_order_type = self.dynamic_fees.optimize_order_type(symbol, 'normal')
            print(f"💰 Ordre optimisé: {optimal_order_type} (frais réduits)")
        except:
            optimal_order_type = 'market'
        
        # 7. Exécuter achat avec données optimisées
        self.execute_optimized_buy(symbol, position_data, current_price, reason, timing_data)
    
    def get_real_trading_fee(self, symbol, order_type='market'):
        """Récupère frais réels au lieu des frais statiques"""
        try:
            return self.dynamic_fees.get_fee_for_trade(symbol, order_type)
        except:
            return self.trading_fee  # Fallback
    
    def calculate_real_trade_cost(self, symbol, amount_usdt, order_type='market'):
        """Calcule coût réel avec frais dynamiques"""
        try:
            return self.dynamic_fees.calculate_trade_cost(symbol, amount_usdt, order_type)
        except:
            # Fallback avec frais statiques
            fee_cost = amount_usdt * self.trading_fee
            return {
                'amount': amount_usdt,
                'fee_rate': self.trading_fee,
                'fee_cost': fee_cost,
                'total_cost': amount_usdt + fee_cost,
                'vip_level': 'Unknown',
                'bnb_discount': False
            }
    
    def show_professional_metrics(self):
        """Affiche métriques professionnelles"""
        try:
            # Frais dynamiques
            fees_summary = self.dynamic_fees.get_fees_summary()
            print(f"💰 FRAIS: {fees_summary['vip_level']} | BNB: {fees_summary['bnb_discount']} | Optimal: {fees_summary['optimal_fee']}")
            
            # Seuils adaptatifs pour cryptos tradables
            trading_pairs = os.getenv('TRADING_PAIRS', 'BTCUSDT,ETHUSDT').split(',')
            for pair in trading_pairs[:2]:  # Top 2
                symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
                crypto = symbol.split('/')[0]
                
                if symbol in self.adaptive_thresholds.adaptive_thresholds:
                    threshold_summary = self.adaptive_thresholds.get_threshold_summary(symbol)
                    print(f"🎯 {crypto}: Seuil {threshold_summary['threshold_final']} (Perf: {threshold_summary['performance_adj']}, Market: {threshold_summary['market_adj']})")
        
        except Exception as e:
            pass  # Silencieux si erreur
    
    def run_daily_optimizations(self):
        """Lance optimisations quotidiennes comme les pros"""
        try:
            # Optimiser seuils adaptatifs
            self.adaptive_thresholds.optimize_thresholds_daily()
            
            # Refresh frais si nécessaire
            self.dynamic_fees.get_real_trading_fees('BTC/USDT')  # Force refresh
            
        except Exception as e:
            pass  # Silencieux si erreur
    
    def get_optimal_check_interval(self, tradable_pairs):
        """Calcule intervalle optimal selon volatilité multi-pairs - Niveau Professionnel"""
        if not tradable_pairs:
            return 2  # Fallback par défaut 2s
        
        try:
            intervals = []
            
            for symbol in tradable_pairs:
                # 1. Volatilité de la crypto
                volatility = self.get_pair_volatility(symbol)
                
                # 2. Position existante (surveillance renforcée)
                has_position = self.has_active_position(symbol)
                
                # 3. Heure de la journée (sessions actives)
                hour = datetime.now().hour
                is_active_session = 8 <= hour <= 22  # Sessions EU/US
                
                # 4. Volume relatif
                volume_ratio = self.get_volume_ratio(symbol)
                
                # Calcul base selon volatilité - NIVEAU PROFESSIONNEL
                if volatility >= 4.0:
                    base_interval = 2     # Très volatil = 2s
                elif volatility >= 3.0:
                    base_interval = 5     # Volatil = 5s
                elif volatility >= 2.0:
                    base_interval = 10    # Moyen = 10s
                else:
                    base_interval = 15    # Calme = 15s
                
                # Ajustements professionnels
                if has_position:
                    base_interval *= 0.7  # Position ouverte = plus de surveillance
                
                if not is_active_session:
                    base_interval *= 2.0  # Sessions fermées = moins urgent
                
                if volume_ratio > 2.0:
                    base_interval *= 0.7  # Volume élevé = plus réactif
                elif volume_ratio < 0.5:
                    base_interval *= 1.5  # Volume faible = moins urgent
                
                intervals.append(int(base_interval))
            
            # Prendre le MINIMUM (crypto la plus urgente)
            optimal_interval = min(intervals)
            
            # Contraintes de sécurité - NIVEAU PROFESSIONNEL
            return max(2, min(optimal_interval, 60))  # 2s à 1min
            
        except Exception as e:
            print(f"⚠️ Erreur calcul intervalle: {e}")
            return 2  # Fallback par défaut 2s
    
    def get_pair_volatility(self, symbol):
        """Récupère volatilité pour une crypto spécifique"""
        try:
            klines = self.get_klines(symbol, 20, '15m')
            if len(klines) >= 10:
                from utils.volatility_calculator import VolatilityCalculator
                return VolatilityCalculator.calculate(klines, symbol)
            return 2.0
        except:
            return 2.0
    
    def has_active_position(self, symbol):
        """Vérifie si position active sur cette crypto"""
        try:
            balance = self.balance_manager.get_balance()
            crypto = symbol.split('/')[0]
            
            free = balance.get(crypto, {}).get('free', 0)
            locked = balance.get(crypto, {}).get('used', 0)
            total = free + locked
            
            if total > 0.00001:
                value = total * self.get_price(symbol)
                min_cost = self.get_min_amount(symbol)['min_cost']
                return value >= min_cost
            
            return False
        except:
            return False
    
    def get_volume_ratio(self, symbol):
        """Calcule ratio volume actuel vs moyenne"""
        try:
            klines = self.get_klines(symbol, 10, '15m')
            if len(klines) < 5:
                return 1.0
            
            current_volume = klines[-1]['volume']
            avg_volume = sum(k['volume'] for k in klines[:-1]) / (len(klines) - 1)
            
            return current_volume / avg_volume if avg_volume > 0 else 1.0
        except:
            return 1.0
    
    def can_open_position(self, symbol):
        """Vérifie si on peut ouvrir une position"""
        max_positions = int(os.getenv('MAX_POSITIONS_PER_CRYPTO', '4'))
        existing_positions = [p for p in self.state.get('positions', []) 
                            if p['symbol'] == symbol and p['side'] == 'buy']
        return len(existing_positions) < max_positions
    




    def get_entry_signal(self, symbol, current_price):
        """Obtient le signal d'entrée - NIVEAUX DYNAMIQUES + PATTERNS"""
        # 1. Niveaux dynamiques professionnels (priorité)
        entry_opportunities = self.dynamic_levels.get_entry_levels(symbol, current_price)
        if entry_opportunities:
            best_entry = entry_opportunities[0]
            return True, f"Niveau dynamique: {best_entry['type']} ({best_entry['distance']:.1f}%)"
        
        # 2. Pattern Recognition (nouveau)
        try:
            klines = self.get_klines(symbol, 50, '1h')
            if len(klines) >= 20:
                pattern_result = self.pattern_recognition.detect_patterns(klines)
                
                # Patterns haussiers détectés
                if pattern_result['bullish_patterns']:
                    strongest = max(pattern_result['bullish_patterns'], key=lambda x: x['confidence'])
                    if strongest['confidence'] > 75:
                        return True, f"Pattern: {strongest['description']} ({strongest['confidence']:.0f}%)"
                
                # Bloquer si patterns baissiers forts
                if pattern_result['bearish_detected']:
                    crypto = symbol.split('/')[0]
                    bearish_pattern = next(p for p in pattern_result['patterns'] if p.get('bullish') == False)
                    print()
                    print(f"❌ {crypto}: Pattern baissier {bearish_pattern['description']} détecté")
                    return False, None
        except Exception as e:
            print(f"⚠️ Erreur pattern recognition {symbol}: {e}")
        
        # 3. Signaux techniques (fallback)
        try:
            analysis = self.get_cached_analysis(symbol, current_price)
            global_signal = analysis['global_signal']
            min_confidence = int(os.getenv('MIN_CONFIDENCE', '30'))
            
            if (global_signal['action'] in ['BUY', 'STRONG_BUY'] and 
                global_signal['confidence'] >= min_confidence):
                return True, f"Signal technique {global_signal['confidence']:.0f}%"
        except:
            pass
        
        return False, None
    

    def calculate_ema(self, prices, period):
        """Calcule l'EMA"""
        if len(prices) < period:
            return prices[-1] if prices else 0
        
        multiplier = 2 / (period + 1)
        ema = prices[0]
        
        for price in prices[1:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        
        return ema
    
    def check_htf_bias(self, symbol):
        """Filtre HTF adaptatif - Détection automatique du régime de marché"""
        try:
            market_type = self.detect_market_regime(symbol)
            crypto = symbol.split('/')[0]
            
            if market_type == 'BULL':
                return self.check_bullish_htf_bias(symbol)
            elif market_type == 'BEAR':
                return self.check_bearish_htf_bias(symbol)
            else:  # SIDEWAYS
                return True  # Marché latéral = autoriser
                
        except Exception as e:
            print(f"⚠️ Erreur filtre HTF {symbol}: {e}")
            return True
    
    def detect_market_regime(self, symbol):
        """Détecte automatiquement le régime de marché"""
        daily_klines = self.get_klines(symbol, 50, '1d')
        if len(daily_klines) < 50:
            return 'SIDEWAYS'
        
        closes = [k['close'] for k in daily_klines]
        ema_20 = self.calculate_ema(closes, 20)
        ema_50 = self.calculate_ema(closes, 50)
        current_price = closes[-1]
        
        if current_price > ema_20 > ema_50:
            return 'BULL'
        elif current_price < ema_20 < ema_50:
            return 'BEAR'
        else:
            return 'SIDEWAYS'
    
    def check_bullish_htf_bias(self, symbol):
        """Filtre HTF strict pour marché haussier"""
        daily_klines = self.get_klines(symbol, 50, '1d')
        closes = [k['close'] for k in daily_klines]
        ema_50 = self.calculate_ema(closes, 50)
        ema_200 = self.calculate_ema(closes, 200)
        current_price = closes[-1]
        
        return current_price > ema_50 > ema_200
    
    def check_bearish_htf_bias(self, symbol):
        """Filtre HTF avec exceptions pour marché baissier"""
        crypto = symbol.split('/')[0]
        
        # Exception 1: Support fort
        if self.is_near_strong_support(symbol):
            print(f"✅ {crypto}: Support fort détecté - Achat autorisé")
            return True
        
        # Exception 2: RSI oversold extrême
        if self.is_extreme_oversold(symbol):
            print(f"✅ {crypto}: RSI oversold - Achat autorisé")
            return True
        
        print(f"❌ {crypto}: Marché baissier sans exception - Skip")
        return False
    
    def is_near_strong_support(self, symbol):
        """Vérifie proximité support fort"""
        try:
            klines = self.get_klines(symbol, 100, '4h')
            levels_data = self.sr_analyzer.find_support_resistance_levels(klines)
            current_price = self.get_price(symbol)
            
            for support in levels_data['support_levels'][:2]:
                distance_pct = abs(current_price - support['price']) / current_price
                if distance_pct <= 0.02 and support['strength'] >= 3:
                    return True
            return False
        except:
            return False
    
    def is_extreme_oversold(self, symbol):
        """Vérifie RSI oversold extrême"""
        try:
            klines = self.get_klines(symbol, 30, '4h')
            if len(klines) < 14:
                return False
            
            closes = [k['close'] for k in klines]
            rsi = self.signal_generator.technical_indicators.calculate_rsi(closes)
            return rsi is not None and rsi < 25
        except:
            return False
    

    def get_signal_strength(self, symbol, current_price):
        """Calcule la force du signal (0-100)"""
        try:
            analysis = self.get_cached_analysis(symbol, current_price)
            return analysis.get('global_signal', {}).get('confidence', 50)
        except:
            return 50
    
    def get_account_balance(self):
        """Récupère le solde total du compte"""
        try:
            balance = self.balance_manager.get_balance()
            usdt_balance = balance.get('USDT', {}).get('free', 0)
            
            if self.paper_trading:
                return self.paper_balance
            
            return usdt_balance
        except:
            return 100  # Fallback
    
    def execute_optimized_buy(self, symbol, position_data, current_price, reason, timing_data):
        """Exécute l'achat avec données optimisées"""
        crypto = symbol.split('/')[0]
        existing_positions = [p for p in self.state.get('positions', []) 
                            if p['symbol'] == symbol and p['side'] == 'buy']
        position_count = len(existing_positions)
        
        # Affichage amélioré
        print(f"🚀 ACHAT OPTIMISÉ {crypto}: {position_data['position_size_usdt']:.1f} USDT (Position #{position_count + 1})")
        print(f"   💡 Raison: {reason}")
        print(f"   ⏰ Timing: {timing_data['score']:.2f} ({timing_data['action']})")
        print(f"   💰 Prix: {current_price:.2f} | Stop: {position_data['stop_loss_price']:.2f} (-{position_data['stop_loss_percent']:.1f}%)")
        print(f"   📈 R/R: 1:{position_data['risk_reward_ratio']:.1f} | Quantité: {position_data['position_size_crypto']:.6f} {crypto}")
        
        # Exécuter
        result = self.buy_market(symbol, position_data['position_size_crypto'])
        
        if result:
            print(f"✅ Achat exécuté avec succès")
            # Ajouter trailing stop avec prix optimisé
            if hasattr(self, 'trailing_stop_manager'):
                self.trailing_stop_manager.add_position(symbol, current_price)
        else:
            print(f"❌ Échec de l'achat")