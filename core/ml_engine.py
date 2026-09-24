"""
Core Machine Learning Engine (MLEngine) for Aegis Trading Bot
Uses LightGBM (default) or Random Forest Classifier to evaluate trade win probability (P_win).
Features:
- 18+ Technical Market Indicators (RSI, EMA Slopes, ATR Volatility, Volume Ratio, Support Proximity)
- Model Persistence (joblib)
- Sub-2ms Real-time Inference Speed
- Decoupled & Transparent (Feature Importance Export)
- LightGBM for better accuracy on tabular data
"""

import os
import time
import logging
import hashlib
import json
import subprocess
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

# LightGBM - meilleur que RF sur données tabulaires
try:
    import lightgbm as lgb
    LIGHTGBM_AVAILABLE = True
except ImportError:
    LIGHTGBM_AVAILABLE = False


class MLEngine:
    """Moteur de Machine Learning dédié pour la prédiction de probabilité de gain"""

    MODEL_FORMAT_VERSION = 3


    def __init__(self, model_dir: str = 'data'):
        self.logger = logging.getLogger(__name__)
        self.model_dir = model_dir
        self.model_path = os.path.join(model_dir, 'aegis_model.joblib')
        
        self.model = None
        self.scaler = None
        self.probability_calibrator = None
        self.edge_model = None
        self.edge_scaler = None
        self.exit_model = None
        self.exit_scaler = None
        self.exit_calibrator = None
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
            # Features 1h supplémentaires (haute importance constatée sur 1h)
            'volume_ratio_1h', 'candle_body_pct_1h', 'rsi_divergence_1h',
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
            # Feature contextuelle (session de marché: 0=off-hours, 1=asia, 2=europe, 3=us, 4=europe+us overlap)
            'market_session',
        ]
        self.exit_feature_names = [
            'entry_p_win', 'continuation_score', 'gross_pnl_pct', 'net_pnl_pct',
            'duration_minutes', 'fee_rate_bps', 'dist_to_stop_pct', 'dist_to_target_pct',
            'rsi_14', 'ema9_slope', 'ema20_slope', 'ema_cross_diff',
            'volatility_directional',  # REMPLACE atr_percent + volatility_std (volatilité × direction)
            'volume_ratio', 'candle_body_pct', 'candle_wick_top',
            'candle_wick_bottom', 'price_change_3b', 'price_change_5b',
            'hour_of_day', 'btc_momentum_3b',
            'symbol_regime_code', 'btc_regime_code', 'bear_mode',
            'reversal_confirmed', 'falling_knife_active',
            'is_support_touch', 'support_confidence',
            'crypto_score', 'score_vs_threshold',
            'is_optimal_trading_time', 'trading_session_code',
            'minutes_to_session_close',
            'technical_action_code', 'technical_confidence',
            'technical_confidence_edge',
            # Features DIRECTIONNELLES ajoutées en fin de schéma (compat champion) pour que
            # le P_exit distingue volatilité HAUSSIÈRE (continuer) de volatilité CHAOTIQUE
            # (sortir), au lieu de se baser surtout sur la volatilité brute (atr/std).
            'exit_short_tf_alignment', 'exit_multi_tf_trend_alignment',
            'exit_ema20_breakout_15m', 'exit_momentum_accel_5m',
            'exit_consecutive_green_5m',
            # === VOLUME PROFILE (v2) ===
            # Le volume précède le prix : accumulation = continuer, distribution = sortir
            'volume_trend_5b',      # Volume 5 dernières bougies vs moyenne 20 (>1 = accumulation)
            'buy_volume_ratio',     # % du volume sur bougies vertes (>50% = pression acheteuse)
            'volume_price_confirm', # Volume ET prix montent ensemble (1 = confirmé, 0 = divergence)
            # === NIVEAUX DYNAMIQUES (structure de prix) ===
            # Position dans la structure: proche résistance = risque blocage, proche support = filet
            'price_in_range_pct',       # Position dans le range 20 bougies (0=bas, 100=haut)
            'dist_to_recent_high_pct',  # Distance au plus haut récent (négatif = en dessous)
            'dist_to_recent_low_pct',   # Distance au plus bas récent (positif = au dessus)
            'breakout_strength',        # Force du breakout si au-dessus du range (0 si dans le range)
            # === FEATURES DIRECTIONNELLES DEPUIS ENTRÉE (amélioration sortie v3) ===
            # Contexte depuis l'entrée pour mieux décider si continuer ou sortir
            'pnl_trend_3b',             # Tendance du PnL sur 3 dernières bougies (+1=monte, -1=descend)
            'price_vs_entry_ema20',     # Prix actuel vs EMA20 depuis entrée (>0=au-dessus)
            'momentum_since_entry',     # Momentum cumulé depuis entrée (positif=favorable)
        ]
        self.sizing_feature_names = list(self.feature_names)
        # Le modèle P_target réutilise les mêmes features d'entrée que P_win/sizing
        self.target_feature_names = list(self.feature_names)

    def _feature_schema_payload(self) -> Dict:
        return {
            'entry': list(self.feature_names),
            'exit': list(self.exit_feature_names),
            'sizing': list(self.sizing_feature_names),
            'target': list(self.target_feature_names),
        }

    def feature_schema_hash(self) -> str:
        payload = json.dumps(
            self._feature_schema_payload(),
            sort_keys=True,
            separators=(',', ':'),
        ).encode('utf-8')
        return hashlib.sha256(payload).hexdigest()

    def _config_hash(self) -> str:
        keys = [
            'TRADING_FEE_PERCENT',
            'ML_MIN_PROBABILITY',
            'ML_MIN_EXPECTED_NET_PNL_PCT',
            'ML_EXPECTED_SLIPPAGE_PCT',
            'ML_EXIT_SELL_THRESHOLD',
            'ML_EXIT_ENTRY_MIN_CONTINUE_PROB',
            'ML_TARGET_PATH_QUANTILE',
            'HARD_ANTI_FALLING_KNIFE',
            'ML_USE_LIGHTGBM',
        ]
        payload = {key: os.getenv(key) for key in keys}
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
        ).hexdigest()

    @staticmethod
    def _git_sha() -> str:
        env_sha = os.getenv('GITHUB_SHA') or os.getenv('AEGIS_GIT_SHA')
        if env_sha:
            return str(env_sha)
        try:
            return subprocess.check_output(
                ['git', 'rev-parse', 'HEAD'],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=2,
            ).strip()
        except Exception:
            return 'unknown'

    def _model_contract(self) -> Dict:
        metadata = dict(getattr(self, 'model_metadata', {}) or {})
        return {
            'model_format_version': int(self.MODEL_FORMAT_VERSION),
            'model_version': str(os.getenv('AEGIS_MODEL_VERSION', '3')),
            'feature_schema_hash': self.feature_schema_hash(),
            'feature_schema': self._feature_schema_payload(),
            'git_sha': self._git_sha(),
            'config_hash': self._config_hash(),
            'training_start': metadata.get('training_start'),
            'training_end': metadata.get('training_end'),
            'data_provider': metadata.get('data_provider'),
            'fee_assumption_percent': float(os.getenv('TRADING_FEE_PERCENT', '0.4')),
            'ml_min_probability': float(os.getenv('ML_MIN_PROBABILITY', '50.0')),
        }

    def _validate_loaded_contract(self, data: Dict) -> bool:
        strict = os.getenv('ML_STRICT_MODEL_SCHEMA', 'True').lower() == 'true'
        contract = data.get('model_contract') or {}
        expected_hash = self.feature_schema_hash()
        actual_hash = contract.get('feature_schema_hash')

        if not strict:
            return True
        if int(contract.get('model_format_version') or 0) != int(self.MODEL_FORMAT_VERSION):
            self.logger.error(
                "Modèle refusé: format version %s != runtime %s",
                contract.get('model_format_version'),
                self.MODEL_FORMAT_VERSION,
            )
            return False
        if not actual_hash or actual_hash != expected_hash:
            self.logger.error(
                "Modèle refusé: feature schema incompatible (%s != %s)",
                actual_hash,
                expected_hash,
            )
            return False
        return True

        
        self.is_trained = False
        self.is_edge_trained = False
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
            
            # Feature contextuelle: session de marché (heures UTC)
            # 0 = off-hours (22-00 UTC), 1 = asia (00-08), 2 = europe (08-13), 
            # 3 = us (17-22), 4 = europe+us overlap (13-17, meilleure liquidité)
            if 13 <= dt.hour < 17:
                market_session = 4.0  # Europe + US overlap (meilleure liquidité)
            elif 17 <= dt.hour < 22:
                market_session = 3.0  # US seul
            elif 8 <= dt.hour < 13:
                market_session = 2.0  # Europe seul
            elif 0 <= dt.hour < 8:
                market_session = 1.0  # Asia
            else:
                market_session = 0.0  # Off-hours (22-00)
            
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
                opens_1h = np.array([float(k['open']) for k in klines_1h], dtype=np.float64)
                highs_1h = np.array([float(k['high']) for k in klines_1h], dtype=np.float64)
                lows_1h = np.array([float(k['low']) for k in klines_1h], dtype=np.float64)
                volumes_1h = np.array([float(k.get('volume', 0.0) or 0.0) for k in klines_1h], dtype=np.float64)
                
                rsi_1h = self._calc_rsi(closes_1h, 14)
                ema20_slope_1h = self._calc_ema_slope(closes_1h, 20)
                ema50_slope_1h = self._calc_ema_slope(closes_1h, 50) if len(closes_1h) >= 50 else ema20_slope_1h
                price_change_3b_1h = (closes_1h[-1] - closes_1h[-4]) / (closes_1h[-4] + 1e-9) * 100.0 if len(closes_1h) >= 4 else 0.0
                
                # Nouvelles features 1h (haute importance constatée)
                avg_vol_1h = np.mean(volumes_1h[-20:]) if len(volumes_1h) >= 20 else (np.mean(volumes_1h) + 1e-9)
                volume_ratio_1h = float(volumes_1h[-1] / (avg_vol_1h + 1e-9))
                c_range_1h = highs_1h[-1] - lows_1h[-1] + 1e-9
                candle_body_pct_1h = abs(closes_1h[-1] - opens_1h[-1]) / c_range_1h
                # RSI divergence: prix monte mais RSI descend (ou inverse) = signal faiblesse
                rsi_prev_1h = self._calc_rsi(closes_1h[:-1], 14) if len(closes_1h) >= 16 else rsi_1h
                price_up_1h = closes_1h[-1] > closes_1h[-2] if len(closes_1h) >= 2 else False
                rsi_up_1h = rsi_1h > rsi_prev_1h
                # divergence: +1 si confirmé (prix et RSI même direction), -1 si divergence baissière, 0 neutre
                if price_up_1h and rsi_up_1h:
                    rsi_divergence_1h = 1.0  # Confirmé haussier
                elif price_up_1h and not rsi_up_1h:
                    rsi_divergence_1h = -1.0  # Divergence baissière (warning)
                elif not price_up_1h and rsi_up_1h:
                    rsi_divergence_1h = 0.5  # Divergence haussière cachée (potentiel)
                else:
                    rsi_divergence_1h = 0.0  # Confirmé baissier
            else:
                rsi_1h = rsi
                ema20_slope_1h = ema20_slope
                ema50_slope_1h = ema20_slope * 0.8
                price_change_3b_1h = price_change_3b * 2.0
                volume_ratio_1h = volume_ratio
                candle_body_pct_1h = candle_body_pct
                rsi_divergence_1h = 0.0

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
                # Features 1h supplémentaires (haute importance)
                volume_ratio_1h, candle_body_pct_1h, rsi_divergence_1h,
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
                # Feature contextuelle (session de marché)
                market_session,
            ], dtype=np.float64)

            return features

        except Exception as e:
            self.logger.error(f"Erreur d'extraction des caractéristiques ML: {e}")
            return None

    def _temporal_holdout_split(self, X, y, sample_weight=None):
        """Split chronologique: le passé entraîne, la période la plus récente valide."""
        ratio = float(os.getenv('ML_TEMPORAL_TEST_RATIO', '0.20'))
        ratio = max(0.10, min(0.40, ratio))
        split_idx = int(len(X) * (1.0 - ratio))
        split_idx = max(20, min(len(X) - 10, split_idx))
        X_train, X_test = X[:split_idx], X[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]
        if sample_weight is None:
            return X_train, X_test, y_train, y_test, None, None
        return (
            X_train, X_test, y_train, y_test,
            sample_weight[:split_idx], sample_weight[split_idx:]
        )

    def _fit_isotonic_calibrator(self, raw_probs: np.ndarray, y_true: np.ndarray):
        """Fit a monotonic probability calibrator on a chronological holdout."""
        try:
            from sklearn.isotonic import IsotonicRegression
            raw_probs = np.asarray(raw_probs, dtype=np.float64)
            y_true = np.asarray(y_true, dtype=np.float64)
            if len(raw_probs) < 40 or len(np.unique(y_true)) < 2:
                return None
            return IsotonicRegression(out_of_bounds='clip').fit(raw_probs, y_true)
        except Exception:
            return None

    @staticmethod
    def _apply_calibrator(calibrator, probability: float) -> float:
        try:
            if calibrator is None:
                return float(probability)
            return float(calibrator.predict([float(probability)])[0])
        except Exception:
            return float(probability)

    def predict_win_probability_from_features(self, features: np.ndarray) -> float:
        """Predict calibrated P_win from an already-built feature vector."""
        if not self.is_trained or self.model is None or features is None:
            return 50.0
        try:
            aligned = self._align_features_for_loaded_model(np.asarray(features, dtype=np.float64))
            X = aligned.reshape(1, -1)
            if self.scaler is not None:
                X = self.scaler.transform(X)
            probs = self.model.predict_proba(X)[0]
            raw = float(probs[1]) if len(probs) > 1 else 0.5
            calibrated = self._apply_calibrator(self.probability_calibrator, raw)
            return round(max(0.0, min(1.0, calibrated)) * 100.0, 1)
        except Exception as e:
            self.logger.error(f"Erreur prédiction P_win depuis features: {e}")
            return 50.0

    def train_edge_model(self, X: np.ndarray, y_net_pnl: np.ndarray, sample_weight: Optional[np.ndarray] = None, use_lightgbm: bool = True) -> bool:
        """Predict expected net PnL (%) for candidate entries using temporal validation."""
        if not SKLEARN_AVAILABLE or len(X) < 30:
            return False
        try:
            from sklearn.metrics import mean_absolute_error, mean_squared_error
            X_train, X_test, y_train, y_test, sw_train, _ = self._temporal_holdout_split(
                X, np.asarray(y_net_pnl, dtype=np.float64), sample_weight
            )
            self.edge_scaler = StandardScaler()
            X_train_s = self.edge_scaler.fit_transform(X_train)
            X_test_s = self.edge_scaler.transform(X_test)
            if use_lightgbm and LIGHTGBM_AVAILABLE:
                self.edge_model = lgb.LGBMRegressor(
                    n_estimators=180, max_depth=6, learning_rate=0.04,
                    num_leaves=31, random_state=46, n_jobs=-1, verbose=-1
                )
            else:
                self.edge_model = RandomForestRegressor(
                    n_estimators=180, max_depth=8, min_samples_split=8,
                    random_state=46, n_jobs=-1
                )
            self.edge_model.fit(X_train_s, y_train, sample_weight=sw_train)
            pred = self.edge_model.predict(X_test_s)
            mae = mean_absolute_error(y_test, pred)
            rmse = mean_squared_error(y_test, pred) ** 0.5
            self.model_metadata = dict(getattr(self, 'model_metadata', {}) or {})
            self.model_metadata['edge_test_mae_pct'] = round(float(mae), 4)
            self.model_metadata['edge_test_rmse_pct'] = round(float(rmse), 4)
            self.model_metadata['edge_validation_type'] = 'temporal_holdout'

            self.edge_scaler = StandardScaler()
            X_all = self.edge_scaler.fit_transform(X)
            self.edge_model.fit(X_all, np.asarray(y_net_pnl, dtype=np.float64), sample_weight=sample_weight)
            self.is_edge_trained = True
            self.save_model()
            return True
        except Exception as e:
            self.logger.error(f"Erreur entraînement expected PnL: {e}")
            return False

    def predict_expected_net_pnl(self, features: np.ndarray) -> Dict:
        if not self.is_edge_trained or self.edge_model is None or features is None:
            return {'ml_edge_available': False, 'expected_net_pnl_pct': None}
        try:
            aligned = self._align_features_for_loaded_model(np.asarray(features, dtype=np.float64))
            X = aligned.reshape(1, -1)
            if self.edge_scaler is not None:
                X = self.edge_scaler.transform(X)
            value = float(self.edge_model.predict(X)[0])
            return {
                'ml_edge_available': True,
                'expected_net_pnl_pct': round(value, 4),
                'reason': f'expected_net_pnl_{value:+.3f}%'
            }
        except Exception as e:
            self.logger.error(f"Erreur prédiction expected PnL: {e}")
            return {'ml_edge_available': False, 'expected_net_pnl_pct': None}

    def train_model(self, X: np.ndarray, y: np.ndarray, n_estimators: int = 100, max_depth: int = 6, min_samples_split: int = 5, criterion: str = 'gini', sample_weight: Optional[np.ndarray] = None, use_lightgbm: bool = True) -> bool:
        """Entraîne LightGBM (défaut) ou Random Forest avec holdout chronologique."""
        if not SKLEARN_AVAILABLE:
            self.logger.warning("scikit-learn n'est pas disponible pour l'entraînement ML.")
            return False
        if len(X) < 30:
            self.logger.warning("Données insuffisantes pour l'entraînement ML (minimum 30 exemples requis).")
            return False

        try:
            from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score

            X_train, X_test, y_train, y_test, sw_train, _sw_test = self._temporal_holdout_split(
                X, y, sample_weight
            )
            if len(np.unique(y_train)) < 2:
                self.logger.warning("Holdout temporel invalide: une seule classe dans la fenêtre d'entraînement.")
                return False

            self.scaler = StandardScaler()
            X_train_scaled = self.scaler.fit_transform(X_train)
            X_test_scaled = self.scaler.transform(X_test)

            model_type = 'lightgbm'
            if use_lightgbm and LIGHTGBM_AVAILABLE:
                self.model = lgb.LGBMClassifier(
                    n_estimators=n_estimators,
                    max_depth=max_depth if max_depth else -1,
                    min_child_samples=min_samples_split,
                    learning_rate=0.05,
                    num_leaves=31,
                    random_state=42,
                    n_jobs=-1,
                    verbose=-1,
                    importance_type='gain'
                )
            else:
                model_type = 'random_forest'
                self.model = RandomForestClassifier(
                    n_estimators=n_estimators,
                    max_depth=max_depth,
                    min_samples_split=min_samples_split,
                    criterion=criterion,
                    random_state=42,
                    n_jobs=-1,
                    oob_score=True
                )

            self.model.fit(X_train_scaled, y_train, sample_weight=sw_train)
            self.is_trained = True

            y_pred = self.model.predict(X_test_scaled)
            raw_holdout_probs = self.model.predict_proba(X_test_scaled)[:, 1]
            self.probability_calibrator = self._fit_isotonic_calibrator(raw_holdout_probs, y_test)
            calibrated_holdout_probs = np.array([
                self._apply_calibrator(self.probability_calibrator, p) for p in raw_holdout_probs
            ])
            brier = float(np.mean((calibrated_holdout_probs - y_test) ** 2))
            test_acc = accuracy_score(y_test, y_pred) * 100
            test_prec = precision_score(y_test, y_pred, zero_division=0) * 100
            test_recall = recall_score(y_test, y_pred, zero_division=0) * 100
            test_f1 = f1_score(y_test, y_pred, zero_division=0) * 100
            train_acc = self.model.score(X_train_scaled, y_train) * 100
            oob = self.model.oob_score_ * 100 if hasattr(self.model, 'oob_score_') and self.model.oob_score_ else None

            _base_metadata = dict(getattr(self, 'model_metadata', {}) or {})
            self.model_metadata = {
                **_base_metadata,
                'trained_at': datetime.now().isoformat(),
                'model_type': model_type,
                'validation_type': 'temporal_holdout',
                'temporal_test_ratio': round(len(X_test) / max(1, len(X)), 4),
                'n_features': int(X.shape[1]),
                'exit_n_features': len(self.exit_feature_names),
                'train_samples': int(len(X)),
                'train_win_rate': f"{int(sum(y))/len(y)*100:.1f}%",
                'test_accuracy': round(test_acc, 1),
                'test_precision': round(test_prec, 1),
                'test_recall': round(test_recall, 1),
                'test_f1': round(test_f1, 1),
                'test_brier': round(brier, 5),
                'probability_calibrated': bool(self.probability_calibrator is not None),
                'train_accuracy': round(train_acc, 1),
                'oob_score': round(oob, 1) if oob else None,
            }

            self.logger.info(
                f"Model trained: {model_type} | temporal holdout | "
                f"Acc={test_acc:.1f}% | Prec={test_prec:.1f}% | F1={test_f1:.1f}%"
            )

            # Une fois les métriques hors-échantillon figées, réentraîner le champion
            # candidat sur toutes les données disponibles.
            self.scaler = StandardScaler()
            X_scaled = self.scaler.fit_transform(X)
            self.model.fit(X_scaled, y, sample_weight=sample_weight)
            self.save_model()
            return True

        except Exception as e:
            self.logger.error(f"Erreur lors de l'entraînement ML: {e}")
            return False

    def train_model_with_grid_search(self, X: np.ndarray, y: np.ndarray, sample_weight: Optional[np.ndarray] = None, use_lightgbm: bool = True, cv: int = 3) -> bool:
        """Grid Search temporel: TimeSeriesSplit sur le passé, holdout final sur le futur."""
        if not SKLEARN_AVAILABLE:
            self.logger.warning("scikit-learn n'est pas disponible pour l'entraînement ML.")
            return False
        if len(X) < 100:
            self.logger.warning("Grid Search nécessite au moins 100 samples. Fallback vers train_model standard.")
            return self.train_model(X, y, sample_weight=sample_weight, use_lightgbm=use_lightgbm)

        try:
            from sklearn.model_selection import GridSearchCV, TimeSeriesSplit
            from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, make_scorer

            X_train, X_test, y_train, y_test, sw_train, _sw_test = self._temporal_holdout_split(
                X, y, sample_weight
            )
            if len(np.unique(y_train)) < 2:
                self.logger.warning("Grid Search temporel invalide: une seule classe dans la fenêtre d'entraînement.")
                return False

            self.scaler = StandardScaler()
            X_train_scaled = self.scaler.fit_transform(X_train)
            X_test_scaled = self.scaler.transform(X_test)

            precision_scorer = make_scorer(precision_score, zero_division=0)
            if use_lightgbm and LIGHTGBM_AVAILABLE:
                param_grid = {
                    'n_estimators': [100, 200, 300],
                    'max_depth': [4, 6, 8, -1],
                    'learning_rate': [0.01, 0.05, 0.1],
                    'num_leaves': [15, 31, 63],
                    'min_child_samples': [5, 10, 20],
                }
                base_model = lgb.LGBMClassifier(random_state=42, n_jobs=-1, verbose=-1)
                model_type = 'lightgbm'
            else:
                param_grid = {
                    'n_estimators': [100, 200, 300],
                    'max_depth': [4, 6, 8, None],
                    'min_samples_split': [2, 5, 10],
                    'min_samples_leaf': [1, 2, 4],
                }
                base_model = RandomForestClassifier(random_state=42, n_jobs=-1)
                model_type = 'random_forest'

            requested_cv = int(os.getenv('ML_CV_SPLITS', str(cv)))
            max_splits = max(2, min(requested_cv, max(2, len(X_train) // 50)))
            tscv = TimeSeriesSplit(n_splits=max_splits)
            grid_search = GridSearchCV(
                base_model,
                param_grid,
                cv=tscv,
                scoring=precision_scorer,
                n_jobs=-1,
                verbose=1
            )
            grid_search.fit(X_train_scaled, y_train, sample_weight=sw_train)

            self.model = grid_search.best_estimator_
            self.is_trained = True

            y_pred = self.model.predict(X_test_scaled)
            raw_holdout_probs = self.model.predict_proba(X_test_scaled)[:, 1]
            self.probability_calibrator = self._fit_isotonic_calibrator(raw_holdout_probs, y_test)
            calibrated_holdout_probs = np.array([
                self._apply_calibrator(self.probability_calibrator, p) for p in raw_holdout_probs
            ])
            brier = float(np.mean((calibrated_holdout_probs - y_test) ** 2))
            test_acc = accuracy_score(y_test, y_pred) * 100
            test_prec = precision_score(y_test, y_pred, zero_division=0) * 100
            test_recall = recall_score(y_test, y_pred, zero_division=0) * 100
            test_f1 = f1_score(y_test, y_pred, zero_division=0) * 100
            train_acc = self.model.score(X_train_scaled, y_train) * 100

            _base_metadata = dict(getattr(self, 'model_metadata', {}) or {})
            self.model_metadata = {
                **_base_metadata,
                'trained_at': datetime.now().isoformat(),
                'model_type': f'{model_type}_grid_search',
                'validation_type': 'temporal_holdout_timeseries_cv',
                'temporal_test_ratio': round(len(X_test) / max(1, len(X)), 4),
                'n_features': int(X.shape[1]),
                'exit_n_features': len(self.exit_feature_names),
                'train_samples': int(len(X)),
                'train_win_rate': f"{int(sum(y))/len(y)*100:.1f}%",
                'test_accuracy': round(test_acc, 1),
                'test_precision': round(test_prec, 1),
                'test_recall': round(test_recall, 1),
                'test_f1': round(test_f1, 1),
                'test_brier': round(brier, 5),
                'probability_calibrated': bool(self.probability_calibrator is not None),
                'train_accuracy': round(train_acc, 1),
                'best_params': grid_search.best_params_,
                'best_cv_score': round(grid_search.best_score_ * 100, 1),
                'cv_type': 'TimeSeriesSplit',
                'cv_splits': max_splits,
            }

            self.logger.info(
                f"Grid Search complete: {model_type} | TimeSeriesSplit | "
                f"Acc={test_acc:.1f}% | Prec={test_prec:.1f}% | F1={test_f1:.1f}%"
            )

            self.scaler = StandardScaler()
            X_scaled = self.scaler.fit_transform(X)
            self.model.fit(X_scaled, y, sample_weight=sample_weight)
            self.save_model()
            return True

        except Exception as e:
            self.logger.error(f"Erreur lors du Grid Search ML: {e}")
            return self.train_model(X, y, sample_weight=sample_weight, use_lightgbm=use_lightgbm)

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
            fee_rate = float(position_data.get('fee_rate', float(os.getenv('TRADING_FEE_PERCENT', '0.4')) / 100.0))
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
            
            # VOLATILITY_DIRECTIONAL: Mesure si la volatilité est "favorable" ou non
            # CORRECTION: Ne PAS paniquer sur un pullback court terme !
            # On utilise une combinaison de signaux pour déterminer si la tendance est intacte:
            # 1. net_pnl_pct > 0 → position en profit = tendance probablement intacte
            # 2. ema9_slope > 0 → EMA9 monte = momentum positif
            # 3. price_change_5b > 0 → tendance 5 bougies (plus stable que 3)
            # 4. multi_tf_trend_alignment > 0.5 → timeframes alignés haussier
            
            # Score de tendance: combien de signaux sont positifs ?
            trend_signals = 0
            if net_pnl_pct > 0.3:  # Position en profit > 0.3%
                trend_signals += 2  # Poids double pour le profit
            if ema9_slope > 0:
                trend_signals += 1
            if price_change_5b > 0:
                trend_signals += 1
            multi_tf_align = float(market_features[54]) if len(market_features) > 54 else 0.5
            if multi_tf_align > 0.5:
                trend_signals += 1
            
            # Direction: positive si majorité de signaux positifs (>= 2 sur 5)
            # Neutre (pas négatif!) si tendance mixte
            if trend_signals >= 3:
                direction_factor = 1.0  # Tendance clairement haussière
            elif trend_signals >= 2:
                direction_factor = 0.5  # Tendance mixte mais pas alarmante
            else:
                direction_factor = -0.3  # Seulement légèrement négatif, pas panique
            
            # Volatilité brute (toujours positive)
            volatility_raw = (atr_percent + volatility_std) / 2.0
            
            # volatility_directional: favorable si tendance intacte, défavorable sinon
            # Mais JAMAIS aussi négatif que l'ancien calcul (qui multipliait par -1)
            volatility_directional = volatility_raw * direction_factor

            # Features DIRECTIONNELLES piochées dans le schéma 78 (indices fixes) pour
            # que le P_exit sache si la volatilité va dans le BON sens (tendance/momentum
            # haussier -> continuer) ou est CHAOTIQUE (sortir). Bornées à 0.0 si le vecteur
            # marché est plus court (sécurité si schéma réduit).
            def _mf(idx):
                return float(market_features[idx]) if len(market_features) > idx else 0.0
            exit_short_tf_alignment = _mf(76)       # short_tf_alignment
            exit_multi_tf_trend_alignment = _mf(54)  # multi_tf_trend_alignment
            exit_ema20_breakout_15m = _mf(68)        # ema20_breakout_15m
            exit_momentum_accel_5m = _mf(73)         # momentum_accel_5m
            exit_consecutive_green_5m = _mf(75)      # consecutive_green_5m

            # === VOLUME PROFILE ===
            # Le volume précède le prix : accumulation = continuer, distribution = sortir
            closes = np.array([float(k['close']) for k in klines], dtype=np.float64)
            opens = np.array([float(k['open']) for k in klines], dtype=np.float64)
            volumes = np.array([float(k.get('volume', 0.0) or 0.0) for k in klines], dtype=np.float64)

            # 1. volume_trend_5b: Volume récent (5 bougies) vs moyenne (20 bougies)
            #    >1 = accumulation récente, <1 = distribution/calme
            if len(volumes) >= 20:
                avg_vol_20 = np.mean(volumes[-20:])
                avg_vol_5 = np.mean(volumes[-5:]) if len(volumes) >= 5 else avg_vol_20
                volume_trend_5b = avg_vol_5 / max(avg_vol_20, 1e-9)
            else:
                volume_trend_5b = 1.0

            # 2. buy_volume_ratio: % du volume sur bougies vertes (close > open)
            #    >50% = pression acheteuse dominante
            if len(volumes) >= 10 and len(closes) >= 10 and len(opens) >= 10:
                recent_closes = closes[-10:]
                recent_opens = opens[-10:]
                recent_vols = volumes[-10:]
                green_mask = recent_closes > recent_opens
                total_vol = np.sum(recent_vols)
                buy_vol = np.sum(recent_vols[green_mask]) if np.any(green_mask) else 0.0
                buy_volume_ratio = (buy_vol / max(total_vol, 1e-9)) * 100.0
            else:
                buy_volume_ratio = 50.0

            # 3. volume_price_confirm: Volume ET prix montent ensemble ?
            #    1 = tendance confirmée (hausse prix + hausse volume), 0 = divergence
            if len(closes) >= 5 and len(volumes) >= 5:
                price_up = closes[-1] > closes[-5]
                vol_up = np.mean(volumes[-3:]) > np.mean(volumes[-6:-3]) if len(volumes) >= 6 else True
                volume_price_confirm = 1.0 if (price_up and vol_up) else 0.0
            else:
                volume_price_confirm = 0.5

            # === NIVEAUX DYNAMIQUES (structure de prix) ===
            # Position dans la structure: proche résistance = risque blocage, proche support = filet
            if len(closes) >= 20:
                highs = np.array([float(k['high']) for k in klines[-20:]], dtype=np.float64)
                lows = np.array([float(k['low']) for k in klines[-20:]], dtype=np.float64)
                recent_high = np.max(highs)
                recent_low = np.min(lows)
                range_size = recent_high - recent_low

                # 1. price_in_range_pct: Position dans le range (0=bas, 100=haut)
                if range_size > 0:
                    price_in_range_pct = ((current_price - recent_low) / range_size) * 100.0
                else:
                    price_in_range_pct = 50.0

                # 2. dist_to_recent_high_pct: Distance au plus haut (négatif = en dessous)
                dist_to_recent_high_pct = ((current_price - recent_high) / max(recent_high, 1e-9)) * 100.0

                # 3. dist_to_recent_low_pct: Distance au plus bas (positif = au dessus)
                dist_to_recent_low_pct = ((current_price - recent_low) / max(recent_low, 1e-9)) * 100.0

                # 4. breakout_strength: Force du breakout si au-dessus du range
                #    0 si dans le range, sinon % au-dessus du high
                if current_price > recent_high:
                    breakout_strength = ((current_price - recent_high) / max(recent_high, 1e-9)) * 100.0
                else:
                    breakout_strength = 0.0
            else:
                price_in_range_pct = 50.0
                dist_to_recent_high_pct = 0.0
                dist_to_recent_low_pct = 0.0
                breakout_strength = 0.0

            # === FEATURES DIRECTIONNELLES DEPUIS ENTRÉE (amélioration sortie v3) ===
            # Ces features donnent du contexte sur l'évolution DEPUIS l'entrée, pas juste l'état actuel
            
            # 1. pnl_trend_3b: Tendance du PnL sur les 3 dernières bougies
            #    +1 = PnL monte (position s'améliore), -1 = PnL descend (position se dégrade)
            if len(closes) >= 4:
                pnl_3b_ago = ((closes[-4] - buy_price) / max(buy_price, 1e-9)) * 100.0
                pnl_now = gross_pnl_pct
                if pnl_now > pnl_3b_ago + 0.1:
                    pnl_trend_3b = 1.0  # PnL monte
                elif pnl_now < pnl_3b_ago - 0.1:
                    pnl_trend_3b = -1.0  # PnL descend
                else:
                    pnl_trend_3b = 0.0  # Stable
            else:
                pnl_trend_3b = 0.0
            
            # 2. price_vs_entry_ema20: Prix actuel vs EMA20 au moment de l'évaluation
            #    >0 = prix au-dessus de l'EMA20 (tendance favorable)
            #    <0 = prix en dessous (tendance défavorable)
            ema20_current = np.mean(closes[-20:]) if len(closes) >= 20 else closes[-1]
            price_vs_entry_ema20 = ((current_price - ema20_current) / max(ema20_current, 1e-9)) * 100.0
            
            # 3. momentum_since_entry: Momentum cumulé depuis l'entrée
            #    Basé sur le nombre de bougies haussières vs baissières depuis l'entrée
            #    Simplifié: on utilise la durée pour estimer le nombre de bougies (15min)
            candles_since_entry = max(1, int(duration_minutes / 15))
            if len(closes) > candles_since_entry:
                entry_idx = max(0, len(closes) - candles_since_entry - 1)
                closes_since = closes[entry_idx:]
                opens_since = opens[entry_idx:] if len(opens) > entry_idx else opens
                if len(closes_since) >= 2 and len(opens_since) >= 2:
                    green_count = sum(1 for c, o in zip(closes_since, opens_since) if c > o)
                    red_count = len(closes_since) - green_count
                    momentum_since_entry = (green_count - red_count) / max(len(closes_since), 1) * 100.0
                else:
                    momentum_since_entry = 0.0
            else:
                momentum_since_entry = 0.0

            bot_features = self._normalise_bot_context(bot_context, hour_of_day)

            return np.array([
                float(entry_p_win), float(continuation_score), gross_pnl_pct, net_pnl_pct,
                duration_minutes, fee_rate * 10000.0, dist_to_stop_pct, dist_to_target_pct,
                rsi_14, ema9_slope, ema20_slope, ema_cross_diff,
                volatility_directional, volume_ratio, candle_body_pct, candle_wick_top,
                candle_wick_bottom, price_change_3b, price_change_5b,
                hour_of_day, btc_momentum_3b,
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
                bot_features['technical_confidence_edge'],
                # Features directionnelles (fin de schéma, compat champion)
                exit_short_tf_alignment, exit_multi_tf_trend_alignment,
                exit_ema20_breakout_15m, exit_momentum_accel_5m,
                exit_consecutive_green_5m,
                # === VOLUME PROFILE ===
                volume_trend_5b,
                buy_volume_ratio,
                volume_price_confirm,
                # === NIVEAUX DYNAMIQUES ===
                price_in_range_pct,
                dist_to_recent_high_pct,
                dist_to_recent_low_pct,
                breakout_strength,
                # === FEATURES DIRECTIONNELLES DEPUIS ENTRÉE (amélioration sortie v3) ===
                pnl_trend_3b,
                price_vs_entry_ema20,
                momentum_since_entry,
            ], dtype=np.float64)

        except Exception as e:
            self.logger.error(f"Erreur extraction features ML sortie: {e}")
            return None

    def train_exit_model(self, X: np.ndarray, y: np.ndarray, timestamps: Optional[np.ndarray] = None, n_estimators: int = 150, max_depth: int = 6, min_samples_split: int = 10, criterion: str = 'gini', use_lightgbm: bool = True) -> bool:
        """Train P_continue with a chronological holdout and calibrated probabilities."""
        if not SKLEARN_AVAILABLE or len(X) < 30:
            self.logger.warning("Données insuffisantes pour entraîner le modèle ML de sortie.")
            return False
        try:
            from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score

            X_arr = np.asarray(X, dtype=np.float64)
            y_arr = np.asarray(y, dtype=np.int64)
            if timestamps is not None and len(timestamps) == len(X_arr):
                order = np.argsort(np.asarray(timestamps, dtype=np.float64), kind='stable')
                X_arr = X_arr[order]
                y_arr = y_arr[order]

            X_train, X_test, y_train, y_test, _, _ = self._temporal_holdout_split(X_arr, y_arr)
            if len(np.unique(y_train)) < 2:
                self.logger.warning("P_exit temporel invalide: une seule classe en train.")
                return False

            self.exit_scaler = StandardScaler()
            X_train_s = self.exit_scaler.fit_transform(X_train)
            X_test_s = self.exit_scaler.transform(X_test)

            if use_lightgbm and LIGHTGBM_AVAILABLE:
                self.exit_model = lgb.LGBMClassifier(
                    n_estimators=n_estimators,
                    max_depth=max_depth if max_depth else -1,
                    min_child_samples=min_samples_split,
                    learning_rate=0.05,
                    is_unbalance=True,
                    random_state=43,
                    n_jobs=-1,
                    verbose=-1
                )
            else:
                cw_env = os.getenv('ML_EXIT_CLASS_WEIGHT', 'balanced_subsample').strip().lower()
                class_weight = None if cw_env in ('none', '', 'off') else cw_env
                self.exit_model = RandomForestClassifier(
                    n_estimators=n_estimators,
                    max_depth=max_depth,
                    min_samples_split=min_samples_split,
                    criterion=criterion,
                    class_weight=class_weight,
                    random_state=43,
                    n_jobs=-1
                )

            self.exit_model.fit(X_train_s, y_train)
            raw_probs = self.exit_model.predict_proba(X_test_s)[:, 1]
            self.exit_calibrator = self._fit_isotonic_calibrator(raw_probs, y_test)
            calibrated = np.array([self._apply_calibrator(self.exit_calibrator, p) for p in raw_probs])
            y_pred = (calibrated >= 0.5).astype(int)
            brier = float(np.mean((calibrated - y_test) ** 2))

            exit_metrics = {
                'exit_validation_type': 'temporal_holdout',
                'exit_test_accuracy': round(float(accuracy_score(y_test, y_pred) * 100), 1),
                'exit_test_precision': round(float(precision_score(y_test, y_pred, zero_division=0) * 100), 1),
                'exit_test_recall': round(float(recall_score(y_test, y_pred, zero_division=0) * 100), 1),
                'exit_test_f1': round(float(f1_score(y_test, y_pred, zero_division=0) * 100), 1),
                'exit_test_brier': round(brier, 5),
                'exit_probability_calibrated': bool(self.exit_calibrator is not None),
                'exit_samples': int(len(X_arr)),
            }
            self.model_metadata = dict(getattr(self, 'model_metadata', {}) or {})
            self.model_metadata.update(exit_metrics)

            self.exit_scaler = StandardScaler()
            X_all = self.exit_scaler.fit_transform(X_arr)
            self.exit_model.fit(X_all, y_arr)
            self.is_exit_trained = True
            self.save_model()
            return True
        except Exception as e:
            self.logger.error(f"Erreur entraînement ML sortie: {e}")
            return False

    def train_sizing_model(self, X: np.ndarray, y: np.ndarray, n_estimators: int = 120, max_depth: int = 6, min_samples_split: int = 10, use_lightgbm: bool = True) -> bool:
        """Entraîne le modèle ML de facteur de taille de position avec LightGBM ou RandomForest."""
        if not SKLEARN_AVAILABLE:
            return False
        if len(X) < 30:
            self.logger.warning("Données insuffisantes pour entraîner le modèle ML de sizing.")
            return False
        try:
            self.sizing_scaler = StandardScaler()
            X_scaled = self.sizing_scaler.fit_transform(X)
            
            if use_lightgbm and LIGHTGBM_AVAILABLE:
                self.sizing_model = lgb.LGBMRegressor(
                    n_estimators=n_estimators,
                    max_depth=max_depth if max_depth else -1,
                    min_child_samples=min_samples_split,
                    learning_rate=0.05,
                    random_state=44,
                    n_jobs=-1,
                    verbose=-1
                )
            else:
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

    def train_target_model(self, X: np.ndarray, y: np.ndarray, n_estimators: int = 120, max_depth: int = 8, min_samples_split: int = 10, use_lightgbm: bool = True) -> bool:
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
            
            if use_lightgbm and LIGHTGBM_AVAILABLE:
                self.target_model = lgb.LGBMRegressor(
                    n_estimators=n_estimators,
                    max_depth=max_depth if max_depth else -1,
                    min_child_samples=min_samples_split,
                    learning_rate=0.05,
                    random_state=45,
                    n_jobs=-1,
                    verbose=-1
                )
            else:
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
            raw_continue = float(probs[1]) if len(probs) > 1 else 0.5
            calibrated_continue = self._apply_calibrator(self.exit_calibrator, raw_continue)
            p_continue = max(0.0, min(1.0, calibrated_continue)) * 100.0

            buy_price = float(position_data.get('entry_price') or position_data.get('buy_price') or position_data.get('price') or position_data.get('avg_entry_price') or current_price)
            fee_rate = float(position_data.get('fee_rate', float(os.getenv('TRADING_FEE_PERCENT', '0.4')) / 100.0))
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
            raw_prob = float(probs[1]) if len(probs) > 1 else 0.5
            calibrated_prob = self._apply_calibrator(self.probability_calibrator, raw_prob)
            win_prob = max(0.0, min(1.0, calibrated_prob)) * 100.0
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
            model_contract = self._model_contract()
            self.model_metadata = {
                **dict(getattr(self, 'model_metadata', {}) or {}),
                **model_contract,
            }
            joblib.dump({
                'model_contract': model_contract,
                'model': self.model,
                'scaler': self.scaler,
                'probability_calibrator': self.probability_calibrator,
                'edge_model': self.edge_model,
                'edge_scaler': self.edge_scaler,
                'exit_model': self.exit_model,
                'exit_scaler': self.exit_scaler,
                'exit_calibrator': self.exit_calibrator,
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
            if not self._validate_loaded_contract(data):
                self.is_trained = False
                return False
            self.model = data.get('model')
            self.scaler = data.get('scaler')
            self.probability_calibrator = data.get('probability_calibrator')
            self.edge_model = data.get('edge_model')
            self.edge_scaler = data.get('edge_scaler')
            self.exit_model = data.get('exit_model')
            self.exit_scaler = data.get('exit_scaler')
            self.exit_calibrator = data.get('exit_calibrator')
            self.sizing_model = data.get('sizing_model')
            self.sizing_scaler = data.get('sizing_scaler')
            self.target_model = data.get('target_model')
            self.target_scaler = data.get('target_scaler')
            if self.model is not None and hasattr(self.model, 'n_jobs'):
                self.model.n_jobs = 1
            if self.edge_model is not None and hasattr(self.edge_model, 'n_jobs'):
                self.edge_model.n_jobs = 1
            if self.exit_model is not None and hasattr(self.exit_model, 'n_jobs'):
                self.exit_model.n_jobs = 1
            if self.sizing_model is not None and hasattr(self.sizing_model, 'n_jobs'):
                self.sizing_model.n_jobs = 1
            if self.target_model is not None and hasattr(self.target_model, 'n_jobs'):
                self.target_model.n_jobs = 1
            self.is_trained = self.model is not None
            self.is_edge_trained = self.edge_model is not None
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
