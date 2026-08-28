"""
Core Machine Learning Engine (MLEngine) for Aegis Trading Bot
Uses scikit-learn / Random Forest Classifier to evaluate trade win probability (P_win).
Features:
- 18 Technical Market Indicators (RSI, EMA Slopes, ATR Volatility, Volume Ratio, Support Proximity)
- Model Persistence (joblib)
- Sub-2ms Real-time Inference Speed
- Decoupled & Transparent (Feature Importance Export)
"""

import os
import time
import logging
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

try:
    import joblib
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False


class MLEngine:
    """Moteur de Machine Learning dédié pour la prédiction de probabilité de gain"""

    def __init__(self, model_dir: str = 'data'):
        self.logger = logging.getLogger(__name__)
        self.model_dir = model_dir
        self.model_path = os.path.join(model_dir, 'aegis_model.joblib')
        
        self.model = None
        self.scaler = None
        self.exit_model = None
        self.exit_scaler = None
        self.sizing_model = None
        self.sizing_scaler = None
        self.target_model = None
        self.target_scaler = None
        self.feature_names = [
            'rsi_14', 'ema9_slope', 'ema20_slope', 'ema_cross_diff',
            'atr_percent', 'volume_ratio', 'candle_body_pct', 'candle_wick_top',
            'candle_wick_bottom', 'dist_to_support_pct', 'dist_to_resistance_pct',
            'volume_spike', 'price_change_3b', 'price_change_5b', 'price_change_10b',
            'volatility_std', 'hour_of_day', 'day_of_week',
            # Nouveaux indicateurs Multi-Timeframe (5m & 1H)
            'rsi_5m', 'ema9_slope_5m', 'price_change_3b_5m', 'candle_body_pct_5m',
            'rsi_1h', 'ema20_slope_1h', 'ema50_slope_1h', 'price_change_3b_1h',
            # Paramètre de trade connu au moment de l'entrée (les 4 autres retirés: importance nulle)
            'planned_exit_hour',
            # Contexte/verrous du bot exposés au ML
            'symbol_regime_code', 'btc_regime_code', 'bear_mode',
            'reversal_confirmed', 'falling_knife_active',
            'is_support_touch', 'support_confidence', 'support_rebounds',
            'support_backtest_winrate', 'support_backtest_total_pnl',
            'support_backtest_avg_pnl',
            'crypto_score', 'dynamic_min_score', 'score_vs_threshold',
            'is_optimal_trading_time', 'trading_session_code',
            'minutes_to_session_close',
            'technical_action_code', 'technical_confidence',
            'technical_min_confidence', 'technical_confidence_edge',
            # Phase 5: ajout uniquement en fin de schema pour compatibilite champion.
            'rsi_4h', 'ema20_slope_4h', 'ema50_slope_4h', 'price_change_3b_4h',
            'daily_recovery_score', 'multi_tf_reversal_score',
            'multi_tf_trend_alignment', 'volume_recovery_score',
            # Faux rebonds: ajout en fin de schema pour compatibilite champion.
            'rebound_from_recent_low_pct', 'previous_drop_pct',
            'rebound_vs_drop_ratio', 'rebound_volume_ratio',
            'green_candle_count_5', 'follow_through_3b_pct',
            'momentum_decay_3b', 'upper_wick_rejection_ratio',
            'distance_to_ema20_pct', 'ema20_rejection_active',
            'rsi_rebound_strength', 'rebound_stall_score',
            # Features rapides ajoutées (cassure/momentum court terme) — en fin de schéma
            'ema20_breakout_15m', 'ema9_cross_ema20_15m', 'breakout_high_20b', 'price_vs_vwap_pct',
            'ema9_cross_ema20_5m', 'momentum_accel_5m', 'volume_surge_5m', 'consecutive_green_5m',
            'short_tf_alignment', 'rsi_rising_5m_15m',
        ]
        self.exit_feature_names = [
            'entry_p_win', 'continuation_score', 'gross_pnl_pct', 'net_pnl_pct',
            'duration_minutes', 'fee_rate_bps', 'dist_to_stop_pct', 'dist_to_target_pct',
            'rsi_14', 'ema9_slope', 'ema20_slope', 'ema_cross_diff',
            'atr_percent', 'volume_ratio', 'candle_body_pct', 'candle_wick_top',
            'candle_wick_bottom', 'price_change_3b', 'price_change_5b',
            'volatility_std', 'hour_of_day', 'btc_momentum_3b',
            'symbol_regime_code', 'btc_regime_code', 'bear_mode',
            'reversal_confirmed', 'falling_knife_active',
            'is_support_touch', 'support_confidence',
            'crypto_score', 'score_vs_threshold',
            'is_optimal_trading_time', 'trading_session_code',
            'minutes_to_session_close',
            'technical_action_code', 'technical_confidence',
            'technical_confidence_edge'
        ]
        self.sizing_feature_names = list(self.feature_names)
        # Le modèle P_target réutilise les mêmes features d'entrée que P_win/sizing
        self.target_feature_names = list(self.feature_names)
        
        self.is_trained = False
        self.is_exit_trained = False
        self.is_sizing_trained = False
        self.is_target_trained = False
        self.load_model()

    def _default_trade_context(self, entry_dt: datetime) -> Dict[str, float]:
        fee_rate = float(os.getenv('TRADING_FEE_PERCENT', '0.4')) / 100.0
        max_hold_candles = int(os.getenv('BACKTEST_MAX_HOLD_CANDLES', '96'))
        planned_hold_minutes = float(os.getenv('ML_PLANNED_HOLD_MINUTES', max_hold_candles * 15))
        planned_exit_dt = entry_dt + timedelta(minutes=planned_hold_minutes)
        position_value_usd = float(os.getenv('TRADE_AMOUNT', '5'))
        account_balance = float(os.getenv('PAPER_BALANCE', '1000'))
        position_pct = (position_value_usd / account_balance) * 100.0 if account_balance > 0 else 0.0
        return {
            'fee_rate': fee_rate,
            'position_value_usd': position_value_usd,
            'position_value_pct_balance': position_pct,
            'planned_hold_minutes': planned_hold_minutes,
            'planned_exit_hour': float(planned_exit_dt.hour)
        }

    def _normalise_trade_context(self, trade_context: Optional[Dict], entry_dt: datetime) -> Dict[str, float]:
        context = self._default_trade_context(entry_dt)
        explicit_position_pct = None
        if isinstance(trade_context, dict):
            explicit_position_pct = trade_context.get('position_value_pct_balance')
            context.update({k: v for k, v in trade_context.items() if v is not None})

        fee_rate = float(context.get('fee_rate', 0.0) or 0.0)
        position_value = float(context.get('position_value_usd', 0.0) or 0.0)
        balance = float(context.get('account_balance', 0.0) or 0.0)
        position_pct = explicit_position_pct
        if position_pct is None:
            position_pct = (position_value / balance) * 100.0 if balance > 0 else 0.0

        planned_hold = float(context.get('planned_hold_minutes', 0.0) or 0.0)
        planned_exit_hour = context.get('planned_exit_hour')
        if planned_exit_hour is None:
            planned_exit_hour = float((entry_dt + timedelta(minutes=planned_hold)).hour)

        return {
            'fee_rate_bps': fee_rate * 10000.0,
            'position_value_usd': position_value,
            'position_value_pct_balance': float(position_pct),
            'planned_hold_minutes': planned_hold,
            'planned_exit_hour': float(planned_exit_hour)
        }

    def _regime_code(self, value) -> float:
        if value is None:
            return 0.0
        text = str(value).upper().replace(' ', '_')
        mapping = {
            'BEAR_STRONG': -3.0,
            'BEAR': -2.0,
            'BEAR_WEAK': -1.5,
            'SIDEWAYS_DOWN': -1.0,
            'SIDEWAYS': 0.0,
            'RANGE': 0.0,
            'SIDEWAYS_UP': 1.0,
            'BULL_WEAK': 1.5,
            'BULL': 2.0,
            'BULL_STRONG': 3.0,
        }
        return mapping.get(text, 0.0)

    def _session_features(self, hour: float) -> Tuple[float, float, float]:
        hour = float(hour)
        if 0 <= hour <= 4:
            return 1.0, 1.0, max(0.0, (4.0 - hour) * 60.0)
        if 8 <= hour <= 16:
            return 1.0, 2.0, max(0.0, (16.0 - hour) * 60.0)
        if 4 < hour < 8:
            return 0.0, 0.0, (8.0 - hour) * 60.0
        if 16 < hour <= 23:
            return 0.0, 0.0, ((24.0 - hour) + 0.0) * 60.0
        return 0.0, 0.0, 0.0

    def _technical_action_code(self, action) -> float:
        mapping = {
            'STRONG_SELL': -2.0,
            'SELL': -1.0,
            'HOLD': 0.0,
            'NEUTRAL': 0.0,
            'BUY': 1.0,
            'STRONG_BUY': 2.0,
        }
        return mapping.get(str(action or 'HOLD').upper(), 0.0)

    def _normalise_bot_context(self, bot_context: Optional[Dict], hour_of_day: float) -> Dict[str, float]:
        context = bot_context if isinstance(bot_context, dict) else {}
        is_optimal, session_code, minutes_to_close = self._session_features(hour_of_day)
        crypto_score = float(context.get('crypto_score', 0.0) or 0.0)
        dynamic_min_score = float(context.get('dynamic_min_score', 0.0) or 0.0)
        technical_confidence = float(context.get('technical_confidence', 0.0) or 0.0)
        technical_min_confidence = float(context.get('technical_min_confidence', 0.0) or 0.0)

        return {
            'symbol_regime_code': self._regime_code(context.get('symbol_regime') or context.get('market_regime')),
            'btc_regime_code': self._regime_code(context.get('btc_regime')),
            'bear_mode': 1.0 if context.get('bear_mode') else 0.0,
            'reversal_confirmed': 1.0 if context.get('reversal_confirmed') else 0.0,
            'falling_knife_active': 1.0 if context.get('falling_knife_active') else 0.0,
            'is_support_touch': 1.0 if context.get('is_support_touch') else 0.0,
            'support_confidence': float(context.get('support_confidence', 0.0) or 0.0),
            'support_rebounds': float(context.get('support_rebounds', 0.0) or 0.0),
            'support_backtest_winrate': float(context.get('support_backtest_winrate', 0.0) or 0.0),
            'support_backtest_total_pnl': float(context.get('support_backtest_total_pnl', 0.0) or 0.0),
            'support_backtest_avg_pnl': float(context.get('support_backtest_avg_pnl', 0.0) or 0.0),
            'crypto_score': crypto_score,
            'dynamic_min_score': dynamic_min_score,
            'score_vs_threshold': crypto_score - dynamic_min_score,
            'is_optimal_trading_time': float(context.get('is_optimal_trading_time', is_optimal)),
            'trading_session_code': float(context.get('trading_session_code', session_code)),
            'minutes_to_session_close': float(context.get('minutes_to_session_close', minutes_to_close)),
            'technical_action_code': self._technical_action_code(context.get('technical_action')),
            'technical_confidence': technical_confidence,
            'technical_min_confidence': technical_min_confidence,
            'technical_confidence_edge': technical_confidence - technical_min_confidence,
        }

    def _model_feature_count(self) -> int:
        if self.scaler is not None and hasattr(self.scaler, 'n_features_in_'):
            return int(self.scaler.n_features_in_)
        if self.model is not None and hasattr(self.model, 'n_features_in_'):
            return int(self.model.n_features_in_)
        return len(self.feature_names)

    def _align_features_for_loaded_model(self, features: np.ndarray) -> np.ndarray:
        expected = self._model_feature_count()
        if len(features) == expected:
            return features
        if len(features) > expected:
            self.logger.warning(
                "Modèle ML entraîné avec %s features, schéma courant %s. "
                "Compatibilité active: les nouvelles features sont ignorées jusqu'au réentraînement.",
                expected,
                len(features)
            )
            return features[:expected]
        padded = np.zeros(expected, dtype=np.float64)
        padded[:len(features)] = features
        return padded

    def _exit_model_feature_count(self) -> int:
        if self.exit_scaler is not None and hasattr(self.exit_scaler, 'n_features_in_'):
            return int(self.exit_scaler.n_features_in_)
        if self.exit_model is not None and hasattr(self.exit_model, 'n_features_in_'):
            return int(self.exit_model.n_features_in_)
        return len(self.exit_feature_names)

    def _align_exit_features_for_loaded_model(self, features: np.ndarray) -> np.ndarray:
        expected = self._exit_model_feature_count()
        if len(features) == expected:
            return features
        if len(features) > expected:
            return features[:expected]
        padded = np.zeros(expected, dtype=np.float64)
        padded[:len(features)] = features
        return padded

    def _sizing_model_feature_count(self) -> int:
        if self.sizing_scaler is not None and hasattr(self.sizing_scaler, 'n_features_in_'):
            return int(self.sizing_scaler.n_features_in_)
        if self.sizing_model is not None and hasattr(self.sizing_model, 'n_features_in_'):
            return int(self.sizing_model.n_features_in_)
        return len(self.sizing_feature_names)

    def _align_sizing_features_for_loaded_model(self, features: np.ndarray) -> np.ndarray:
        expected = self._sizing_model_feature_count()
        if len(features) == expected:
            return features
        if len(features) > expected:
            return features[:expected]
        padded = np.zeros(expected, dtype=np.float64)
        padded[:len(features)] = features
        return padded

    def _target_model_feature_count(self) -> int:
        if self.target_scaler is not None and hasattr(self.target_scaler, 'n_features_in_'):
            return int(self.target_scaler.n_features_in_)
        if self.target_model is not None and hasattr(self.target_model, 'n_features_in_'):
            return int(self.target_model.n_features_in_)
        return len(self.target_feature_names)

    def _align_target_features_for_loaded_model(self, features: np.ndarray) -> np.ndarray:
        expected = self._target_model_feature_count()
        if len(features) == expected:
            return features
        if len(features) > expected:
            return features[:expected]
        padded = np.zeros(expected, dtype=np.float64)
        padded[:len(features)] = features
        return padded

    def _calc_rsi(self, closes: np.ndarray, period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        rs = avg_gain / (avg_loss + 1e-9)
        return float(100.0 - (100.0 / (1.0 + rs)))

    def _calc_ema_slope(self, closes: np.ndarray, period: int = 9) -> float:
        if len(closes) < period + 3:
            return 0.0
        ema = np.mean(closes[-period:])
        ema_prev = np.mean(closes[-(period+3):-3])
        return float((ema - ema_prev) / (ema_prev + 1e-9) * 100.0)

    def _timeframe_snapshot(
        self,
        klines: Optional[List[Dict]],
        fallback_rsi: float,
        fallback_ema20_slope: float,
        fallback_change: float
    ) -> Dict[str, float]:
        if not klines or len(klines) < 15:
            return {
                'rsi': fallback_rsi,
                'ema20_slope': fallback_ema20_slope,
                'ema50_slope': fallback_ema20_slope * 0.8,
                'price_change_3b': fallback_change,
                'volume_ratio': 1.0,
                'recovery_score': 0.0,
            }

        closes = np.array([float(k['close']) for k in klines], dtype=np.float64)
        volumes = np.array([float(k.get('volume', 0.0) or 0.0) for k in klines], dtype=np.float64)
        highs = np.array([float(k['high']) for k in klines], dtype=np.float64)
        lows = np.array([float(k['low']) for k in klines], dtype=np.float64)
        rsi = self._calc_rsi(closes, 14)
        ema20_slope = self._calc_ema_slope(closes, 20)
        ema50_slope = self._calc_ema_slope(closes, 50) if len(closes) >= 50 else ema20_slope
        price_change_3b = (closes[-1] - closes[-4]) / (closes[-4] + 1e-9) * 100.0 if len(closes) >= 4 else 0.0
        avg_vol = np.mean(volumes[-20:]) if len(volumes) >= 20 else np.mean(volumes) if len(volumes) else 0.0
        volume_ratio = float(volumes[-1] / (avg_vol + 1e-9)) if avg_vol > 0 else 1.0

        lookback = min(len(closes), 30)
        recent_low = float(np.min(lows[-lookback:]))
        recent_high = float(np.max(highs[-lookback:]))
        recovery_score = ((closes[-1] - recent_low) / (recent_high - recent_low + 1e-9)) * 100.0
        return {
            'rsi': float(rsi),
            'ema20_slope': float(ema20_slope),
            'ema50_slope': float(ema50_slope),
            'price_change_3b': float(price_change_3b),
            'volume_ratio': volume_ratio,
            'recovery_score': float(recovery_score),
        }

    def _rebound_exhaustion_features(
        self,
        closes: np.ndarray,
        opens: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        volumes: np.ndarray,
        px: float,
        ema20: float,
        rsi: float,
        price_change_3b: float,
    ) -> Dict[str, float]:
        """Features ML pour distinguer vrai rebond et rebond qui s'essouffle."""
        defaults = {
            'rebound_from_recent_low_pct': 0.0,
            'previous_drop_pct': 0.0,
            'rebound_vs_drop_ratio': 0.0,
            'rebound_volume_ratio': 0.0,
            'green_candle_count_5': 0.0,
            'follow_through_3b_pct': 0.0,
            'momentum_decay_3b': 0.0,
            'upper_wick_rejection_ratio': 0.0,
            'distance_to_ema20_pct': 0.0,
            'ema20_rejection_active': 0.0,
            'rsi_rebound_strength': 0.0,
            'rebound_stall_score': 0.0,
        }
        try:
            lookback = min(20, len(closes))
            recent_lows = lows[-lookback:]
            low_rel_idx = int(np.argmin(recent_lows))
            low_abs_idx = len(lows) - lookback + low_rel_idx
            recent_low = float(lows[low_abs_idx])

            prior_start = max(0, low_abs_idx - 40)
            prior_high = float(np.max(highs[prior_start:low_abs_idx + 1]))
            rebound_from_low = max(0.0, (float(px) - recent_low) / (recent_low + 1e-9) * 100.0)
            previous_drop = max(0.0, (prior_high - recent_low) / (prior_high + 1e-9) * 100.0)
            rebound_vs_drop = rebound_from_low / (previous_drop + 1e-9) if previous_drop > 0 else 0.0

            avg_vol_20 = float(np.mean(volumes[-lookback:])) if lookback else 0.0
            rebound_volumes = volumes[low_abs_idx:]
            rebound_volume_ratio = float(np.mean(rebound_volumes) / (avg_vol_20 + 1e-9)) if len(rebound_volumes) else 0.0

            recent_count = min(5, len(closes))
            green_candle_count_5 = float(np.sum(closes[-recent_count:] > opens[-recent_count:]))
            follow_through_3b = float(price_change_3b)
            prior_3b = (
                (closes[-4] - closes[-7]) / (closes[-7] + 1e-9) * 100.0
                if len(closes) >= 7 else 0.0
            )
            momentum_decay_3b = max(0.0, float(prior_3b - price_change_3b))

            upper_wicks = []
            for idx in range(len(closes) - recent_count, len(closes)):
                candle_range = highs[idx] - lows[idx] + 1e-9
                upper_wicks.append((highs[idx] - max(opens[idx], closes[idx])) / candle_range)
            upper_wick_rejection_ratio = float(np.mean(upper_wicks)) if upper_wicks else 0.0

            distance_to_ema20 = (float(px) - float(ema20)) / (float(ema20) + 1e-9) * 100.0
            touched_ema20 = bool(lows[-1] <= ema20 <= highs[-1])
            ema20_rejection_active = 1.0 if touched_ema20 and closes[-1] < ema20 and upper_wick_rejection_ratio > 0.35 else 0.0
            rsi_rebound_strength = max(0.0, min(100.0, float(rsi) - 30.0))

            stall_score = (
                max(0.0, -follow_through_3b) * 20.0
                + momentum_decay_3b * 15.0
                + upper_wick_rejection_ratio * 35.0
                + ema20_rejection_active * 20.0
                + max(0.0, 1.0 - rebound_volume_ratio) * 15.0
            )
            return {
                'rebound_from_recent_low_pct': float(rebound_from_low),
                'previous_drop_pct': float(previous_drop),
                'rebound_vs_drop_ratio': float(rebound_vs_drop),
                'rebound_volume_ratio': float(rebound_volume_ratio),
                'green_candle_count_5': green_candle_count_5,
                'follow_through_3b_pct': follow_through_3b,
                'momentum_decay_3b': float(momentum_decay_3b),
                'upper_wick_rejection_ratio': upper_wick_rejection_ratio,
                'distance_to_ema20_pct': float(distance_to_ema20),
                'ema20_rejection_active': ema20_rejection_active,
                'rsi_rebound_strength': float(rsi_rebound_strength),
                'rebound_stall_score': max(0.0, min(100.0, float(stall_score))),
            }
        except Exception:
            return defaults

    def extract_features_from_klines(
        self,
        klines: List[Dict],
        current_price: Optional[float] = None,
        klines_5m: Optional[List[Dict]] = None,
        klines_1h: Optional[List[Dict]] = None,
        klines_4h: Optional[List[Dict]] = None,
        klines_1d: Optional[List[Dict]] = None,
        trade_context: Optional[Dict] = None,
        bot_context: Optional[Dict] = None
    ) -> Optional[np.ndarray]:
        """Extrait un vecteur de caractéristiques marché + paramètres de trade connus à l'entrée."""
        if not klines or len(klines) < 20:
            return None

        try:
            closes = np.array([float(k['close']) for k in klines], dtype=np.float64)
            opens = np.array([float(k['open']) for k in klines], dtype=np.float64)
            highs = np.array([float(k['high']) for k in klines], dtype=np.float64)
            lows = np.array([float(k['low']) for k in klines], dtype=np.float64)
            volumes = np.array([float(k['volume']) for k in klines], dtype=np.float64)
            
            px = current_price if current_price else closes[-1]

            # 1. RSI (14 périodes - 15m)
            rsi = self._calc_rsi(closes, 14)

            # 2. Pente des EMA (9 & 20 - 15m)
            ema9_slope = self._calc_ema_slope(closes, 9)
            ema20_slope = self._calc_ema_slope(closes, 20)
            ema9 = np.mean(closes[-9:])
            ema20 = np.mean(closes[-20:])
            ema_cross_diff = (ema9 - ema20) / (ema20 + 1e-9) * 100.0

            # 3. ATR Volatilité (%)
            tr = np.maximum(highs[1:] - lows[1:], np.maximum(np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1])))
            atr = np.mean(tr[-14:]) if len(tr) >= 14 else (highs[-1] - lows[-1])
            atr_percent = (atr / (px + 1e-9)) * 100.0

            # 4. Volume Ratio
            avg_vol_20 = np.mean(volumes[-20:]) if len(volumes) >= 20 else 1.0
            volume_ratio = volumes[-1] / (avg_vol_20 + 1e-9)
            volume_spike = 1.0 if volume_ratio >= 1.8 else 0.0

            # 5. Anatomie de la dernière bougie
            c_open = opens[-1]
            c_high = highs[-1]
            c_low = lows[-1]
            c_close = closes[-1]
            total_range = c_high - c_low + 1e-9
            candle_body_pct = abs(c_close - c_open) / total_range
            candle_wick_top = (c_high - max(c_open, c_close)) / total_range
            candle_wick_bottom = (min(c_open, c_close) - c_low) / total_range

            # 6. Proximité Support / Résistance
            min_low_20 = np.min(lows[-20:])
            max_high_20 = np.max(highs[-20:])
            dist_to_support_pct = (px - min_low_20) / (px + 1e-9) * 100.0
            dist_to_resistance_pct = (max_high_20 - px) / (px + 1e-9) * 100.0

            # 7. Momentum multi-bougies
            price_change_3b = (closes[-1] - closes[-4]) / (closes[-4] + 1e-9) * 100.0 if len(closes) >= 4 else 0.0
            price_change_5b = (closes[-1] - closes[-6]) / (closes[-6] + 1e-9) * 100.0 if len(closes) >= 6 else 0.0
            price_change_10b = (closes[-1] - closes[-11]) / (closes[-11] + 1e-9) * 100.0 if len(closes) >= 11 else 0.0

            # 8. Écart-Type (Bruit)
            returns = np.diff(closes[-15:]) / (closes[-15:-1] + 1e-9)
            volatility_std = np.std(returns) * 100.0 if len(returns) > 0 else 0.0

            # 9. Temporalité
            ts = klines[-1].get('timestamp', time.time() * 1000)
            dt = datetime.fromtimestamp(ts / 1000.0)
            hour_of_day = float(dt.hour)
            day_of_week = float(dt.weekday())
            trade_features = self._normalise_trade_context(trade_context, dt)
            bot_features = self._normalise_bot_context(bot_context, hour_of_day)

            # =========================================================================
            # MULTI-TIMEFRAMES : FEATURES 5M (MICRO)
            # =========================================================================
            if klines_5m and len(klines_5m) >= 15:
                closes_5m = np.array([float(k['close']) for k in klines_5m], dtype=np.float64)
                opens_5m = np.array([float(k['open']) for k in klines_5m], dtype=np.float64)
                highs_5m = np.array([float(k['high']) for k in klines_5m], dtype=np.float64)
                lows_5m = np.array([float(k['low']) for k in klines_5m], dtype=np.float64)
                volumes_5m = np.array([float(k.get('volume', 0.0) or 0.0) for k in klines_5m], dtype=np.float64)

                rsi_5m = self._calc_rsi(closes_5m, 14)
                ema9_slope_5m = self._calc_ema_slope(closes_5m, 9)
                price_change_3b_5m = (closes_5m[-1] - closes_5m[-4]) / (closes_5m[-4] + 1e-9) * 100.0 if len(closes_5m) >= 4 else 0.0
                c_range_5m = highs_5m[-1] - lows_5m[-1] + 1e-9
                candle_body_pct_5m = abs(closes_5m[-1] - opens_5m[-1]) / c_range_5m

                # --- GROUPE B: momentum/accélération 5m (features rapides) ---
                ema9_5m = np.mean(closes_5m[-9:])
                ema20_5m = np.mean(closes_5m[-20:]) if len(closes_5m) >= 20 else np.mean(closes_5m)
                ema9_prev_5m = np.mean(closes_5m[-10:-1])
                ema20_prev_5m = np.mean(closes_5m[-21:-1]) if len(closes_5m) >= 21 else ema20_5m
                # Croisement haussier frais EMA9>EMA20 sur 5m (était sous, passe au-dessus)
                ema9_cross_ema20_5m = 1.0 if (ema9_5m > ema20_5m and ema9_prev_5m <= ema20_prev_5m) else 0.0
                # Accélération: momentum 3 dernières bougies vs 3 précédentes
                chg_recent_5m = (closes_5m[-1] - closes_5m[-4]) / (closes_5m[-4] + 1e-9) * 100.0 if len(closes_5m) >= 4 else 0.0
                chg_prior_5m = (closes_5m[-4] - closes_5m[-7]) / (closes_5m[-7] + 1e-9) * 100.0 if len(closes_5m) >= 7 else 0.0
                momentum_accel_5m = float(chg_recent_5m - chg_prior_5m)
                # Expansion de volume 5m
                avg_vol_5m = np.mean(volumes_5m[-20:]) if len(volumes_5m) >= 20 else (np.mean(volumes_5m) if len(volumes_5m) else 0.0)
                volume_surge_5m = float(volumes_5m[-1] / (avg_vol_5m + 1e-9)) if avg_vol_5m > 0 else 1.0
                # Bougies vertes consécutives (jusqu'à 5)
                consecutive_green_5m = 0.0
                for i in range(len(closes_5m) - 1, max(-1, len(closes_5m) - 6), -1):
                    if closes_5m[i] > opens_5m[i]:
                        consecutive_green_5m += 1.0
                    else:
                        break
                rsi_prev_5m = self._calc_rsi(closes_5m[:-1], 14) if len(closes_5m) >= 16 else rsi_5m
            else:
                rsi_5m = rsi
                ema9_slope_5m = ema9_slope
                price_change_3b_5m = price_change_3b / 3.0
                candle_body_pct_5m = candle_body_pct
                ema9_cross_ema20_5m = 0.0
                momentum_accel_5m = 0.0
                volume_surge_5m = 1.0
                consecutive_green_5m = 0.0
                rsi_prev_5m = rsi_5m

            # =========================================================================
            # MULTI-TIMEFRAMES : FEATURES 1H (MACRO)
            # =========================================================================
            if klines_1h and len(klines_1h) >= 15:
                closes_1h = np.array([float(k['close']) for k in klines_1h], dtype=np.float64)
                rsi_1h = self._calc_rsi(closes_1h, 14)
                ema20_slope_1h = self._calc_ema_slope(closes_1h, 20)
                ema50_slope_1h = self._calc_ema_slope(closes_1h, 50) if len(closes_1h) >= 50 else ema20_slope_1h
                price_change_3b_1h = (closes_1h[-1] - closes_1h[-4]) / (closes_1h[-4] + 1e-9) * 100.0 if len(closes_1h) >= 4 else 0.0
            else:
                rsi_1h = rsi
                ema20_slope_1h = ema20_slope
                ema50_slope_1h = ema20_slope * 0.8
                price_change_3b_1h = price_change_3b * 2.0

            tf_4h = self._timeframe_snapshot(klines_4h, rsi_1h, ema20_slope_1h, price_change_3b_1h)
            tf_1d = self._timeframe_snapshot(klines_1d, rsi_1h, ema20_slope_1h, price_change_3b_1h)
            rsi_4h = tf_4h['rsi']
            ema20_slope_4h = tf_4h['ema20_slope']
            ema50_slope_4h = tf_4h['ema50_slope']
            price_change_3b_4h = tf_4h['price_change_3b']
            daily_recovery_score = tf_1d['recovery_score']

            positive_frames = [
                price_change_3b_5m > 0,
                price_change_3b > 0,
                price_change_3b_1h > 0,
                price_change_3b_4h > 0,
                tf_1d['price_change_3b'] > 0,
            ]
            slope_frames = [
                ema9_slope_5m > 0,
                ema20_slope > 0,
                ema20_slope_1h > 0,
                ema20_slope_4h > 0,
                tf_1d['ema20_slope'] > 0,
            ]
            multi_tf_reversal_score = (sum(positive_frames) + sum(slope_frames)) / 10.0 * 100.0
            multi_tf_trend_alignment = sum(1 if flag else -1 for flag in slope_frames)
            volume_recovery_score = min(300.0, max(0.0, (volume_ratio + tf_4h['volume_ratio'] + tf_1d['volume_ratio']) / 3.0 * 100.0))
            rebound_features = self._rebound_exhaustion_features(
                closes, opens, highs, lows, volumes, px, ema20, rsi, price_change_3b
            )

            # =========================================================================
            # GROUPE A : CASSURE / FRANCHISSEMENT (signaux rapides "ça repart maintenant")
            # =========================================================================
            # Cassure fraîche de l'EMA20 15m: le prix était sous l'EMA20 à la bougie
            # précédente et repasse au-dessus maintenant (pas juste "au-dessus depuis longtemps")
            ema20_prev = np.mean(closes[-21:-1]) if len(closes) >= 21 else ema20
            ema20_breakout_15m = 1.0 if (closes[-1] > ema20 and closes[-2] <= ema20_prev) else 0.0
            # Croisement haussier frais EMA9>EMA20 sur 15m
            ema9_prev = np.mean(closes[-10:-1]) if len(closes) >= 10 else ema9
            ema9_cross_ema20_15m = 1.0 if (ema9 > ema20 and ema9_prev <= ema20_prev) else 0.0
            # Cassure du plus haut des 20 dernières bougies (breakout de range)
            prev_high_20 = float(np.max(highs[-21:-1])) if len(highs) >= 21 else max_high_20
            breakout_high_20b = 1.0 if px > prev_high_20 else 0.0
            # Position du prix vs VWAP (approx sur la fenêtre disponible): pression acheteuse
            typical = (highs + lows + closes) / 3.0
            vwap_window = min(len(closes), 30)
            vol_slice = volumes[-vwap_window:]
            tp_slice = typical[-vwap_window:]
            vwap = float(np.sum(tp_slice * vol_slice) / (np.sum(vol_slice) + 1e-9)) if np.sum(vol_slice) > 0 else float(np.mean(tp_slice))
            price_vs_vwap_pct = (float(px) - vwap) / (vwap + 1e-9) * 100.0

            # =========================================================================
            # GROUPE C : CONFIRMATION MULTI-TF COURT TERME (5m + 15m, avant confirmation lente)
            # =========================================================================
            # Alignement haussier des timeframes COURTS uniquement (5m + 15m)
            short_frames = [
                ema9_slope_5m > 0,
                price_change_3b_5m > 0,
                ema9_slope > 0,
                ema20_slope > 0,
                price_change_3b > 0,
            ]
            short_tf_alignment = float(sum(1 if f else 0 for f in short_frames)) / len(short_frames) * 100.0
            # RSI qui monte simultanément sur 5m et 15m (momentum d'oscillateur naissant)
            rsi_prev_15m = self._calc_rsi(closes[:-1], 14) if len(closes) >= 16 else rsi
            rsi_rising_5m_15m = 1.0 if (rsi_5m > rsi_prev_5m and rsi > rsi_prev_15m) else 0.0

            features = np.array([
                rsi, ema9_slope, ema20_slope, ema_cross_diff,
                atr_percent, volume_ratio, candle_body_pct, candle_wick_top,
                candle_wick_bottom, dist_to_support_pct, dist_to_resistance_pct,
                volume_spike, price_change_3b, price_change_5b, price_change_10b,
                volatility_std, hour_of_day, day_of_week,
                # Multi-Timeframe 5m & 1H
                rsi_5m, ema9_slope_5m, price_change_3b_5m, candle_body_pct_5m,
                rsi_1h, ema20_slope_1h, ema50_slope_1h, price_change_3b_1h,
                trade_features['planned_exit_hour'],
                bot_features['symbol_regime_code'],
                bot_features['btc_regime_code'],
                bot_features['bear_mode'],
                bot_features['reversal_confirmed'],
                bot_features['falling_knife_active'],
                bot_features['is_support_touch'],
                bot_features['support_confidence'],
                bot_features['support_rebounds'],
                bot_features['support_backtest_winrate'],
                bot_features['support_backtest_total_pnl'],
                bot_features['support_backtest_avg_pnl'],
                bot_features['crypto_score'],
                bot_features['dynamic_min_score'],
                bot_features['score_vs_threshold'],
                bot_features['is_optimal_trading_time'],
                bot_features['trading_session_code'],
                bot_features['minutes_to_session_close'],
                bot_features['technical_action_code'],
                bot_features['technical_confidence'],
                bot_features['technical_min_confidence'],
                bot_features['technical_confidence_edge'],
                rsi_4h, ema20_slope_4h, ema50_slope_4h, price_change_3b_4h,
                daily_recovery_score, multi_tf_reversal_score,
                multi_tf_trend_alignment, volume_recovery_score,
                rebound_features['rebound_from_recent_low_pct'],
                rebound_features['previous_drop_pct'],
                rebound_features['rebound_vs_drop_ratio'],
                rebound_features['rebound_volume_ratio'],
                rebound_features['green_candle_count_5'],
                rebound_features['follow_through_3b_pct'],
                rebound_features['momentum_decay_3b'],
                rebound_features['upper_wick_rejection_ratio'],
                rebound_features['distance_to_ema20_pct'],
                rebound_features['ema20_rejection_active'],
                rebound_features['rsi_rebound_strength'],
                rebound_features['rebound_stall_score'],
                # === Features rapides ajoutées (cassure/momentum court terme) ===
                # Groupe A: cassure/franchissement (15m)
                ema20_breakout_15m, ema9_cross_ema20_15m, breakout_high_20b, price_vs_vwap_pct,
                # Groupe B: momentum/accélération (5m)
                ema9_cross_ema20_5m, momentum_accel_5m, volume_surge_5m, consecutive_green_5m,
                # Groupe C: confirmation court terme (5m+15m)
                short_tf_alignment, rsi_rising_5m_15m,
            ], dtype=np.float64)

            return features

        except Exception as e:
            self.logger.error(f"Erreur d'extraction des caractéristiques ML: {e}")
            return None

    def train_model(self, X: np.ndarray, y: np.ndarray, n_estimators: int = 100, max_depth: int = 6, min_samples_split: int = 5, criterion: str = 'gini', sample_weight: Optional[np.ndarray] = None) -> bool:
        """Entraîne le classifieur Random Forest avec hyperparamètres configurables"""
        if not SKLEARN_AVAILABLE:
            self.logger.warning("scikit-learn n'est pas disponible pour l'entraînement ML.")
            return False

        if len(X) < 30:
            self.logger.warning("Données insuffisantes pour l'entraînement ML (minimum 30 exemples requis).")
            return False

        try:
            from sklearn.model_selection import train_test_split
            from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score

            # Split train/test pour évaluer
            X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y if len(set(y)) > 1 else None)
            
            self.scaler = StandardScaler()
            X_train_scaled = self.scaler.fit_transform(X_train)
            X_test_scaled = self.scaler.transform(X_test)

            self.model = RandomForestClassifier(
                n_estimators=n_estimators,
                max_depth=max_depth,
                min_samples_split=min_samples_split,
                criterion=criterion,
                random_state=42,
                n_jobs=-1,
                oob_score=True
            )
            sw_train = sample_weight[:len(X_train)] if sample_weight is not None else None
            self.model.fit(X_train_scaled, y_train, sample_weight=sw_train)
            self.is_trained = True

            # Calculer et stocker les métriques
            y_pred = self.model.predict(X_test_scaled)
            test_acc = accuracy_score(y_test, y_pred) * 100
            test_prec = precision_score(y_test, y_pred, zero_division=0) * 100
            test_recall = recall_score(y_test, y_pred, zero_division=0) * 100
            test_f1 = f1_score(y_test, y_pred, zero_division=0) * 100
            train_acc = self.model.score(X_train_scaled, y_train) * 100
            oob = self.model.oob_score_ * 100 if hasattr(self.model, 'oob_score_') else None

            self.model_metadata = {
                'trained_at': datetime.now().isoformat(),
                'n_features': int(X.shape[1]),
                'exit_n_features': len(self.exit_feature_names),
                'train_samples': int(len(X)),
                'train_win_rate': f"{int(sum(y))/len(y)*100:.1f}%",
                'test_accuracy': round(test_acc, 1),
                'test_precision': round(test_prec, 1),
                'test_recall': round(test_recall, 1),
                'test_f1': round(test_f1, 1),
                'train_accuracy': round(train_acc, 1),
                'oob_score': round(oob, 1) if oob else None,
            }

            # Ré-entraîner sur toutes les données pour le modèle final
            self.scaler = StandardScaler()
            X_scaled = self.scaler.fit_transform(X)
            self.model.fit(X_scaled, y, sample_weight=sample_weight)

            self.save_model()
            return True

        except Exception as e:
            self.logger.error(f"Erreur lors de l'entraînement ML: {e}")
            return False

    def extract_exit_features(
        self,
        klines: List[Dict],
        current_price: float,
        position_data: Dict,
        continuation_score: float,
        entry_p_win: float = 50.0,
        btc_klines: Optional[List[Dict]] = None,
        bot_context: Optional[Dict] = None
    ) -> Optional[np.ndarray]:
        """Extrait les features ML pour décider si une position doit continuer ou sortir."""
        if not klines or len(klines) < 20:
            return None

        try:
            market_features = self.extract_features_from_klines(klines, current_price, bot_context=bot_context)
            if market_features is None:
                return None

            buy_price = float(position_data.get('entry_price') or position_data.get('buy_price') or position_data.get('price') or position_data.get('avg_entry_price') or current_price)
            fee_rate = float(position_data.get('fee_rate', float(os.getenv('TRADING_FEE_PERCENT', '0.1')) / 100.0))
            breakeven_price = buy_price * (1 + fee_rate) / max(0.000001, (1 - fee_rate))
            gross_pnl_pct = ((current_price - buy_price) / max(buy_price, 1e-9)) * 100.0
            net_pnl_pct = ((current_price - breakeven_price) / max(buy_price, 1e-9)) * 100.0

            duration_minutes = float(position_data.get('duration_minutes') or 0.0)
            created_at = position_data.get('created_at') or position_data.get('buy_time')
            if created_at and not position_data.get('duration_minutes'):
                try:
                    created_dt = datetime.fromisoformat(str(created_at).replace('Z', '+00:00'))
                    now_for_delta = datetime.now(created_dt.tzinfo) if created_dt.tzinfo else datetime.now()
                    duration_minutes = max(0.0, (now_for_delta - created_dt).total_seconds() / 60.0)
                except Exception:
                    duration_minutes = 0.0

            stop_price = float(position_data.get('stop_price') or position_data.get('stop_loss_price') or 0.0)
            target_price = float(position_data.get('target_price') or position_data.get('resistance_price') or 0.0)
            dist_to_stop_pct = ((current_price - stop_price) / max(current_price, 1e-9)) * 100.0 if stop_price > 0 else 0.0
            dist_to_target_pct = ((target_price - current_price) / max(current_price, 1e-9)) * 100.0 if target_price > 0 else 0.0

            btc_momentum_3b = 0.0
            if btc_klines and len(btc_klines) >= 4:
                btc_closes = np.array([float(k['close']) for k in btc_klines], dtype=np.float64)
                btc_momentum_3b = (btc_closes[-1] - btc_closes[-4]) / (btc_closes[-4] + 1e-9) * 100.0

            # Reuse core market features by index.
            rsi_14 = market_features[0]
            ema9_slope = market_features[1]
            ema20_slope = market_features[2]
            ema_cross_diff = market_features[3]
            atr_percent = market_features[4]
            volume_ratio = market_features[5]
            candle_body_pct = market_features[6]
            candle_wick_top = market_features[7]
            candle_wick_bottom = market_features[8]
            price_change_3b = market_features[12]
            price_change_5b = market_features[13]
            volatility_std = market_features[15]
            hour_of_day = market_features[16]
            bot_features = self._normalise_bot_context(bot_context, hour_of_day)

            return np.array([
                float(entry_p_win), float(continuation_score), gross_pnl_pct, net_pnl_pct,
                duration_minutes, fee_rate * 10000.0, dist_to_stop_pct, dist_to_target_pct,
                rsi_14, ema9_slope, ema20_slope, ema_cross_diff,
                atr_percent, volume_ratio, candle_body_pct, candle_wick_top,
                candle_wick_bottom, price_change_3b, price_change_5b,
                volatility_std, hour_of_day, btc_momentum_3b,
                bot_features['symbol_regime_code'],
                bot_features['btc_regime_code'],
                bot_features['bear_mode'],
                bot_features['reversal_confirmed'],
                bot_features['falling_knife_active'],
                bot_features['is_support_touch'],
                bot_features['support_confidence'],
                bot_features['crypto_score'],
                bot_features['score_vs_threshold'],
                bot_features['is_optimal_trading_time'],
                bot_features['trading_session_code'],
                bot_features['minutes_to_session_close'],
                bot_features['technical_action_code'],
                bot_features['technical_confidence'],
                bot_features['technical_confidence_edge']
            ], dtype=np.float64)

        except Exception as e:
            self.logger.error(f"Erreur extraction features ML sortie: {e}")
            return None

    def train_exit_model(self, X: np.ndarray, y: np.ndarray, n_estimators: int = 150, max_depth: int = 6, min_samples_split: int = 10, criterion: str = 'gini') -> bool:
        """Entraîne le modèle ML de continuation/sortie."""
        if not SKLEARN_AVAILABLE:
            return False
        if len(X) < 30:
            self.logger.warning("Données insuffisantes pour entraîner le modèle ML de sortie.")
            return False
        try:
            self.exit_scaler = StandardScaler()
            X_scaled = self.exit_scaler.fit_transform(X)
            self.exit_model = RandomForestClassifier(
                n_estimators=n_estimators,
                max_depth=max_depth,
                min_samples_split=min_samples_split,
                criterion=criterion,
                random_state=43,
                n_jobs=-1
            )
            self.exit_model.fit(X_scaled, y)
            self.is_exit_trained = True
            self.save_model()
            return True
        except Exception as e:
            self.logger.error(f"Erreur entraînement ML sortie: {e}")
            return False

    def train_sizing_model(self, X: np.ndarray, y: np.ndarray, n_estimators: int = 120, max_depth: int = 6, min_samples_split: int = 10) -> bool:
        """Entraîne le modèle ML de facteur de taille de position."""
        if not SKLEARN_AVAILABLE:
            return False
        if len(X) < 30:
            self.logger.warning("Données insuffisantes pour entraîner le modèle ML de sizing.")
            return False
        try:
            self.sizing_scaler = StandardScaler()
            X_scaled = self.sizing_scaler.fit_transform(X)
            self.sizing_model = RandomForestRegressor(
                n_estimators=n_estimators,
                max_depth=max_depth,
                min_samples_split=min_samples_split,
                random_state=44,
                n_jobs=-1
            )
            self.sizing_model.fit(X_scaled, y)
            self.is_sizing_trained = True
            self.save_model()
            return True
        except Exception as e:
            self.logger.error(f"Erreur entraînement ML sizing: {e}")
            return False

    def train_target_model(self, X: np.ndarray, y: np.ndarray, n_estimators: int = 120, max_depth: int = 8, min_samples_split: int = 10) -> bool:
        """Entraîne le modèle P_target: régresseur du gain maximum atteignable (%) d'un trade.

        y = pour chaque sample, le meilleur gain net % observé pendant le hold
        (max favorable excursion). Sert à poser un take-profit intelligent."""
        if not SKLEARN_AVAILABLE:
            return False
        if len(X) < 30:
            self.logger.warning("Données insuffisantes pour entraîner le modèle ML P_target.")
            return False
        try:
            self.target_scaler = StandardScaler()
            X_scaled = self.target_scaler.fit_transform(X)
            self.target_model = RandomForestRegressor(
                n_estimators=n_estimators,
                max_depth=max_depth,
                min_samples_split=min_samples_split,
                random_state=45,
                n_jobs=-1
            )
            self.target_model.fit(X_scaled, y)
            self.is_target_trained = True
            self.save_model()
            return True
        except Exception as e:
            self.logger.error(f"Erreur entraînement ML P_target: {e}")
            return False

    def predict_target(
        self,
        features: Optional[np.ndarray] = None,
        klines: Optional[List[Dict]] = None,
        current_price: Optional[float] = None,
        klines_5m: Optional[List[Dict]] = None,
        klines_1h: Optional[List[Dict]] = None,
        klines_4h: Optional[List[Dict]] = None,
        klines_1d: Optional[List[Dict]] = None,
        trade_context: Optional[Dict] = None,
        bot_context: Optional[Dict] = None
    ) -> Dict:
        """Prédit le gain net maximum réaliste (%) atteignable par un trade à l'entrée.

        Retourne un take-profit cible clampé à des bornes prudentes. Utilisé pour
        sécuriser les gains avant qu'ils ne s'évaporent (P_exit reste le filet)."""
        min_target = float(os.getenv('ML_TARGET_MIN_PCT', '0.8'))
        max_target = float(os.getenv('ML_TARGET_MAX_PCT', '12.0'))

        if not self.is_target_trained or self.target_model is None or not SKLEARN_AVAILABLE:
            return {
                'ml_target_available': False,
                'target_gain_pct': None,
                'reason': 'target_model_untrained'
            }

        if features is None:
            if not klines:
                return {
                    'ml_target_available': False,
                    'target_gain_pct': None,
                    'reason': 'target_features_unavailable'
                }
            features = self.extract_features_from_klines(
                klines,
                current_price,
                klines_5m=klines_5m,
                klines_1h=klines_1h,
                klines_4h=klines_4h,
                klines_1d=klines_1d,
                trade_context=trade_context,
                bot_context=bot_context
            )
        if features is None:
            return {
                'ml_target_available': False,
                'target_gain_pct': None,
                'reason': 'target_features_unavailable'
            }

        try:
            features = self._align_target_features_for_loaded_model(features)
            X = features.reshape(1, -1)
            if self.target_scaler is not None:
                X = self.target_scaler.transform(X)
            raw_target = float(self.target_model.predict(X)[0])
            target_gain_pct = max(min_target, min(max_target, raw_target))
            return {
                'ml_target_available': True,
                'target_gain_pct': round(target_gain_pct, 3),
                'raw_target_gain_pct': round(raw_target, 3),
                'reason': f'ml_target_+{target_gain_pct:.2f}%'
            }
        except Exception as e:
            self.logger.error(f"Erreur prédiction ML P_target: {e}")
            return {
                'ml_target_available': False,
                'target_gain_pct': None,
                'reason': 'target_prediction_error'
            }

    def predict_position_size_factor(
        self,
        features: Optional[np.ndarray] = None,
        klines: Optional[List[Dict]] = None,
        current_price: Optional[float] = None,
        klines_5m: Optional[List[Dict]] = None,
        klines_1h: Optional[List[Dict]] = None,
        klines_4h: Optional[List[Dict]] = None,
        klines_1d: Optional[List[Dict]] = None,
        trade_context: Optional[Dict] = None,
        bot_context: Optional[Dict] = None
    ) -> Dict:
        """Retourne le facteur ML de taille de position, clampé par prudence."""
        if not self.is_sizing_trained or self.sizing_model is None or not SKLEARN_AVAILABLE:
            return {
                'ml_sizing_available': False,
                'sizing_factor': 1.0,
                'reason': 'sizing_model_untrained'
            }

        if features is None:
            if not klines:
                return {
                    'ml_sizing_available': False,
                    'sizing_factor': 1.0,
                    'reason': 'sizing_features_unavailable'
                }
            features = self.extract_features_from_klines(
                klines,
                current_price,
                klines_5m=klines_5m,
                klines_1h=klines_1h,
                klines_4h=klines_4h,
                klines_1d=klines_1d,
                trade_context=trade_context,
                bot_context=bot_context
            )
        if features is None:
            return {
                'ml_sizing_available': False,
                'sizing_factor': 1.0,
                'reason': 'sizing_features_unavailable'
            }

        try:
            features = self._align_sizing_features_for_loaded_model(features)
            X = features.reshape(1, -1)
            if self.sizing_scaler is not None:
                X = self.sizing_scaler.transform(X)
            raw_factor = float(self.sizing_model.predict(X)[0])
            factor = max(0.25, min(1.25, raw_factor))
            return {
                'ml_sizing_available': True,
                'sizing_factor': round(factor, 3),
                'raw_sizing_factor': round(raw_factor, 3),
                'reason': f'ml_sizing_factor_{factor:.2f}x'
            }
        except Exception as e:
            self.logger.error(f"Erreur prédiction ML sizing: {e}")
            return {
                'ml_sizing_available': False,
                'sizing_factor': 1.0,
                'reason': 'sizing_prediction_error'
            }

    def predict_exit_decision(
        self,
        klines: List[Dict],
        current_price: float,
        position_data: Dict,
        continuation_score: float,
        entry_p_win: float = 50.0,
        btc_klines: Optional[List[Dict]] = None,
        bot_context: Optional[Dict] = None
    ) -> Dict:
        """Retourne la probabilité ML de continuer et une décision de gestion de sortie."""
        if not self.is_exit_trained or self.exit_model is None or not SKLEARN_AVAILABLE:
            return {
                'ml_exit_available': False,
                'p_continue': 50.0,
                'decision': 'HOLD',
                'reason': 'exit_model_untrained'
            }

        features = self.extract_exit_features(
            klines, current_price, position_data, continuation_score, entry_p_win, btc_klines, bot_context
        )
        if features is None:
            return {
                'ml_exit_available': False,
                'p_continue': 50.0,
                'decision': 'HOLD',
                'reason': 'exit_features_unavailable'
            }

        try:
            features = self._align_exit_features_for_loaded_model(features)
            X = features.reshape(1, -1)
            if self.exit_scaler is not None:
                X = self.exit_scaler.transform(X)
            probs = self.exit_model.predict_proba(X)[0]
            p_continue = float(probs[1]) * 100.0 if len(probs) > 1 else 50.0

            buy_price = float(position_data.get('entry_price') or position_data.get('buy_price') or position_data.get('price') or position_data.get('avg_entry_price') or current_price)
            fee_rate = float(position_data.get('fee_rate', float(os.getenv('TRADING_FEE_PERCENT', '0.1')) / 100.0))
            breakeven_price = buy_price * (1 + fee_rate) / max(0.000001, (1 - fee_rate))
            net_pnl_pct = ((current_price - breakeven_price) / max(buy_price, 1e-9)) * 100.0

            sell_threshold = float(os.getenv('ML_EXIT_SELL_THRESHOLD', '35.0'))
            avg_fee_pct = fee_rate * 100.0  # Moyenne des frais (frais_achat + frais_vente)/2
            env_min_net = float(os.getenv('ML_EXIT_PROFIT_PROTECT_MIN_NET_PCT', '0.35'))
            profit_protect_min_net = max(avg_fee_pct, env_min_net)
            profit_protect_threshold = float(os.getenv('ML_EXIT_PROFIT_PROTECT_THRESHOLD', '70.0'))
            if net_pnl_pct >= profit_protect_min_net:
                sell_threshold = max(sell_threshold, profit_protect_threshold)

            if p_continue < sell_threshold:
                decision = 'FORCE_EXIT'
            else:
                decision = 'HOLD'

            return {
                'ml_exit_available': True,
                'p_continue': round(p_continue, 1),
                'decision': decision,
                'reason': f'ml_continue_{p_continue:.1f}%_threshold_{sell_threshold:.1f}%'
            }
        except Exception as e:
            self.logger.error(f"Erreur prédiction ML sortie: {e}")
            return {
                'ml_exit_available': False,
                'p_continue': 50.0,
                'decision': 'HOLD',
                'reason': 'exit_prediction_error'
            }

    def predict_win_probability(
        self,
        klines: List[Dict],
        current_price: Optional[float] = None,
        klines_5m: Optional[List[Dict]] = None,
        klines_1h: Optional[List[Dict]] = None,
        klines_4h: Optional[List[Dict]] = None,
        klines_1d: Optional[List[Dict]] = None,
        trade_context: Optional[Dict] = None,
        bot_context: Optional[Dict] = None
    ) -> float:
        """Calcule la probabilité P_win [0.0 - 100.0]% en < 2ms avec support Multi-Timeframe"""
        if not self.is_trained or self.model is None or not SKLEARN_AVAILABLE:
            return 50.0  # Valeur neutre par défaut si modèle non encore entraîné

        features = self.extract_features_from_klines(
            klines,
            current_price,
            klines_5m=klines_5m,
            klines_1h=klines_1h,
            klines_4h=klines_4h,
            klines_1d=klines_1d,
            trade_context=trade_context,
            bot_context=bot_context
        )
        if features is None:
            return 50.0

        try:
            features = self._align_features_for_loaded_model(features)
            X = features.reshape(1, -1)
            if self.scaler is not None:
                X = self.scaler.transform(X)

            probs = self.model.predict_proba(X)[0]
            win_prob = float(probs[1]) * 100.0 if len(probs) > 1 else 50.0
            return round(win_prob, 1)

        except Exception as e:
            self.logger.error(f"Erreur de prédiction ML: {e}")
            return 50.0

    def save_model(self) -> bool:
        """Sauvegarde le modèle et le scaler sur le disque"""
        if not SKLEARN_AVAILABLE or self.model is None:
            return False

        try:
            os.makedirs(self.model_dir, exist_ok=True)
            joblib.dump({
                'model': self.model,
                'scaler': self.scaler,
                'exit_model': self.exit_model,
                'exit_scaler': self.exit_scaler,
                'sizing_model': self.sizing_model,
                'sizing_scaler': self.sizing_scaler,
                'target_model': self.target_model,
                'target_scaler': self.target_scaler,
                'model_metadata': getattr(self, 'model_metadata', None),
            }, self.model_path)

            importance = {}
            if hasattr(self.model, 'feature_importances_'):
                for name, imp in zip(self.feature_names, self.model.feature_importances_):
                    importance[name] = round(float(imp), 4)

            metadata = {
                'trained_at': datetime.now().isoformat(),
                'feature_importance': sorted(importance.items(), key=lambda x: x[1], reverse=True),
                'n_features': len(self.feature_names)
            }
            # Merger les métriques de test si disponibles
            if hasattr(self, 'model_metadata') and isinstance(self.model_metadata, dict):
                metadata.update(self.model_metadata)
            if self.exit_model is not None and hasattr(self.exit_model, 'feature_importances_'):
                exit_importance = {}
                for name, imp in zip(self.exit_feature_names, self.exit_model.feature_importances_):
                    exit_importance[name] = round(float(imp), 4)
                metadata['exit_feature_importance'] = sorted(exit_importance.items(), key=lambda x: x[1], reverse=True)
                metadata['exit_n_features'] = len(self.exit_feature_names)
            if self.sizing_model is not None and hasattr(self.sizing_model, 'feature_importances_'):
                sizing_importance = {}
                for name, imp in zip(self.sizing_feature_names, self.sizing_model.feature_importances_):
                    sizing_importance[name] = round(float(imp), 4)
                metadata['sizing_feature_importance'] = sorted(sizing_importance.items(), key=lambda x: x[1], reverse=True)
                metadata['sizing_n_features'] = len(self.sizing_feature_names)
            if self.target_model is not None and hasattr(self.target_model, 'feature_importances_'):
                target_importance = {}
                for name, imp in zip(self.target_feature_names, self.target_model.feature_importances_):
                    target_importance[name] = round(float(imp), 4)
                metadata['target_feature_importance'] = sorted(target_importance.items(), key=lambda x: x[1], reverse=True)
                metadata['target_n_features'] = len(self.target_feature_names)
            try:
                if os.getenv('ML_SKIP_MODEL_METADATA', '').lower() in ('1', 'true', 'yes'):
                    return True
                from core.ml_live_logger import MLLiveLogger
                with MLLiveLogger(
                    data_dir=self.model_dir,
                    sqlite_file=os.getenv('ML_LIVE_SQLITE_FILE', os.path.join(self.model_dir, 'aegis_db.sqlite3'))
                ) as logger:
                    logger.record_ml_model_metadata(metadata, model_path=self.model_path)
            except Exception:
                pass

            return True
        except Exception as e:
            self.logger.error(f"Erreur lors de la sauvegarde du modèle ML: {e}")
            return False

    def load_model(self) -> bool:
        """Charge le modèle ML depuis le disque si présent"""
        if not SKLEARN_AVAILABLE or not os.path.exists(self.model_path):
            self.is_trained = False
            return False

        try:
            data = joblib.load(self.model_path)
            self.model = data.get('model')
            self.scaler = data.get('scaler')
            self.exit_model = data.get('exit_model')
            self.exit_scaler = data.get('exit_scaler')
            self.sizing_model = data.get('sizing_model')
            self.sizing_scaler = data.get('sizing_scaler')
            self.target_model = data.get('target_model')
            self.target_scaler = data.get('target_scaler')
            if self.model is not None and hasattr(self.model, 'n_jobs'):
                self.model.n_jobs = 1
            if self.exit_model is not None and hasattr(self.exit_model, 'n_jobs'):
                self.exit_model.n_jobs = 1
            if self.sizing_model is not None and hasattr(self.sizing_model, 'n_jobs'):
                self.sizing_model.n_jobs = 1
            if self.target_model is not None and hasattr(self.target_model, 'n_jobs'):
                self.target_model.n_jobs = 1
            self.is_trained = self.model is not None
            self.is_exit_trained = self.exit_model is not None
            self.is_sizing_trained = self.sizing_model is not None
            self.is_target_trained = self.target_model is not None
            self.model_metadata = data.get('model_metadata') or {}

            # Re-publier les feature importances en BD au chargement (ex: après reset DB)
            try:
                importance = {}
                if self.model is not None and hasattr(self.model, 'feature_importances_'):
                    for name, imp in zip(self.feature_names, self.model.feature_importances_):
                        importance[name] = round(float(imp), 4)
                metadata = {
                    'trained_at': datetime.now().isoformat(),
                    'feature_importance': sorted(importance.items(), key=lambda x: x[1], reverse=True),
                    'n_features': len(self.feature_names),
                }
                if self.exit_model is not None and hasattr(self.exit_model, 'feature_importances_'):
                    exit_importance = {}
                    for name, imp in zip(self.exit_feature_names, self.exit_model.feature_importances_):
                        exit_importance[name] = round(float(imp), 4)
                    metadata['exit_feature_importance'] = sorted(exit_importance.items(), key=lambda x: x[1], reverse=True)
                    metadata['exit_n_features'] = len(self.exit_feature_names)
                if self.sizing_model is not None and hasattr(self.sizing_model, 'feature_importances_'):
                    sizing_importance = {}
                    for name, imp in zip(self.sizing_feature_names, self.sizing_model.feature_importances_):
                        sizing_importance[name] = round(float(imp), 4)
                    metadata['sizing_feature_importance'] = sorted(sizing_importance.items(), key=lambda x: x[1], reverse=True)
                    metadata['sizing_n_features'] = len(self.sizing_feature_names)
                if self.target_model is not None and hasattr(self.target_model, 'feature_importances_'):
                    target_importance = {}
                    for name, imp in zip(self.target_feature_names, self.target_model.feature_importances_):
                        target_importance[name] = round(float(imp), 4)
                    metadata['target_feature_importance'] = sorted(target_importance.items(), key=lambda x: x[1], reverse=True)
                    metadata['target_n_features'] = len(self.target_feature_names)
                if not os.getenv('ML_SKIP_MODEL_METADATA', '').lower() in ('1', 'true', 'yes'):
                    from core.ml_live_logger import MLLiveLogger
                    with MLLiveLogger(
                        data_dir=self.model_dir,
                        sqlite_file=os.getenv('ML_LIVE_SQLITE_FILE', os.path.join(self.model_dir, 'aegis_db.sqlite3'))
                    ) as logger:
                        logger.record_ml_model_metadata(metadata, model_path=self.model_path)
            except Exception:
                pass

            return self.is_trained
        except Exception as e:
            self.logger.error(f"Erreur de chargement du modèle ML: {e}")
            self.is_trained = False
            return False


    def get_feature_importance(self) -> List[Tuple[str, float]]:
        """Retourne l'importance des variables sous forme d'une liste (nom, importance)"""
        try:
            from core.ml_live_logger import MLLiveLogger
            with MLLiveLogger(
                data_dir=self.model_dir,
                sqlite_file=os.getenv('ML_LIVE_SQLITE_FILE', os.path.join(self.model_dir, 'aegis_db.sqlite3'))
            ) as logger:
                meta = logger.get_latest_ml_model_metadata()
            return meta.get('feature_importance', [])
        except:
            return []

    def get_exit_feature_importance(self) -> List[Tuple[str, float]]:
        """Retourne l'importance des variables du modèle ML de sortie."""
        try:
            from core.ml_live_logger import MLLiveLogger
            with MLLiveLogger(
                data_dir=self.model_dir,
                sqlite_file=os.getenv('ML_LIVE_SQLITE_FILE', os.path.join(self.model_dir, 'aegis_db.sqlite3'))
            ) as logger:
                meta = logger.get_latest_ml_model_metadata()
            return meta.get('exit_feature_importance', [])
        except:
            return []
