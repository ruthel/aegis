"""
Shadow Predictor pour le modèle Deep Learning
=============================================

Exécute les prédictions en temps réel en mode shadow (observation).
Les prédictions sont logguées mais n'influencent pas les décisions de trading.
"""

import torch
import numpy as np
from typing import Dict, Optional, Tuple, List, Any
from pathlib import Path
from datetime import datetime
import logging
import json

from ..models.lstm_attention import LSTMAttentionModel
from ..data.feature_engineer import FeatureEngineer
from ..data.normalizer import AdaptiveNormalizer
from ..data.sequence_builder import SequenceBuilder
from ..config import DLConfig

logger = logging.getLogger(__name__)


class ShadowPredictor:
    """
    Prédicteur en mode shadow pour le Deep Learning.
    
    Fonctionnalités:
    - Prédictions temps réel sans impact sur le trading
    - Logging de toutes les prédictions
    - Comparaison avec les décisions RF
    - Calcul de confiance et incertitude
    """
    
    def __init__(
        self,
        model_path: Optional[Path] = None,
        config: Optional[DLConfig] = None,
        device: Optional[str] = None
    ):
        """
        Args:
            model_path: Chemin vers le modèle sauvegardé
            config: Configuration DL
            device: 'cuda' ou 'cpu'
        """
        self.config = config or DLConfig()
        self.device = device or ('cuda' if torch.cuda.is_available() else 'cpu')
        
        # Composants
        self.model: Optional[LSTMAttentionModel] = None
        self.feature_engineer = FeatureEngineer()
        self.normalizer: Optional[AdaptiveNormalizer] = None
        self.sequence_builder = SequenceBuilder(
            sequence_length=self.config.model.sequence_length
        )
        
        # État
        self.is_loaded = False
        self.prediction_count = 0
        
        # Buffer pour les features récentes
        self.feature_buffer: Dict[str, List[np.ndarray]] = {}
        self.buffer_size = self.config.model.sequence_length + 10
        
        # Historique des prédictions
        self.prediction_history: List[Dict] = []
        self.max_history = 1000
        
        # Charger le modèle si spécifié
        if model_path:
            self.load_model(model_path)
    
    def load_model(self, model_path: Path):
        """Charge le modèle et le normalizer"""
        model_path = Path(model_path)
        
        if not model_path.exists():
            logger.warning(f"Model not found at {model_path}")
            return False
        
        try:
            checkpoint = torch.load(model_path, map_location=self.device)
            
            # Créer le modèle
            self.model = LSTMAttentionModel(
                input_size=self.config.model.input_size,
                hidden_size=self.config.model.hidden_size,
                num_lstm_layers=self.config.model.num_lstm_layers,
                num_attention_heads=self.config.model.num_attention_heads,
                dropout=0.0,  # Pas de dropout en inférence
                bidirectional=self.config.model.bidirectional
            )
            
            self.model.load_state_dict(checkpoint['model_state_dict'])
            self.model.to(self.device)
            self.model.eval()
            
            # Charger le normalizer si disponible
            normalizer_path = model_path.parent / 'normalizer.json'
            if normalizer_path.exists():
                self.normalizer = AdaptiveNormalizer.load(normalizer_path)
            else:
                logger.warning("Normalizer not found, using default")
                self.normalizer = AdaptiveNormalizer(n_features=78)
            
            self.is_loaded = True
            logger.info(f"Model loaded from {model_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            return False
    
    def update_buffer(
        self,
        symbol: str,
        candle: Dict[str, float],
        btc_candle: Optional[Dict[str, float]] = None
    ):
        """
        Met à jour le buffer de features avec une nouvelle bougie.
        
        Args:
            symbol: Symbole de trading
            candle: Dict avec open, high, low, close, volume, timestamp
            btc_candle: Bougie BTC optionnelle pour corrélations
        """
        import pandas as pd
        
        if symbol not in self.feature_buffer:
            self.feature_buffer[symbol] = []
        
        # Construire un mini-DataFrame pour le calcul des features
        buffer = self.feature_buffer[symbol]
        buffer.append(candle)
        
        # Garder seulement buffer_size bougies
        if len(buffer) > self.buffer_size:
            buffer.pop(0)
        
        # Si assez de données, calculer les features
        if len(buffer) >= 50:  # Minimum pour indicateurs
            df = pd.DataFrame(buffer)
            
            # BTC data si disponible
            btc_df = None
            if btc_candle and 'BTCUSDT' in self.feature_buffer:
                btc_df = pd.DataFrame(self.feature_buffer['BTCUSDT'])
            
            # Calculer features
            result = self.feature_engineer.compute_all_features(df, btc_df)
            
            # Stocker les features normalisées
            if self.normalizer and self.normalizer._fitted:
                features = self.normalizer.transform(result.features)
            else:
                features = result.features
            
            # Remplacer le buffer par les features
            self.feature_buffer[f"{symbol}_features"] = features
    
    @torch.no_grad()
    def predict(
        self,
        symbol: str,
        current_state: Optional[Dict] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Fait une prédiction pour un symbole.
        
        Args:
            symbol: Symbole de trading
            current_state: État actuel optionnel (prix, position, etc.)
            
        Returns:
            Dict avec prédictions ou None si pas prêt
        """
        if not self.is_loaded:
            logger.warning("Model not loaded")
            return None
        
        features_key = f"{symbol}_features"
        if features_key not in self.feature_buffer:
            logger.debug(f"No features available for {symbol}")
            return None
        
        features = self.feature_buffer[features_key]
        
        if len(features) < self.config.model.sequence_length:
            logger.debug(f"Not enough features: {len(features)}/{self.config.model.sequence_length}")
            return None
        
        try:
            # Créer la séquence
            sequence, mask = self.sequence_builder.create_inference_sequence(features)
            
            # Convertir en tensors
            sequence_tensor = torch.tensor(sequence, dtype=torch.float32, device=self.device)
            mask_tensor = torch.tensor(mask, dtype=torch.float32, device=self.device)
            
            # Prédiction
            self.model.eval()
            outputs = self.model(sequence_tensor, mask_tensor)
            
            # Extraire les probabilités
            prediction = {
                'symbol': symbol,
                'timestamp': datetime.now().isoformat(),
                'win_probability': float(outputs['win_probability'].squeeze().cpu().numpy()),
                'continue_probability': float(outputs['continue_probability'].squeeze().cpu().numpy()),
                'optimal_sizing': float(outputs['optimal_sizing'].squeeze().cpu().numpy()),
                'current_state': current_state
            }
            
            # Calculer la confiance
            prediction['confidence'] = self._compute_confidence(prediction)
            
            # Générer le signal
            prediction['signal'] = self._generate_signal(prediction)
            
            # Ajouter à l'historique
            self._add_to_history(prediction)
            
            self.prediction_count += 1
            
            return prediction
            
        except Exception as e:
            logger.error(f"Prediction error: {e}")
            return None
    
    def _compute_confidence(self, prediction: Dict) -> float:
        """
        Calcule un score de confiance basé sur la clarté de la prédiction.
        
        Plus la probabilité est proche de 0 ou 1, plus la confiance est haute.
        """
        win_prob = prediction['win_probability']
        
        # Distance à 0.5 (incertitude maximale)
        distance_to_uncertainty = abs(win_prob - 0.5) * 2
        
        # Confiance = distance à 0.5 normalisée
        confidence = distance_to_uncertainty
        
        return float(confidence)
    
    def _generate_signal(self, prediction: Dict) -> str:
        """
        Génère un signal de trading basé sur les prédictions.
        
        Returns:
            'strong_buy', 'buy', 'hold', 'sell', 'strong_sell'
        """
        win_prob = prediction['win_probability']
        confidence = prediction['confidence']
        
        high_conf = self.config.shadow.high_confidence
        min_conf = self.config.shadow.min_confidence
        
        if win_prob >= 0.8 and confidence >= high_conf:
            return 'strong_buy'
        elif win_prob >= 0.6 and confidence >= min_conf:
            return 'buy'
        elif win_prob <= 0.2 and confidence >= high_conf:
            return 'strong_sell'
        elif win_prob <= 0.4 and confidence >= min_conf:
            return 'sell'
        else:
            return 'hold'
    
    def _add_to_history(self, prediction: Dict):
        """Ajoute une prédiction à l'historique"""
        self.prediction_history.append(prediction)
        
        # Limiter la taille
        if len(self.prediction_history) > self.max_history:
            self.prediction_history.pop(0)
    
    def get_prediction_summary(self, n_recent: int = 100) -> Dict:
        """
        Résumé des prédictions récentes.
        """
        if not self.prediction_history:
            return {'count': 0}
        
        recent = self.prediction_history[-n_recent:]
        
        win_probs = [p['win_probability'] for p in recent]
        confidences = [p['confidence'] for p in recent]
        signals = [p['signal'] for p in recent]
        
        signal_counts = {}
        for s in signals:
            signal_counts[s] = signal_counts.get(s, 0) + 1
        
        return {
            'count': len(recent),
            'avg_win_prob': np.mean(win_probs),
            'std_win_prob': np.std(win_probs),
            'avg_confidence': np.mean(confidences),
            'signal_distribution': signal_counts,
            'buy_signals': signal_counts.get('buy', 0) + signal_counts.get('strong_buy', 0),
            'sell_signals': signal_counts.get('sell', 0) + signal_counts.get('strong_sell', 0),
            'total_predictions': self.prediction_count
        }
    
    def compare_with_rf(
        self,
        rf_prediction: Dict,
        dl_prediction: Dict
    ) -> Dict:
        """
        Compare une prédiction DL avec une prédiction RF.
        
        Args:
            rf_prediction: Prédiction du RandomForest
            dl_prediction: Prédiction du Deep Learning
            
        Returns:
            Dict avec analyse de la comparaison
        """
        rf_signal = rf_prediction.get('decision', 'hold')
        dl_signal = dl_prediction.get('signal', 'hold')
        
        # Mapper les signaux RF au format DL
        rf_signal_mapped = {
            'buy': 'buy',
            'sell': 'sell',
            'hold': 'hold',
            'strong_buy': 'strong_buy',
            'strong_sell': 'strong_sell'
        }.get(rf_signal, 'hold')
        
        # Accord/désaccord
        signals_agree = (
            (rf_signal_mapped in ['buy', 'strong_buy'] and dl_signal in ['buy', 'strong_buy']) or
            (rf_signal_mapped in ['sell', 'strong_sell'] and dl_signal in ['sell', 'strong_sell']) or
            (rf_signal_mapped == 'hold' and dl_signal == 'hold')
        )
        
        # Conflit (directions opposées)
        signals_conflict = (
            (rf_signal_mapped in ['buy', 'strong_buy'] and dl_signal in ['sell', 'strong_sell']) or
            (rf_signal_mapped in ['sell', 'strong_sell'] and dl_signal in ['buy', 'strong_buy'])
        )
        
        return {
            'rf_signal': rf_signal_mapped,
            'dl_signal': dl_signal,
            'dl_win_probability': dl_prediction.get('win_probability'),
            'dl_confidence': dl_prediction.get('confidence'),
            'signals_agree': signals_agree,
            'signals_conflict': signals_conflict,
            'timestamp': datetime.now().isoformat()
        }
    
    def reset_buffers(self, symbol: Optional[str] = None):
        """Réinitialise les buffers"""
        if symbol:
            self.feature_buffer.pop(symbol, None)
            self.feature_buffer.pop(f"{symbol}_features", None)
        else:
            self.feature_buffer.clear()
