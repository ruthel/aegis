import time
import json
import os
import threading
import logging
from logging.handlers import RotatingFileHandler
import subprocess
import sys
from queue import Queue
from datetime import datetime

# Managers
from core.managers.notification import NotificationManager
from core.managers.balance import BalanceManager

# WebSocket
from core.websocket import WebSocketManager

# Utils
from utils.risk_manager import RiskManager, TrailingStopManager, CorrelationManager
import time
import json
import os
import threading
import logging
from logging.handlers import RotatingFileHandler
import subprocess
import sys
from queue import Queue
from datetime import datetime

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
from core.managers.execution_manager import ExecutionManager
from core.managers.health_manager import HealthManager
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
        self.exchange = None
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
        
        # Frais dynamiques
        self.trading_fee = 0.001
        self.min_profit_threshold = float(os.getenv('MIN_PROFIT_THRESHOLD', '0.8')) / 100
        
        # Stats
        self.daily_pnl = 0
        self.total_trades = 0
        self.winning_trades = 0
        self.global_stats_30d = None
        self.last_winrate_calculation = 0
        
        self.realtime_trading = False
        self.last_analysis = {}
        self.cumulative_tracker = {}
        self.last_dynamic_notifications = {}
        self.support_touch_cache = {}
        self._last_decision = {}
        self._decision_log_throttle = {}
        self.decision_journal_max = int(os.getenv('DECISION_JOURNAL_MAX', '5000'))
        self._ml_exit_learning_last = {}
        self._last_score_append = {}
        self.symbol_cooldown_seconds = int(os.getenv('SYMBOL_COOLDOWN_SECONDS', '300'))
        self.symbol_failure_cooldown_seconds = int(os.getenv('SYMBOL_FAILURE_COOLDOWN_SECONDS', '120'))
        self.ml_reject_cooldown_min_seconds = int(os.getenv('ML_REJECT_COOLDOWN_MIN_SECONDS', '60'))
        self.ml_reject_cooldown_max_seconds = int(os.getenv('ML_REJECT_COOLDOWN_MAX_SECONDS', '300'))
        self._buy_locks = {}
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
        self.health_check_interval = int(os.getenv('HEALTH_CHECK_INTERVAL_SECONDS', '300'))
        self.health_notify_interval = int(os.getenv('HEALTH_NOTIFY_INTERVAL_SECONDS', '1800'))
        self.health_safe_fallback_enabled = os.getenv('HEALTH_SAFE_FALLBACK_ENABLED', 'false').lower() == 'true'
        self.health_critical_fallback_after = int(os.getenv('HEALTH_CRITICAL_FALLBACK_AFTER', '3'))
        self._last_health_check = 0
        self._last_health_notify = 0
        self._last_health_status = None
        self._health_critical_count = 0
        self.ml_auto_retrain_enabled = os.getenv('ML_AUTO_RETRAIN_ENABLED', 'false').lower() == 'true'
        self.ml_auto_retrain_interval = int(os.getenv('ML_AUTO_RETRAIN_INTERVAL_SECONDS', '604800'))
        self.ml_auto_retrain_check_only = os.getenv('ML_AUTO_RETRAIN_CHECK_ONLY', 'true').lower() == 'true'
        self.ml_auto_retrain_fast = os.getenv('ML_AUTO_RETRAIN_FAST', 'false').lower() == 'true'
        self._last_ml_auto_retrain = 0
        self._ml_auto_retrain_process = None
        self.safe_fallback_enabled = os.getenv('SAFE_FALLBACK_ENABLED', 'true').lower() == 'true'
        self.safe_fallback_check_interval = int(os.getenv('SAFE_FALLBACK_CHECK_INTERVAL_SECONDS', '300'))
        self.safe_fallback_consecutive_losses = int(os.getenv('SAFE_FALLBACK_CONSECUTIVE_LOSSES', '3'))
        self.safe_fallback_daily_loss_usd = float(os.getenv('SAFE_FALLBACK_DAILY_LOSS_USD', str(max(20.0, self.max_daily_loss))))
        self.safe_fallback_weekly_loss_usd = float(os.getenv('SAFE_FALLBACK_WEEKLY_LOSS_USD', os.getenv('MAX_WEEKLY_LOSS', '300')))
        self.safe_fallback_drift_statuses = {
            item.strip().lower()
            for item in os.getenv('SAFE_FALLBACK_DRIFT_STATUSES', 'warning,critical').split(',')
            if item.strip()
        }
        self._last_safe_fallback_check = 0
        self.safe_fallback_mode = False
        self.consecutive_losses = 0
        self.pending_orders = {}
        self.order_timeout = 86400

        # Logger ML
        self.ml_live_logger = MLLiveLogger(
            data_dir='data',
            sqlite_file=os.getenv('ML_LIVE_SQLITE_FILE', 'data/aegis_db.sqlite3')
        )

        # TOUS LES GESTIONNAIRES (Instanciés dans l'ordre de dépendance)
        self.balance_manager = BalanceManager(self)
        self.capital_manager = CapitalManager(self)
        self.risk_manager = RiskManager(
            max_daily_trades=self.max_daily_trades,
            max_daily_loss=self.max_daily_loss,
            emergency_stop_loss=float(os.getenv('EMERGENCY_STOP_LOSS', '500'))
        )
        self.risk_manager.bot = self
        self.trailing_stop_manager = TrailingStopManager(float(os.getenv('TRAILING_STOP_PERCENT', '3')))
        self.correlation_manager = CorrelationManager()
        
        exit_enabled = os.getenv('EXIT_ENGINE_ENABLED', 'True').lower() == 'true'
        fragile_pct = float(os.getenv('PROFIT_FRAGILE_MAX_NET_PCT', '0.40'))
        time_stop_min = int(os.getenv('TIME_STOP_MINUTES', '12'))
        self.exit_decision_engine = ExitDecisionEngine(
            fragile_max_net_pct=fragile_pct,
            time_stop_minutes=time_stop_min
        ) if exit_enabled else None

        self.execution_manager = ExecutionManager(self)
        self.health_manager = HealthManager(self)
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

        from core.ml_engine import MLEngine
        self.ml_engine = MLEngine()
        self.ml_min_probability = float(os.getenv('ML_MIN_PROBABILITY', '65.0'))
        self.ml_exit_entry_min_continue_prob = float(os.getenv('ML_EXIT_ENTRY_MIN_CONTINUE_PROB', '50.0'))

        # Notifications
        self.notifier = NotificationManager()
        self.notifier.set_bot(self)

        # WebSocket & Display
        self.websocket = WebSocketManager()
        self.websocket.set_bot_callback(self.on_realtime_signal)
        self.websocket.set_balance_callback(self.on_balance_update)
        
        os.makedirs('data', exist_ok=True)
        self.display_queue = Queue(maxsize=100)

        # Connexion & état
        self.connect()
        self.load_state()
        self.websocket.set_exchange_client(self.exchange)
        self.websocket.preload_klines(self.exchange)
        self.websocket.start()
        self.refresh_support_touch_filter()
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
        
        # Calculer win rate global 30 jours au démarrage
        if not self.paper_trading:
            print("📊 Calcul win rate global (30 derniers jours)...")
            self.global_stats_30d = self.calculate_winrate_30d()
        
        # NOUVEAU: Placer automatiquement les cryptos disponibles en mode vente au démarrage
        print("🔍 Vérification positions existantes...")
        if hasattr(self, '_optimize_all_positions_at_startup'):
            self._optimize_all_positions_at_startup()

        # Mettre à jour prédictions ML au démarrage de façon asynchrone (non-bloquante)
        threading.Thread(target=self.update_ml_predictions_for_all_pairs, daemon=True).start()
        
        # Notification de démarrage
        mode = "PAPER" if self.paper_trading else "LIVE"
        self.notifier.notify(f"🤖 Bot démarré - {mode}")
        self.realtime_trading = True  # Init complète, activer le trading

    def update_ml_predictions_for_all_pairs(self):
        """Met à jour les prédictions ML pour toutes les paires actives en direct"""
        if not hasattr(self, 'ml_engine') or self.ml_engine is None or not getattr(self.ml_engine, 'is_trained', False):
            return

        try:
            trading_pairs = os.getenv('TRADING_PAIRS', 'BTCUSD,ETHUSD,SOLUSD,ADAUSD').split(',')
            ml_preds = self.state.setdefault('ml_predictions', {})

            for pair in trading_pairs:
                try:
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
                    
                    curr_price = float(klines_15m[-1]['close'])
                    trade_context = self._build_ml_trade_context() if hasattr(self, '_build_ml_trade_context') else {}
                    prob = self.ml_engine.predict_win_probability(
                        klines_15m,
                        curr_price,
                        trade_context=trade_context
                    )
                    rec = 'BUY_HIGH_CONFIDENCE' if prob >= getattr(self, 'ml_min_probability', 65.0) else ('NEUTRAL' if prob >= 50.0 else 'REJECT_RISK')

                    ml_preds[symbol] = {
                        'symbol': symbol,
                        'prob': round(float(prob), 2),
                        'p_win': prob,
                        'rec': rec,
                        'recommendation': rec,
                        'min_probability': getattr(self, 'ml_min_probability', 65.0),
                        'updated_at': datetime.now().isoformat(),
                        'timestamp': datetime.now().isoformat()
                    }
                except Exception as ex_pair:
                    pass
            self.save_state()
        except Exception as e:
            pass

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
        """Redirige vers la méthode unifiée d'optimisation de position.
        Si ML_OWNS_EXITS=true, crée quand même une position sell 'opened' pour le Dashboard
        (le ML décide quand exécuter, mais on trace l'intention de vente avec un prix cible).
        """
        if os.getenv('ML_OWNS_EXITS', 'true').lower() == 'true':
            try:
                import time as _time
                from datetime import datetime as _dt
                # Vérifier qu'il n'y a pas déjà un sell opened pour ce symbole
                existing_sell = any(
                    p.get('symbol') == symbol and p.get('side') == 'sell' and p.get('status') == 'opened'
                    for p in self.state.get('positions', [])
                )
                if existing_sell:
                    return True

                # Calculer le montant total d'achats non vendus
                open_buys = [
                    p for p in self.state.get('positions', [])
                    if p.get('symbol') == symbol and p.get('side') == 'buy'
                    and not p.get('closed_at')
                ]
                total_amount = sum(float(p.get('amount') or 0) for p in open_buys)
                if total_amount <= 0:
                    return False

                # Calculer prix moyen d'entrée
                total_cost = sum(float(p.get('amount') or 0) * float(p.get('price') or 0) for p in open_buys)
                avg_price = total_cost / total_amount if total_amount > 0 else 0

                # Prix cible = prix moyen + profit minimum configuré
                min_profit = float(os.getenv('MIN_PROFIT_THRESHOLD', '1.0')) / 100
                target_price = avg_price * (1 + min_profit)

                order_id = f'ml_sell_{symbol.replace("/", "")}_{_time.time_ns()}'
                position = {
                    'symbol': symbol,
                    'side': 'sell',
                    'amount': total_amount,
                    'price': target_price,
                    'timestamp': _dt.now().isoformat(),
                    'order_id': order_id,
                    'source': 'ml_exit_engine',
                    'paper': True,
                    'status': 'opened',
                    'position_size_crypto': total_amount,
                    'position_size_usd': total_amount * target_price,
                }
                self.state.setdefault('positions', []).append(position)
                if getattr(self, 'ml_live_logger', None):
                    self.ml_live_logger.record_order_transaction(
                        symbol,
                        'sell',
                        total_amount,
                        target_price,
                        order_type='limit',
                        status='open',
                        order_id=order_id,
                        mode='paper',
                        source='paper_trade'
                    )
                self.save_state()
                print(f"📋 ML EXIT - Position sell tracée: {total_amount:.6f} {symbol.split('/')[0]} @ {target_price:.6f} (ML décidera quand vendre)")
                return True
            except Exception as e:
                print(f"⚠️ Erreur _place_paper_sell_order: {e}")
                return False

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
        self.save_state()

    def get_ml_reject_cooldown_seconds(self, ml_win_prob, ml_exit_forecast=None, ml_bot_context=None):
        """Cooldown dynamique après refus ML pour éviter de relogger le même setup trop vite."""
        min_seconds = max(0, int(self.ml_reject_cooldown_min_seconds))
        max_seconds = max(min_seconds, int(self.ml_reject_cooldown_max_seconds))
        if max_seconds <= 0:
            return 0

        try:
            p_win = float(ml_win_prob or 0.0)
        except Exception:
            p_win = 0.0
        p_continue = self.ml_exit_entry_min_continue_prob
        if isinstance(ml_exit_forecast, dict) and ml_exit_forecast.get('p_continue') is not None:
            try:
                p_continue = float(ml_exit_forecast.get('p_continue'))
            except Exception:
                p_continue = self.ml_exit_entry_min_continue_prob

        p_win_gap = max(0.0, self.ml_min_probability - p_win)
        p_continue_gap = max(0.0, self.ml_exit_entry_min_continue_prob - p_continue)
        severity = max(p_win_gap / 30.0, p_continue_gap / 25.0)
        severity = max(0.0, min(1.0, severity))
        seconds = min_seconds + (max_seconds - min_seconds) * severity

        context = ml_bot_context if isinstance(ml_bot_context, dict) else {}
        if context.get('bear_mode') or context.get('falling_knife_active'):
            seconds *= 1.25
        if p_win >= self.ml_min_probability - 5 and p_continue >= self.ml_exit_entry_min_continue_prob:
            seconds *= 0.65

        return int(max(min_seconds, min(max_seconds, round(seconds))))

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
        try:
            symbol_momentum = self._get_symbol_short_momentum(symbol)
        except Exception:
            symbol_momentum = 0

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
            'symbol_momentum_percent': symbol_momentum,
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

    def _get_symbol_short_momentum(self, symbol, candles=6, timeframe='15m'):
        """Momentum court affichable: variation recente du symbole en pourcentage."""
        klines = self.get_klines(symbol, candles, timeframe)
        if not klines or len(klines) < 2:
            return 0.0
        first_close = float(klines[0].get('close') or 0.0)
        last_close = float(klines[-1].get('close') or 0.0)
        if first_close <= 0 or last_close <= 0:
            return 0.0
        return ((last_close - first_close) / first_close) * 100.0

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

    def _confidence_sizing_factor(self, signal_strength):
        """Ajuste prudemment la taille avant le ML selon la force du signal technique."""
        try:
            strength = float(signal_strength or 0.0)
        except Exception:
            strength = 50.0

        if strength >= 80.0:
            return 1.0
        if strength >= 65.0:
            return 0.85
        if strength >= 50.0:
            return 0.70
        if strength >= 35.0:
            return 0.50
        return 0.35

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
                    exchange_name = os.getenv('EXCHANGE', 'kraken').lower()
                    if exchange_name == 'kraken':
                        min_costs = {'BTC/USD': 0.5, 'ETH/USD': 0.5, 'SOL/USD': 0.5, 'ADA/USD': 0.5}
                        min_amounts = {'BTC/USD': 0.0001, 'ETH/USD': 0.001, 'SOL/USD': 0.01, 'ADA/USD': 0.1}
                    else:
                        min_costs = {'BTC/USD': 15, 'ETH/USD': 10, 'SOL/USD': 8, 'ADA/USD': 12}
                        min_amounts = {'BTC/USD': 0.00015, 'ETH/USD': 0.003, 'SOL/USD': 0.04, 'ADA/USD': 0.01}
                    self.min_amounts[symbol] = {
                        'min_amount': min_amounts.get(symbol, 0.001), 
                        'min_cost': min_costs.get(symbol, 0.5 if exchange_name == 'kraken' else 10)
                    }
            except Exception as e:
                # Fallback avec minimums du marché (pas API)
                exchange_name = os.getenv('EXCHANGE', 'kraken').lower()
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
            
            if str(result.get('decision') or '').upper() != 'HOLD':
                self.record_decision(
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
        """Applique uniquement les décisions de sortie ML actives."""
        if not exit_result:
            return False
        if not hasattr(self, 'trailing_stop_manager') or symbol not in getattr(self.trailing_stop_manager, 'positions', {}):
            return False

        decision = exit_result.get('decision')

        if decision in ('FORCE_EXIT', 'TAKE_PROFIT'):
            if not self._cancel_sell_orders_for_symbol(symbol):
                return False
            balance = self.balance_manager.get_balance(force_refresh=True)
            base_currency = symbol.split('/')[0]
            available = balance.get(base_currency, {}).get('free', 0)
            position_data = self.trailing_stop_manager.positions.get(symbol, {})
            pos_amount = float(position_data.get('amount') or position_data.get('position_size_crypto') or 0.0)
            sell_amount = max(available, pos_amount) if self.paper_trading else available
            if sell_amount <= 0.00001:
                return False
            if self.sell_market(symbol, sell_amount, reason=f"ml_exit_{decision.lower()}"):
                self.trailing_stop_manager.remove_position(symbol)
                if hasattr(self, 'set_symbol_cooldown'):
                    self.set_symbol_cooldown(symbol, reason=f"ml_exit_{decision.lower()}")
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

        return False

    def _rehydrate_open_positions_for_exit_evaluation(self):
        """Re-hydrate les positions ouvertes dans trailing_stop_manager pour l'évaluation de sortie ML."""
        if not hasattr(self, 'trailing_stop_manager') or not self.trailing_stop_manager:
            return
        open_pos = self.get_open_positions()
        for symbol, data in open_pos.items():
            if symbol not in getattr(self.trailing_stop_manager, 'positions', {}):
                entry_price = float(data.get('entry_price', 0.0) or 0.0)
                amount = float(data.get('amount', 0.0) or 0.0)
                if entry_price > 0 and amount > 0:
                    self.trailing_stop_manager.positions[symbol] = {
                        'entry_price': entry_price,
                        'buy_price': entry_price,
                        'avg_entry_price': entry_price,
                        'price': entry_price,
                        'highest_price': entry_price,
                        'stop_price': entry_price * (1 - getattr(self, 'stop_loss_percent', 5.0) / 100.0),
                        'trailing_active': False,
                        'amount': amount,
                        'buy_time': time.time()
                    }

    def _update_trailing_stop_from_tick(self, symbol, current_price):
        """Évalue la sortie ML dès le tick WebSocket, sans attendre la boucle principale."""
        if not hasattr(self, 'trailing_stop_manager'):
            return
        if symbol not in getattr(self.trailing_stop_manager, 'positions', {}):
            self._rehydrate_open_positions_for_exit_evaluation()
            if symbol not in getattr(self.trailing_stop_manager, 'positions', {}):
                return

        try:
            ml_owns_exits = os.getenv('ML_OWNS_EXITS', 'true').lower() == 'true'
            changed = False if ml_owns_exits else self.trailing_stop_manager.update_position(symbol, current_price)
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
                if os.getenv('ML_OWNS_EXITS', 'true').lower() == 'true':
                    continue
                # VENTE EXÉCUTÉE
                buy_price = self.get_real_buy_price(symbol)
                fee_rate = float(getattr(self, 'trading_fee', 0) or 0)
                if fee_rate <= 0:
                    fee_rate = float(os.getenv('TRADING_FEE_PERCENT', '0.1')) / 100.0
                revenue = amount * current_price
                if getattr(self, 'ml_live_logger', None):
                    self.ml_live_logger.record_fill_transaction(
                        order_id,
                        symbol,
                        'sell',
                        amount,
                        current_price,
                        fee_amount=revenue * fee_rate,
                        fee_asset='USD',
                        mode='paper',
                        source='paper_trade'
                    )
                    self._refresh_paper_balance_from_accounting()
                else:
                    self.paper_balance += (revenue * (1 - fee_rate))
                crypto = symbol.split('/')[0]
                print(f"✅ PAPER VENTE EXÉCUTÉE: {amount:.6f} {crypto} @ {current_price:.2f} (cible: {limit_price:.2f})")
                
                pnl = self.calculate_pnl(symbol, 'sell', amount, current_price, buy_price=buy_price)
                if hasattr(self, 'risk_manager') and pnl is not None:
                    self.risk_manager.record_trade(pnl)
                
                # Marquer les positions buy correspondantes comme closed (style Binance)
                self._close_buy_positions(symbol, amount, current_price)
                
                found = False
                fee_details = self._calculate_fee_details(amount, current_price, buy_price)
                for p in reversed(self.state.get('positions', [])):
                    if p.get('order_id') == order_id and p.get('status') == 'opened':
                        p['status'] = 'executed'
                        p['price'] = current_price
                        p['avg_entry_price'] = buy_price
                        p['position_size_crypto'] = amount
                        p['position_size_usd'] = amount * current_price
                        p.update(fee_details)
                        found = True
                        break
                if not found:
                    position = {
                        'symbol': symbol, 'side': 'sell', 'amount': amount,
                        'price': current_price, 'timestamp': datetime.now().isoformat(),
                        'order_id': order_id, 'source': 'bot', 'paper': True,
                        'avg_entry_price': buy_price, 'status': 'executed'
                    }
                    position.update(fee_details)
                    self.state.setdefault('positions', []).append(position)
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
                fee_rate = float(getattr(self, 'trading_fee', 0) or 0)
                if fee_rate <= 0:
                    fee_rate = float(os.getenv('TRADING_FEE_PERCENT', '0.1')) / 100.0
                buy_fee = amount * current_price * fee_rate
                if getattr(self, 'ml_live_logger', None):
                    self.ml_live_logger.record_fill_transaction(
                        order_id,
                        symbol,
                        'buy',
                        amount,
                        current_price,
                        fee_amount=buy_fee,
                        fee_asset='USD',
                        mode='paper',
                        source='paper_trade'
                    )
                    self._refresh_paper_balance_from_accounting()
                else:
                    self.paper_balance -= (cost * (1 + fee_rate))

                position = {
                    'symbol': symbol, 'side': 'buy', 'amount': amount,
                    'price': current_price, 'timestamp': datetime.now().isoformat(),
                    'order_id': order_id, 'source': 'bot', 'paper': True, 'status': 'executed',
                    'fee_rate': fee_rate, 'fee': buy_fee
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
                self.run_health_checks_if_due()
                self.run_ml_auto_retraining_if_due()
                self.evaluate_safe_fallback_if_due()
                
                time.sleep(0.5)
                
        except KeyboardInterrupt:
            print("🛑 Arrêt du bot...")
            self.notifier.notify("🛑 Bot arrêté")
            if hasattr(self, 'websocket'):
                self.websocket.stop()
            self.save_state()
        except Exception as e:
            print(f"⚠️ Erreur bot: {e}")
            raise e
        finally:
            self.shutdown()

    def shutdown(self):
        """Ferme proprement les ressources longues du bot."""
        for attr in ('websocket', 'risk_manager', 'ml_live_logger'):
            try:
                resource = getattr(self, attr, None)
                if resource and hasattr(resource, 'close'):
                    resource.close()
                elif resource and hasattr(resource, 'stop'):
                    resource.stop()
            except Exception:
                pass
    
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
            best_level_logs = []
            # Utiliser directement la liste des cryptos tradables passée en paramètre
            for symbol in tradable_pairs:
                current_price = self.get_price(symbol)
                entry_opportunities = self.pattern_analyzer.get_entry_levels(symbol, current_price)
                
                if entry_opportunities:
                    crypto = symbol.split('/')[0]
                    best_entry = entry_opportunities[0]
                    best_level_logs.append(
                        f"{crypto} {best_entry['price']:.2f} ({best_entry['type']}, {best_entry['distance']:.1f}%)"
                    )
                    
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
            return
        
        # 1. VÉRIFICATIONS ABSOLUES DE SÉCURITÉ (CAPITAL / BEAR CONTEXT)

        # 1A. Détection Couteau qui tombe: feature ML uniquement, pas verrou dur.
        falling_knife = self._detect_falling_knife(symbol)

        # 1B. Vérifier position existante et capital
        if not self.can_open_position(symbol):
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
                klines_4h = self.get_klines(symbol, 30, '4h')
                klines_1d = self.get_klines(symbol, 30, '1d')
                ml_trade_context = self._build_ml_trade_context(position_data, account_balance)
                ml_entry_features = self.ml_engine.extract_features_from_klines(
                    klines_15m,
                    current_price,
                    klines_5m=klines_5m,
                    klines_1h=klines_1h,
                    klines_4h=klines_4h,
                    klines_1d=klines_1d,
                    trade_context=ml_trade_context,
                    bot_context=ml_bot_context
                )
                ml_win_prob = self.ml_engine.predict_win_probability(
                    klines_15m,
                    current_price,
                    klines_5m=klines_5m,
                    klines_1h=klines_1h,
                    klines_4h=klines_4h,
                    klines_1d=klines_1d,
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

                # ── Option A : Sizing gradué selon confiance ML ──────────────────
                # REJECT_RISK  < 50%   → Position 0%   (bloqué — ML a une conviction négative)
                # NEUTRAL bas  50-55%  → Position 40%  (signal incertain — taille mini)
                # NEUTRAL haut 55-65%  → Position 70%  (signal douteux — taille réduite)
                # BUY_HIGH     ≥ 65%   → Position 100% (pleine confiance — taille normale)
                if ml_win_prob < 50.0:
                    # REJECT_RISK : ML dit NON — bloquer
                    reject_cooldown_seconds = self.get_ml_reject_cooldown_seconds(
                        ml_win_prob,
                        ml_exit_forecast,
                        ml_bot_context
                    )
                    self.record_ml_entry_learning_sample(
                        symbol,
                        'rejected',
                        current_price,
                        ml_win_prob,
                        ml_exit_forecast,
                        features=ml_entry_features,
                        bot_context=ml_bot_context,
                        trade_context=ml_trade_context,
                        reason=f'ml_reject_risk_{ml_win_prob:.1f}%'
                    )
                    self.record_decision(
                        symbol, 'buy', False, f'ml_reject_risk_{ml_win_prob:.1f}%',
                        self._build_ml_entry_decision_metrics(
                            current_price,
                            ml_win_prob,
                            ml_exit_forecast,
                            ml_bot_context,
                            extra={'reject_cooldown_seconds': reject_cooldown_seconds}
                        ),
                        throttle_seconds=120
                    )
                    self.set_symbol_cooldown(
                        symbol,
                        reject_cooldown_seconds,
                        reason=f'ml_reject_risk_{ml_win_prob:.1f}%'
                    )
                    return
                # ── Option A : Sizing gradué selon confiance ML & Kelly (Phase 6) ──
                sizing_info = self.risk_manager.calculate_position_size(
                    self, symbol, base_amount=getattr(self, 'trade_amount', 10), ml_win_prob=ml_win_prob
                )
                position_data['sizing_reason'] = sizing_info['sizing_reason']
                position_data['ml_buy_prob'] = ml_win_prob

                if ml_win_prob < self.ml_min_probability:
                    ml_position_factor = sizing_info['ml_factor']
                    position_data['position_size_usd'] = sizing_info['position_size_usd']
                    raw_crypto = (position_data['position_size_usd'] / current_price) if current_price > 0 else 0
                    position_data['position_size_crypto'] = self.stuck_manager.round_quantity(symbol, raw_crypto)
                    position_data['ml_position_factor'] = ml_position_factor
                    position_data['ml_neutral_sizing'] = True
                    print(f"🟡 {crypto}: ML NEUTRE {ml_win_prob:.1f}% → Sizing Phase 6: {position_data['position_size_usd']:.2f} USD [{position_data['sizing_reason']}]")
                else:
                    position_data['position_size_usd'] = sizing_info['position_size_usd']
                    raw_crypto = (position_data['position_size_usd'] / current_price) if current_price > 0 else 0
                    position_data['position_size_crypto'] = self.stuck_manager.round_quantity(symbol, raw_crypto)

                if self._should_reject_entry_for_ml_exit(ml_exit_forecast):
                    reject_cooldown_seconds = self.get_ml_reject_cooldown_seconds(
                        ml_win_prob,
                        ml_exit_forecast,
                        ml_bot_context
                    )
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
                            ml_bot_context,
                            extra={'reject_cooldown_seconds': reject_cooldown_seconds}
                        ),
                        throttle_seconds=120
                    )
                    self.set_symbol_cooldown(
                        symbol,
                        reject_cooldown_seconds,
                        reason=f"ml_reject_exit_{ml_exit_forecast.get('p_continue', 0):.1f}%"
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
            throttle_seconds=0,
            entry_id=ml_entry_learning_id
        )
        self.execute_buy(symbol, position_data, current_price, reason, ml_entry_learning_id=ml_entry_learning_id)
    
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
        except Exception:
            return False

    def trigger_safe_fallback_mode(self, reason="Perte de performance ou drift critique"):
        """
        Déclenche le Mode Safe Fallback & Auto-Rollback (Phase 10) :
        - Active le mode Safe (réduction sizing à 35%)
        - Restaure le modèle Champion de sauvegarde `aegis_model_backup.joblib` s'il existe
        - Journalise dans governance_logs et alerte sur Telegram.
        """
        try:
            if getattr(self, 'safe_fallback_mode', False):
                return False

            self.safe_fallback_mode = True
            print(f"🚨 DÉCLENCHEMENT MODE SAFE FALLBACK & AUTO-ROLLBACK ({reason})")

            backup_path = os.path.join('data', 'aegis_model_backup.joblib')
            champion_path = os.path.join('data', 'aegis_model.joblib')
            restored = False

            if os.path.exists(backup_path):
                import shutil
                shutil.copy2(backup_path, champion_path)
                if hasattr(self, 'ml_engine') and self.ml_engine:
                    self.ml_engine.model_path = champion_path
                    self.ml_engine.load_model()
                restored = True
                print("  ✅ Modèle Champion de sauvegarde restauré avec succès.")

                # Sauvegarde d'archive du rollback dans data/backups/
                try:
                    backups_dir = os.path.join('data', 'backups')
                    os.makedirs(backups_dir, exist_ok=True)
                    from datetime import datetime as _dt
                    ts_rb_path = os.path.join(backups_dir, f"aegis_model_{_dt.now().strftime('%Y%m%d_%H%M%S')}.joblib")
                    shutil.copy2(backup_path, ts_rb_path)
                    print(f"  📦 Archive du rollback conservée dans backups/ : {ts_rb_path}")
                except Exception:
                    pass

            if getattr(self, 'ml_live_logger', None):
                self.ml_live_logger.record_governance_event(
                    event_type='auto_rollback' if restored else 'safe_mode_enabled',
                    source_model='champion_live',
                    target_model='champion_backup' if restored else 'none',
                    metrics={'safe_fallback_mode': True, 'restored_backup': restored},
                    trigger_type='auto',
                    reason=reason
                )

            if hasattr(self, 'notifier') and self.notifier:
                msg = f"🚨 **AUTO-ROLLBACK & SAFE MODE ACTIVÉ**\n\nMotif: {reason}\nRestauré backup: {'Oui' if restored else 'Non'}\nAction: Position Sizing réduit à 35%"
                self.notifier.notify(msg)

            return True
        except Exception as e:
            print(f"⚠️ Erreur trigger_safe_fallback_mode: {e}")
            return False

    def run_health_checks_if_due(self, force=False):
        """Execute les health checks Phase 8 avec throttling et journal de gouvernance."""
        try:
            if not getattr(self, 'health_manager', None):
                return None

            now = time.time()
            if not force and now - self._last_health_check < max(30, self.health_check_interval):
                return None
            self._last_health_check = now

            result = self.health_manager.run_checks()
            status = str(result.get('global_status') or 'UNKNOWN').upper()
            previous = self._last_health_status
            status_changed = previous != status
            self._last_health_status = status

            should_notify = (
                status in ('WARN', 'CRITICAL')
                and (
                    status_changed
                    or now - self._last_health_notify >= max(300, self.health_notify_interval)
                )
            )

            if getattr(self, 'ml_live_logger', None) and (status_changed or status in ('WARN', 'CRITICAL')):
                metrics = {
                    'global_status': status,
                    'database': result.get('database', {}),
                    'websocket': result.get('websocket', {}),
                    'exchange': result.get('exchange', {}),
                    'ml_engine': result.get('ml_engine', {}),
                    'bot_loop': result.get('bot_loop', {}),
                }
                self.ml_live_logger.record_governance_event(
                    event_type='health_status',
                    source_model='runtime',
                    target_model=None,
                    metrics=metrics,
                    trigger_type='auto',
                    reason=f"Health status {previous or 'UNKNOWN'} -> {status}" if status_changed else f"Health status {status}"
                )

            if should_notify and getattr(self, 'notifier', None):
                self._last_health_notify = now
                self.notifier.notify_health_status(self.health_manager.get_summary_text(result))

            if status == 'CRITICAL':
                self._health_critical_count += 1
                if getattr(self, 'ml_live_logger', None):
                    self.ml_live_logger.record_governance_event(
                        event_type='health_action_required',
                        source_model='runtime',
                        target_model='operator',
                        metrics={'critical_count': self._health_critical_count, 'safe_fallback_enabled': self.health_safe_fallback_enabled},
                        trigger_type='auto',
                        reason='Health check critique detecte'
                    )
                if (
                    self.health_safe_fallback_enabled
                    and self._health_critical_count >= max(1, self.health_critical_fallback_after)
                ):
                    self.trigger_safe_fallback_mode(reason='Health check critique persistant')
            else:
                self._health_critical_count = 0

            return result
        except Exception as e:
            print(f"⚠️ Erreur run_health_checks_if_due: {e}")
            return None

    def connect(self):
        """Initialise la connexion avec l'exchange configuré (Binance/Kraken)."""
        try:
            exchange_name = os.getenv('EXCHANGE', 'binance').lower()
            if exchange_name == 'kraken':
                try:
                    from core.exchange.kraken import KrakenClient
                    self.exchange = KrakenClient(self.api_key, self.api_secret, self.testnet)
                except Exception:
                    from core.exchange.binance import BinanceClient
                    self.exchange = BinanceClient(self.api_key, self.api_secret, self.testnet)
            else:
                from core.exchange.binance import BinanceClient
                self.exchange = BinanceClient(self.api_key, self.api_secret, self.testnet)

            if hasattr(self.exchange, 'connect'):
                self.exchange.connect()
            print(f"✅ Exchange {exchange_name.upper()} connecté avec succès.")
            return True
        except Exception as e:
            print(f"⚠️ Avertissement connexion exchange: {e}")
            if not hasattr(self, 'exchange') or self.exchange is None:
                from core.exchange.binance import BinanceClient
                self.exchange = BinanceClient(self.api_key, self.api_secret, self.testnet)
            return False

    def record_decision(self, symbol, action_type=None, confidence=None, p_win=None, reason="", features=None, mode='paper', throttle_seconds=0, **kwargs):
        """Journalise une décision (Achat, Vente, Refus ML, Trailing Stop) dans SQLite et governance_logs avec throttling."""
        try:
            action = kwargs.get('action', action_type)
            allowed = kwargs.get('allowed', confidence if isinstance(confidence, bool) else None)
            metrics = kwargs.get('metrics', features)
            
            # Si le 4ème argument positionnel est une chaîne de caractères, c'est 'reason' et non 'p_win'
            if isinstance(p_win, str) and not reason:
                reason = p_win
                p_win = None

            final_features = metrics if isinstance(metrics, dict) else (features if isinstance(features, dict) else {})
            
            # Gestion du throttling (pour éviter de spammer le même log pour un même symbole / raison)
            if throttle_seconds > 0:
                if not hasattr(self, '_decision_log_throttle'):
                    self._decision_log_throttle = {}
                throttle_key = (symbol, str(action), str(reason))
                now = time.time()
                last_time = self._decision_log_throttle.get(throttle_key, 0)
                if now - last_time < throttle_seconds:
                    return
                self._decision_log_throttle[throttle_key] = now

            conf_val = confidence if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) else None
            p_win_val = p_win if isinstance(p_win, (int, float)) and not isinstance(p_win, bool) else None

            entry = {
                'timestamp': datetime.now().isoformat(),
                'symbol': symbol,
                'action_type': action,
                'action': action,
                'confidence': conf_val,
                'allowed': allowed,
                'p_win': p_win_val,
                'reason': reason,
                'features': final_features,
                'metrics': final_features
            }
            if hasattr(self, 'ml_live_logger') and self.ml_live_logger:
                self.ml_live_logger.record_decision_journal(entry, mode=mode)
        except Exception as e:
            print(f"⚠️ Erreur record_decision: {e}")

    def run_daily_optimizations(self):
        """Exécute les optimisations et nettoyages quotidiens du bot."""
        try:
            now = time.time()
            last_opt = getattr(self, '_last_daily_optimizations', 0)
            if now - last_opt > 86400:  # Une fois par jour
                self._last_daily_optimizations = now
                if hasattr(self, 'risk_manager') and hasattr(self.risk_manager, 'update_daily_stats'):
                    self.risk_manager.update_daily_stats()
                if hasattr(self, '_decision_log_throttle'):
                    self._decision_log_throttle = {k: v for k, v in self._decision_log_throttle.items() if now - v < 3600}
        except Exception as e:
            print(f"⚠️ Erreur run_daily_optimizations: {e}")

    def run_ml_live_analysis_if_due(self):
        """Lance l'analyse de performance ML en arrière-plan si l'intervalle est écoulé."""
        try:
            now = time.time()
            last_analysis = getattr(self, '_last_ml_live_analysis', 0)
            interval = getattr(self, 'ml_live_analysis_interval', 21600)
            if now - last_analysis > interval:
                self._last_ml_live_analysis = now
                script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts', 'analyze_ml_live_performance.py')
                if os.path.exists(script_path):
                    proc = getattr(self, '_ml_live_analysis_process', None)
                    if proc is None or proc.poll() is not None:
                        self._ml_live_analysis_process = subprocess.Popen([sys.executable, script_path])
        except Exception as e:
            print(f"⚠️ Erreur run_ml_live_analysis_if_due: {e}")

    def run_ml_auto_retraining_if_due(self, force=False):
        """Planifie le retraining ML sans bloquer la boucle de trading."""
        try:
            if not force and not getattr(self, 'ml_auto_retrain_enabled', False):
                return False

            proc = getattr(self, '_ml_auto_retrain_process', None)
            if proc is not None and proc.poll() is None:
                return False

            now = time.time()
            interval = max(3600, int(getattr(self, 'ml_auto_retrain_interval', 604800)))
            last_run = getattr(self, '_last_ml_auto_retrain', 0)
            if not force and now - last_run < interval:
                return False

            script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts', 'train_and_evaluate_ml_model.py')
            if not os.path.exists(script_path):
                if getattr(self, 'ml_live_logger', None):
                    self.ml_live_logger.record_governance_event(
                        event_type='auto_retraining_skipped',
                        source_model='runtime',
                        target_model='challenger',
                        trigger_type='auto',
                        reason='Script train_and_evaluate_ml_model.py introuvable'
                    )
                return False

            command = [
                sys.executable,
                script_path,
                '--dir',
                'data',
                '--db',
                os.getenv('ML_LIVE_SQLITE_FILE', 'data/aegis_db.sqlite3'),
                '--trigger',
                'auto',
            ]
            if getattr(self, 'ml_auto_retrain_check_only', True):
                command.append('--check-only')
            if getattr(self, 'ml_auto_retrain_fast', False):
                command.append('--fast')

            self._last_ml_auto_retrain = now
            self._ml_auto_retrain_process = subprocess.Popen(command)
            if getattr(self, 'ml_live_logger', None):
                self.ml_live_logger.record_governance_event(
                    event_type='auto_retraining_started',
                    source_model='champion',
                    target_model='challenger',
                    metrics={
                        'check_only': bool(getattr(self, 'ml_auto_retrain_check_only', True)),
                        'fast': bool(getattr(self, 'ml_auto_retrain_fast', False)),
                        'interval_seconds': interval,
                        'pid': self._ml_auto_retrain_process.pid,
                    },
                    trigger_type='auto',
                    reason='Retraining planifie lance en arriere-plan'
                )
            return True
        except Exception as e:
            print(f"⚠️ Erreur run_ml_auto_retraining_if_due: {e}")
            return False

    def evaluate_safe_fallback_if_due(self, force=False):
        """Active le safe fallback si les signaux de risque Phase 10 deviennent critiques."""
        try:
            if not force and not getattr(self, 'safe_fallback_enabled', True):
                return False
            if getattr(self, 'safe_fallback_mode', False):
                return False

            now = time.time()
            if not force and now - self._last_safe_fallback_check < max(60, self.safe_fallback_check_interval):
                return False
            self._last_safe_fallback_check = now

            signals = self._collect_safe_fallback_signals()
            reasons = []
            if signals.get('consecutive_losses', 0) >= self.safe_fallback_consecutive_losses:
                reasons.append(f"{signals['consecutive_losses']} pertes consecutives")
            if abs(signals.get('daily_loss_usd', 0.0)) >= self.safe_fallback_daily_loss_usd:
                reasons.append(f"perte journaliere {signals['daily_loss_usd']:.2f} USD")
            if abs(signals.get('weekly_loss_usd', 0.0)) >= self.safe_fallback_weekly_loss_usd:
                reasons.append(f"perte hebdo {signals['weekly_loss_usd']:.2f} USD")
            if str(signals.get('drift_status') or '').lower() in self.safe_fallback_drift_statuses:
                reasons.append(f"drift ML {signals.get('drift_status')}")

            if not reasons:
                return False

            reason = '; '.join(reasons)
            if getattr(self, 'ml_live_logger', None):
                self.ml_live_logger.record_governance_event(
                    event_type='safe_fallback_triggered',
                    source_model='runtime',
                    target_model='safe_fallback',
                    metrics=signals,
                    trigger_type='auto',
                    reason=reason
                )
            return self.trigger_safe_fallback_mode(reason=reason)
        except Exception as e:
            print(f"⚠️ Erreur evaluate_safe_fallback_if_due: {e}")
            return False

    def _collect_safe_fallback_signals(self):
        signals = {
            'consecutive_losses': 0,
            'daily_loss_usd': 0.0,
            'weekly_loss_usd': 0.0,
            'drift_status': None,
        }
        try:
            if getattr(self, 'risk_manager', None):
                stats = self.risk_manager.get_stats() if hasattr(self.risk_manager, 'get_stats') else getattr(self.risk_manager, 'daily_stats', {})
                signals['daily_loss_usd'] = abs(float((stats or {}).get('total_loss') or 0.0))
                if hasattr(self.risk_manager, 'get_weekly_loss'):
                    signals['weekly_loss_usd'] = abs(float(self.risk_manager.get_weekly_loss() or 0.0))
        except Exception:
            pass

        try:
            if getattr(self, 'ml_live_logger', None):
                import sqlite3 as _sqlite3
                conn = _sqlite3.connect(self.ml_live_logger.sqlite_file)
                cur = conn.cursor()
                rows = cur.execute("""
                    SELECT pnl
                    FROM ml_trade_outcomes
                    WHERE pnl IS NOT NULL
                    ORDER BY timestamp DESC
                    LIMIT 10
                """).fetchall()
                losses = 0
                for (pnl,) in rows:
                    if float(pnl or 0.0) < 0:
                        losses += 1
                    else:
                        break
                signals['consecutive_losses'] = losses

                drift = cur.execute("""
                    SELECT status
                    FROM ml_drift_alerts
                    ORDER BY generated_at DESC
                    LIMIT 1
                """).fetchone()
                if drift:
                    signals['drift_status'] = drift[0]
                conn.close()
        except Exception:
            pass
        return signals

    def safe_request(self, func, *args, **kwargs):
        """Exécute une requête exchange de manière sécurisée avec retries et gestion des erreurs."""
        if not func:
            return None
        max_retries = getattr(self, 'max_retries', 3)
        retry_delay = getattr(self, 'retry_delay', 1)
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if attempt == max_retries - 1:
                    raise e
                time.sleep(retry_delay)
        return None

    def can_open_position(self, symbol):
        """Vérifie si on peut ouvrir une position - IGNORE LA POUSSIÈRE + vérifie capital et positions ouvertes"""
        from utils.market_analyzer import MarketAnalyzer
        
        # Gouvernance Risque Phase 10 : Perte hebdo & exposition globale
        if hasattr(self, 'risk_manager') and self.risk_manager.is_weekly_loss_exceeded():
            print(f"🛑 GOUVERNANCE RISQUE: Perte hebdomadaire max atteinte ({self.risk_manager.get_weekly_loss():.2f} USD). Achats bloqués.")
            return False

        if hasattr(self, 'capital_manager'):
            trade_size_usd = self.capital_manager.get_trade_amount(symbol)
            if not self.capital_manager.can_open_new_position(symbol, trade_size_usd):
                return False

        # 1. Vérification en Paper Trading
        if self.paper_trading:
            open_paper_positions = [
                p for p in self.state.get('positions', [])
                if p.get('symbol') == symbol and p.get('side') == 'sell' and p.get('status') == 'opened'
            ]
            if open_paper_positions:
                return False  # Déjà 1 position ouverte sur ce symbole en Paper Trading -> BLOQUER

            total_open = len([
                p for p in self.state.get('positions', [])
                if p.get('side') == 'sell' and p.get('status') == 'opened'
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
            target_sym = str(symbol).replace('/', '').upper()
            for order_id, order_data in list(self.pending_orders.items()):
                if str(order_data.get('symbol', '')).replace('/', '').upper() == target_sym and order_data.get('side') == 'sell':
                    del self.pending_orders[order_id]
            for p in reversed(self.state.get('positions', [])):
                p_sym = str(p.get('symbol', '')).replace('/', '').upper()
                if p_sym == target_sym and p.get('side') == 'sell' and p.get('status') == 'opened':
                    p['status'] = 'canceled'
            if getattr(self, 'ml_live_logger', None):
                self.ml_live_logger.cancel_open_orders(symbol=symbol, side='sell', mode='paper')
                if hasattr(self, '_refresh_paper_balance_from_accounting'):
                    self._refresh_paper_balance_from_accounting()
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
        if os.getenv('ML_OWNS_EXITS', 'true').lower() == 'true':
            return
        if not hasattr(self, 'trailing_stop_manager') or not tradable_pairs:
            return

        for symbol in tradable_pairs:
            try:
                current_price = self.get_price(symbol)
                if not current_price:
                    continue

                ml_owns_exits = os.getenv('ML_OWNS_EXITS', 'true').lower() == 'true'
                if not ml_owns_exits:
                    self.trailing_stop_manager.update_position(symbol, current_price)
                self._evaluate_exit_engine_for_symbol(symbol, current_price)
                if ml_owns_exits:
                    continue
                hard_stop_enabled = os.getenv('HARD_STOP_EXIT_ENABLED', 'False').lower() == 'true'
                if not hard_stop_enabled or not self.trailing_stop_manager.should_stop_loss(symbol, current_price):
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
        """Exécute l'achat avec exécution intelligente et microstructure de marché (Phase 7)."""
        if hasattr(self, 'execution_manager') and self.execution_manager:
            return self.execution_manager.execute_smart_buy(
                symbol, position_data, current_price, reason, ml_entry_learning_id
            )
        
        crypto = symbol.split('/')[0]
        cooldown_remaining = self.get_symbol_cooldown_remaining(symbol)
        if cooldown_remaining > 0 or not self.can_open_position(symbol):
            return False

        result = self.buy_market(
            symbol,
            position_data['position_size_crypto'],
            sizing_reason=position_data.get('sizing_reason'),
            ml_buy_prob=position_data.get('ml_buy_prob')
        )
        if result:
            self.set_symbol_cooldown(symbol, reason='buy_executed')
            return True
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
            return False
            
    def _poll_dashboard_commands(self):
        """Lit et exécute les commandes envoyées depuis le ui."""
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
                    
                print(f"🎮 Commande reçue du ui: {action} sur {symbol if symbol else 'global'}")
                
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
            print(f"⚠️ Erreur lors du polling des commandes du ui: {e}")

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
            
            reason = "Achat manuel forcé via UI"
            
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
                # En paper trading, trouver les positions d'achat non encore clôturées
                amount_to_sell = 0
                for p in self.state.get('positions', []):
                    if p.get('symbol') == symbol and p.get('side') == 'buy' and not p.get('closed_at'):
                        amount_to_sell += float(p.get('amount') or 0)
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
    
