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
import json
import time
import logging
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Tuple

try:
    import joblib
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False


class MLEngine:
    """Moteur de Machine Learning dédié pour la prédiction de probabilité de gain"""

    def __init__(self, model_dir: str = 'data'):
        self.logger = logging.getLogger(__name__)
        self.model_dir = model_dir
        self.model_path = os.path.join(model_dir, 'aegis_ml_model.joblib')
        self.metadata_path = os.path.join(model_dir, 'aegis_ml_metadata.json')
        
        self.model = None
        self.scaler = None
        self.feature_names = [
            'rsi_14', 'ema9_slope', 'ema20_slope', 'ema_cross_diff',
            'atr_percent', 'volume_ratio', 'candle_body_pct', 'candle_wick_top',
            'candle_wick_bottom', 'dist_to_support_pct', 'dist_to_resistance_pct',
            'volume_spike', 'price_change_3b', 'price_change_5b', 'price_change_10b',
            'volatility_std', 'hour_of_day', 'day_of_week'
        ]
        
        self.is_trained = False
        self.load_model()

    def extract_features_from_klines(self, klines: List[Dict], current_price: Optional[float] = None) -> Optional[np.ndarray]:
        """Extrait un vecteur de 18 caractéristiques techniques à partir des klines (15m)"""
        if not klines or len(klines) < 20:
            return None

        try:
            closes = np.array([float(k['close']) for k in klines], dtype=np.float64)
            opens = np.array([float(k['open']) for k in klines], dtype=np.float64)
            highs = np.array([float(k['high']) for k in klines], dtype=np.float64)
            lows = np.array([float(k['low']) for k in klines], dtype=np.float64)
            volumes = np.array([float(k['volume']) for k in klines], dtype=np.float64)
            
            px = current_price if current_price else closes[-1]

            # 1. RSI (14 périodes)
            deltas = np.diff(closes)
            gains = np.where(deltas > 0, deltas, 0)
            losses = np.where(deltas < 0, -deltas, 0)
            avg_gain = np.mean(gains[-14:]) if len(gains) >= 14 else 0.001
            avg_loss = np.mean(losses[-14:]) if len(losses) >= 14 else 0.001
            rs = avg_gain / (avg_loss + 1e-9)
            rsi = 100.0 - (100.0 / (1.0 + rs))

            # 2. Pente des EMA (9 & 20)
            ema9 = np.mean(closes[-9:])
            ema9_prev = np.mean(closes[-12:-3]) if len(closes) >= 12 else ema9
            ema9_slope = (ema9 - ema9_prev) / (ema9_prev + 1e-9) * 100.0

            ema20 = np.mean(closes[-20:])
            ema20_prev = np.mean(closes[-23:-3]) if len(closes) >= 23 else ema20
            ema20_slope = (ema20 - ema20_prev) / (ema20_prev + 1e-9) * 100.0

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

            features = np.array([
                rsi, ema9_slope, ema20_slope, ema_cross_diff,
                atr_percent, volume_ratio, candle_body_pct, candle_wick_top,
                candle_wick_bottom, dist_to_support_pct, dist_to_resistance_pct,
                volume_spike, price_change_3b, price_change_5b, price_change_10b,
                volatility_std, hour_of_day, day_of_week
            ], dtype=np.float64)

            return features

        except Exception as e:
            self.logger.error(f"Erreur d'extraction des caractéristiques ML: {e}")
            return None

    def train_model(self, X: np.ndarray, y: np.ndarray) -> bool:
        """Entraîne le classifieur Random Forest sur la matrice de données X et les résultats y (0/1)"""
        if not SKLEARN_AVAILABLE:
            self.logger.warning("scikit-learn n'est pas disponible pour l'entraînement ML.")
            return False

        if len(X) < 30:
            self.logger.warning("Données insuffisantes pour l'entraînement ML (minimum 30 exemples requis).")
            return False

        try:
            self.scaler = StandardScaler()
            X_scaled = self.scaler.fit_transform(X)

            self.model = RandomForestClassifier(
                n_estimators=100,
                max_depth=6,
                min_samples_split=5,
                random_state=42,
                n_jobs=-1
            )
            self.model.fit(X_scaled, y)
            self.is_trained = True

            self.save_model()
            return True

        except Exception as e:
            self.logger.error(f"Erreur lors de l'entraînement ML: {e}")
            return False

    def predict_win_probability(self, klines: List[Dict], current_price: Optional[float] = None) -> float:
        """Calcule la probabilité P_win [0.0 - 100.0]% en < 2ms"""
        if not self.is_trained or self.model is None or not SKLEARN_AVAILABLE:
            return 50.0  # Valeur neutre par défaut si modèle non encore entraîné

        features = self.extract_features_from_klines(klines, current_price)
        if features is None:
            return 50.0

        try:
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
            joblib.dump({'model': self.model, 'scaler': self.scaler}, self.model_path)

            importance = {}
            if hasattr(self.model, 'feature_importances_'):
                for name, imp in zip(self.feature_names, self.model.feature_importances_):
                    importance[name] = round(float(imp), 4)

            metadata = {
                'trained_at': datetime.now().isoformat(),
                'feature_importance': sorted(importance.items(), key=lambda x: x[1], reverse=True),
                'n_features': len(self.feature_names)
            }
            with open(self.metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2)

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
            self.is_trained = self.model is not None
            return self.is_trained
        except Exception as e:
            self.logger.error(f"Erreur de chargement du modèle ML: {e}")
            self.is_trained = False
            return False

    def get_feature_importance(self) -> List[Tuple[str, float]]:
        """Retourne l'importance des variables sous forme d'une liste (nom, importance)"""
        if not os.path.exists(self.metadata_path):
            return []
        try:
            with open(self.metadata_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
                return meta.get('feature_importance', [])
        except:
            return []
