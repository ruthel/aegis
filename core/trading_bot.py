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
from utils.exit_engine import ExitDecisionEngine
from core.ml_live_logger import MLLiveLogger

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
        
        # Configuration état selon le mode
        self.paper_trading = os.getenv('PAPER_TRADING', 'True') == 'True'
        self._state_save_lock = threading.Lock()
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
        
        self._last_decision = {}  # Anti-spam logs
        self._decision_log_throttle = {}
        self.decision_journal_max = int(os.getenv('DECISION_JOURNAL_MAX', '5000'))
        self.ml_live_logger = MLLiveLogger(
            data_dir='data',
            sqlite_file=os.getenv('ML_LIVE_SQLITE_FILE', 'data/aegis_db.sqlite3')
        )
        self._ml_exit_learning_last = {}
        self._last_score_append = {}
        self.symbol_cooldown_seconds = int(os.getenv('SYMBOL_COOLDOWN_SECONDS', '300'))
        self.symbol_failure_cooldown_seconds = int(os.getenv('SYMBOL_FAILURE_COOLDOWN_SECONDS', '120'))
        # Verrous par symbole : empêche deux threads d'acheter simultanément le même actif
        self._buy_locks: dict = {}
        self._last_trailing_stop_save = 0
        self.market_regime_filter = os.getenv('MARKET_REGIME_FILTER', 'True').lower() == 'true'
        self.bear_mode_trade_multiplier = float(os.getenv('BEAR_MODE_TRADE_MULTIPLIER', '0.35'))
        self.bear_mode_min_confidence_bonus = float(os.getenv('BEAR_MODE_MIN_CONFIDENCE_BONUS', '20'))
        self.market_context_cache_seconds = int(os.getenv('MARKET_CONTEXT_CACHE_SECONDS', '300'))
        self.market_context_cache = {}
        self.support_touch_adaptive_filter = os.getenv('SUPPORT_TOUCH_ADAPTIVE_FILTER', 'True').lower() == 'true'
        self.support_touch_backtest_interval = 5 * 60
        self.support_touch_backtest_file = os.getenv('SUPPORT_TOUCH_BACKTEST_SOURCE', 'data/aegis_db.sqlite3')
        self.support_touch_backtest_timeout = int(os.getenv('SUPPORT_TOUCH_BACKTEST_TIMEOUT_SECONDS', '90'))
        self.ml_live_analysis_interval = int(os.getenv('ML_LIVE_ANALYSIS_INTERVAL_SECONDS', '21600'))
        self._last_ml_live_analysis = 0
        self._ml_live_analysis_process = None
        
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
        
        # Exit Decision Engine fusionne au ML pour la gestion active des sorties
        exit_enabled = os.getenv('EXIT_ENGINE_ENABLED', 'True').lower() == 'true'
        fragile_pct = float(os.getenv('PROFIT_FRAGILE_MAX_NET_PCT', '0.40'))
        time_stop_min = int(os.getenv('TIME_STOP_MINUTES', '12'))
        self.exit_decision_engine = ExitDecisionEngine(
            fragile_max_net_pct=fragile_pct,
            time_stop_minutes=time_stop_min
        ) if exit_enabled else None
        
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
        
        # Core Machine Learning Engine
        from core.ml_engine import MLEngine
        self.ml_engine = MLEngine()
        self.ml_min_probability = float(os.getenv('ML_MIN_PROBABILITY', '65.0'))
        self.ml_exit_entry_min_continue_prob = float(os.getenv('ML_EXIT_ENTRY_MIN_CONTINUE_PROB', '50.0'))
        
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
        self.capital_manager.sync_fees_to_bot()
        print()  # Ligne vide après l'analyse du capital
        
        # Calculer win rate global 30 jours au démarrage
        if not self.paper_trading:
            print("📊 Calcul win rate global (30 derniers jours)...")
            self.global_stats_30d = self.calculate_winrate_30d()
            print()
        
        # NOUVEAU: Placer automatiquement les cryptos disponibles en mode vente au démarrage
        print("\n🔍 Vérification positions existantes...")
        self._optimize_all_positions_at_startup()

        # Mettre à jour prédictions ML au démarrage
        print("🧠 Calcul des prédictions ML en direct pour toutes les paires...")
        self.update_ml_predictions_for_all_pairs()
        
        # Notification de démarrage
        mode = "PAPER" if self.paper_trading else "LIVE"
        self.notifier.notify(f"🤖 Bot démarré - {mode}")
        self.realtime_trading = True  # Init complète, activer le trading

    def update_ml_predictions_for_all_pairs(self):
        """Met à jour les prédictions ML pour toutes les paires actives en direct"""
        if not hasattr(self, 'ml_engine') or self.ml_engine is None or not self.ml_engine.is_trained:
            return

        try:
            trading_pairs = os.getenv('TRADING_PAIRS', 'BTCUSD,ETHUSD,SOLUSD,ADAUSD').split(',')
            ml_preds = self.state.setdefault('ml_predictions', {})

            for pair in trading_pairs:
                pair_clean = pair.strip()
                if '/' in pair_clean:
                    symbol = pair_clean
                elif pair_clean.endswith('USD'):
                    symbol = f"{pair_clean[:-3]}/USD"
                elif pair_clean.endswith('USDT'):
                    symbol = f"{pair_clean[:-4]}/USDT"
                else:
                    symbol = f"{pair_clean[:3]}/{pair_clean[3:]}"

                klines_15m = self.get_klines(symbol, 50, '15m')
                if not klines_15m or len(klines_15m) < 20:
                    continue
                
                klines_5m = self.get_klines(symbol, 30, '5m')
                klines_1h = self.get_klines(symbol, 30, '1h')
                curr_price = klines_15m[-1]['close']

                trade_context = self._build_ml_trade_context()
                prob = self.ml_engine.predict_win_probability(
                    klines_15m,
                    curr_price,
                    klines_5m=klines_5m,
                    klines_1h=klines_1h,
                    trade_context=trade_context
                )
                rec = 'BUY_HIGH_CONFIDENCE' if prob >= self.ml_min_probability else ('NEUTRAL' if prob >= 50.0 else 'REJECT_RISK')

                ml_preds[symbol] = {
                    'symbol': symbol,
                    'p_win': prob,
                    'recommendation': rec,
                    'min_probability': self.ml_min_probability,
                    'timestamp': datetime.now().isoformat()
                }

            self.save_state()
        except Exception as e:
            print(f"⚠️ Erreur mise à jour ML predictions: {e}")

    def _build_ml_trade_context(self, position_data=None, account_balance=None):
        """Construit les paramètres de trade utilisables par le ML sans fuite d'information future."""
        try:
            fee_rate = float(getattr(self, 'trading_fee', 0) or 0)
            if fee_rate <= 0:
                fee_rate = float(os.getenv('TRADING_FEE_PERCENT', '0.1')) / 100.0

            if account_balance is None:
                account_balance = self.get_account_balance()

            position_value = None
            if isinstance(position_data, dict):
                position_value = position_data.get('position_size_usd')
            if position_value is None:
                position_value = float(os.getenv('TRADE_AMOUNT', '5'))

            max_hold_candles = int(os.getenv('BACKTEST_MAX_HOLD_CANDLES', '96'))
            planned_hold_minutes = float(os.getenv('ML_PLANNED_HOLD_MINUTES', max_hold_candles * 15))
            position_value = float(position_value or 0)
            account_balance = float(account_balance or 0)

            return {
                'fee_rate': fee_rate,
                'position_value_usd': position_value,
                'account_balance': account_balance,
                'position_value_pct_balance': (position_value / account_balance) * 100.0 if account_balance > 0 else 0.0,
                'planned_hold_minutes': planned_hold_minutes
            }
        except Exception:
            return None

    def _build_ml_bot_context(
        self,
        symbol,
        market_context=None,
        falling_knife=None,
        support_check=None,
        support_metrics=None,
        crypto_score=None,
        dynamic_min_score=None,
        technical_action=None,
        technical_confidence=None,
        technical_min_confidence=None
    ):
        """Expose au ML les signaux/verrous du bot sous forme de contexte structuré."""
        context = dict(market_context or {})
        falling = falling_knife if isinstance(falling_knife, dict) else context.get('falling_knife', {})
        reversal = context.get('reversal', {})
        support = support_check if isinstance(support_check, dict) else {}
        support_bt = support_metrics if isinstance(support_metrics, dict) else {}

        return {
            'symbol_regime': context.get('symbol_regime'),
            'btc_regime': context.get('btc_regime'),
            'bear_mode': bool(context.get('bear_mode')),
            'reversal_confirmed': bool(reversal.get('confirmed')),
            'falling_knife_active': bool(falling.get('is_falling')),
            'is_support_touch': bool(support.get('is_support_touch')),
            'support_confidence': float(support.get('confidence') or 0.0),
            'support_rebounds': float(support.get('rebounds') or support_bt.get('rebounds') or 0.0),
            'support_backtest_winrate': float(
                support_bt.get('win_rate') or support_bt.get('winrate') or support_bt.get('win_rate_pct') or 0.0
            ),
            'support_backtest_total_pnl': float(
                support_bt.get('total_pnl_percent')
                or support_bt.get('total_pnl')
                or support_bt.get('total_pnl_pct')
                or 0.0
            ),
            'support_backtest_avg_pnl': float(
                support_bt.get('avg_pnl_percent')
                or support_bt.get('avg_pnl')
                or support_bt.get('average_pnl')
                or 0.0
            ),
            'crypto_score': float(crypto_score or 0.0),
            'dynamic_min_score': float(dynamic_min_score or 0.0),
            'is_optimal_trading_time': 1.0 if self._is_optimal_trading_time() else 0.0,
            'technical_action': technical_action,
            'technical_confidence': float(technical_confidence or 0.0),
            'technical_min_confidence': float(technical_min_confidence or 0.0),
        }

    def _predict_ml_exit_entry_forecast(self, symbol, current_price, position_data, entry_p_win=50.0, bot_context=None):
        """Prévoit, au moment de l'entrée, si la future position aura assez de marge pour continuer."""
        if not hasattr(self, 'ml_engine') or self.ml_engine is None:
            return None

        try:
            tf = os.getenv('MAIN_TIMEFRAME', '15m')
            klines = self.get_klines(symbol, 50, tf)
            if not klines or len(klines) < 20:
                return None

            btc_klines = self.get_klines('BTC/USD', 30, tf) if symbol != 'BTC/USD' else None
            fee_rate = float(getattr(self, 'trading_fee', 0) or 0)
            if fee_rate <= 0:
                fee_rate = float(os.getenv('TRADING_FEE_PERCENT', '0.1')) / 100.0

            preview_position = dict(position_data or {})
            preview_position.setdefault('buy_price', current_price)
            preview_position.setdefault('avg_entry_price', current_price)
            preview_position.setdefault('fee_rate', fee_rate)
            preview_position.setdefault('duration_minutes', 0.0)

            continuation_score = 50.0
            if getattr(self, 'exit_decision_engine', None):
                continuation_score = self.exit_decision_engine.compute_continuation_score(
                    symbol, current_price, klines[-30:], btc_klines, preview_position
                )

            forecast = self.ml_engine.predict_exit_decision(
                klines,
                current_price,
                preview_position,
                continuation_score,
                entry_p_win=entry_p_win,
                btc_klines=btc_klines,
                bot_context=bot_context
            )
            forecast['entry_continuation_score'] = continuation_score
            forecast['min_continue_probability'] = self.ml_exit_entry_min_continue_prob
            return forecast
        except Exception as e:
            print(f"⚠️ Erreur prévision ML sortie à l'entrée pour {symbol}: {e}")
            return None

    def _should_reject_entry_for_ml_exit(self, ml_exit_forecast):
        """Retourne True si la prévision de sortie ML juge l'entrée trop fragile."""
        if not ml_exit_forecast or not ml_exit_forecast.get('ml_exit_available'):
            return False
        return float(ml_exit_forecast.get('p_continue', 50.0)) < self.ml_exit_entry_min_continue_prob

    def _build_ml_entry_decision_metrics(self, current_price, ml_win_prob, ml_exit_forecast, ml_bot_context=None, extra=None):
        """Construit les métriques lisibles pour une décision finale ML d'entrée."""
        context = ml_bot_context or {}
        p_continue = None
        if isinstance(ml_exit_forecast, dict):
            p_continue = ml_exit_forecast.get('p_continue')

        metrics = {
            'price': current_price,
            'ml_decision': {
                'p_win': ml_win_prob,
                'min_p_win': self.ml_min_probability,
                'p_continue': p_continue,
                'min_p_continue': self.ml_exit_entry_min_continue_prob,
                'exit_recommendation': (ml_exit_forecast or {}).get('decision') if isinstance(ml_exit_forecast, dict) else None,
                'exit_reason': (ml_exit_forecast or {}).get('reason') if isinstance(ml_exit_forecast, dict) else None,
            },
            'ml_inputs': {
                'support_touch': bool(context.get('is_support_touch')),
                'support_confidence': context.get('support_confidence'),
                'support_backtest_winrate': context.get('support_backtest_winrate'),
                'support_backtest_total_pnl': context.get('support_backtest_total_pnl'),
                'crypto_score': context.get('crypto_score'),
                'dynamic_min_score': context.get('dynamic_min_score'),
                'technical_action': context.get('technical_action'),
                'technical_confidence': context.get('technical_confidence'),
                'technical_min_confidence': context.get('technical_min_confidence'),
                'is_optimal_trading_time': context.get('is_optimal_trading_time'),
                'symbol_regime': context.get('symbol_regime'),
                'btc_regime': context.get('btc_regime'),
                'bear_mode': context.get('bear_mode'),
                'falling_knife_active': context.get('falling_knife_active'),
            },
            'ml_exit_entry_forecast': ml_exit_forecast,
        }
        if extra:
            metrics.update(extra)
        return metrics

    def record_ml_entry_learning_sample(
        self,
        symbol,
        decision,
        current_price,
        ml_win_prob,
        ml_exit_forecast,
        features=None,
        bot_context=None,
        trade_context=None,
        reason=None
    ):
        """Enregistre un sample live ML sans influencer la décision du bot."""
        try:
            if not getattr(self, 'ml_live_logger', None):
                return None
            p_continue = None
            if isinstance(ml_exit_forecast, dict):
                p_continue = ml_exit_forecast.get('p_continue')
            return self.ml_live_logger.record_entry_decision(
                symbol=symbol,
                decision=decision,
                price=current_price,
                p_win=ml_win_prob,
                min_p_win=self.ml_min_probability,
                p_continue=p_continue,
                min_p_continue=self.ml_exit_entry_min_continue_prob,
                features=features,
                feature_names=getattr(self.ml_engine, 'feature_names', []),
                bot_context=bot_context,
                trade_context=trade_context,
                exit_forecast=ml_exit_forecast,
                reason=reason,
                mode='paper' if self.paper_trading else 'live'
            )
        except Exception:
            return None

    def record_ml_exit_learning_sample(self, symbol, sell_price, amount, buy_price=None, pnl=None, hold_time=None, reason=None, order=None):
        """Lie le résultat réel d'une sortie au sample d'entrée ML ouvert."""
        try:
            if not getattr(self, 'ml_live_logger', None):
                return None
            pnl_pct = None
            if buy_price and buy_price > 0 and pnl is not None and amount:
                cost_basis = float(buy_price) * float(amount)
                pnl_pct = (float(pnl) / cost_basis) * 100.0 if cost_basis > 0 else None
            return self.ml_live_logger.record_exit_outcome(
                symbol=symbol,
                sell_price=sell_price,
                amount=amount,
                buy_price=buy_price,
                pnl=pnl,
                pnl_pct=pnl_pct,
                hold_time=hold_time,
                reason=reason,
                order=order,
                mode='paper' if self.paper_trading else 'live'
            )
        except Exception:
            return None

    def record_ml_exit_decision_learning_sample(self, symbol, current_price, exit_result, exit_features=None, entry_p_win=None):
        """Enregistre les 37 features vues par le ML au moment d'une décision de sortie."""
        try:
            if not getattr(self, 'ml_live_logger', None):
                return None
            decision = (exit_result or {}).get('decision')
            throttle_key = f"{symbol}:{decision}"
            now = time.time()
            if now - self._ml_exit_learning_last.get(throttle_key, 0) < 30:
                return None
            self._ml_exit_learning_last[throttle_key] = now
            ml_exit = (exit_result or {}).get('ml_exit') or {}
            return self.ml_live_logger.record_exit_decision(
                symbol=symbol,
                decision=decision,
                current_price=current_price,
                features=exit_features,
                feature_names=getattr(self.ml_engine, 'exit_feature_names', []),
                entry_p_win=entry_p_win,
                continuation_score=(exit_result or {}).get('continuation_score'),
                p_continue=ml_exit.get('p_continue'),
                net_pnl_pct=(exit_result or {}).get('net_pnl_pct'),
                duration_minutes=(exit_result or {}).get('duration_minutes'),
                reason=(exit_result or {}).get('reason'),
                mode='paper' if self.paper_trading else 'live'
            )
        except Exception:
            return None
    
    def _place_paper_sell_order(self, symbol):
        """Redirige vers la méthode unifiée d'optimisation de position"""
        return self.optimize_existing_position(symbol)

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
        state_key = 'paper' if self.paper_trading else 'live'
        db_state = self.ml_live_logger.load_bot_state(state_key)
        if isinstance(db_state, dict) and db_state:
            self.state = db_state
            loaded = True

        if not loaded:
            self.state = {'positions': [], 'last_update': None}
        self._ensure_state_defaults()
        if self.paper_trading:
            self._restore_paper_balance()
        self._restore_trailing_stops_from_state()
        self.pending_orders = self.state.get('pending_orders', {})

    def _ensure_state_defaults(self):
        self.state.setdefault('positions', [])
        self.state.setdefault('decision_journal', [])
        self.state.setdefault('symbol_cooldowns', {})
        self.state.setdefault('support_touch_filter', {'last_run_ts': 0, 'pairs': {}})
        self.state.setdefault('market_context', {})
        if len(self.state['decision_journal']) > self.decision_journal_max:
            self.state['decision_journal'] = self.state['decision_journal'][-self.decision_journal_max:]

    def get_open_positions(self):
        """Calcule les positions nettes ouvertes (style Binance: achats - ventes filled)."""
        by_symbol = {}
        for p in sorted(self.state.get('positions', []), key=lambda x: x.get('timestamp', '')):
            sym = p.get('symbol')
            amt = float(p.get('amount') or 0)
            price = float(p.get('price') or 0)
            if not sym or amt <= 0 or price <= 0:
                continue
            data = by_symbol.setdefault(sym, {'amount': 0.0, 'cost': 0.0})
            if p['side'] == 'buy':
                data['amount'] += amt
                data['cost'] += amt * price
            elif p['side'] == 'sell':
                sold = min(amt, data['amount'])
                avg = data['cost'] / data['amount'] if data['amount'] else 0
                data['amount'] -= sold
                data['cost'] -= sold * avg
                if data['amount'] < 1e-8:
                    data['amount'] = 0.0
                    data['cost'] = 0.0
        return {sym: d for sym, d in by_symbol.items() if d['amount'] > 1e-8}

    def _close_buy_positions(self, symbol, sell_amount, sell_price):
        """Marque les positions buy comme closed quand vendues (style Binance)."""
        remaining = sell_amount
        for p in self.state.get('positions', []):
            if remaining <= 0:
                break
            if p.get('symbol') == symbol and p.get('side') == 'buy' and p.get('status') != 'closed':
                p['status'] = 'closed'
                p['closed_at'] = datetime.now().isoformat()
                p['sell_price'] = sell_price
                remaining -= float(p.get('amount') or 0)

    def _restore_paper_balance(self):
        """Restaure l'USD paper depuis le state, ou le reconstruit de manière exacte."""
        saved_balance = self.state.get('paper_balance')
        if saved_balance is not None:
            self.paper_balance = float(saved_balance)
            return

        initial_balance = float(os.getenv('PAPER_BALANCE', '1000'))
        try:
            from dashboard.app import trade_stats, weighted_positions
            stats = trade_stats(self.state.get('positions', []))
            open_pos = weighted_positions(self.state.get('positions', []), self.state.get('trailing_stops'), self.state.get('pending_orders'))
            open_cost = sum(p['entry_value'] for p in open_pos)
            self.paper_balance = max(0, initial_balance + stats.get('total_pnl_net', 0) - open_cost)
        except Exception:
            self.paper_balance = initial_balance

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

        saved_stops = self.state.get('trailing_stops', {})
        for symbol, data in open_positions.items():
            if data['amount'] > 0.00001 and data['last_buy_price']:
                saved_data = saved_stops.get(symbol, {})
                saved_percent = saved_data.get('trailing_percent')
                
                # Restaurer le trailing stop avec son pourcentage spécifique
                self.trailing_stop_manager.add_position(
                    symbol, data['last_buy_price'], 
                    trailing_percent=saved_percent
                )
                
                # Restaurer le plus haut historique et le stop calculé
                if symbol in self.trailing_stop_manager.positions and saved_data:
                    pos = self.trailing_stop_manager.positions[symbol]
                    if 'highest_price' in saved_data:
                        pos['highest_price'] = float(saved_data['highest_price'])
                    if 'stop_price' in saved_data:
                        pos['stop_price'] = float(saved_data['stop_price'])
                    if 'initial_trailing_percent' in saved_data:
                        pos['initial_trailing_percent'] = float(saved_data['initial_trailing_percent'])
                    elif saved_percent is not None:
                        pos['initial_trailing_percent'] = float(saved_percent)
                    if 'breakeven_active' in saved_data:
                        pos['breakeven_active'] = bool(saved_data['breakeven_active'])
                    # Restaurer resistance_price pour que le breakeven mode soit identique après redémarrage
                    if 'resistance_price' in saved_data and saved_data['resistance_price'] is not None:
                        pos['resistance_price'] = float(saved_data['resistance_price'])
    
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
            self.state['pending_orders'] = self.pending_orders
            if 'decision_journal' in self.state and len(self.state['decision_journal']) > self.decision_journal_max:
                self.state['decision_journal'] = self.state['decision_journal'][-self.decision_journal_max:]
            if hasattr(self, 'trailing_stop_manager'):
                self.state['trailing_stops'] = {
                    symbol: {
                        'stop_price': float(data['stop_price']),
                        'highest_price': float(data['highest_price']),
                        'buy_price': float(data['buy_price']),
                        'trailing_percent': float(data.get('trailing_percent', self.trailing_stop_manager.trailing_percent)),
                        'initial_trailing_percent': float(data.get('initial_trailing_percent', data.get('trailing_percent', self.trailing_stop_manager.trailing_percent))),
                        'breakeven_active': bool(data.get('breakeven_active', False)),
                        'resistance_price': float(data['resistance_price']) if data.get('resistance_price') else None
                    }
                    for symbol, data in self.trailing_stop_manager.positions.items()
                }
            self.state['last_update'] = datetime.now().isoformat()
            with self._state_save_lock:
                state_key = 'paper' if self.paper_trading else 'live'
                if self.ml_live_logger.save_bot_state(self.state, state_key):
                    return
                raise RuntimeError("SQLite bot_state save failed")
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

            if getattr(self, 'ml_live_logger', None):
                self.ml_live_logger.record_decision_journal(
                    entry,
                    mode='paper' if self.paper_trading else 'live',
                    max_entries=self.decision_journal_max
                )
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
        return regime in ['BEAR', 'BEAR_WEAK', 'BEAR_STRONG', 'SIDEWAYS_DOWN']

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

        falling = self._detect_falling_knife(symbol)
        reversal = self._has_reversal_confirmation(symbol)
        is_alt = symbol not in ('BTC/USD', 'BTC/USD')
        btc_bear = self._is_bear_regime(btc_regime) or btc_momentum <= -2
        symbol_bear = self._is_bear_regime(symbol_regime)
        bear_mode = symbol_bear or (is_alt and btc_bear)

        if symbol_bear:
            mode_display = 'BEAR'
        elif 'BULL' in str(symbol_regime) or symbol_regime == 'SIDEWAYS_UP':
            mode_display = 'BULL'
        elif 'SIDE' in str(symbol_regime) or 'RANGE' in str(symbol_regime):
            mode_display = 'RANGE'
        else:
            mode_display = 'BEAR' if bear_mode else 'NORMAL'

        context = {
            'mode': mode_display,
            'bear_mode': bear_mode,
            'symbol_bear': symbol_bear,
            'btc_bear': btc_bear,
            'symbol_regime': symbol_regime,
            'btc_regime': btc_regime,
            'btc_momentum_percent': btc_momentum,
            'falling_knife': falling,
            'reversal': reversal,
            'trade_multiplier': self.bear_mode_trade_multiplier if bear_mode else 1.0,
            'confidence_bonus': self.bear_mode_min_confidence_bonus if bear_mode else 0,
            'reason': 'bear_mode' if bear_mode else 'normal_market'
        }
        self.state.setdefault('market_context', {})[symbol] = {
            **context,
            'last_update': datetime.now().isoformat()
        }
        self.save_state()
        self.market_context_cache[symbol] = {'timestamp': now, 'context': context}
        return context

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
            if avg_vol >= 3.0:   return 15 * 60     # très volatile  → 15 min
            if avg_vol >= 1.5:   return 60 * 60     # volatile       → 1 heure
            if avg_vol >= 0.5:   return 3 * 3600    # normal         → 3 heures
            return 6 * 3600                         # calme          → 6 heures
        except:
            return self.support_touch_backtest_interval

    def _get_dynamic_backtest_limit(self):
        """Calcule dynamiquement la limite de bougies du backtest selon la volatilité globale"""
        try:
            pairs = [p.strip() for p in os.getenv('TRADING_PAIRS', 'BTCUSD,ETHUSD').split(',') if p.strip()]
            vol_scores = []
            for pair in pairs:
                symbol = self._normalize_symbol(pair)
                try:
                    if self.websocket and self.websocket.is_connected():
                        ws_klines = self.websocket.get_klines(symbol, 60)
                        if len(ws_klines) >= 10:
                            vol = self.market_analyzer.calculate_volatility(ws_klines, symbol)
                            vol_scores.append(vol)
                    else:
                        klines = self.get_klines(symbol, 60, os.getenv('MAIN_TIMEFRAME', '15m'))
                        vol = self.market_analyzer.calculate_volatility(klines, symbol)
                        vol_scores.append(vol)
                except:
                    pass
            
            avg_vol = sum(vol_scores) / len(vol_scores) if vol_scores else 3.0
            
            # Plus le marché est calme, plus on étend la période pour avoir un échantillon statistique suffisant de trades
            # Plus le marché est agité, plus on réduit la période pour s'adapter rapidement aux retournements
            if avg_vol <= 1.5:
                return 1920  # Très calme : évaluer sur 20 jours
            elif avg_vol <= 2.5:
                return 1344  # Calme : évaluer sur 14 jours
            elif avg_vol <= 3.5:
                return 720   # Normal : évaluer sur 7.5 jours
            elif avg_vol <= 4.5:
                return 480   # Volatile : évaluer sur 5 jours
            else:
                return 288   # Très volatile : évaluer sur 3 jours
        except Exception:
            try:
                return int(os.getenv('BACKTEST_LIMIT', '720'))
            except:
                return 720

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
            dynamic_limit = self._get_dynamic_backtest_limit()
            command = [
                sys.executable,
                'scripts/backtest_support_touch.py',
                '--dynamic-hold',
                '--limit',
                str(dynamic_limit),
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

            if getattr(self, 'ml_live_logger', None):
                backtest = self.ml_live_logger.get_latest_support_touch_backtest()
            else:
                backtest = {}
            if not backtest:
                raise RuntimeError('support touch backtest DB result unavailable')

            pairs = {}
            for item in backtest.get('results', []):
                symbol = item.get('symbol')
                if not symbol:
                    continue

                trades = int(item.get('trades') or 0)
                win_rate = float(item.get('win_rate') or 0)
                total_pnl = float(item.get('total_pnl_percent') or 0)
                avg_pnl = float(item.get('avg_pnl_percent') or 0)

                # Détection dynamique du régime du marché pour adapter les seuils
                regime = 'UNKNOWN'
                try:
                    klines_15m = self.get_klines(symbol, 20, '15m')
                    if klines_15m and len(klines_15m) >= 20:
                        regime = self.market_analyzer._detect_market_regime(klines_15m)
                except Exception as e:
                    self.logger.warning(f"Erreur détection régime pour Support Touch {symbol}: {e}")

                pairs[symbol] = {
                    'reason': 'ml_feature_only',
                    'trades': trades,
                    'win_rate': win_rate,
                    'total_pnl_percent': total_pnl,
                    'avg_pnl_percent': avg_pnl,
                    'regime': regime,
                    'last_checked': datetime.now().isoformat()
                }

            self.state['support_touch_filter'] = {
                'last_run_ts': time.time(),
                'last_run': datetime.now().isoformat(),
                'pairs': pairs,
                'last_error': None
            }
            self.save_state()

            symbols = [symbol.split('/')[0] for symbol in pairs]
            print(f"🧪 Support Touch metrics ML: {symbols or 'aucune'}")
            return True
        except Exception as e:
            filter_state['last_error'] = str(e)
            self.state['support_touch_filter'] = filter_state
            self.save_state()
            print(f"⚠️ Backtest Support Touch indisponible: {e}")
            return False

    def get_support_touch_metrics(self, symbol):
        """Retourne les métriques Support Touch connues, sans les utiliser comme verrou d'entrée."""
        filter_state = self.state.get('support_touch_filter', {})
        pair_data = filter_state.get('pairs', {}).get(symbol)
        return pair_data if isinstance(pair_data, dict) else {}
    
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
                        min_costs = {'BTC/USD': 15, 'ETH/USD': 10, 'SOL/USD': 8, 'ADA/USD': 12}
                        min_amounts = {'BTC/USD': 0.00015, 'ETH/USD': 0.003, 'SOL/USD': 0.04, 'ADA/USD': 0.01}
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
                        'ADA/USD': {'min_amount': 0.001, 'min_cost': 12.0},
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
                fallback_prices = {'BTC': 50000, 'ETH': 3000, 'SOL': 100, 'ADA': 300}
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
        
        if '/' in symbol:
            formatted_symbol = symbol
        elif symbol.endswith("USD"):
            formatted_symbol = f"{symbol[:-3]}/USD"
        else:
            formatted_symbol = symbol

        self._update_trailing_stop_from_tick(formatted_symbol, price)
        
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

    def _evaluate_exit_engine_for_symbol(self, symbol, current_price):
        """Évalue une position ouverte avec l'ExitDecisionEngine (ContinuationScore + Recommandations)."""
        if not getattr(self, 'exit_decision_engine', None):
            return None
        if not hasattr(self, 'trailing_stop_manager') or symbol not in getattr(self.trailing_stop_manager, 'positions', {}):
            return None

        try:
            position_data = self.trailing_stop_manager.positions[symbol]
            tf = os.getenv('MAIN_TIMEFRAME', '15m')
            klines = self.get_klines(symbol, 30, tf)
            btc_klines = self.get_klines('BTC/USD', 30, tf) if symbol != 'BTC/USD' else None
            market_context = self.get_market_context(symbol)
            bot_context = self._build_ml_bot_context(symbol, market_context=market_context)
            preliminary_score = self.exit_decision_engine.compute_continuation_score(
                symbol, current_price, klines, btc_klines, position_data
            )
            entry_p_win = 50.0
            try:
                entry_p_win = float(self.state.get('ml_predictions', {}).get(symbol, {}).get('p_win', 50.0))
            except Exception:
                entry_p_win = 50.0
            ml_exit = None
            ml_exit_features = None
            if hasattr(self, 'ml_engine') and self.ml_engine is not None:
                ml_exit_features = self.ml_engine.extract_exit_features(
                    klines,
                    current_price,
                    position_data,
                    preliminary_score,
                    entry_p_win=entry_p_win,
                    btc_klines=btc_klines,
                    bot_context=bot_context
                )
                ml_exit = self.ml_engine.predict_exit_decision(
                    klines,
                    current_price,
                    position_data,
                    preliminary_score,
                    entry_p_win=entry_p_win,
                    btc_klines=btc_klines,
                    bot_context=bot_context
                )
            
            result = self.exit_decision_engine.evaluate_position(
                symbol, current_price, position_data, klines, btc_klines, ml_exit=ml_exit
            )
            self.record_ml_exit_decision_learning_sample(
                symbol,
                current_price,
                result,
                exit_features=ml_exit_features,
                entry_p_win=entry_p_win
            )
            
            if 'exit_recommendations' not in self.state:
                self.state['exit_recommendations'] = {}
            self.state['exit_recommendations'][symbol] = result
            
            self._log_decision(
                symbol=symbol,
                action="exit_decision",
                allowed=True,
                reason=result['reason'],
                metrics={
                    'decision': result['decision'],
                    'rule_decision': result.get('rule_decision'),
                    'continuation_score': result['continuation_score'],
                    'ml_exit': result.get('ml_exit', {}),
                    'net_pnl_pct': result['net_pnl_pct'],
                    'duration_minutes': result['duration_minutes']
                },
                throttle_seconds=30
            )
            self._apply_ml_exit_management(symbol, current_price, result)
            return result
        except Exception as e:
            print(f"⚠️ Erreur évaluation ExitDecisionEngine {symbol}: {e}")
            return None

    def _apply_ml_exit_management(self, symbol, current_price, exit_result):
        """Applique les décisions de sortie fusionnées ML + règles quand le mode actif est autorisé."""
        if not exit_result:
            return False
        if not hasattr(self, 'trailing_stop_manager') or symbol not in getattr(self.trailing_stop_manager, 'positions', {}):
            return False

        decision = exit_result.get('decision')
        position = self.trailing_stop_manager.positions[symbol]
        fee_rate = float(position.get('fee_rate') or getattr(self, 'trading_fee', 0) or 0)
        buy_price = float(position.get('buy_price') or current_price)
        breakeven_price = buy_price * (1 + fee_rate) / max(0.000001, (1 - fee_rate))

        if decision in ('FORCE_EXIT', 'TAKE_PROFIT'):
            if not self._cancel_sell_orders_for_symbol(symbol):
                return False
            balance = self.balance_manager.get_balance(force_refresh=True)
            base_currency = symbol.split('/')[0]
            available = balance.get(base_currency, {}).get('free', 0)
            if available <= 0.00001:
                return False
            if self.sell_market(symbol, available):
                self.trailing_stop_manager.remove_position(symbol)
                self.record_decision(
                    symbol, 'sell', True, f"ml_exit_{decision.lower()}",
                    {
                        'price': current_price,
                        'decision': decision,
                        'ml_exit': exit_result.get('ml_exit', {}),
                        'net_pnl_pct': exit_result.get('net_pnl_pct'),
                        'continuation_score': exit_result.get('continuation_score')
                    },
                    throttle_seconds=0
                )
                return True
            return False

        if decision in ('TIGHTEN_STOP', 'PROTECT_BREAKEVEN'):
            min_gap_pct = float(os.getenv('ML_EXIT_MIN_STOP_GAP_PCT', '0.08'))
            max_safe_stop = current_price * (1 - min_gap_pct / 100.0)
            if decision == 'PROTECT_BREAKEVEN':
                proposed_stop = min(max_safe_stop, breakeven_price)
            else:
                tighten_gap_pct = float(os.getenv('ML_EXIT_TIGHTEN_STOP_GAP_PCT', '0.18'))
                proposed_stop = max(breakeven_price, current_price * (1 - tighten_gap_pct / 100.0))
                proposed_stop = min(proposed_stop, max_safe_stop)

            if proposed_stop > float(position.get('stop_price') or 0):
                old_stop = position.get('stop_price')
                position['stop_price'] = proposed_stop
                position['ml_exit_managed'] = True
                position['ml_exit_decision'] = decision
                self.record_decision(
                    symbol, 'exit_management', True, f"ml_exit_{decision.lower()}",
                    {
                        'price': current_price,
                        'old_stop': old_stop,
                        'new_stop': proposed_stop,
                        'ml_exit': exit_result.get('ml_exit', {}),
                        'net_pnl_pct': exit_result.get('net_pnl_pct'),
                        'continuation_score': exit_result.get('continuation_score')
                    },
                    throttle_seconds=30
                )
                return True

        return False

    def _update_trailing_stop_from_tick(self, symbol, current_price):
        """Met à jour le trailing stop dès le tick WebSocket, sans attendre la boucle principale."""
        if not hasattr(self, 'trailing_stop_manager'):
            return
        if symbol not in getattr(self.trailing_stop_manager, 'positions', {}):
            return

        try:
            changed = self.trailing_stop_manager.update_position(symbol, current_price)
            eval_res = self._evaluate_exit_engine_for_symbol(symbol, current_price)
            
            save_interval = float(os.getenv('TRAILING_STOP_SAVE_INTERVAL_SECONDS', '1'))
            now = time.time()
            if changed or eval_res:
                if now - self._last_trailing_stop_save >= save_interval:
                    self._last_trailing_stop_save = now
                    self.save_state()
        except Exception as e:
            print(f"⚠️ Erreur update trailing live {symbol}: {e}")
    
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
                
                # Marquer les positions buy correspondantes comme closed (style Binance)
                self._close_buy_positions(symbol, amount, current_price)
                
                position = {
                    'symbol': symbol, 'side': 'sell', 'amount': amount,
                    'price': current_price, 'timestamp': datetime.now().isoformat(),
                    'order_id': order_id, 'source': 'bot', 'paper': True,
                    'avg_entry_price': buy_price, 'status': 'filled'
                }
                position.update(self._calculate_fee_details(amount, current_price, buy_price))
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
                self._poll_dashboard_commands()
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
                self.run_ml_live_analysis_if_due()
                
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
            print(f"⚠️ Erreur affichage niveaux dynamiques: {e}")
    
    def intelligent_strategy(self, symbol, amount, current_price):
        """Stratégie intelligente - Support touch PRIORITAIRE"""
        # --- Verrou par symbole : empêche deux threads d'exécuter simultanément ---
        if symbol not in self._buy_locks:
            self._buy_locks[symbol] = threading.Lock()
        if not self._buy_locks[symbol].acquire(blocking=False):
            # Un autre thread traite déjà ce symbole — on abandonne silencieusement
            return
        try:
            return self._intelligent_strategy_locked(symbol, amount, current_price)
        finally:
            self._buy_locks[symbol].release()

    def _intelligent_strategy_locked(self, symbol, amount, current_price):
        """Corps de la stratégie exécuté sous verrou par symbole"""
        crypto = symbol.split('/')[0]
        market_context = self.get_market_context(symbol)

        # Calcul du Trailing Stop Adaptatif selon le régime de marché et la volatilité ATR
        regime = market_context.get('symbol_regime', 'SIDEWAYS')
        base_trailing = float(os.getenv('TRAILING_STOP_PERCENT', '2.5'))
        
        # 1. Multiplicateur de régime de marché (direction)
        if regime == 'BULL_STRONG':
            regime_multiplier = 1.4
        elif regime == 'BULL_WEAK':
            regime_multiplier = 1.2
        elif regime == 'BEAR_STRONG':
            regime_multiplier = 0.6
        elif regime == 'BEAR_WEAK':
            regime_multiplier = 0.8
        else:
            regime_multiplier = 1.0
            
        # 2. Multiplicateur de volatilité basé sur l'ATR (référence: volatilité moyenne de 2.0%)
        atr_multiplier = 1.0
        try:
            atr_data = self.stuck_manager._calculate_atr(symbol)
            atr_percent = atr_data.get('atr_percent', 2.0)
            if atr_percent > 0:
                atr_multiplier = atr_percent / 2.0
        except Exception as e:
            print(f"⚠️ Impossible de calculer l'ATR pour le trailing stop adaptatif: {e}")
            
        # 3. Combinaison finale bornée
        adaptive_trailing = base_trailing * regime_multiplier * atr_multiplier
        adaptive_trailing = round(max(0.5, min(10.0, adaptive_trailing)), 2)

        cooldown_remaining = self.get_symbol_cooldown_remaining(symbol)
        if cooldown_remaining > 0:
            self.record_decision(
                symbol, 'buy', False, 'symbol_cooldown_active',
                {'price': current_price, 'cooldown_remaining_seconds': cooldown_remaining},
                throttle_seconds=60
            )
            return
        
        # 1. VÉRIFICATIONS ABSOLUES DE SÉCURITÉ (CAPITAL / BEAR CONTEXT)

        # 1A. Détection Couteau qui tombe: feature ML uniquement, pas verrou dur.
        falling_knife = self._detect_falling_knife(symbol)

        # 1B. Vérifier position existante et capital
        if not self.can_open_position(symbol):
            self.record_decision(
                symbol, 'buy', False, 'position_or_capital_blocked',
                {'price': current_price}, throttle_seconds=120
            )
            return

        support_check = self.check_support_touch(symbol, current_price)
        support_metrics = self.get_support_touch_metrics(symbol) if support_check.get('is_support_touch') else {}

        # 3. SCORING PROFESSIONNEL (si pas de support touch)
        websocket_manager = getattr(self, 'websocket', None)
        crypto_score = self.market_analyzer.score_crypto(self, symbol, [], websocket_manager)
        self._append_score_history(symbol, crypto_score, current_price)
        dynamic_min_score = getattr(self.market_analyzer, 'last_dynamic_threshold', 10)
        
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
            
            signal_action = global_signal.get('action')
            signal_confidence = global_signal.get('confidence', 0)
                
        except Exception as e:
            self.record_decision(
                symbol, 'buy', False, 'analysis_error',
                {'price': current_price, 'error': str(e)}, throttle_seconds=120
            )
            return  # Silencieux - trop fréquent
        
        # 6. Calculer position sizing avant le ML pour que le modèle voie la valeur réelle prévue.
        signal_strength = self.get_signal_strength(symbol, current_price)
        account_balance = self.get_account_balance()
        position_data = self.stuck_manager.calculate_position_size(symbol, signal_strength, account_balance)

        factor = self._confidence_sizing_factor(signal_strength)
        if factor != 1.0:
            position_data['position_size_usd'] = round(position_data['position_size_usd'] * factor, 2)
            raw_crypto = position_data['position_size_crypto'] * factor
            position_data['position_size_crypto'] = self.stuck_manager.round_quantity(symbol, raw_crypto)

        position_data = self.apply_market_context_position_adjustment(position_data, market_context)
        position_data['trailing_stop_percent'] = adaptive_trailing
        if support_check.get('is_support_touch'):
            position_data['target_price'] = support_check.get('target_price')
            position_data['stop_loss_price'] = support_check.get('stop_loss')
            position_data['support_price'] = support_check.get('support_price')

        # 6. Core ML actif: décision d'entrée + prévision de sortie
        ml_win_prob = 50.0
        ml_exit_forecast = None
        ml_entry_features = None
        ml_trade_context = None
        ml_entry_learning_id = None
        ml_bot_context = self._build_ml_bot_context(
            symbol,
            market_context=market_context,
            falling_knife=falling_knife,
            support_check=support_check,
            support_metrics=support_metrics,
            crypto_score=crypto_score,
            dynamic_min_score=dynamic_min_score,
            technical_action=global_signal.get('action'),
            technical_confidence=global_signal.get('confidence'),
            technical_min_confidence=adaptive_threshold
        )
        if hasattr(self, 'ml_engine') and self.ml_engine is not None:
            try:
                klines_15m = self.get_klines(symbol, 50, '15m')
                klines_5m = self.get_klines(symbol, 30, '5m')
                klines_1h = self.get_klines(symbol, 30, '1h')
                ml_trade_context = self._build_ml_trade_context(position_data, account_balance)
                ml_entry_features = self.ml_engine.extract_features_from_klines(
                    klines_15m,
                    current_price,
                    klines_5m=klines_5m,
                    klines_1h=klines_1h,
                    trade_context=ml_trade_context,
                    bot_context=ml_bot_context
                )
                ml_win_prob = self.ml_engine.predict_win_probability(
                    klines_15m,
                    current_price,
                    klines_5m=klines_5m,
                    klines_1h=klines_1h,
                    trade_context=ml_trade_context,
                    bot_context=ml_bot_context
                )
                ml_exit_forecast = self._predict_ml_exit_entry_forecast(
                    symbol, current_price, position_data, entry_p_win=ml_win_prob, bot_context=ml_bot_context
                )
                recommendation = 'BUY_HIGH_CONFIDENCE' if ml_win_prob >= self.ml_min_probability else ('NEUTRAL' if ml_win_prob >= 50.0 else 'REJECT_RISK')
                
                ml_preds = self.state.setdefault('ml_predictions', {})
                ml_preds[symbol] = {
                    'symbol': symbol,
                    'p_win': ml_win_prob,
                    'recommendation': recommendation,
                    'min_probability': self.ml_min_probability,
                    'ml_exit_entry_forecast': ml_exit_forecast,
                    'bot_context': ml_bot_context,
                    'timestamp': datetime.now().isoformat()
                }
                self.save_state()

                if ml_win_prob < self.ml_min_probability:
                    self.record_ml_entry_learning_sample(
                        symbol,
                        'rejected',
                        current_price,
                        ml_win_prob,
                        ml_exit_forecast,
                        features=ml_entry_features,
                        bot_context=ml_bot_context,
                        trade_context=ml_trade_context,
                        reason=f'ml_filter_rejected_{ml_win_prob:.1f}%'
                    )
                    self.record_decision(
                        symbol, 'buy', False, f'ml_filter_rejected_{ml_win_prob:.1f}%',
                        self._build_ml_entry_decision_metrics(
                            current_price,
                            ml_win_prob,
                            ml_exit_forecast,
                            ml_bot_context
                        ),
                        throttle_seconds=120
                    )
                    return
                if self._should_reject_entry_for_ml_exit(ml_exit_forecast):
                    self.record_ml_entry_learning_sample(
                        symbol,
                        'rejected',
                        current_price,
                        ml_win_prob,
                        ml_exit_forecast,
                        features=ml_entry_features,
                        bot_context=ml_bot_context,
                        trade_context=ml_trade_context,
                        reason=f"ml_exit_entry_rejected_{ml_exit_forecast.get('p_continue', 0):.1f}%"
                    )
                    self.record_decision(
                        symbol, 'buy', False, f"ml_exit_entry_rejected_{ml_exit_forecast.get('p_continue', 0):.1f}%",
                        self._build_ml_entry_decision_metrics(
                            current_price,
                            ml_win_prob,
                            ml_exit_forecast,
                            ml_bot_context
                        ),
                        throttle_seconds=120
                    )
                    return
            except Exception as e:
                print(f"⚠️ Erreur prédiction ML pour {symbol}: {e}")
        
        # ✅ TOUS LES CRITÈRES PASSÉS - LOG CRITIQUE (SYNC)
        print(f"✅ {crypto}: VALIDATION COMPLÈTE - Score {crypto_score}/100 ≥ {dynamic_min_score} | Signal {global_signal['confidence']:.0f}% ≥ {adaptive_threshold:.0f}%")
        
        # 7. NOUVEAU: Optimiser type d'ordre pour frais
        try:
            optimal_order_type = self.capital_manager.optimize_order_type(symbol, 'normal')
            print(f"💰 Ordre optimisé: {optimal_order_type} (frais réduits)")  # SYNC - Important
        except:
            optimal_order_type = 'market'
        
        # 8. Exécuter achat avec données optimisées
        reason = f"Validation complète - Score {crypto_score}/100"
        ml_entry_learning_id = self.record_ml_entry_learning_sample(
            symbol,
            'accepted',
            current_price,
            ml_win_prob,
            ml_exit_forecast,
            features=ml_entry_features,
            bot_context=ml_bot_context,
            trade_context=ml_trade_context,
            reason=reason
        )
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
                **self._build_ml_entry_decision_metrics(current_price, ml_win_prob, ml_exit_forecast, ml_bot_context),
                'market_context': market_context
            },
            throttle_seconds=0
        )
        self.execute_buy(symbol, position_data, current_price, reason, ml_entry_learning_id=ml_entry_learning_id)
    
    def _confidence_sizing_factor(self, confidence):
        """Calcule un multiplicateur de position selon la confiance du signal"""
        try:
            conf = float(confidence)
        except:
            return 1.0
        
        if conf < 55:
            return 0.5
        elif conf < 65:
            return 0.6
        elif conf < 75:
            return 0.8
        elif conf < 85:
            return 1.0
        elif conf < 95:
            return 1.2
        else:
            return 1.4
            
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
            self.capital_manager.sync_fees_to_bot()  # Force refresh and sync fees
            
        except Exception as e:
            print(f"⚠️ Erreur optimisations quotidiennes: {e}")

    def run_ml_live_analysis_if_due(self):
        """Lance l'analyse Phase 4B en arrière-plan sans bloquer le trading."""
        try:
            if self.ml_live_analysis_interval <= 0:
                return False
            now = time.time()
            if self._ml_live_analysis_process and self._ml_live_analysis_process.poll() is None:
                return False
            if now - self._last_ml_live_analysis < self.ml_live_analysis_interval:
                return False

            self._last_ml_live_analysis = now
            command = [
                sys.executable,
                'scripts/analyze_ml_live_performance.py',
                '--max-replay',
                os.getenv('ML_LIVE_ANALYSIS_MAX_REPLAY', '250')
            ]
            creationflags = 0
            if os.name == 'nt':
                creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            self._ml_live_analysis_process = subprocess.Popen(
                command,
                cwd=os.getcwd(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags
            )
            return True
        except Exception as e:
            print(f"⚠️ Analyse ML live indisponible: {e}")
            return False
    
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
        """Vérifie si on peut ouvrir une position - IGNORE LA POUSSIÈRE + vérifie capital et positions ouvertes"""
        from utils.market_analyzer import MarketAnalyzer
        
        # 1. Vérification en Paper Trading
        if self.paper_trading:
            open_paper_positions = [
                p for p in self.state.get('positions', [])
                if p.get('symbol') == symbol and p.get('side') == 'buy' and p.get('status') != 'closed'
            ]
            if open_paper_positions:
                return False  # Déjà 1 position ouverte sur ce symbole en Paper Trading -> BLOQUER

            total_open = len([
                p for p in self.state.get('positions', [])
                if p.get('side') == 'buy' and p.get('status') != 'closed'
            ])
            if total_open >= 3:
                return False  # Maximum 3 positions globales simultanées atteint -> BLOQUER

            min_cost = self.get_min_amount(symbol)['min_cost']
            if self.paper_balance < min_cost:
                return False  # Solde USD insuffisant -> BLOQUER

            return True

        # 2. Vérification en Trading Réel (Exchange Balance)
        try:
            total_capital = self.capital_manager.get_total_capital()
            balance = self.balance_manager.get_balance(force_refresh=True)
            crypto = symbol.split('/')[0]
            
            free_amount = balance.get(crypto, {}).get('free', 0)
            locked_amount = balance.get(crypto, {}).get('used', 0)
            total_holding = free_amount + locked_amount
            
            if total_holding > 0.00001:
                current_price = self.get_price(symbol)
                position_value = total_holding * current_price
                min_cost = self.get_min_amount(symbol)['min_cost']
                
                if position_value < min_cost:
                    return True  # Poussière ignorée
                
                return False  # Position réelle déjà ouverte, bloquer
            
            usd_available = balance.get('USD', {}).get('free', 0)
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
                self._evaluate_exit_engine_for_symbol(symbol, current_price)
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
        self.save_state()
    
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
    
    def execute_buy(self, symbol, position_data, current_price, reason, ml_entry_learning_id=None):
        """Exécute l'achat avec données optimisées"""
        crypto = symbol.split('/')[0]
        existing_positions = [p for p in self.state.get('positions', []) 
                            if p['symbol'] == symbol and p['side'] == 'buy']
        position_count = len(existing_positions)

        # Dernière barrière anti-double-buy: l'état peut avoir changé entre
        # l'analyse du signal et l'exécution effective.
        cooldown_remaining = self.get_symbol_cooldown_remaining(symbol)
        if cooldown_remaining > 0:
            self.record_decision(
                symbol, 'buy_executed', False, 'symbol_cooldown_active_at_execution',
                {'price': current_price, 'cooldown_remaining_seconds': cooldown_remaining},
                throttle_seconds=0
            )
            return False

        if not self.can_open_position(symbol):
            self.record_decision(
                symbol, 'buy_executed', False, 'position_blocked_at_execution',
                {'price': current_price},
                throttle_seconds=0
            )
            return False
             
        # Exécuter
        result = self.buy_market(symbol, position_data['position_size_crypto'])
        
        if result:
            if ml_entry_learning_id and getattr(self, 'ml_live_logger', None):
                try:
                    self.ml_live_logger.mark_entry_opened(
                        symbol,
                        ml_entry_learning_id,
                        order=result,
                        price=current_price,
                        amount=position_data.get('position_size_crypto')
                    )
                except Exception:
                    pass
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
                self.trailing_stop_manager.add_position(
                    symbol, current_price, 
                    trailing_percent=position_data.get('trailing_stop_percent'),
                    support_price=position_data.get('support_price'),
                    resistance_price=position_data.get('resistance_price')
                )
            
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
            
    def _poll_dashboard_commands(self):
        """Lit et exécute les commandes envoyées depuis le dashboard."""
        try:
            commands = self.ml_live_logger.claim_pending_bot_commands() if getattr(self, 'ml_live_logger', None) else []
            if not commands or not isinstance(commands, list):
                return

            # Exécuter chaque commande
            for cmd in commands:
                action = cmd.get('action')
                symbol = cmd.get('symbol')
                if not action:
                    continue
                    
                print(f"🎮 Commande reçue du dashboard: {action} sur {symbol if symbol else 'global'}")
                
                if action == 'force_buy' and symbol:
                    self._execute_force_buy(symbol)
                elif action == 'force_sell' and symbol:
                    self._execute_force_sell(symbol)
                elif action == 'pause_pair' and symbol:
                    seconds = int(cmd.get('seconds') or 3600)
                    self.set_symbol_cooldown(symbol, seconds=seconds, reason='manual_pause')
                    print(f"⏸️ Paire {symbol} mise en pause pour {seconds}s")
                elif action == 'refresh_support_touch':
                    self.refresh_support_touch_filter(force=True)
                    print("🧪 Filtre Support Touch rafraîchi manuellement avec succès.")
                    
        except Exception as e:
            print(f"⚠️ Erreur lors du polling des commandes du dashboard: {e}")

    def _execute_force_buy(self, symbol):
        """Force un achat en ignorant les filtres techniques, mais en validant le capital"""
        try:
            # 1. Vérifier capital USD disponible
            balance = self.balance_manager.get_balance(force_refresh=True)
            quote = 'USD'
            usd_available = balance.get(quote, {}).get('free', 0) if not self.paper_trading else self.paper_balance
            
            min_cost = self.get_min_amount(symbol)['min_cost']
            if usd_available < min_cost:
                print(f"❌ Impossible de forcer l'achat: Capital insuffisant ({usd_available:.2f} USD < min {min_cost:.2f} USD)")
                return
                
            # 2. Calculer position sizing avec une confiance fixée à 100% pour avoir la taille maximale autorisée
            account_balance = self.get_account_balance()
            position_data = self.stuck_manager.calculate_position_size(symbol, 100, account_balance)
            
            # Ne pas appliquer de réduction de bear mode pour un force buy manuel
            position_data['target_price'] = self.get_price(symbol) * 1.015  # cible +1.5% par défaut
            position_data['stop_loss_price'] = self.get_price(symbol) * 0.95  # stop -5% par défaut
            
            reason = "Achat manuel forcé via Dashboard"
            
            # Exécuter l'achat
            self.execute_buy(symbol, position_data, self.get_price(symbol), reason)
            
        except Exception as e:
            print(f"❌ Erreur lors du force buy: {e}")

    def _execute_force_sell(self, symbol):
        """Force la vente de toute la crypto disponible pour un symbole"""
        try:
            # 1. Annuler les ordres de vente actifs pour ce symbole
            self._cancel_sell_orders_for_symbol(symbol)
            
            # 2. Récupérer le solde disponible
            balance = self.balance_manager.get_balance(force_refresh=True)
            base_currency = symbol.split('/')[0]
            
            if self.paper_trading:
                # En paper trading, trouver les positions correspondantes dans self.state['positions']
                amount_to_sell = 0
                for p in self.state.get('positions', []):
                    if p['symbol'] == symbol and p['side'] == 'buy':
                        amount_to_sell += p['amount']
            else:
                amount_to_sell = balance.get(base_currency, {}).get('free', 0)
                
            if amount_to_sell <= 0.00001:
                print(f"❌ Impossible de forcer la vente: Aucun solde disponible pour {base_currency}")
                return
                
            # 3. Exécuter la vente au marché
            if self.sell_market(symbol, amount_to_sell):
                if hasattr(self, 'trailing_stop_manager'):
                    self.trailing_stop_manager.remove_position(symbol)
                self.set_symbol_cooldown(symbol, 1800, reason='manual_force_sell')
                print(f"✅ Vente forcée exécutée avec succès pour {amount_to_sell:.6f} {base_currency} (Cooldown 30m actif)")
            else:
                print(f"❌ Échec de la vente forcée pour {symbol}")
                
        except Exception as e:
            print(f"❌ Erreur lors du force sell: {e}")

    def _append_score_history(self, symbol, score, price):
        """Historise le score crypto dans SQLite (max 1 fois par 5 minutes par symbole)."""
        try:
            now = time.time()
            last_append = self._last_score_append.get(symbol, 0)
            if now - last_append < 300:  # 5 minutes
                return
                
            self._last_score_append[symbol] = now
            
            if getattr(self, 'ml_live_logger', None):
                self.ml_live_logger.record_crypto_score(symbol, score, price)
                
        except Exception as e:
            print(f"⚠️ Erreur lors de l'historisation du score pour {symbol}: {e}")
    
