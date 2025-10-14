import time
import json
import ccxt
import os
import threading
from queue import Queue
from datetime import datetime, timedelta
from core.websocket_manager import WebSocketManager
from core.notification_manager import NotificationManager
from core.technical_indicators import SignalGenerator
from core.earn_manager import BinanceEarnManager
from utils.advanced_risk_manager import AdvancedRiskManager, TrailingStopManager, CorrelationManager
from utils.multi_timeframe_analyzer import MultiTimeframeAnalyzer
from utils.safety_manager import SafetyManager
from utils.stuck_position_manager import StuckPositionManager
from utils.crypto_scorer import CryptoScorer
import logging

class BinanceSpotBot:
    def __init__(self, api_key, api_secret, testnet=True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.max_retries = 3
        self.retry_delay = 5
        self.state_file = 'data/bot_state.json'
        self.min_amounts = {}
        self.price_cache = {}
        self.cache_timeout = 1
        
        # Configuration depuis .env
        self.paper_trading = os.getenv('PAPER_TRADING', 'True') == 'True'
        self.paper_balance = float(os.getenv('PAPER_BALANCE', '1000'))
        self.max_daily_loss = float(os.getenv('MAX_DAILY_LOSS', '100'))
        self.stop_loss_percent = float(os.getenv('STOP_LOSS_PERCENT', '5'))
        self.notify_trades = os.getenv('NOTIFY_TRADES', 'True') == 'True'
        self.save_logs = os.getenv('SAVE_LOGS', 'True') == 'True'
        
        # Frais de trading
        self.trading_fee = float(os.getenv('TRADING_FEE_PERCENT', '0.1')) / 100
        self.min_profit_threshold = float(os.getenv('MIN_PROFIT_THRESHOLD', '0.3')) / 100
        
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
        self.websocket.set_bot_callback(self.on_realtime_signal)
        self.websocket.set_balance_callback(self.on_balance_update)
        self.websocket.start()
        
        # Trading temps réel
        self.realtime_trading = os.getenv('REALTIME_TRADING', 'False') == 'True'
        self.last_analysis = {}
        
        # Gestion intelligente des ordres
        self.order_type = os.getenv('ORDER_TYPE', 'adaptive')
        self.pending_orders = {}
        self.order_timeout = 300  # 5 minutes
        
        # Générateur de signaux techniques
        self.signal_generator = SignalGenerator()
        
        # Gestionnaires avancés
        self.risk_manager = AdvancedRiskManager()
        self.trailing_stop = TrailingStopManager(float(os.getenv('TRAILING_STOP_PERCENT', '3')))
        self.correlation_manager = CorrelationManager()
        self.multi_tf_analyzer = MultiTimeframeAnalyzer()
        self.safety_manager = SafetyManager(
            max_daily_trades=int(os.getenv('MAX_DAILY_TRADES', '50')),
            max_daily_loss=self.max_daily_loss,
            emergency_stop_loss=float(os.getenv('EMERGENCY_STOP_LOSS', '500'))
        )
        
        # Gestionnaire Earn pour revenus passifs
        self.earn_manager = BinanceEarnManager(self)
        
        # Gestionnaire positions bloquées
        self.stuck_manager = StuckPositionManager(
            max_loss_percent=float(os.getenv('MAX_STUCK_LOSS', '15')),
            stuck_threshold_hours=int(os.getenv('STUCK_THRESHOLD_HOURS', '24'))
        )
        
        # Système de scoring cryptos
        self.crypto_scorer = CryptoScorer(
            min_score=int(os.getenv('MIN_CRYPTO_SCORE', '50')),
            max_tradeable=int(os.getenv('MAX_TRADEABLE_CRYPTOS', '2'))
        )
        
        # Cache analyses techniques (throttling intelligent)
        self.analysis_cache = {}
        self.analysis_cache_timeout = 10  # 10s cache
        self.price_change_threshold = 0.001  # 0.1% variation minimum
        
        # Créer le dossier data s'il n'existe pas
        os.makedirs('data', exist_ok=True)
        
        # File d'affichage asynchrone
        self.display_queue = Queue(maxsize=100)
        self.start_async_display()
        
        if not self.paper_trading:
            self.connect()
        self.load_state()
        
        # Synchronisation initiale (message seulement si erreur)
        if not self.paper_trading:
            try:
                self.sync_positions_from_exchange()
                self.earn_manager.sync_earn_positions_from_api()
                self.websocket.start_user_data_stream(self)
            except Exception as e:
                print(f"⚠️ Erreur sync initiale: {e}")
    
    def start_async_display(self):
        """Démarre le thread d'affichage asynchrone"""
        def display_worker():
            while True:
                try:
                    message = self.display_queue.get(timeout=1)
                    if message is None:  # Signal d'arrêt
                        break
                    print(message)
                    self.display_queue.task_done()
                except:
                    continue
        
        self.display_thread = threading.Thread(target=display_worker, daemon=True)
        self.display_thread.start()
    
    def async_print(self, message):
        """Affichage asynchrone non-bloquant"""
        try:
            self.display_queue.put_nowait(message)
        except:
            pass  # File pleine, ignorer
    
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
            # Supprimer les doublons par order_id avant sauvegarde
            if 'positions' in self.state:
                seen_orders = set()
                unique_positions = []
                for pos in self.state['positions']:
                    order_id = pos.get('order_id')
                    if order_id and order_id in seen_orders:
                        continue  # Doublon, ignorer
                    if order_id:
                        seen_orders.add(order_id)
                    unique_positions.append(pos)
                
                # Trier par ordre chronologique
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
                    # Montants minimums réels selon les paires Binance
                    min_costs = {
                        'BTC/USDT': 5,
                        'ETH/USDT': 10,
                        'SOL/USDT': 8,
                        'BNB/USDT': 12
                    }
                    self.min_amounts[symbol] = {
                        'min_amount': 0.001, 
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
                shortage = cost - self.paper_balance
                if self.earn_manager.withdraw_from_flexible(shortage):
                    print(f"💰 Retrait Earn: {shortage:.2f} USDT pour trade")
                    return True
                else:
                    return False
        else:
            balance = self.get_balance()
            if symbol.endswith('/USDT'):
                available = balance.get('USDT', {}).get('free', 0)
                if cost > available:
                    shortage = cost - available
                    if self.earn_manager.withdraw_from_flexible(shortage):
                        print(f"💰 Retrait Earn: {shortage:.2f} USDT pour trade")
                        return True
                    else:
                        return False
        
        return True
        
    def get_balance(self):
        if self.paper_trading:
            return {'USDT': {'free': self.paper_balance}}
        return self.safe_request(self.exchange.fetch_balance)
    
    def sync_positions_from_exchange(self):
        """Synchronise les positions avec le solde réel Binance + historique trades"""
        if self.paper_trading:
            return
        
        try:
            # 1. Récupérer historique des trades Binance
            self.sync_trade_history()
            
            # 2. Synchroniser positions actuelles
            balance = self.get_balance()
            trading_pairs = os.getenv('TRADING_PAIRS', 'BTCUSDT,ETHUSDT').split(',')
            
            # Garder historique complet (bot + binance)
            all_positions = [p for p in self.state.get('positions', [])]
            active_buy_positions = []
            new_positions = []
            changed = False
            
            for pair in trading_pairs:
                symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
                base_currency = symbol.split('/')[0]
                available = balance.get(base_currency, {}).get('free', 0)
                
                if available > 0.00001:  # Seuil minimum
                    # Chercher dernière position d'achat
                    existing_buys = [p for p in all_positions 
                                   if p['symbol'] == symbol and p['side'] == 'buy']
                    
                    if existing_buys:
                        # Utiliser le dernier achat
                        position = existing_buys[-1].copy()
                        old_amount = position.get('amount', 0)
                        position['amount'] = available
                        active_buy_positions.append(position)
                        
                        if abs(old_amount - available) > 0.00001:
                            changed = True
                    else:
                        # Position inconnue - chercher dans historique Binance
                        last_trade = self.get_last_buy_from_history(symbol)
                        if last_trade:
                            active_buy_positions.append(last_trade)
                        else:
                            # Créer position avec prix actuel
                            current_price = self.get_price(symbol)
                            active_buy_positions.append({
                                'symbol': symbol,
                                'side': 'buy',
                                'amount': available,
                                'price': current_price,
                                'timestamp': datetime.now().isoformat(),
                                'order_id': 'synced',
                                'source': 'binance_manual',
                                'paper': False
                            })
                        new_positions.append(f"{base_currency} {available:.6f}")
                        changed = True
            
            # Détecter suppression
            old_active = [p for p in all_positions if p['side'] == 'buy' and p.get('source') != 'binance_history']
            if len(active_buy_positions) != len(old_active):
                changed = True
            
            # Mettre à jour: historique complet + positions actives
            if changed:
                # Garder historique (ventes) + nouvelles positions actives
                history = [p for p in all_positions if p['side'] == 'sell' or p.get('source') == 'binance_history']
                self.state['positions'] = history + active_buy_positions
                self.save_state()
                
                if new_positions:
                    print(f"🔄 Nouvelle position: {', '.join(new_positions)}")
                
        except Exception as e:
            print(f"⚠️ Erreur sync: {e}")
    
    def sync_trade_history(self):
        """Synchronise l'historique des trades Binance (ajout incrémental)"""
        try:
            trading_pairs = os.getenv('TRADING_PAIRS', 'BTCUSDT,ETHUSDT').split(',')
            new_trades = []
            
            # Créer un set des order_id existants pour vérification rapide
            existing_order_ids = {p.get('order_id') for p in self.state.get('positions', []) if p.get('order_id')}
            
            for pair in trading_pairs:
                symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
                
                # Récupérer trades des dernières 24h
                trades = self.safe_request(self.exchange.fetch_my_trades, symbol, limit=50)
                
                for trade in trades:
                    trade_id = str(trade['id'])
                    
                    # Vérifier si déjà enregistré (rapide avec set)
                    if trade_id in existing_order_ids:
                        continue
                    
                    # Nouveau trade Binance à ajouter
                    position = {
                        'symbol': symbol,
                        'side': trade['side'],
                        'amount': trade['amount'],
                        'price': trade['price'],
                        'timestamp': datetime.fromtimestamp(trade['timestamp']/1000).isoformat(),
                        'order_id': trade_id,
                        'source': 'binance_history',
                        'fee': trade.get('fee', {}).get('cost', 0),
                        'paper': False
                    }
                    new_trades.append(position)
                    existing_order_ids.add(trade_id)  # Ajouter au set
                    print(f"💼 Trade Binance importé: {trade['side'].upper()} {trade['amount']:.6f} {symbol.split('/')[0]} @ {trade['price']:.2f}")
            
            # Ajouter les nouveaux trades et trier par timestamp
            if new_trades:
                self.state['positions'].extend(new_trades)
                # Trier par ordre chronologique
                self.state['positions'].sort(key=lambda x: x['timestamp'])
                self.save_state()
            
        except Exception as e:
            print(f"⚠️ Erreur sync historique: {e}")
    
    def get_last_buy_from_history(self, symbol):
        """Récupère le dernier achat depuis l'historique"""
        buys = [p for p in self.state.get('positions', []) 
               if p['symbol'] == symbol and p['side'] == 'buy' and p.get('source') == 'binance_history']
        return buys[-1] if buys else None
    
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
        # PROTECTION: Vérifier si position ACTIVE déjà ouverte (ignorer historique)
        # Vérifier le solde réel au lieu de l'historique
        balance = self.get_balance()
        base_currency = symbol.split('/')[0]
        current_holding = balance.get(base_currency, {}).get('free', 0)
        
        if current_holding > 0.00001:
            # Vérifier si position est "poussière" (trop petite pour vendre)
            position_value = current_holding * self.get_price(symbol)
            min_trade_value = self.get_min_amount(symbol)['min_cost']
            
            if position_value < min_trade_value:
                # Position poussière - Autoriser nouvel achat
                print(f"🧹 {base_currency} poussière ({position_value:.2f} < {min_trade_value:.2f}) - achat autorisé")
            else:
                # Position normale - Bloquer
                print(f"⚠️ {base_currency} déjà détenu ({position_value:.2f} USDT) - 1 max/crypto")
                return None
        
        if not self.validate_order(symbol, amount):
            return None
        
        price = self.get_price(symbol)
        cost = amount * price
        
        if cost > self.max_daily_loss:
            print(f"❌ Dépassement limite quotidienne: {cost} > {self.max_daily_loss}")
            return None
        
        # Double vérification du solde juste avant l'achat
        if not self.paper_trading:
            balance = self.get_balance()
            available = balance.get('USDT', {}).get('free', 0)
            if cost > available:
                shortage = cost - available
                if not self.earn_manager.withdraw_from_flexible(shortage):
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
                    'source': 'bot',
                    'paper': self.paper_trading
                }
                self.state['positions'].append(position)
                self.save_state()  # Sauvegarde instantanée
                self.total_trades += 1
                print(f"💾 bot_state.json mis à jour (achat)")
                
                if self.notify_trades:
                    mode = "PAPER" if self.paper_trading else "LIVE"
                    self.notifier.notify(f"🟢 {mode} ACHAT: {amount:.6f} {symbol} à {price:.6f}")
            
            return order
        except Exception as e:
            error_msg = str(e)
            print(f"❌ Erreur achat: {error_msg}")
            self.logger.error(f"Erreur achat {symbol}: {error_msg}")
            
            # Notifier l'erreur
            if self.notify_trades and 'insufficient balance' in error_msg.lower():
                self.notifier.notify(f"❌ ERROR ALERT\n🔧 Erreur achat {symbol}: {error_msg}")
            
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
                    'source': 'bot',
                    'paper': self.paper_trading
                }
                self.state['positions'].append(position)
                self.save_state()  # Sauvegarde instantanée
                self.total_trades += 1
                print(f"💾 bot_state.json mis à jour (vente)")
                
                self.calculate_pnl(symbol, 'sell', amount, price)
                
                if self.notify_trades:
                    mode = "PAPER" if self.paper_trading else "LIVE"
                    self.notifier.notify(f"🔴 {mode} VENTE: {amount:.6f} {symbol} à {price:.6f}")
            
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
            balance = self.get_balance()
            usdt_balance = balance.get('USDT', {}).get('free', 0)
            base_currency = symbol.split('/')[0]
            crypto_balance = balance.get(base_currency, {}).get('free', 0)
            
            # Récupérer montant minimum pour cette paire
            min_limits = self.get_min_amount(symbol)
            min_cost = min_limits['min_cost']
            
            # Vérifier si on peut VRAIMENT trader
            can_buy = usdt_balance >= min_cost  # Solde USDT >= minimum paire
            crypto_value = crypto_balance * price
            can_sell = crypto_value >= min_cost  # Valeur crypto >= minimum paire
            
            # Si aucune action possible, skip complètement (pas d'affichage, pas d'analyse)
            if not can_buy and not can_sell:
                return
            
            if not self.paper_trading:
                ticker = self.safe_request(self.exchange.fetch_ticker, symbol)
                change_24h = ticker.get('percentage') or 0
            else:
                change_24h = 2.5
            
            # Affichage prix uniquement (asynchrone)
            self.async_print(f"\n⚡ {symbol} {price:.2f} ({change_24h:+.2f}%)")
            
            if strategy_type == 'intelligent':
                self.intelligent_strategy(symbol, amount, price)
            elif strategy_type == 'adaptive':
                self.adaptive_strategy(symbol, amount, price)
            elif strategy_type == 'scalping':
                self.scalping_strategy(symbol, amount, price)
            elif strategy_type == 'dca':
                self.dca_strategy(symbol, amount, price)
            
        except Exception as e:
            print(f"❌ Erreur stratégie {symbol}: {e}")
    
    def scalping_strategy(self, symbol, amount, current_price):
        # Vérifications de sécurité
        if not self.safety_manager.can_trade():
            return
        
        # Analyse multi-timeframes avec throttling intelligent
        multi_tf_analysis = self.get_cached_analysis(symbol, current_price)
        global_signal = multi_tf_analysis['global_signal']
        
        # Afficher analyse UNIQUEMENT si signal BUY/SELL (asynchrone)
        if global_signal['action'] in ['BUY', 'STRONG_BUY', 'SELL', 'STRONG_SELL']:
            self.async_print(f"🎯 {global_signal['action']} (Force: {global_signal['strength']:.1f}, Confiance: {global_signal['confidence']:.1f}%)")
            self.async_print(f"📝 {global_signal['summary']}")
        
        # Position sizing intelligent
        smart_amount = self.risk_manager.calculate_position_size(self, symbol, amount)
        
        # Logique d'achat avancée
        if (global_signal['action'] in ['BUY', 'STRONG_BUY'] and 
            global_signal['confidence'] >= 60 and
            self.correlation_manager.can_open_position(symbol, self)):
            
            trade_amount = smart_amount / current_price
            print(f"🟢 SIGNAL ACHAT - Montant: {trade_amount:.6f} {symbol.split('/')[0]}")
            
            result = self.buy_market(symbol, trade_amount)
            if result:
                # Activer trailing stop
                self.trailing_stop.add_position(symbol, current_price)
                self.correlation_manager.add_position(symbol)
                self.safety_manager.record_trade(0)
                print(f"✅ Ordre + Trailing Stop activé: {result.get('id', 'N/A')}")
        
        # Mise à jour trailing stop
        self.trailing_stop.update_position(symbol, current_price)
        
        # Logique de vente avancée
        base_currency = symbol.split('/')[0]
        balance = self.get_balance()
        available = balance.get(base_currency, {}).get('free', 0)
        
        if available > 0:
            # Vérifier rentabilité avant vente
            buy_positions = [p for p in self.state['positions'] if p['symbol'] == symbol and p['side'] == 'buy']
            if buy_positions:
                avg_buy_price = sum(p['price'] for p in buy_positions) / len(buy_positions)
                expected_profit_pct = (current_price - avg_buy_price) / avg_buy_price
                min_profit_needed = self.min_profit_threshold + (2 * self.trading_fee)
                
                # PRIORITÉ AU PROFIT: Vendre dès que profit suffisant
                should_sell = (
                    expected_profit_pct >= min_profit_needed or
                    self.trailing_stop.should_stop_loss(symbol, current_price)
                )
                
                if should_sell:
                    print(f"🔴 SIGNAL VENTE - Montant: {available:.6f} {base_currency}")
                    print(f"💰 Profit attendu: {expected_profit_pct*100:+.2f}% (Min: {min_profit_needed*100:.2f}%)")
                    
                    result = self.sell_market(symbol, available)
                    if result:
                        profit = self.calculate_pnl(symbol, 'sell', available, current_price)
                        self.safety_manager.record_trade(profit)
                        
                        self.trailing_stop.remove_position(symbol)
                        self.correlation_manager.remove_position(symbol)
                        print(f"✅ Vente exécutée: {result.get('id', 'N/A')}")
                else:
                    print(f"⏳ Profit insuffisant: {expected_profit_pct*100:+.2f}% < {min_profit_needed*100:.2f}%")
        
        elif available == 0:
            print("🔄 Aucune position - Attente signal d'achat")
        else:
            print("🔄 Signal faible ou conditions non remplies - Attente")
    
    def dca_strategy(self, symbol, amount, current_price):
        trade_amount = amount / current_price
        print(f"⚡ DCA: +{trade_amount:.6f} {symbol.split('/')[0]} @ {current_price/1000:.1f}K")
        
        result = self.buy_market(symbol, trade_amount)
        if not result:
            print("❌ Échec DCA")
    
    def calculate_pnl(self, symbol, side, amount, price):
        if side == 'sell':
            buy_positions = [p for p in self.state['positions'] 
                           if p['symbol'] == symbol and p['side'] == 'buy']
            if buy_positions:
                avg_buy_price = sum(p['price'] for p in buy_positions) / len(buy_positions)
                
                # Calcul avec frais
                buy_cost = avg_buy_price * amount * (1 + self.trading_fee)
                sell_revenue = price * amount * (1 - self.trading_fee)
                pnl = sell_revenue - buy_cost
                
                self.daily_pnl += pnl
                if pnl > 0:
                    self.winning_trades += 1
                
                fee_cost = (avg_buy_price + price) * amount * self.trading_fee
                print(f"💰 P&L: {pnl:+.2f} USDT (Frais: -{fee_cost:.2f})")
                
                return pnl
    
    def on_balance_update(self, data):
        """Callback déclenché lors d'un changement de solde en temps réel"""
        try:
            print(f"⚡ Changement détecté - Sync instantanée...")
            self.sync_positions_from_exchange()
            # Sauvegarder immédiatement
            self.save_state()
            print(f"✅ bot_state.json mis à jour")
        except Exception as e:
            print(f"⚠️ Erreur sync: {e}")
    
    def on_realtime_signal(self, symbol, price):
        """Callback temps réel déclenché par WebSocket"""
        if not self.realtime_trading:
            return
            
        # Éviter les analyses trop fréquentes (max 10 par seconde)
        now = time.time()
        last_time = self.last_analysis.get(symbol, 0)
        if now - last_time < 0.1:  # 100ms entre analyses
            return
        self.last_analysis[symbol] = now
        
        try:
            # Convertir BTCUSDT -> BTC/USDT
            formatted_symbol = f"{symbol[:-4]}/{symbol[-4:]}"
            
            # Exécuter stratégie en temps réel (affichage dans la stratégie)
            strategy_type = os.getenv('STRATEGY_TYPE', 'scalping')
            trade_amount = float(os.getenv('TRADE_AMOUNT', '8'))
            
            if strategy_type == 'intelligent':
                self.realtime_intelligent(formatted_symbol, trade_amount, price)
            elif strategy_type == 'adaptive':
                self.realtime_adaptive(formatted_symbol, trade_amount, price)
            elif strategy_type == 'scalping':
                self.realtime_scalping(formatted_symbol, trade_amount, price)
                
        except Exception as e:
            print(f"❌ Erreur signal temps réel {symbol}: {e}")
    
    def realtime_scalping(self, symbol, amount, current_price):
        """Scalping temps réel déclenché par WebSocket"""
        if not self.safety_manager.can_trade():
            return
        
        # Analyse rapide avec throttling
        multi_tf_analysis = self.get_cached_analysis(symbol, current_price, force=True)
        global_signal = multi_tf_analysis['global_signal']
        
        # Seuil plus élevé pour trading temps réel
        if global_signal['confidence'] < 70:
            return
        
        print(f"🎯 {global_signal['action']} (Confiance: {global_signal['confidence']:.1f}%)")
        
        # Position sizing intelligent
        smart_amount = self.risk_manager.calculate_position_size(self, symbol, amount)
        
        # Logique d'achat temps réel
        if (global_signal['action'] in ['BUY', 'STRONG_BUY'] and 
            self.correlation_manager.can_open_position(symbol, self)):
            
            trade_amount = smart_amount / current_price
            print(f"🟢 ACHAT TEMPS RÉEL: {trade_amount:.6f} {symbol.split('/')[0]}")
            
            result = self.buy_market(symbol, trade_amount)
            if result:
                self.trailing_stop.add_position(symbol, current_price)
                self.correlation_manager.add_position(symbol)
                print(f"⚡ Exécuté en temps réel: {result.get('id', 'N/A')}")
        
        # Mise à jour trailing stop temps réel
        self.trailing_stop.update_position(symbol, current_price)
        
        # Logique de vente temps réel
        base_currency = symbol.split('/')[0]
        balance = self.get_balance()
        available = balance.get(base_currency, {}).get('free', 0)
        
        if available > 0:
            buy_positions = [p for p in self.state['positions'] if p['symbol'] == symbol and p['side'] == 'buy']
            if buy_positions:
                avg_buy_price = sum(p['price'] for p in buy_positions) / len(buy_positions)
                expected_profit_pct = (current_price - avg_buy_price) / avg_buy_price
                min_profit_needed = self.min_profit_threshold + (2 * self.trading_fee)
                
                # PRIORITÉ AU PROFIT: Vendre dès que profit suffisant
                should_sell = (
                    expected_profit_pct >= min_profit_needed or
                    self.trailing_stop.should_stop_loss(symbol, current_price)
                )
                
                if should_sell:
                    print(f"🔴 VENTE TEMPS RÉEL: {available:.6f} {base_currency}")
                    result = self.sell_market(symbol, available)
                    if result:
                        profit = self.calculate_pnl(symbol, 'sell', available, current_price)
                        self.safety_manager.record_trade(profit)
                        self.trailing_stop.remove_position(symbol)
                        self.correlation_manager.remove_position(symbol)
                        print(f"⚡ Vente temps réel exécutée: {result.get('id', 'N/A')}")
    
    def adaptive_strategy(self, symbol, amount, current_price):
        """Stratégie adaptative qui choisit automatiquement scalping ou DCA"""
        if not self.safety_manager.can_trade():
            return
        
        # Analyse multi-timeframes avec throttling
        multi_tf_analysis = self.get_cached_analysis(symbol, current_price)
        global_signal = multi_tf_analysis['global_signal']
        
        # Calculer la volatilité récente
        klines = self.get_klines(symbol, 20)
        if len(klines) >= 10:
            prices = [k['close'] for k in klines[-10:]]
            volatility = (max(prices) - min(prices)) / min(prices) * 100
        else:
            volatility = 5.0  # Valeur par défaut
        
        # Déterminer la stratégie optimale
        strategy_choice = self.choose_optimal_strategy(global_signal, volatility, symbol)
        
        print(f"🧠 STRATÉGIE ADAPTATIVE: {strategy_choice.upper()}")
        print(f"📊 Volatilité: {volatility:.1f}% | Confiance: {global_signal['confidence']:.1f}%")
        print(f"📈 Tendance: {global_signal.get('dominant_trend', 'unknown')}")
        
        # Exécuter la stratégie choisie
        if strategy_choice == 'scalping':
            self.scalping_strategy(symbol, amount, current_price)
        elif strategy_choice == 'dca':
            self.dca_strategy(symbol, amount, current_price)
        elif strategy_choice == 'hold':
            print(f"⏸️ HOLD - Conditions défavorables pour {symbol}")
    
    def choose_optimal_strategy(self, global_signal, volatility, symbol):
        """Choisit la stratégie optimale selon les conditions de marché"""
        action = global_signal['action']
        confidence = global_signal['confidence']
        trend = global_signal.get('dominant_trend', 'neutral')
        
        # Conditions pour SCALPING
        if (volatility >= 3.0 and  # Volatilité suffisante
            confidence >= 65 and  # Confiance élevée
            action in ['BUY', 'STRONG_BUY', 'SELL', 'STRONG_SELL'] and  # Signal clair
            trend in ['bullish', 'neutral']):  # Tendance favorable
            return 'scalping'
        
        # Conditions pour DCA (accumulation)
        elif (trend == 'bearish' and  # Marché baissier
              confidence >= 50 and  # Confiance modérée
              action in ['BUY', 'STRONG_BUY']):  # Signal d'achat
            return 'dca'
        
        # Conditions pour HOLD (attente)
        elif (volatility < 2.0 or  # Faible volatilité
              confidence < 50 or  # Faible confiance
              action == 'HOLD'):  # Signal neutre
            return 'hold'
        
        # Par défaut, scalping modéré
        return 'scalping'
    
    def realtime_adaptive(self, symbol, amount, current_price):
        """Version temps réel de la stratégie adaptative"""
        if not self.safety_manager.can_trade():
            return
        
        # Analyse rapide avec throttling
        multi_tf_analysis = self.get_cached_analysis(symbol, current_price, force=True)
        global_signal = multi_tf_analysis['global_signal']
        
        # Volatilité simplifiée pour temps réel
        klines = self.get_klines(symbol, 10)
        if len(klines) >= 5:
            prices = [k['close'] for k in klines[-5:]]
            volatility = (max(prices) - min(prices)) / min(prices) * 100
        else:
            volatility = 5.0
        
        # Choisir stratégie optimale
        strategy_choice = self.choose_optimal_strategy(global_signal, volatility, symbol)
        
        print(f"⚡ TEMPS RÉEL - {strategy_choice.upper()} (Vol: {volatility:.1f}%)")
        
        # Exécuter selon le choix
        if strategy_choice == 'scalping':
            self.realtime_scalping(symbol, amount, current_price)
        elif strategy_choice == 'dca' and global_signal['action'] in ['BUY', 'STRONG_BUY']:
            # DCA simplifié en temps réel
            trade_amount = amount / current_price
            print(f"🔄 DCA TEMPS RÉEL: {trade_amount:.6f} {symbol.split('/')[0]}")
            result = self.buy_market(symbol, trade_amount)
            if result:
                print(f"⚡ DCA exécuté en temps réel: {result.get('id', 'N/A')}")
        # Si 'hold', ne rien faire
    
    def intelligent_strategy(self, symbol, amount, current_price):
        """Stratégie intelligente qui choisit stratégie ET type d'ordre optimal"""
        if not self.safety_manager.can_trade():
            return
        
        # Analyse complète avec throttling
        multi_tf_analysis = self.get_cached_analysis(symbol, current_price)
        global_signal = multi_tf_analysis['global_signal']
        
        # Calculer métriques de marché
        market_metrics = self.analyze_market_conditions(symbol, current_price)
        
        # Choisir stratégie optimale
        strategy_choice = self.choose_optimal_strategy_advanced(global_signal, market_metrics)
        
        # Choisir type d'ordre optimal
        order_type = self.choose_optimal_order_type(global_signal, market_metrics, strategy_choice)
        
        # Affichage UNIQUEMENT si action (BUY/SELL)
        if strategy_choice in ['scalping', 'dca']:
            print(f"⚡ {symbol} {current_price:.2f} → {strategy_choice.upper()} ({global_signal.get('dominant_trend', 'unknown')} {global_signal['confidence']:.0f}%)")
            print(f"📊 V{market_metrics['volatility']:.1f}% | L:{market_metrics['liquidity']} | S{market_metrics['spread']:.3f}% | 🎯{order_type.upper()}")
        
        # Exécuter avec stratégie et ordre optimaux
        if strategy_choice == 'scalping':
            self.execute_scalping_with_order_type(symbol, amount, current_price, order_type, global_signal)
        elif strategy_choice == 'dca':
            self.execute_dca_with_order_type(symbol, amount, current_price, order_type)
    
    def analyze_market_conditions(self, symbol, current_price):
        """Analyse les conditions de marché pour optimiser les ordres"""
        klines = self.get_klines(symbol, 20)
        
        # Volatilité
        if len(klines) >= 10:
            prices = [k['close'] for k in klines[-10:]]
            volatility = (max(prices) - min(prices)) / min(prices) * 100
        else:
            volatility = 5.0
        
        # Spread estimé (simulation)
        spread = 0.01 if volatility > 5 else 0.005  # 0.01% si volatil, 0.005% si calme
        
        # Liquidité (basée sur le volume)
        if len(klines) >= 5:
            avg_volume = sum(k['volume'] for k in klines[-5:]) / 5
            liquidity = 'high' if avg_volume > 1000000 else 'medium' if avg_volume > 100000 else 'low'
        else:
            liquidity = 'medium'
        
        return {
            'volatility': volatility,
            'spread': spread,
            'liquidity': liquidity,
            'avg_volume': avg_volume if 'avg_volume' in locals() else 500000
        }
    
    def choose_optimal_strategy_advanced(self, global_signal, market_metrics):
        """Choisit la stratégie optimale avec analyse avancée"""
        action = global_signal['action']
        confidence = global_signal['confidence']
        trend = global_signal.get('dominant_trend', 'neutral')
        volatility = market_metrics['volatility']
        liquidity = market_metrics['liquidity']
        
        # SCALPING - Conditions optimales
        if (volatility >= 2.5 and  # Volatilité suffisante
            confidence >= 60 and  # Confiance raisonnable
            liquidity in ['high', 'medium'] and  # Liquidité suffisante
            action in ['BUY', 'STRONG_BUY', 'SELL', 'STRONG_SELL']):
            return 'scalping'
        
        # DCA - Marché baissier ou accumulation
        elif (trend == 'bearish' and
              confidence >= 45 and
              action in ['BUY', 'STRONG_BUY']):
            return 'dca'
        
        # HOLD - Conditions défavorables
        else:
            return 'hold'
    
    def choose_optimal_order_type(self, global_signal, market_metrics, strategy):
        """Choisit le type d'ordre optimal selon les conditions"""
        volatility = market_metrics['volatility']
        spread = market_metrics['spread']
        liquidity = market_metrics['liquidity']
        confidence = global_signal['confidence']
        urgency = global_signal['strength']
        
        # MARKET - Conditions d'urgence
        if (urgency >= 2.0 or  # Signal très fort
            volatility >= 5.0 or  # Marché très volatil
            confidence >= 80 or  # Très haute confiance
            strategy == 'scalping' and confidence >= 70):  # Scalping haute confiance
            return 'market'
        
        # LIMIT - Conditions d'optimisation
        elif (spread >= 0.008 and  # Spread élevé (>0.8%)
              volatility <= 3.0 and  # Marché relativement calme
              liquidity == 'high' and  # Haute liquidité
              confidence >= 65):  # Confiance suffisante
            return 'limit'
        
        # MARKET par défaut (sécurité)
        else:
            return 'market'
    
    def execute_scalping_with_order_type(self, symbol, amount, current_price, order_type, global_signal):
        """Exécute scalping avec type d'ordre optimal"""
        smart_amount = self.risk_manager.calculate_position_size(self, symbol, amount)
        
        # Logique d'achat
        if (global_signal['action'] in ['BUY', 'STRONG_BUY'] and
            self.correlation_manager.can_open_position(symbol, self)):
            
            trade_amount = smart_amount / current_price
            
            if order_type == 'limit':
                # Ordre limite légèrement en dessous du prix actuel
                limit_price = current_price * 0.999  # -0.1%
                result = self.buy_limit(symbol, trade_amount, limit_price)
                print(f"🎯 ACHAT LIMIT: {trade_amount:.6f} {symbol.split('/')[0]} à {limit_price:.6f}")
            else:
                result = self.buy_market(symbol, trade_amount)
                print(f"⚡ ACHAT MARKET: {trade_amount:.6f} {symbol.split('/')[0]}")
            
            if result:
                self.trailing_stop.add_position(symbol, current_price)
                self.correlation_manager.add_position(symbol)
                self.safety_manager.record_trade(0)
        
        # Mise à jour trailing stop
        self.trailing_stop.update_position(symbol, current_price)
        
        # Logique de vente
        self.handle_sell_logic(symbol, current_price, order_type, global_signal)
    
    def execute_dca_with_order_type(self, symbol, amount, current_price, order_type):
        """Exécute DCA avec type d'ordre optimal"""
        trade_amount = amount / current_price
        
        if order_type == 'limit':
            # DCA avec limite pour meilleur prix
            limit_price = current_price * 0.998  # -0.2%
            result = self.buy_limit(symbol, trade_amount, limit_price)
            print(f"🎯 DCA LIMIT: {trade_amount:.6f} {symbol.split('/')[0]} à {limit_price:.6f}")
        else:
            result = self.buy_market(symbol, trade_amount)
            print(f"⚡ DCA MARKET: {trade_amount:.6f} {symbol.split('/')[0]}")
    
    def buy_limit(self, symbol, amount, price):
        """Place un ordre d'achat limite avec gestion intelligente"""
        if not self.validate_order(symbol, amount, price):
            return None
        
        try:
            if self.paper_trading:
                # Simulation ordre limite
                order = {
                    'id': f'limit_{int(time.time())}',
                    'price': price,
                    'amount': amount,
                    'type': 'limit',
                    'side': 'buy',
                    'timestamp': time.time()
                }
                self.pending_orders[order['id']] = order
                print(f"🎯 PAPER - Ordre limite placé: {amount:.6f} {symbol} à {price:.6f}")
                
                # Simuler exécution immédiate si prix favorable
                current_price = self.get_price(symbol)
                if current_price <= price:
                    self.paper_balance -= amount * price
                    del self.pending_orders[order['id']]
                    print(f"✅ PAPER - Ordre exécuté immédiatement")
                    return order
                
                return order
            else:
                order = self.safe_request(self.exchange.create_limit_buy_order, symbol, amount, price)
                if order:
                    self.pending_orders[order['id']] = {
                        'order': order,
                        'timestamp': time.time(),
                        'symbol': symbol
                    }
                    print(f"✅ Ordre limite placé: {order.get('id', 'N/A')}")
                return order
                
        except Exception as e:
            print(f"❌ Erreur ordre limite: {e}")
            return None
    
    def handle_sell_logic(self, symbol, current_price, order_type, global_signal):
        """Gestion intelligente de la vente"""
        base_currency = symbol.split('/')[0]
        balance = self.get_balance()
        available = balance.get(base_currency, {}).get('free', 0)
        
        if available > 0:
            buy_positions = [p for p in self.state['positions'] if p['symbol'] == symbol and p['side'] == 'buy']
            if buy_positions:
                avg_buy_price = sum(p['price'] for p in buy_positions) / len(buy_positions)
                expected_profit_pct = (current_price - avg_buy_price) / avg_buy_price
                min_profit_needed = self.min_profit_threshold + (2 * self.trading_fee)
                
                # PRIORITÉ AU PROFIT: Vendre dès que profit suffisant
                should_sell = (
                    expected_profit_pct >= min_profit_needed or
                    self.trailing_stop.should_stop_loss(symbol, current_price)
                )
                
                if should_sell:
                    if order_type == 'limit' and expected_profit_pct > min_profit_needed * 1.5:
                        # Vente limite pour optimiser le prix
                        limit_price = current_price * 1.001  # +0.1%
                        print(f"🎯 VENTE LIMIT: {available:.6f} {base_currency} à {limit_price:.6f}")
                        # Implémentation sell_limit similaire à buy_limit
                    else:
                        # Vente market pour exécution garantie
                        print(f"⚡ VENTE MARKET: {available:.6f} {base_currency}")
                        result = self.sell_market(symbol, available)
                        if result:
                            profit = self.calculate_pnl(symbol, 'sell', available, current_price)
                            self.safety_manager.record_trade(profit)
                            self.trailing_stop.remove_position(symbol)
                            self.correlation_manager.remove_position(symbol)
    
    def manage_pending_orders(self):
        """Gestion des ordres en attente avec annulation intelligente"""
        current_time = time.time()
        orders_to_cancel = []
        
        for order_id, order_data in self.pending_orders.items():
            # Vérifier timeout
            if current_time - order_data['timestamp'] > self.order_timeout:
                orders_to_cancel.append(order_id)
                print(f"⏰ Timeout ordre {order_id} - Annulation")
            
            # Vérifier si le prix s'éloigne trop
            elif 'symbol' in order_data:
                symbol = order_data['symbol']
                current_price = self.get_price(symbol)
                order_price = order_data['order']['price']
                price_diff = abs(current_price - order_price) / order_price
                
                if price_diff > 0.02:  # 2% d'écart
                    orders_to_cancel.append(order_id)
                    print(f"📈 Prix éloigné pour ordre {order_id} - Annulation")
        
        # Annuler les ordres identifiés
        for order_id in orders_to_cancel:
            self.cancel_order(order_id)
    
    def cancel_order(self, order_id):
        """Annule un ordre en attente"""
        try:
            if order_id in self.pending_orders:
                if self.paper_trading:
                    del self.pending_orders[order_id]
                    print(f"❌ PAPER - Ordre annulé: {order_id}")
                else:
                    order_data = self.pending_orders[order_id]
                    self.safe_request(self.exchange.cancel_order, order_id, order_data['symbol'])
                    del self.pending_orders[order_id]
                    print(f"❌ Ordre annulé: {order_id}")
        except Exception as e:
            print(f"⚠️ Erreur annulation ordre {order_id}: {e}")
    
    def realtime_intelligent(self, symbol, amount, current_price):
        """Version temps réel de la stratégie intelligente"""
        if not self.safety_manager.can_trade():
            return
        
        # Analyse rapide avec throttling
        multi_tf_analysis = self.get_cached_analysis(symbol, current_price, force=True)
        global_signal = multi_tf_analysis['global_signal']
        market_metrics = self.analyze_market_conditions(symbol, current_price)
        
        # Choisir stratégie et ordre optimaux
        strategy_choice = self.choose_optimal_strategy_advanced(global_signal, market_metrics)
        order_type = self.choose_optimal_order_type(global_signal, market_metrics, strategy_choice)
        
        # Gérer les ordres en attente
        self.manage_pending_orders()
        
        # Exécuter selon le choix
        if strategy_choice == 'scalping':
            self.execute_scalping_with_order_type(symbol, amount, current_price, order_type, global_signal)
        elif strategy_choice == 'dca' and global_signal['action'] in ['BUY', 'STRONG_BUY']:
            self.execute_dca_with_order_type(symbol, amount, current_price, order_type)
    
    def get_cached_analysis(self, symbol, current_price, force=False):
        """Récupère analyse depuis cache ou calcule si nécessaire (throttling intelligent)"""
        cache_key = f"analysis_{symbol}"
        now = time.time()
        
        # Vérifier si cache existe et valide
        if cache_key in self.analysis_cache and not force:
            cached = self.analysis_cache[cache_key]
            age = now - cached['timestamp']
            
            # Cache valide si < 10s ET prix n'a pas bougé significativement
            if age < self.analysis_cache_timeout:
                price_change = abs(current_price - cached['price']) / cached['price']
                
                if price_change < self.price_change_threshold:
                    # Réutiliser cache (marché calme)
                    return cached['analysis']
        
        # Cache invalide ou mouvement significatif → Nouvelle analyse
        analysis = self.multi_tf_analyzer.analyze_all_timeframes(self, symbol, current_price)
        
        # Mettre en cache
        self.analysis_cache[cache_key] = {
            'analysis': analysis,
            'price': current_price,
            'timestamp': now
        }
        
        return analysis
    
    def show_realtime_prices(self, trading_pairs):
        """Affiche les prix en temps réel (format compact, asynchrone)"""
        prices = []
        for pair in trading_pairs:
            symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
            try:
                price = self.get_price(symbol)
                crypto = symbol.split('/')[0]
                # Format intelligent selon le prix
                if price >= 10000:
                    price_str = f"{price/1000:.1f}K"
                elif price >= 1000:
                    price_str = f"{price/1000:.2f}K"
                else:
                    price_str = f"{price:.0f}"
                prices.append(f"{crypto} {price_str}")
            except Exception as e:
                prices.append(f"{symbol.split('/')[0]} ERR")
        
        self.async_print(f"\n⚡ {datetime.now().strftime('%H:%M:%S')} | {' | '.join(prices)}")
    
    def ensure_trading_balance(self, trade_amount):
        """Assure qu'il y a assez de solde pour trader en retirant de Earn si nécessaire"""
        if self.paper_trading:
            return
        
        try:
            balance = self.get_balance()
            available = balance.get('USDT', {}).get('free', 0)
            needed_balance = trade_amount * 1.2
            
            if available < needed_balance:
                shortage = needed_balance - available
                if self.earn_manager.withdraw_from_flexible(shortage):
                    time.sleep(2)
        except Exception as e:
            pass
    
    def check_and_recover_stuck_positions(self):
        """Vérifie et récupère les positions bloquées"""
        # Vérifier uniquement les positions ACTIVES (solde réel)
        balance = self.get_balance()
        
        for pair in os.getenv('TRADING_PAIRS', 'BTCUSDT,ETHUSDT').split(','):
            symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
            base_currency = symbol.split('/')[0]
            current_holding = balance.get(base_currency, {}).get('free', 0)
            
            # Ignorer si pas de solde réel
            if current_holding <= 0.00001:
                continue
            
            position_value = current_holding * self.get_price(symbol)
            min_trade_value = self.get_min_amount(symbol)['min_cost']
            
            # Ignorer les positions poussière
            if position_value < min_trade_value:
                continue
            
            # Trouver la DERNIÈRE position d'achat (la plus récente)
            buy_positions = [p for p in self.state['positions'] 
                           if p['symbol'] == symbol and p['side'] == 'buy']
            
            if not buy_positions:
                continue
            
            # Utiliser la position la plus récente
            latest_position = buy_positions[-1]
            buy_price = latest_position['price']
            buy_time = datetime.fromisoformat(latest_position['timestamp']).timestamp()
            current_price = self.get_price(symbol)
            
            is_stuck, loss_percent = self.stuck_manager.check_stuck_position(
                symbol, current_price, buy_price, buy_time
            )
            
            if is_stuck:
                self.stuck_manager.execute_recovery(self, symbol, current_price)
    
    def show_spot_balances(self, trading_pairs):
        """Affiche tous les soldes Spot disponibles sur une ligne"""
        balance = self.get_balance()
        balances = []
        
        # USDT toujours en premier
        usdt = balance.get('USDT', {}).get('free', 0)
        if usdt > 0.01:
            balances.append(f"USDT {usdt:.2f}")
        
        # Autres cryptos
        for pair in trading_pairs:
            symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
            crypto = symbol.split('/')[0]
            amount = balance.get(crypto, {}).get('free', 0)
            if amount > 0.00001:
                balances.append(f"{crypto} {amount:.6f}")
        
        if balances:
            print(f"💳 SPOT: {' | '.join(balances)}")
        else:
            print(f"💳 SPOT: Vide")
    
    def show_performance(self):
        if os.getenv('SHOW_PERFORMANCE', 'True') != 'True':
            return
        
        # Stats compactes
        win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0
        print(f"\n📊 {self.daily_pnl:+.2f} | {self.total_trades} trades ({win_rate:.0f}% win)")
        
        # Cache pour éviter appels répétés
        balance = self.get_balance()
        trading_pairs = os.getenv('TRADING_PAIRS', 'BTCUSDT,ETHUSDT').split(',')
        min_profit_needed = self.min_profit_threshold + (2 * self.trading_fee)
        target_pct = min_profit_needed * 100
        
        # Positions ouvertes (1 seule boucle)
        has_positions = False
        for pair in trading_pairs:
            symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
            base_currency = symbol.split('/')[0]
            current_holding = balance.get(base_currency, {}).get('free', 0)
            
            if current_holding <= 0.00001:
                continue
            
            # Vérifications rapides
            current_price = self.get_price(symbol)
            position_value = current_holding * current_price
            
            if position_value < self.get_min_amount(symbol)['min_cost']:
                continue
            
            # Trouver dernière position (bot prioritaire)
            buy_positions = [p for p in self.state['positions'] 
                           if p['symbol'] == symbol and p['side'] == 'buy' 
                           and p.get('source') != 'binance_history']
            
            if not buy_positions:
                buy_positions = [p for p in self.state['positions'] 
                               if p['symbol'] == symbol and p['side'] == 'buy']
            
            if not buy_positions:
                continue
            
            has_positions = True
            buy_price = buy_positions[-1]['price']
            pnl_pct = ((current_price - buy_price) / buy_price) * 100
            
            # Affichage conditionnel compact (asynchrone)
            if pnl_pct >= min_profit_needed * 100:
                self.async_print(f"🎯 {base_currency} {current_holding:.6f} @ {buy_price:.2f} → {current_price:.2f} ({pnl_pct:+.2f}%) ✅")
            elif pnl_pct < 0:
                target_price = buy_price * (1 + min_profit_needed)
                self.async_print(f"🔴 {base_currency} {current_holding:.6f} @ {buy_price:.2f} → {current_price:.2f} ({pnl_pct:+.2f}%/+{target_pct:.2f}%)")
            else:
                target_price = buy_price * (1 + min_profit_needed)
                progress = int((pnl_pct / target_pct) * 100)
                self.async_print(f"⏳ {base_currency} {current_holding:.6f} @ {buy_price:.2f} → {current_price:.2f} ({pnl_pct:+.2f}%/+{target_pct:.2f}%) {progress}%")
        
        if not has_positions:
            print(f"⏳ Aucune position")
        
        self.stuck_manager.show_stuck_positions()
    
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
        
        mode = "PAPER" if self.paper_trading else "LIVE"
        realtime = "⚡ TEMPS RÉEL" if self.realtime_trading else "🔄 CYCLIQUE"
        cryptos = ', '.join([p.replace('USDT', '') for p in trading_pairs])
        positions = len([p for p in self.state['positions'] if p['side'] == 'buy'])
        earn_status = "Earn ON" if os.getenv('TIRELIRE_MODE', 'False') == 'True' else "Earn OFF"
        
        print(f"🤖 Bot {strategy_type.upper()} | {mode} {realtime} | {positions} positions")
        print(f"📊 {cryptos} | {trade_amount} USDT/trade | Seuil 70% | {earn_status}")
        print("🛑 Ctrl+C pour arrêter")
        
        if backtesting:
            self.run_backtest()
            return
        
        if self.notify_trades:
            self.notifier.notify(f"🤖 Bot démarré - {mode}")
        
        try:
            while True:
                self.show_performance()
                self.show_spot_balances(trading_pairs)
                self.earn_manager.show_earn_performance()
                self.show_realtime_prices(trading_pairs)
                
                # Vérifier et récupérer positions bloquées
                self.check_and_recover_stuck_positions()
                
                # Retrait préventif de Earn si solde faible
                self.ensure_trading_balance(trade_amount)
                
                # Allocation automatique vers Earn
                self.earn_manager.auto_allocate_idle_funds()
                
                # Synchroniser positions en temps réel
                self.sync_positions_from_exchange()
                
                # Filtrer paires tradables (solde suffisant pour acheter OU vendre)
                balance = self.get_balance()
                usdt_available = balance.get('USDT', {}).get('free', 0)
                tradable_pairs = []
                
                for pair in trading_pairs:
                    symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
                    base_currency = symbol.split('/')[0]
                    crypto_balance = balance.get(base_currency, {}).get('free', 0)
                    min_cost = self.get_min_amount(symbol)['min_cost']
                    price = self.get_price(symbol)
                    
                    # Tradable si: solde USDT suffisant OU crypto vendable
                    can_buy = usdt_available >= min_cost
                    can_sell = (crypto_balance * price) >= min_cost
                    
                    if can_buy or can_sell:
                        tradable_pairs.append(symbol)
                
                # Traiter uniquement paires tradables
                if tradable_pairs:
                    # Vérifier positions existantes à vendre
                    for symbol in tradable_pairs:
                        base_currency = symbol.split('/')[0]
                        available = balance.get(base_currency, {}).get('free', 0)
                        if available > 0:
                            self.execute_strategy(symbol, strategy_type, trade_amount)
                    
                    # Nouveaux achats si solde USDT suffisant
                    if usdt_available >= trade_amount:
                        stuck_positions = self.stuck_manager.stuck_positions
                        best_cryptos = self.crypto_scorer.rank_cryptos(self, trading_pairs, stuck_positions)
                        
                        if best_cryptos:
                            print(f"\n🎯 NOUVEAUX ACHATS: {', '.join(best_cryptos)}")
                            for symbol in best_cryptos:
                                self.execute_strategy(symbol, strategy_type, trade_amount)
                
                time.sleep(check_interval)
                
        except KeyboardInterrupt:
            print("\n🛑 Arrêt du bot...")
            if self.notify_trades:
                self.notifier.notify("🛑 Bot arrêté")
            if hasattr(self, 'websocket'):
                self.websocket.stop()
            self.save_state()