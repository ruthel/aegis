import time
import json
import os
import threading
import logging
import subprocess
import sys
from queue import Queue
from datetime import datetime

# Exchange
from core.exchange.factory import create_exchange_client

# Managers
from core.managers.notification import NotificationManager
from core.managers.balance import BalanceManager

# WebSocket
from core.websocket import WebSocketManager

# Utils
from utils.risk_manager import RiskManager, TrailingStopManager, CorrelationManager
from utils.timeframe_analyzer import TimeframeAnalyzer
from utils.position_manager import PositionManager
from utils.pattern_analyzer import PatternAnalyzer
from utils.market_analyzer import MarketAnalyzer
from utils.capital_manager import CapitalManager

# Mixins
from core.bot.trading import TradingMixin
from core.bot.sync import SyncMixin
from core.bot.analysis import AnalysisMixin
from core.bot.display import DisplayMixin

class TradingBot(TradingMixin, SyncMixin, AnalysisMixin, DisplayMixin):
    """Bot de trading multi-exchange avec stratégies avancées"""
    
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
        self.max_daily_trades = int(os.getenv('MAX_DAILY_TRADES', '50'))
        self.stop_loss_percent = float(os.getenv('STOP_LOSS_PERCENT', '5'))
        self.save_logs = os.getenv('SAVE_LOGS', 'True') == 'True'
        
        # Frais dynamiques (remplace frais statiques)
        self.trading_fee = 0.001  # Fallback seulement
        self.min_profit_threshold = float(os.getenv('MIN_PROFIT_THRESHOLD', '0.8')) / 100
        
        # Stats
        self.daily_pnl = 0
        self.total_trades = 0
        self.winning_trades = 0
        self.global_stats_30d = None  # Win rate global 30 jours
        self.last_winrate_calculation = 0  # Timestamp dernier calcul
        
        self.setup_logging()
        
        # Notifications TOUJOURS activées
        self.notifier = NotificationManager()
        self.notifier.set_bot(self)
        
        # WebSocket (démarré après connect() et load_state())
        self.websocket = WebSocketManager()
        self.websocket.set_bot_callback(self.on_realtime_signal)
        self.websocket.set_balance_callback(self.on_balance_update)
        
        # Trading temps réel (TOUJOURS activé par défaut)
        self.realtime_trading = False  # Activé après init complète
        self.last_analysis = {}
        
        # Détection tendance cumulative
        self.cumulative_tracker = {}  # {symbol: {'direction': 1/-1, 'count': 0, 'start_price': 0}}
        self.last_dynamic_notifications = {}  # Éviter notifications consécutives identiques
        
        # NOUVEAU: Cache centralisé support touch (approche institutionnelle)
        self.support_touch_cache = {}  # {symbol: {'result': {...}, 'timestamp': float}}
        
        # NOUVEAU: Cache de décisions unifié - Niveau Institutionnel
        self.decision_cache = {}  # {symbol: {'decision': bool, 'reason': str, 'timestamp': float}}
        self._last_decision = {}  # Anti-spam logs
        self._decision_log_throttle = {}
        self.decision_journal_file = os.getenv('DECISION_JOURNAL_FILE', 'data/decision_journal.jsonl')
        self.decision_journal_max = int(os.getenv('DECISION_JOURNAL_MAX', '500'))
        self._decision_journal_since_compact = 0
        self.symbol_cooldown_seconds = int(os.getenv('SYMBOL_COOLDOWN_SECONDS', '300'))
        self.symbol_failure_cooldown_seconds = int(os.getenv('SYMBOL_FAILURE_COOLDOWN_SECONDS', '120'))
        self.market_regime_filter = os.getenv('MARKET_REGIME_FILTER', 'True').lower() == 'true'
        self.falling_knife_filter = os.getenv('FALLING_KNIFE_FILTER', 'True').lower() == 'true'
        self.require_reversal_in_bear = os.getenv('REQUIRE_REVERSAL_CONFIRMATION_IN_BEAR', 'True').lower() == 'true'
        self.bear_mode_trade_multiplier = float(os.getenv('BEAR_MODE_TRADE_MULTIPLIER', '0.35'))
        self.bear_mode_min_confidence_bonus = float(os.getenv('BEAR_MODE_MIN_CONFIDENCE_BONUS', '20'))
        self.bear_mode_support_touch_override = os.getenv('BEAR_MODE_SUPPORT_TOUCH_OVERRIDE', 'False').lower() == 'true'
        self.bear_mode_allowed_pairs = {
            pair.strip() for pair in os.getenv('BEAR_MODE_ALLOWED_PAIRS', 'BTC/USD,ETH/USD').split(',')
            if pair.strip()
        }
        self.market_context_cache_seconds = int(os.getenv('MARKET_CONTEXT_CACHE_SECONDS', '300'))
        self.market_context_cache = {}
        self.support_touch_adaptive_filter = os.getenv('SUPPORT_TOUCH_ADAPTIVE_FILTER', 'True').lower() == 'true'
        self.support_touch_backtest_interval = 5 * 60
        self.support_touch_min_trades = int(os.getenv('SUPPORT_TOUCH_MIN_TRADES', '10'))
        self.support_touch_min_winrate = float(os.getenv('SUPPORT_TOUCH_MIN_WINRATE', '50'))
        self.support_touch_min_total_pnl = float(os.getenv('SUPPORT_TOUCH_MIN_TOTAL_PNL', '0'))
        self.support_touch_min_avg_pnl = float(os.getenv('SUPPORT_TOUCH_MIN_AVG_PNL', '0'))
        self.support_touch_fail_closed = os.getenv('SUPPORT_TOUCH_FAIL_CLOSED', 'True').lower() == 'true'
        self.support_touch_backtest_file = os.getenv('SUPPORT_TOUCH_BACKTEST_FILE', 'data/support_touch_backtest_auto.json')
        self.support_touch_backtest_timeout = int(os.getenv('SUPPORT_TOUCH_BACKTEST_TIMEOUT_SECONDS', '90'))
        
        # Ordres
        self.pending_orders = {}
        self.order_timeout = 86400
        
        # Gestionnaires (nommage cohérent)
        self.risk_manager = RiskManager(
            max_daily_trades=self.max_daily_trades,
            max_daily_loss=self.max_daily_loss,
            emergency_stop_loss=float(os.getenv('EMERGENCY_STOP_LOSS', '500'))
        )
        self.risk_manager.bot = self  # Référence pour les méthodes adaptatives
        self.trailing_stop_manager = TrailingStopManager(float(os.getenv('TRAILING_STOP_PERCENT', '3')))
        self.correlation_manager = CorrelationManager()
        
        # NOUVEAUX DÉTECTEURS CRITIQUES

        self.multi_tf_analyzer = TimeframeAnalyzer()

        self.stuck_manager = PositionManager(
            self,
            max_loss_percent=float(os.getenv('MAX_STUCK_LOSS', '15')),
            stuck_threshold_hours=int(os.getenv('STUCK_THRESHOLD_HOURS', '24'))
        )
        self.market_analyzer = MarketAnalyzer(
            min_score=int(os.getenv('MIN_CRYPTO_SCORE', '40'))
        )


        self.pattern_analyzer = PatternAnalyzer(self)
        self.price_change_threshold = 0.002  # 0.2% au lieu de 0.1%
        
        # Gestionnaire de balance centralisé
        self.balance_manager = BalanceManager(self)
        
        # Gestionnaire de capital automatique
        self.capital_manager = CapitalManager(self)
        

        
        # Gestionnaire de dust (valeurs très petites)

        
        # GESTIONNAIRES PROFESSIONNELS NIVEAU INSTITUTIONNEL


        
        os.makedirs('data', exist_ok=True)
        
        # Affichage async
        self.display_queue = Queue(maxsize=100)
        
        # Toujours connecter pour éviter les erreurs, même en paper trading
        self.connect()
        self.load_state()
        self.websocket.set_exchange_client(self.exchange)
        self.websocket.preload_klines(self.exchange)
        self.websocket.start()
        self.refresh_support_touch_filter()
        
        # Initialiser l'affichage async
        self.start_async_display()
        
        # Sync initiale
        if not self.paper_trading:
            try:
                self.sync_positions_from_exchange()
            except Exception as e:
                print(f"⚠️ Erreur sync initiale: {e}")
        
        # Ajustement automatique selon le capital
        self.capital_manager.auto_adjust_bot()
        print()  # Ligne vide après l'analyse du capital
        
        # Calculer win rate global 30 jours au démarrage
        if not self.paper_trading:
            print("📊 Calcul win rate global (30 derniers jours)...")
            self.global_stats_30d = self.calculate_winrate_30d()
            print()
        
        # NOUVEAU: Placer automatiquement les cryptos disponibles en mode vente au démarrage
        print("\n🔍 Vérification positions existantes...")
        self._optimize_all_positions_at_startup()
        
        # Notification de démarrage
        mode = "PAPER" if self.paper_trading else "LIVE"
        self.notifier.notify(f"🤖 Bot démarré - {mode}")
        self.realtime_trading = True  # Init complète, activer le trading
    
    def _place_paper_sell_order(self, symbol):
        """Place un ordre limite de vente paper au prix cible (0.8% profit)"""
        buy_price = self.get_real_buy_price(symbol)
        if not buy_price:
            return
        
        # Calculer quantité depuis positions ouvertes
        net_amount = 0
        for p in self.state.get('positions', []):
            if p.get('symbol') == symbol:
                amt = float(p.get('amount', 0))
                if p.get('side') == 'buy':
                    net_amount += amt
                elif p.get('side') == 'sell':
                    net_amount -= amt
        
        if net_amount <= 0.00001:
            return
        
        # Prix cible = buy_price + MIN_PROFIT_THRESHOLD
        target_price = buy_price * (1 + self.min_profit_threshold)
        crypto = symbol.split('/')[0]
        
        # Vérifier si ordre paper déjà existant pour ce symbol
        for oid, od in self.pending_orders.items():
            if od.get('symbol') == symbol and od.get('side') == 'sell':
                return  # Déjà un ordre actif
        
        order_id = f'paper_sell_{symbol.replace("/", "_")}_{int(time.time())}'
        order = {'id': order_id, 'price': target_price, 'amount': net_amount, 'type': 'limit', 'side': 'sell'}
        self.pending_orders[order_id] = {
            'order': order, 'timestamp': time.time(), 'symbol': symbol, 'side': 'sell'
        }
        profit_pct = self.min_profit_threshold * 100
        print(f"🎯 PAPER {crypto} → Ordre vente @ {target_price:.2f} (+{profit_pct:.1f}%) | Qty: {net_amount:.6f}")

    def _optimize_all_positions_at_startup(self):
        """Optimise TOUTES les positions existantes au démarrage - SANS annuler ordres existants"""
        try:
            trading_pairs = os.getenv('TRADING_PAIRS', 'BTCUSD,ETHUSD').split(',')
            balance = self.balance_manager.get_balance(force_refresh=True)
            
            optimized_count = 0
            skipped_count = 0
            
            for pair in trading_pairs:
                symbol = pair if '/' in pair else (f"{pair.strip()[:-3]}/{pair.strip()[-3:]}" if pair.strip().endswith('USD') else f"{pair.strip()[:3]}/{pair.strip()[3:]}")
                base_currency = symbol.split('/')[0]
                
                if self.paper_trading:
                    # En paper: vérifier positions dans le state
                    net_amount = 0
                    for p in self.state.get('positions', []):
                        if p.get('symbol') == symbol:
                            amt = float(p.get('amount', 0))
                            if p.get('side') == 'buy':
                                net_amount += amt
                            elif p.get('side') == 'sell':
                                net_amount -= amt
                    
                    if net_amount > 0.00001:
                        current_price = self.get_price(symbol)
                        position_value = net_amount * current_price
                        min_cost = self.get_min_amount(symbol)['min_cost']
                        if position_value >= min_cost:
                            print(f"   📊 {base_currency}: {net_amount:.6f} détecté (paper)")
                            self._place_paper_sell_order(symbol)
                            optimized_count += 1
                else:
                    # Mode réel: vérifier balance exchange
                    free_holding = balance.get(base_currency, {}).get('free', 0)
                    locked_holding = balance.get(base_currency, {}).get('used', 0)
                    total_holding = free_holding + locked_holding
                    
                    if total_holding > 0.00001:
                        position_value = total_holding * self.get_price(symbol)
                        min_cost = self.get_min_amount(symbol)['min_cost']
                        
                        if position_value >= min_cost:
                            print(f"   📊 {base_currency}: {total_holding:.6f} détecté (Libre: {free_holding:.6f}, Verrouillé: {locked_holding:.6f})")
                            
                            if locked_holding > 0.00001:
                                print(f"   ✅ {base_currency}: Ordre déjà actif - Conservé")
                                skipped_count += 1
                                continue
                            
                            if self.optimize_existing_position(symbol):
                                optimized_count += 1
            
            if optimized_count > 0:
                print(f"✅ {optimized_count} position(s) optimisée(s) au démarrage")
            if skipped_count > 0:
                print(f"⏭️ {skipped_count} position(s) déjà optimisée(s) - Conservées")
            if optimized_count == 0 and skipped_count == 0:
                print("✅ Aucune position à optimiser")
            print()  # Ligne vide finale
                
        except Exception as e:
            print(f"⚠️ Erreur optimisation démarrage: {e}\n")
    
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
    
    def connect(self, verbose=True):
        self.exchange = create_exchange_client(self.api_key, self.api_secret, self.testnet, verbose=verbose)
    
    def reconnect(self):
        for attempt in range(self.max_retries):
            try:
                self.connect(verbose=False)
                self.exchange.fetch_balance()
                return True
            except Exception as e:
                if self._is_non_retryable_api_error(e):
                    print(f"❌ Reconnexion impossible: {self._api_error_hint(e)}")
                    return False
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
                if self._is_non_retryable_api_error(e):
                    print(f"❌ Erreur API non récupérable: {self._api_error_hint(e)}")
                    raise e
                if attempt < self.max_retries - 1:
                    if self.reconnect():
                        continue
                    time.sleep(self.retry_delay)
                else:
                    print(f"❌ Erreur API: {e}")
                    raise e

    def _is_non_retryable_api_error(self, error):
        """Détecte les erreurs qui ne seront pas corrigées par une reconnexion."""
        try:
            import ccxt
            return isinstance(error, (ccxt.AuthenticationError, ccxt.PermissionDenied))
        except Exception:
            message = str(error).lower()
            return 'permission denied' in message or 'authentication' in message

    def _api_error_hint(self, error):
        message = str(error)
        if 'permission denied' in message.lower():
            return "clé API refusée par l'exchange; vérifier permissions, restrictions IP et clé secrète"
        return message
    
    def load_state(self):
        loaded = False
        for path in [self.state_file, self.state_file + '.tmp']:
            if os.path.exists(path):
                try:
                    with open(path, 'r') as f:
                        self.state = json.load(f)
                    self._ensure_state_defaults()
                    if self.paper_trading:
                        self._restore_paper_balance()
                    self._restore_trailing_stops_from_state()
                    loaded = True
                    break
                except Exception as e:
                    print(f"⚠️ Erreur chargement {path}: {e}")
        if not loaded:
            self.state = {'positions': [], 'last_update': None}
        self._ensure_state_defaults()

    def _ensure_state_defaults(self):
        self.state.setdefault('positions', [])
        self.state.setdefault('decision_journal', [])
        self.state.setdefault('symbol_cooldowns', {})
        self.state.setdefault('support_touch_filter', {'last_run_ts': 0, 'pairs': {}})
        self.state.setdefault('market_context', {})
        if len(self.state['decision_journal']) > self.decision_journal_max:
            self.state['decision_journal'] = self.state['decision_journal'][-self.decision_journal_max:]

    def _restore_paper_balance(self):
        """Restaure l'USD paper depuis le state, ou le reconstruit pour les anciens fichiers."""
        saved_balance = self.state.get('paper_balance')
        if saved_balance is not None:
            self.paper_balance = float(saved_balance)
            return

        initial_balance = float(os.getenv('PAPER_BALANCE', '1000'))
        balance = initial_balance
        for position in self.state.get('positions', []):
            amount = float(position.get('amount', 0) or 0)
            price = float(position.get('price', 0) or 0)
            value = amount * price
            if position.get('side') == 'buy':
                balance -= value
            elif position.get('side') == 'sell':
                balance += value

        self.paper_balance = max(0, balance)

    def _restore_trailing_stops_from_state(self):
        """Restaure les trailing stops en mémoire pour les positions ouvertes."""
        if not hasattr(self, 'trailing_stop_manager'):
            return

        open_positions = {}
        for position in self.state.get('positions', []):
            symbol = position.get('symbol')
            amount = float(position.get('amount', 0) or 0)
            if not symbol or amount <= 0:
                continue

            data = open_positions.setdefault(symbol, {'amount': 0, 'last_buy_price': None})
            if position.get('side') == 'buy':
                data['amount'] += amount
                data['last_buy_price'] = float(position.get('price', 0) or 0)
            elif position.get('side') == 'sell':
                data['amount'] -= amount

        for symbol, data in open_positions.items():
            if data['amount'] > 0.00001 and data['last_buy_price']:
                self.trailing_stop_manager.add_position(symbol, data['last_buy_price'])
    
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
            if self.paper_trading:
                self.state['paper_balance'] = self.paper_balance
            if 'decision_journal' in self.state and len(self.state['decision_journal']) > self.decision_journal_max:
                self.state['decision_journal'] = self.state['decision_journal'][-self.decision_journal_max:]
            self.state['last_update'] = datetime.now().isoformat()
            # Écriture atomique pour éviter que le dashboard lise un fichier incomplet
            tmp_file = self.state_file + '.tmp'
            with open(tmp_file, 'w') as f:
                json.dump(self.state, f, indent=2)
            os.replace(tmp_file, self.state_file)
        except Exception as e:
            print(f"⚠️ Erreur sauvegarde état: {e}")

    def record_decision(self, symbol, action, allowed, reason, metrics=None, throttle_seconds=60):
        """Journalise les décisions importantes sans spammer les skips identiques."""
        try:
            now = time.time()
            throttle_key = f"{symbol}:{action}:{allowed}:{reason}"
            if throttle_seconds and now - self._decision_log_throttle.get(throttle_key, 0) < throttle_seconds:
                return
            self._decision_log_throttle[throttle_key] = now

            entry = {
                'timestamp': datetime.now().isoformat(),
                'symbol': symbol,
                'action': action,
                'allowed': bool(allowed),
                'reason': reason,
                'mode': 'paper' if self.paper_trading else 'live',
                'metrics': metrics or {}
            }

            self.state.setdefault('decision_journal', []).append(entry)
            self.state['decision_journal'] = self.state['decision_journal'][-self.decision_journal_max:]

            os.makedirs(os.path.dirname(self.decision_journal_file) or '.', exist_ok=True)
            with open(self.decision_journal_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
            self._compact_decision_journal_file()
        except Exception:
            pass

    def _compact_decision_journal_file(self):
        """Garde le JSONL borné sur disque sans le réécrire à chaque décision."""
        try:
            self._decision_journal_since_compact += 1
            compact_every = max(50, self.decision_journal_max // 5)
            if self._decision_journal_since_compact < compact_every:
                return
            self._decision_journal_since_compact = 0

            if not os.path.exists(self.decision_journal_file):
                return

            with open(self.decision_journal_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            keep = max(self.decision_journal_max, 1)
            if len(lines) <= keep + compact_every:
                return

            temp_file = f"{self.decision_journal_file}.tmp"
            with open(temp_file, 'w', encoding='utf-8') as f:
                f.writelines(lines[-keep:])
            os.replace(temp_file, self.decision_journal_file)
        except Exception:
            pass

    def get_symbol_cooldown_remaining(self, symbol):
        cooldown_until = float(self.state.get('symbol_cooldowns', {}).get(symbol, 0) or 0)
        return max(0, int(cooldown_until - time.time()))

    def is_symbol_on_cooldown(self, symbol):
        return self.get_symbol_cooldown_remaining(symbol) > 0

    def set_symbol_cooldown(self, symbol, seconds=None, reason='action'):
        seconds = self.symbol_cooldown_seconds if seconds is None else int(seconds)
        if seconds <= 0:
            return

        self.state.setdefault('symbol_cooldowns', {})[symbol] = time.time() + seconds
        self.record_decision(
            symbol, 'cooldown', False, reason,
            {'cooldown_seconds': seconds}, throttle_seconds=0
        )
        self.save_state()

    def _is_bear_regime(self, regime):
        return regime in ['BEAR_WEAK', 'BEAR_STRONG', 'VOLATILE']

    def _normalize_symbol(self, pair):
        pair = pair.strip()
        if '/' in pair:
            return pair
        if pair.endswith('USD'): return f"{pair[:-3]}/USD"
        return pair

    def _calculate_momentum_pct(self, klines, periods):
        if len(klines) <= periods:
            return 0
        old_price = float(klines[-periods]['close'] or 0)
        new_price = float(klines[-1]['close'] or 0)
        if old_price <= 0:
            return 0
        return ((new_price - old_price) / old_price) * 100

    def _detect_falling_knife(self, symbol):
        """Détecte une chute structurelle pour éviter d'acheter juste parce que le prix est bas."""
        try:
            daily = self.get_klines(symbol, 80, '1d')
            h4 = self.get_klines(symbol, 80, '4h')
            if len(daily) < 50 or len(h4) < 30:
                return {
                    'is_falling': False,
                    'reason': 'insufficient_data',
                    'daily_momentum_7d': 0,
                    'h4_momentum_24h': 0
                }

            daily_closes = [float(k['close']) for k in daily]
            h4_closes = [float(k['close']) for k in h4]
            daily_ema20 = self.calculate_ema(daily_closes, 20)
            daily_ema50 = self.calculate_ema(daily_closes, 50)
            h4_ema20 = self.calculate_ema(h4_closes, 20)
            h4_ema50 = self.calculate_ema(h4_closes, 50)
            current_daily = daily_closes[-1]
            current_h4 = h4_closes[-1]

            daily_momentum_7d = self._calculate_momentum_pct(daily, 7)
            h4_momentum_24h = self._calculate_momentum_pct(h4, 6)
            recent_lows = [float(k['low']) for k in daily[-8:]]
            lower_low = min(recent_lows[-3:]) < min(recent_lows[:5])

            ema_downtrend = current_daily < daily_ema20 < daily_ema50 and current_h4 < h4_ema20 < h4_ema50
            momentum_down = daily_momentum_7d <= -3 or h4_momentum_24h <= -2
            is_falling = ema_downtrend and (momentum_down or lower_low)

            reasons = []
            if ema_downtrend:
                reasons.append('ema_downtrend_1d_4h')
            if momentum_down:
                reasons.append('negative_momentum')
            if lower_low:
                reasons.append('lower_lows')

            return {
                'is_falling': is_falling,
                'reason': ','.join(reasons) if reasons else 'not_falling',
                'daily_momentum_7d': daily_momentum_7d,
                'h4_momentum_24h': h4_momentum_24h,
                'daily_ema20': daily_ema20,
                'daily_ema50': daily_ema50,
                'h4_ema20': h4_ema20,
                'h4_ema50': h4_ema50
            }
        except Exception as e:
            return {'is_falling': False, 'reason': f'error:{e}'}

    def _has_reversal_confirmation(self, symbol):
        """Confirmation simple de stabilisation avant achat en bear mode."""
        try:
            h1 = self.get_klines(symbol, 40, '1h')
            if len(h1) < 21:
                return {'confirmed': False, 'reason': 'insufficient_data'}

            closes = [float(k['close']) for k in h1]
            lows = [float(k['low']) for k in h1]
            volumes = [float(k['volume']) for k in h1]
            ema9 = self.calculate_ema(closes, 9)
            ema21 = self.calculate_ema(closes, 21)
            recent_momentum = self._calculate_momentum_pct(h1, 3)
            higher_low = min(lows[-3:]) > min(lows[-8:-3])
            avg_volume = sum(volumes[-12:-1]) / max(1, len(volumes[-12:-1]))
            volume_ok = volumes[-1] >= avg_volume * 1.05 if avg_volume > 0 else False
            price_above_fast_ema = closes[-1] > ema9
            ema_reclaim = ema9 >= ema21 * 0.998

            confirmed = price_above_fast_ema and recent_momentum > 0 and (higher_low or volume_ok or ema_reclaim)
            reasons = []
            if price_above_fast_ema:
                reasons.append('price_above_ema9')
            if recent_momentum > 0:
                reasons.append('positive_1h_momentum')
            if higher_low:
                reasons.append('higher_low')
            if volume_ok:
                reasons.append('volume_confirmed')
            if ema_reclaim:
                reasons.append('ema9_reclaim')

            return {
                'confirmed': confirmed,
                'reason': ','.join(reasons) if reasons else 'no_reversal_confirmation',
                'momentum_3h': recent_momentum,
                'ema9': ema9,
                'ema21': ema21,
                'higher_low': higher_low,
                'volume_ok': volume_ok
            }
        except Exception as e:
            return {'confirmed': False, 'reason': f'error:{e}'}

    def get_market_context(self, symbol, force=False):
        """Contexte marché centralisé et caché pour éviter de dupliquer les filtres."""
        if not self.market_regime_filter:
            return {'mode': 'NORMAL', 'bear_mode': False, 'reason': 'market_regime_filter_disabled'}

        now = time.time()
        cached = self.market_context_cache.get(symbol)
        if cached and not force and now - cached['timestamp'] < self.market_context_cache_seconds:
            return cached['context']

        try:
            symbol_regime = self.risk_manager._detect_market_regime(symbol)
        except Exception:
            symbol_regime = 'UNKNOWN'
        try:
            btc_regime = self.risk_manager._detect_market_regime('BTC/USD')
        except Exception:
            btc_regime = 'UNKNOWN'
        try:
            btc_momentum = self.risk_manager._get_btc_momentum() * 100
        except Exception:
            btc_momentum = 0

        falling = self._detect_falling_knife(symbol) if self.falling_knife_filter else {'is_falling': False, 'reason': 'disabled'}
        reversal = self._has_reversal_confirmation(symbol) if self.require_reversal_in_bear else {'confirmed': True, 'reason': 'not_required'}
        is_alt = symbol not in ('BTC/USD', 'BTC/USD')
        btc_bear = self._is_bear_regime(btc_regime) or btc_momentum <= -2
        symbol_bear = self._is_bear_regime(symbol_regime)
        bear_mode = symbol_bear or (is_alt and btc_bear)

        context = {
            'mode': 'BEAR' if bear_mode else 'NORMAL',
            'bear_mode': bear_mode,
            'symbol_regime': symbol_regime,
            'btc_regime': btc_regime,
            'btc_momentum_percent': btc_momentum,
            'falling_knife': falling,
            'reversal': reversal,
            'trade_multiplier': self.bear_mode_trade_multiplier if bear_mode else 1.0,
            'confidence_bonus': self.bear_mode_min_confidence_bonus if bear_mode else 0,
            'support_touch_override_allowed': (not bear_mode) or self.bear_mode_support_touch_override,
            'reason': 'bear_mode' if bear_mode else 'normal_market'
        }
        self.state.setdefault('market_context', {})[symbol] = {
            **context,
            'last_update': datetime.now().isoformat()
        }
        self.save_state()
        self.market_context_cache[symbol] = {'timestamp': now, 'context': context}
        return context

    def should_block_entry_for_market_context(self, symbol, context, source='normal'):
        """Retourne (blocked, reason) selon bear mode et falling knife."""
        if not context.get('bear_mode'):
            return False, 'normal_market'

        allowed_pairs = {self._normalize_symbol(pair) for pair in self.bear_mode_allowed_pairs}
        if symbol not in allowed_pairs:
            return True, 'bear_mode_pair_not_allowed'

        if source == 'support_touch' and not context.get('support_touch_override_allowed'):
            return True, 'support_touch_disabled_in_bear_mode'

        falling = context.get('falling_knife', {})
        reversal = context.get('reversal', {})
        if self.falling_knife_filter and falling.get('is_falling') and not reversal.get('confirmed'):
            return True, f"falling_knife_without_reversal:{falling.get('reason')}"

        return False, 'bear_mode_allowed_with_confirmation'

    def apply_market_context_position_adjustment(self, position_data, context):
        """Réduit la taille en bear mode sans recalculer tout le sizing."""
        multiplier = float(context.get('trade_multiplier') or 1.0)
        if multiplier >= 0.999:
            return position_data

        adjusted = dict(position_data)
        adjusted['position_size_usd'] = round(float(adjusted.get('position_size_usd') or 0) * multiplier, 2)
        adjusted['position_size_crypto'] = float(adjusted.get('position_size_crypto') or 0) * multiplier
        metrics = dict(adjusted.get('risk_metrics') or {})
        metrics['market_context_multiplier'] = multiplier
        metrics['market_context_mode'] = context.get('mode')
        adjusted['risk_metrics'] = metrics
        return adjusted

    def _get_backtest_interval(self):
        # Dynamique : plus volatile = recalcul plus fréquent
        try:
            pairs = os.getenv('TRADING_PAIRS', 'BTCUSD,ETHUSD').split(',')
            volatilities = []
            for pair in pairs:
                symbol = self._normalize_symbol(pair.strip())
                klines = self.websocket.get_klines(symbol, 20) if self.websocket.is_connected() else []
                if len(klines) >= 10:
                    closes = [k['close'] for k in klines]
                    changes = [abs(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
                    volatilities.append(sum(changes) / len(changes) * 100)
            avg_vol = sum(volatilities) / len(volatilities) if volatilities else 2.0
            if avg_vol >= 3.0:   return 5 * 60      # très volatile  → 5 min
            if avg_vol >= 1.5:   return 5 * 60     # volatile       → 5 min
            if avg_vol >= 0.5:   return 5 * 60     # normal         → 5 min
            return 5 * 60                           # calme          → 5 min
        except:
            return self.support_touch_backtest_interval

    def refresh_support_touch_filter(self, force=False):
        """Relance le backtest Support Touch Pro si les données sont absentes ou trop vieilles."""
        if not self.support_touch_adaptive_filter:
            return True

        filter_state = self.state.setdefault('support_touch_filter', {'last_run_ts': 0, 'pairs': {}})
        last_run = float(filter_state.get('last_run_ts') or 0)
        interval = self._get_backtest_interval()
        if not force and time.time() - last_run < interval:
            return True

        try:
            command = [
                sys.executable,
                'scripts/backtest_support_touch.py',
                '--output',
                self.support_touch_backtest_file
            ]
            result = subprocess.run(
                command,
                cwd=os.getcwd(),
                capture_output=True,
                text=True,
                timeout=self.support_touch_backtest_timeout
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'backtest failed')

            with open(self.support_touch_backtest_file, 'r', encoding='utf-8') as f:
                backtest = json.load(f)

            pairs = {}
            for item in backtest.get('results', []):
                symbol = item.get('symbol')
                if not symbol:
                    continue

                trades = int(item.get('trades') or 0)
                win_rate = float(item.get('win_rate') or 0)
                total_pnl = float(item.get('total_pnl_percent') or 0)
                avg_pnl = float(item.get('avg_pnl_percent') or 0)

                blockers = []
                if trades < self.support_touch_min_trades:
                    blockers.append('insufficient_trades')
                if win_rate < self.support_touch_min_winrate:
                    blockers.append('winrate_below_threshold')
                if total_pnl < self.support_touch_min_total_pnl:
                    blockers.append('total_pnl_below_threshold')
                if avg_pnl < self.support_touch_min_avg_pnl:
                    blockers.append('avg_pnl_below_threshold')

                allowed = not blockers
                pairs[symbol] = {
                    'allowed': allowed,
                    'reason': 'backtest_passed' if allowed else ','.join(blockers),
                    'trades': trades,
                    'win_rate': win_rate,
                    'total_pnl_percent': total_pnl,
                    'avg_pnl_percent': avg_pnl,
                    'last_checked': datetime.now().isoformat()
                }

            self.state['support_touch_filter'] = {
                'last_run_ts': time.time(),
                'last_run': datetime.now().isoformat(),
                'source_file': self.support_touch_backtest_file,
                'pairs': pairs,
                'last_error': None
            }
            self.save_state()

            allowed_symbols = [symbol.split('/')[0] for symbol, data in pairs.items() if data['allowed']]
            blocked_symbols = [symbol.split('/')[0] for symbol, data in pairs.items() if not data['allowed']]
            print(f"🧪 Support Touch filter: OK {allowed_symbols or 'aucune'} | Bloqué {blocked_symbols or 'aucune'}")
            return True
        except Exception as e:
            filter_state['last_error'] = str(e)
            self.state['support_touch_filter'] = filter_state
            self.save_state()
            print(f"⚠️ Backtest Support Touch indisponible: {e}")
            return False

    def is_support_touch_allowed(self, symbol):
        """Vérifie si Support Touch Pro peut override les filtres normaux pour ce symbole."""
        if not self.support_touch_adaptive_filter:
            return True, 'adaptive_filter_disabled', {}

        refreshed = self.refresh_support_touch_filter()
        if not refreshed and self.support_touch_fail_closed:
            return False, 'backtest_unavailable_fail_closed', {}

        filter_state = self.state.get('support_touch_filter', {})
        pair_data = filter_state.get('pairs', {}).get(symbol)
        if not pair_data:
            return (not self.support_touch_fail_closed), 'no_backtest_result', {}

        return bool(pair_data.get('allowed')), pair_data.get('reason', 'unknown'), pair_data
    
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
                    exchange_name = os.getenv('EXCHANGE', 'binance').lower()
                    if exchange_name == 'kraken':
                        min_costs = {'BTC/USD': 0.5, 'ETH/USD': 0.5, 'SOL/USD': 0.5, 'BTC/USD': 0.5, 'ETH/USD': 0.5}
                        min_amounts = {'BTC/USD': 0.0001, 'ETH/USD': 0.001, 'SOL/USD': 0.01, 'BTC/USD': 0.0001, 'ETH/USD': 0.001}
                    else:
                        min_costs = {'BTC/USD': 15, 'ETH/USD': 10, 'SOL/USD': 8, 'BNB/USD': 12}
                        min_amounts = {'BTC/USD': 0.00015, 'ETH/USD': 0.003, 'SOL/USD': 0.04, 'BNB/USD': 0.01}
                    self.min_amounts[symbol] = {
                        'min_amount': min_amounts.get(symbol, 0.001), 
                        'min_cost': min_costs.get(symbol, 0.5 if exchange_name == 'kraken' else 10)
                    }
            except Exception as e:
                # Fallback avec minimums du marché (pas API)
                exchange_name = os.getenv('EXCHANGE', 'binance').lower()
                if exchange_name == 'kraken':
                    fallback_minimums = {
                        'BTC/USD': {'min_amount': 0.0001, 'min_cost': 0.5},
                        'ETH/USD': {'min_amount': 0.001, 'min_cost': 0.5},
                        'SOL/USD': {'min_amount': 0.01, 'min_cost': 0.5},
                        'BTC/USD': {'min_amount': 0.0001, 'min_cost': 0.5},
                        'ETH/USD': {'min_amount': 0.001, 'min_cost': 0.5},
                    }
                else:
                    fallback_minimums = {
                        'BTC/USD': {'min_amount': 0.00001, 'min_cost': 15.0},
                        'ETH/USD': {'min_amount': 0.0001, 'min_cost': 10.0},
                        'SOL/USD': {'min_amount': 0.01, 'min_cost': 8.0},
                        'BNB/USD': {'min_amount': 0.001, 'min_cost': 12.0},
                        'ADA/USD': {'min_amount': 1.0, 'min_cost': 5.0},
                        'DOT/USD': {'min_amount': 0.1, 'min_cost': 6.0},
                        'MATIC/USD': {'min_amount': 1.0, 'min_cost': 3.0},
                        'AVAX/USD': {'min_amount': 0.01, 'min_cost': 7.0}
                    }
                default_min = {'min_amount': 0.001, 'min_cost': 0.5 if exchange_name == 'kraken' else 1.0}
                self.min_amounts[symbol] = fallback_minimums.get(symbol, default_min)
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
            print(f"🧠 Paper trading: Validation OK - Coût {cost:.2f} USD")
            return True
        else:
            balance = self.balance_manager.get_balance()
            if symbol.endswith('/USD') or symbol.endswith('/USD'):
                quote = 'USD' if symbol.endswith('/USD') else 'USD'
                available = balance.get(quote, {}).get('free', 0)
                if cost > available:
                    shortage = cost - available
                    return False
        return True
    
    def get_price(self, symbol, force_refresh=False):
        # WebSocket temps réel - PRIORITÉ ABSOLUE
        if hasattr(self, 'websocket') and self.websocket.is_connected():
            ws_price = self.websocket.get_price(symbol)
            if ws_price is not None:
                return ws_price
        
        # Fallback API REST si WebSocket déconnecté
        try:
            ticker = self.safe_request(self.exchange.fetch_ticker, symbol)
            return ticker['last']
        except Exception as e:
            print(f"❌ Erreur prix {symbol}: {e}")
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
        
        # TOUJOURS utiliser les vraies données exchange (même en paper trading)
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
                if self.multi_tf_analyzer:
                    from utils.market_analyzer import MarketAnalyzer
                    volatility = MarketAnalyzer.get_volatility(self, symbol)
                    timeframe = self.multi_tf_analyzer.get_main_timeframe(symbol, volatility)
                else:
                    timeframe = os.getenv('MAIN_TIMEFRAME', '15m')
            except:
                timeframe = os.getenv('MAIN_TIMEFRAME', '15m')
        
        if self.websocket.is_connected():
            klines = self.websocket.get_klines(symbol, count)
            if len(klines) >= count:
                return klines
        
        # TOUJOURS utiliser les vraies données exchange (même en paper trading)
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
                if hasattr(self, 'notifier'):
                    self.notifier.notify_cumulative_trend(symbol, tracker['direction'], tracker['count'], total_change_pct, current_price)
                
                # Reset après alerte
                tracker['count'] = 0
                tracker['start_price'] = current_price
                tracker['cumulative_change'] = 0
                return True
        
        return False
    
    def on_realtime_signal(self, symbol, price):
        if not self.realtime_trading:
            return
        
        if symbol.endswith("USD"):
            formatted_symbol = f"{symbol[:-3]}/USD"
        elif symbol.endswith("USD"):
            formatted_symbol = f"{symbol[:-3]}/USD"
        elif symbol.endswith("USD"):
            formatted_symbol = f"{symbol[:-3]}/USD"
        else:
            formatted_symbol = symbol
        
        # PAPER: vérifier ordres limite à chaque tick prix
        if self.paper_trading and self.pending_orders:
            self._check_paper_orders_for_symbol(formatted_symbol, price)
        
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
    
    def _check_paper_orders_for_symbol(self, symbol, current_price):
        """Vérifie et exécute les ordres paper pour un symbole au prix temps réel."""
        executed = []
        for order_id, order_data in self.pending_orders.items():
            if order_data.get('symbol') != symbol:
                continue
            order = order_data['order']
            if order.get('type') != 'limit':
                continue
            
            limit_price = order['price']
            side = order['side']
            amount = order['amount']
            
            if side == 'sell' and current_price >= limit_price:
                # VENTE EXÉCUTÉE
                buy_price = self.get_real_buy_price(symbol)
                revenue = amount * current_price
                self.paper_balance += revenue
                crypto = symbol.split('/')[0]
                print(f"✅ PAPER VENTE EXÉCUTÉE: {amount:.6f} {crypto} @ {current_price:.2f} (cible: {limit_price:.2f})")
                
                pnl = self.calculate_pnl(symbol, 'sell', amount, current_price, buy_price=buy_price)
                if hasattr(self, 'risk_manager') and pnl is not None:
                    self.risk_manager.record_trade(pnl)
                
                position = {
                    'symbol': symbol, 'side': 'sell', 'amount': amount,
                    'price': current_price, 'timestamp': datetime.now().isoformat(),
                    'order_id': order_id, 'source': 'bot', 'paper': True,
                    'avg_entry_price': buy_price
                }
                self.state['positions'].append(position)
                self.total_trades += 1
                
                if hasattr(self, 'trailing_stop_manager'):
                    self.trailing_stop_manager.remove_position(symbol)
                if hasattr(self, 'set_symbol_cooldown'):
                    self.set_symbol_cooldown(symbol, reason='paper_sell_executed')
                if hasattr(self, 'notifier'):
                    self.notifier.notify_trade_sell(symbol, amount, current_price, revenue, buy_price or current_price, pnl or 0, "N/A")
                
                executed.append(order_id)
            
            elif side == 'buy' and current_price <= limit_price:
                cost = amount * current_price
                self.paper_balance -= cost
                position = {
                    'symbol': symbol, 'side': 'buy', 'amount': amount,
                    'price': current_price, 'timestamp': datetime.now().isoformat(),
                    'order_id': order_id, 'source': 'bot', 'paper': True
                }
                self.state['positions'].append(position)
                position['avg_entry_price'] = self.get_real_buy_price(symbol)
                if hasattr(self, 'set_symbol_cooldown'):
                    self.set_symbol_cooldown(symbol, reason='paper_buy_executed')
                executed.append(order_id)
        
        for oid in executed:
            del self.pending_orders[oid]
        if executed:
            self.save_state()
    
    def check_and_recover_stuck_positions(self):
        balance = self.balance_manager.get_balance()
        for pair in os.getenv('TRADING_PAIRS', 'BTCUSD,ETHUSD').split(','):
            symbol = pair if '/' in pair else (f"{pair.strip()[:-3]}/{pair.strip()[-3:]}" if pair.strip().endswith('USD') else f"{pair.strip()[:3]}/{pair.strip()[3:]}")
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
        trading_pairs = os.getenv('TRADING_PAIRS', 'BTCUSD,ETHUSD').split(',')

        # Obtenir cryptos tradables via le système de scoring unifié
        balance = self.balance_manager.get_balance()
        stuck_positions = []
        tradable_pairs = self.market_analyzer.rank_cryptos(self, trading_pairs, stuck_positions)
        
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
                usd_available = balance.get('USD', balance.get('USD', {})).get('free', 0)
                
                # Utiliser le market_analyzer pour filtrer les cryptos tradables
                stuck_positions = []
                tradable_pairs = self.market_analyzer.rank_cryptos(self, trading_pairs, stuck_positions)
                
                # Affichage (toutes les cryptos surveillées)
                if tradable_pairs:
                    self.show_spot_balances(tradable_pairs)
                    self.show_realtime_prices(tradable_pairs)
                    self.show_protection_status(tradable_pairs)
                    # NOUVEAU: Afficher métriques professionnelles
                    self.show_professional_metrics()
                else:
                    print("⚠️ Aucune crypto tradable - Attente...")
                
                # Afficher niveaux dynamiques seulement pour cryptos tradables
                if tradable_pairs:
                    self.show_dynamic_levels(tradable_pairs)  # Top 2 cryptos tradables
                
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
                
                # Vérifier exécution ordres limite paper trading
                self.check_paper_limit_orders()
                self.manage_trailing_stops(tradable_pairs)
                
                # Vérifier avec le minimum requis (seulement cryptos tradables)
                min_required = min(self.get_min_amount(symbol)['min_cost'] for symbol in tradable_pairs) if tradable_pairs else 10
                self.balance_manager.ensure_trading_balance(min_required)
                self.sync_positions_from_exchange()
                self.detect_order_modifications()
                self.refresh_support_touch_filter()
                # Rafraîchir les balances selon configuration
                balance = self.balance_manager.get_balance(force_refresh=True)
                
                # Sync périodique supplémentaire toutes les 30 secondes
                if hasattr(self, 'last_balance_sync'):
                    if time.time() - self.last_balance_sync > 30:
                        balance = self.balance_manager.get_balance(force_refresh=True)
                        self.last_balance_sync = time.time()
                else:
                    self.last_balance_sync = time.time()
                
                # Vérifier optimisation positions existantes (mode réel uniquement)
                # En paper, le trailing stop gère la sortie
                optimized_any = False
                if not self.paper_trading:
                    for symbol in tradable_pairs:
                        base_currency = symbol.split('/')[0]
                        balance_fresh = self.balance_manager.get_balance(force_refresh=True)
                        free_holding = balance_fresh.get(base_currency, {}).get('free', 0)
                        locked_holding = balance_fresh.get(base_currency, {}).get('used', 0)
                        total_holding = free_holding + locked_holding
                        if total_holding > 0.00001:
                            position_value = total_holding * self.get_price(symbol)
                            min_cost = self.get_min_amount(symbol)['min_cost']
                            if position_value >= min_cost:
                                if self.optimize_existing_position(symbol):
                                    optimized_any = True
                                    break
                
                if optimized_any:
                    continue
                
                # Envoyer status périodique Telegram
                if hasattr(self, 'notifier'):
                    self.notifier.send_status_update()
                
                # Recalculer win rate global toutes les heures
                if not self.paper_trading:
                    now = time.time()
                    if now - self.last_winrate_calculation > 3600:  # 1 heure
                        self.global_stats_30d = self.calculate_winrate_30d()
                        self.last_winrate_calculation = now
                
                # NOUVEAU: Optimisations quotidiennes automatiques
                self.run_daily_optimizations()
                
                time.sleep(0.5)
                
        except KeyboardInterrupt:
            print("\n🛑 Arrêt du bot...")
            self.notifier.notify("🛑 Bot arrêté")
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
        
        # 1. Protections par symbole (seulement cryptos tradables)
        for symbol in tradable_pairs[:2]:  # Max 2 symboles tradables
            crypto = symbol.split('/')[0]
            
        # Afficher seulement si protections actives
        if protections:
            self.async_print(f"🛡️ PROTECTIONS: {' | '.join(protections[:3])}")  # Max 3
    
    def show_dynamic_levels(self, tradable_pairs):
        """Affiche les niveaux dynamiques pour les cryptos tradables uniquement"""
        try:
            # Utiliser directement la liste des cryptos tradables passée en paramètre
            for symbol in tradable_pairs:
                current_price = self.get_price(symbol)
                entry_opportunities = self.pattern_analyzer.get_entry_levels(symbol, current_price)
                
                if entry_opportunities:
                    crypto = symbol.split('/')[0]
                    best_entry = entry_opportunities[0]
                    self.async_print(f"📊 {crypto}: Meilleur niveau {best_entry['price']:.2f} ({best_entry['type']}) - {best_entry['distance']:.1f}%")
                    
                    # Envoyer notification si niveau très proche (< 2%) et pas déjà envoyée
                    if abs(best_entry['distance']) < 2.0 and hasattr(self, 'notifier'):
                        notification_key = f"{symbol}_{best_entry['type']}_{best_entry['price']:.2f}"
                        last_notification = self.last_dynamic_notifications.get(notification_key)
                        
                        # Envoyer seulement si pas de notification identique récente (5 min)
                        if not last_notification or (time.time() - last_notification) > 300:
                            self.notifier.notify_dynamic_level(symbol, best_entry['type'], best_entry['price'], best_entry['distance'])
                            self.last_dynamic_notifications[notification_key] = time.time()
        except Exception as e:
            pass  # Silencieux
    
    def intelligent_strategy(self, symbol, amount, current_price):
        """Stratégie intelligente - Support touch PRIORITAIRE"""
        crypto = symbol.split('/')[0]
        market_context = self.get_market_context(symbol)

        cooldown_remaining = self.get_symbol_cooldown_remaining(symbol)
        if cooldown_remaining > 0:
            self.record_decision(
                symbol, 'buy', False, 'symbol_cooldown_active',
                {'price': current_price, 'cooldown_remaining_seconds': cooldown_remaining},
                throttle_seconds=60
            )
            return
        
        # 1. Vérifier position existante
        if not self.can_open_position(symbol):
            self.record_decision(
                symbol, 'buy', False, 'position_or_capital_blocked',
                {'price': current_price}, throttle_seconds=120
            )
            return  # Silencieux - trop fréquent

        blocked, block_reason = self.should_block_entry_for_market_context(symbol, market_context, source='normal')
        if blocked:
            self.record_decision(
                symbol, 'buy', False, block_reason,
                {'price': current_price, **market_context}, throttle_seconds=120
            )
            return
        
        # 2. SUPPORT TOUCH EN PREMIER (OVERRIDE TOUT)
        support_check = self.check_support_touch(symbol, current_price)
        if support_check['is_support_touch']:
            support_allowed, support_reason, support_metrics = self.is_support_touch_allowed(symbol)
            support_context_blocked, support_context_reason = self.should_block_entry_for_market_context(
                symbol, market_context, source='support_touch'
            )
            if support_context_blocked:
                support_allowed = False
                support_reason = support_context_reason

            if not support_allowed:
                self.record_decision(
                    symbol, 'support_touch_override', False, support_reason,
                    {
                        'price': current_price,
                        'confidence': support_check['confidence'],
                        'support_price': support_check['support_price'],
                        'market_context': market_context,
                        **support_metrics
                    },
                    throttle_seconds=120
                )
            else:
                print(f"🎯 {crypto}: SUPPORT TOUCH PRO - {support_check['reason']}")  # SYNC - Important
                signal_strength = support_check['confidence']
                account_balance = self.get_account_balance()
                position_data = self.stuck_manager.calculate_position_size(symbol, signal_strength, account_balance)
                position_data = self.apply_market_context_position_adjustment(position_data, market_context)
                position_data['target_price'] = support_check['target_price']
                position_data['stop_loss_price'] = support_check['stop_loss']
                reason = f"Support PRO {support_check['support_price']:.2f} - {support_check['reason']}"
                self.record_decision(
                    symbol, 'buy', True, reason,
                    {
                        'price': current_price,
                        'confidence': support_check['confidence'],
                        'support_price': support_check['support_price'],
                        'target_price': support_check['target_price'],
                        'stop_loss': support_check['stop_loss'],
                        'market_context': market_context,
                        **support_metrics
                    },
                    throttle_seconds=0
                )
                self.execute_buy(symbol, position_data, current_price, reason)
                return
        
        # 3. SCORING PROFESSIONNEL (si pas de support touch)
        websocket_manager = getattr(self, 'websocket', None)
        crypto_score = self.market_analyzer.score_crypto(self, symbol, [], websocket_manager)
        dynamic_min_score = getattr(self.market_analyzer, 'last_dynamic_threshold', 10)
        
        if crypto_score < dynamic_min_score:
            self.record_decision(
                symbol, 'buy', False, 'score_below_dynamic_threshold',
                {'price': current_price, 'score': crypto_score, 'min_score': dynamic_min_score},
                throttle_seconds=120
            )
            return  # Silencieux - trop fréquent
        
        # 4. SIGNAL TECHNIQUE
        try:
            analysis = self.get_cached_analysis(symbol, current_price)
            volatility = analysis.get('volatility', 2.0)
            adaptive_threshold = (
                self.risk_manager.get_adaptive_confidence_threshold(symbol, volatility)
                + market_context.get('confidence_bonus', 0)
            )
            adaptive_threshold = min(adaptive_threshold, 95)
            global_signal = analysis['global_signal']
            
            # REJET si signal insuffisant (seulement si pas de support touch)
            if not (global_signal['action'] in ['BUY', 'STRONG_BUY'] and 
                   global_signal['confidence'] >= adaptive_threshold):
                self.record_decision(
                    symbol, 'buy', False, 'technical_signal_below_threshold',
                    {
                        'price': current_price,
                        'action': global_signal.get('action'),
                        'confidence': global_signal.get('confidence'),
                        'min_confidence': adaptive_threshold,
                        'volatility': volatility,
                        'score': crypto_score,
                        'market_context': market_context
                    },
                    throttle_seconds=120
                )
                return  # Silencieux - trop fréquent
                
        except Exception as e:
            self.record_decision(
                symbol, 'buy', False, 'analysis_error',
                {'price': current_price, 'error': str(e)}, throttle_seconds=120
            )
            return  # Silencieux - trop fréquent
        
        # 4. CONTEXTE MARCHÉ (Troisième filtre)
        if not self.check_htf_bias(symbol):
            self.record_decision(
                symbol, 'buy', False, 'htf_bias_rejected',
                {'price': current_price, 'score': crypto_score, 'market_context': market_context}, throttle_seconds=120
            )
            return  # Silencieux - trop fréquent
        
        # 5. TIMING OPTIMAL (Quatrième filtre)
        if not self._is_optimal_trading_time():
            self.record_decision(
                symbol, 'buy', False, 'outside_optimal_trading_time',
                {'price': current_price, 'score': crypto_score, 'market_context': market_context}, throttle_seconds=120
            )
            return  # Silencieux - trop fréquent
        
        # ✅ TOUS LES CRITÈRES PASSÉS - LOG CRITIQUE (SYNC)
        print(f"✅ {crypto}: VALIDATION COMPLÈTE - Score {crypto_score}/100 ≥ {dynamic_min_score} | Signal {global_signal['confidence']:.0f}% ≥ {adaptive_threshold:.0f}%")
        
        # 6. Calculer position sizing optimal (COMBIEN)
        signal_strength = self.get_signal_strength(symbol, current_price)
        account_balance = self.get_account_balance()
        position_data = self.stuck_manager.calculate_position_size(symbol, signal_strength, account_balance)
        position_data = self.apply_market_context_position_adjustment(position_data, market_context)
        
        # 7. NOUVEAU: Optimiser type d'ordre pour frais
        try:
            optimal_order_type = self.capital_manager.optimize_order_type(symbol, 'normal')
            print(f"💰 Ordre optimisé: {optimal_order_type} (frais réduits)")  # SYNC - Important
        except:
            optimal_order_type = 'market'
        
        # 8. Exécuter achat avec données optimisées
        reason = f"Validation complète - Score {crypto_score}/100"
        self.record_decision(
            symbol, 'buy', True, reason,
            {
                'price': current_price,
                'score': crypto_score,
                'min_score': dynamic_min_score,
                'confidence': global_signal.get('confidence'),
                'min_confidence': adaptive_threshold,
                'position_size_usd': position_data.get('position_size_usd'),
                'position_size_crypto': position_data.get('position_size_crypto'),
                'market_context': market_context
            },
            throttle_seconds=0
        )
        self.execute_buy(symbol, position_data, current_price, reason)
    
    def get_real_trading_fee(self, symbol, order_type='market'):
        """Récupère frais réels au lieu des frais statiques"""
        try:
            return self.capital_manager.get_fee_for_trade(symbol, order_type)
        except:
            return self.trading_fee  # Fallback
    
    def calculate_real_trade_cost(self, symbol, amount_usd, order_type='market'):
        """Calcule coût réel avec frais dynamiques"""
        try:
            return self.capital_manager.calculate_trade_cost(symbol, amount_usd, order_type)
        except:
            # Fallback avec frais statiques
            fee_cost = amount_usd * self.trading_fee
            return {
                'amount': amount_usd,
                'fee_rate': self.trading_fee,
                'fee_cost': fee_cost,
                'total_cost': amount_usd + fee_cost,
                'vip_level': 'Unknown',
                'exchange': os.getenv('EXCHANGE', 'binance').lower()
            }
    
    def show_professional_metrics(self):
        """Affiche métriques professionnelles"""
        try:
            # Frais dynamiques
            fees_summary = self.capital_manager.get_fees_summary()
            self.async_print(f"💰 FRAIS: {fees_summary['vip_level']} | Optimal: {fees_summary['optimal_fee']}")
            
            # Seuils adaptatifs pour cryptos tradables
            trading_pairs = os.getenv('TRADING_PAIRS', 'BTCUSD,ETHUSD').split(',')
            for pair in trading_pairs[:2]:  # Top 2
                symbol = pair if '/' in pair else (f"{pair.strip()[:-3]}/{pair.strip()[-3:]}" if pair.strip().endswith('USD') else f"{pair.strip()[:3]}/{pair.strip()[3:]}")
                crypto = symbol.split('/')[0]
                
                if symbol in self.risk_manager.adaptive_thresholds:
                    threshold_summary = self.risk_manager.get_threshold_summary(symbol)
                    self.async_print(f"🎯 {crypto}: Seuil {threshold_summary['threshold_final']} (Perf: {threshold_summary['performance_adj']}, Market: {threshold_summary['market_adj']})")
        
        except Exception as e:
            pass  # Silencieux si erreur
    
    def run_daily_optimizations(self):
        """Lance optimisations quotidiennes comme les pros"""
        try:
            # Optimiser seuils adaptatifs
            self.risk_manager.optimize_thresholds_daily()
            self.capital_manager.get_real_trading_fees('BTC/USD')  # Force refresh
            
        except Exception as e:
            pass  # Silencieux si erreur
    
    def get_optimal_check_interval(self, all_pairs):
        """Calcule intervalle optimal selon volatilité multi-pairs - TOUTES les cryptos"""
        if not all_pairs:
            return 2
        
        try:
            intervals = []
            
            for pair in all_pairs:
                symbol = pair if '/' in pair else (f"{pair.strip()[:-3]}/{pair.strip()[-3:]}" if pair.strip().endswith('USD') else f"{pair.strip()[:3]}/{pair.strip()[3:]}")
                volatility = self.get_pair_volatility(symbol)
                has_position = self.has_active_position(symbol)
                hour = datetime.now().hour
                is_active_session = 8 <= hour <= 22  # Sessions EU/US
                volume_ratio = self.get_volume_ratio(symbol)
                
                # Calcul base selon volatilité - NIVEAU PROFESSIONNEL
                if volatility >= 4.0:
                    base_interval = 0.1     # Très volatil = 0.1s
                elif volatility >= 3.0:
                    base_interval = 0.5     # Volatil = 1s
                elif volatility >= 2.0:
                    base_interval = 1    # Moyen = 2s
                else:
                    base_interval = 2    # Calme = 3s
                
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
            return max(0.1, min(optimal_interval, 60))  # 2s à 1min
            
        except Exception as e:
            print(f"⚠️ Erreur calcul intervalle: {e}")
            return 0.1  # Fallback par défaut 2s
    
    def get_pair_volatility(self, symbol):
        """Récupère volatilité pour une crypto spécifique"""
        try:
            klines = self.get_klines(symbol, 20, '15m')
            if len(klines) >= 10:
                return self.market_analyzer.calculate_volatility(klines, symbol)
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
        """Vérifie si on peut ouvrir une position - IGNORE LA POUSSIÈRE + vérifie capital"""
        from utils.market_analyzer import MarketAnalyzer
        
        # Calculer max_positions selon capital
        try:
            total_capital = self.capital_manager.get_total_capital()
            limits = MarketAnalyzer.get_position_limits(total_capital)
            max_positions = limits['max_positions_per_crypto']
        except:
            max_positions = 4  # Fallback par défaut
        
        # Utiliser les vraies positions depuis l'exchange
        try:
            balance = self.balance_manager.get_balance(force_refresh=True)
            crypto = symbol.split('/')[0]
            
            # Position réelle = balance libre + verrouillée
            free_amount = balance.get(crypto, {}).get('free', 0)
            locked_amount = balance.get(crypto, {}).get('used', 0)
            total_holding = free_amount + locked_amount
            
            # IGNORER LA POUSSIÈRE: Compter SEULEMENT si valeur >= minimum tradable
            if total_holding > 0.00001:
                current_price = self.get_price(symbol)
                position_value = total_holding * current_price
                min_cost = self.get_min_amount(symbol)['min_cost']
                
                # Si valeur < minimum = poussière = ignorer complètement
                if position_value < min_cost:
                    return True  # Poussière ignorée, position autorisée
                
                # Position réelle détectée, vérifier limite
                return False  # Position déjà ouverte, bloquer
            
            # NOUVEAU: Vérifier capital USD disponible
            quote = 'USD' if symbol.endswith('/USD') else 'USD'
            usd_available = balance.get(quote, {}).get('free', 0)
            min_cost = self.get_min_amount(symbol)['min_cost']
            
            if usd_available < min_cost:
                return False  # Capital insuffisant
            
            return True  # OK pour ouvrir
            
        except Exception as e:
            print(f"⚠️ Erreur vérification position {symbol}: {e}")
            return False

    def _cancel_sell_orders_for_symbol(self, symbol):
        """Annule les ordres de vente actifs avant une sortie d'urgence."""
        if self.paper_trading:
            for order_id, order_data in list(self.pending_orders.items()):
                if order_data.get('symbol') == symbol and order_data.get('side') == 'sell':
                    del self.pending_orders[order_id]
            return True

        try:
            open_orders = self.safe_request(self.exchange.fetch_open_orders, symbol)
            for order in open_orders:
                if order.get('side') == 'sell':
                    self.safe_request(self.exchange.cancel_order, order['id'], symbol)
            return True
        except Exception as e:
            print(f"⚠️ Impossible d'annuler les ordres de vente {symbol}: {e}")
            return False

    def manage_trailing_stops(self, tradable_pairs):
        """Met à jour les trailing stops et vend au marché si un stop est touché."""
        if not hasattr(self, 'trailing_stop_manager') or not tradable_pairs:
            return

        for symbol in tradable_pairs:
            try:
                current_price = self.get_price(symbol)
                if not current_price:
                    continue

                self.trailing_stop_manager.update_position(symbol, current_price)
                if not self.trailing_stop_manager.should_stop_loss(symbol, current_price):
                    continue

                if not self._cancel_sell_orders_for_symbol(symbol):
                    continue

                balance = self.balance_manager.get_balance(force_refresh=True)
                base_currency = symbol.split('/')[0]
                available = balance.get(base_currency, {}).get('free', 0)
                if available <= 0.00001:
                    continue

                if self.sell_market(symbol, available):
                    self.trailing_stop_manager.remove_position(symbol)
            except Exception as e:
                print(f"⚠️ Erreur trailing stop {symbol}: {e}")
    
    def get_entry_signal(self, symbol, current_price):
        """Obtient le signal d'entrée - NIVEAUX DYNAMIQUES + PATTERNS"""
        # 1. Niveaux dynamiques professionnels (priorité)
        entry_opportunities = self.pattern_analyzer.get_entry_levels(symbol, current_price)
        if entry_opportunities:
            best_entry = entry_opportunities[0]
            return True, f"Niveau dynamique: {best_entry['type']} ({best_entry['distance']:.1f}%)"
        
        # 2. Pattern Recognition (nouveau)
        try:
            klines = self.get_klines(symbol, 50, '1h')
            if len(klines) >= 20:
                pattern_result = self.pattern_analyzer.detect_patterns(klines)
                
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
    
    def get_unified_trading_decision(self, symbol):
        """MÉTHODE UNIFIÉE - Niveau Hedge Fund - Élimine toutes contradictions"""
        crypto = symbol.split('/')[0]
        current_time = time.time()
        
        # 1. Vérifier cache (TTL 30 secondes) - Anti-over-trading
        if symbol in self.decision_cache:
            cached = self.decision_cache[symbol]
            if current_time - cached['timestamp'] < 30:
                return cached['decision'], cached['reason']
        
        # 2. LOGIQUE UNIFIÉE - Hiérarchie Institutionnelle
        try:
            # PRIORITÉ 1: RSI oversold extrême (< 25) - OVERRIDE TOUT
            if self.is_extreme_oversold(symbol):
                decision = True
                reason = f"✅ {crypto}: RSI oversold - Achat autorisé"
            
            # PRIORITÉ 2: Support fort - OVERRIDE marché baissier
            elif self.is_near_strong_support(symbol):
                decision = True
                reason = f"✅ {crypto}: Support fort détecté - Achat autorisé"
            
            # PRIORITÉ 3: Régime de marché
            else:
                market_type = self.detect_market_regime(symbol)
                
                if market_type == 'BULL':
                    decision = self.check_bullish_htf_bias(symbol)
                    reason = f"✅ {crypto}: Marché haussier" if decision else f"❌ {crypto}: HTF baissier"
                
                elif market_type == 'BEAR':
                    decision = False
                    reason = f"❌ {crypto}: Marché baissier sans exception - Skip"
                
                else:  # SIDEWAYS
                    decision = True
                    reason = f"✅ {crypto}: Marché latéral - Achat autorisé"
            
            # 3. Sauvegarder dans cache
            self.decision_cache[symbol] = {
                'decision': decision,
                'reason': reason,
                'timestamp': current_time
            }
            self.record_decision(
                symbol, 'htf_filter', decision, reason,
                {'market_regime': locals().get('market_type')},
                throttle_seconds=120
            )
            
            return decision, reason
            
        except Exception as e:
            # Fallback sécurisé
            decision = False
            reason = f"❌ {crypto}: Erreur analyse - Skip"
            self.record_decision(
                symbol, 'htf_filter', False, reason,
                {'error': str(e)}, throttle_seconds=120
            )
            return decision, reason
    
    def check_htf_bias(self, symbol):
        """Filtre HTF unifié - REJET SILENCIEUX"""
        decision, reason = self.get_unified_trading_decision(symbol)
        
        # PAS de log ici - seulement return silencieux
        return decision
    
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
    

    
    def is_near_strong_support(self, symbol):
        """Vérifie proximité support fort - Algorithmic S/R"""
        try:
            klines = self.get_klines(symbol, 100, '4h')
            if len(klines) < 20:
                return False
                
            levels_data = self.pattern_analyzer.find_support_resistance_levels(klines)
            current_price = self.get_price(symbol)
            
            for support in levels_data.get('support_levels', [])[:2]:
                distance_pct = abs(current_price - support['price']) / current_price
                if distance_pct <= 0.02 and support['strength'] >= 3:
                    return True
            return False
        except:
            return False
    
    def is_extreme_oversold(self, symbol):
        """Vérifie RSI oversold extrême (< 25) - Niveau Institutionnel"""
        try:
            klines = self.get_klines(symbol, 30, '4h')
            if len(klines) < 14:
                return False
            
            closes = [k['close'] for k in klines]
            rsi = self.multi_tf_analyzer.calculate_rsi(closes)
            return rsi is not None and rsi < 25  # Seuil institutionnel
        except:
            return False
    

    def _is_optimal_trading_time(self):
        """Vérifie si c'est un moment optimal pour trader (sessions actives)"""
        hour = datetime.now().hour
        # Sessions optimales (UTC): Europe (8-16h) et Asie (0-4h)
        return (8 <= hour <= 16) or (0 <= hour <= 4)
    
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
            usd_balance = balance.get('USD', balance.get('USD', {})).get('free', 0)
            
            if self.paper_trading:
                return self.paper_balance
            
            return usd_balance
        except:
            return 100  # Fallback
    
    def execute_buy(self, symbol, position_data, current_price, reason):
        """Exécute l'achat avec données optimisées"""
        crypto = symbol.split('/')[0]
        existing_positions = [p for p in self.state.get('positions', []) 
                            if p['symbol'] == symbol and p['side'] == 'buy']
        position_count = len(existing_positions)
             
        # Exécuter
        result = self.buy_market(symbol, position_data['position_size_crypto'])
        
        if result:
            self.set_symbol_cooldown(symbol, reason='buy_executed')
            avg_entry_price = self.get_real_buy_price(symbol)
            self.record_decision(
                symbol, 'buy_executed', True, reason,
                {
                    'price': current_price,
                    'avg_entry_price': avg_entry_price,
                    'position_size_usd': position_data.get('position_size_usd'),
                    'position_size_crypto': position_data.get('position_size_crypto'),
                    'stop_loss_price': position_data.get('stop_loss_price'),
                    'risk_reward_ratio': position_data.get('risk_reward_ratio')
                },
                throttle_seconds=0
            )
            # Affichage amélioré
            print(f"✅ ACHAT {crypto}: {position_data['position_size_usd']:.1f} USD (Position #{position_count + 1})")
            print(f"   💡 Raison: {reason}")
            print(f"   💰 Prix: {current_price:.2f} | Stop: {position_data['stop_loss_price']:.2f} (-{position_data['stop_loss_percent']:.1f}%)")
            print(f"   📈 R/R: 1:{position_data['risk_reward_ratio']:.1f} | Quantité: {position_data['position_size_crypto']:.6f} {crypto}")
   
            print(f"✅ Achat exécuté avec succès")
            # Ajouter trailing stop avec prix optimisé
            if hasattr(self, 'trailing_stop_manager'):
                self.trailing_stop_manager.add_position(symbol, current_price)
            
            # Placer ordre de vente (paper ET réel)
            if self.paper_trading:
                self._place_paper_sell_order(symbol)
            else:
                import time
                time.sleep(1)
                if self.optimize_existing_position(symbol):
                    print(f"✅ Ordre de vente placé avec succès")
                else:
                    print(f"⚠️ Ordre de vente sera placé au prochain cycle")
        else:
            self.set_symbol_cooldown(symbol, self.symbol_failure_cooldown_seconds, reason='buy_failed')
            self.record_decision(
                symbol, 'buy_executed', False, 'order_failed',
                {
                    'price': current_price,
                    'reason': reason,
                    'position_size_usd': position_data.get('position_size_usd'),
                    'position_size_crypto': position_data.get('position_size_crypto')
                },
                throttle_seconds=0
            )
            print(f"❌ Échec de l'achat")
    
