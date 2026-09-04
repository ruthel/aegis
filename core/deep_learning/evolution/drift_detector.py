"""
Détection de Drift de Distribution
==================================

Détecte quand la distribution des données change significativement,
indiquant que le modèle doit s'adapter.

Méthodes:
- Page-Hinkley Test
- ADWIN (Adaptive Windowing)
- KL Divergence
- Performance-based drift detection
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from collections import deque
from scipy import stats
import logging

logger = logging.getLogger(__name__)


class DriftDetector:
    """
    Détecteur de drift multi-méthode.
    
    Combine plusieurs méthodes pour une détection robuste:
    - Drift de features (distribution des inputs)
    - Drift de performance (accuracy/win rate en déclin)
    - Drift conceptuel (relation input-output change)
    """
    
    def __init__(
        self,
        window_size: int = 1000,
        drift_threshold: float = 0.05,
        warning_threshold: float = 0.03,
        min_samples: int = 100
    ):
        """
        Args:
            window_size: Taille de la fenêtre de référence
            drift_threshold: Seuil pour déclarer un drift
            warning_threshold: Seuil pour warning (pré-drift)
            min_samples: Minimum de samples avant détection
        """
        self.window_size = window_size
        self.drift_threshold = drift_threshold
        self.warning_threshold = warning_threshold
        self.min_samples = min_samples
        
        # Fenêtres de référence et courante
        self.reference_window: deque = deque(maxlen=window_size)
        self.current_window: deque = deque(maxlen=window_size)
        
        # Statistiques de référence
        self.reference_stats: Optional[Dict] = None
        
        # Performance tracking
        self.performance_history: deque = deque(maxlen=window_size * 2)
        
        # État
        self.drift_detected = False
        self.warning_detected = False
        self.drift_count = 0
        self.samples_since_reset = 0
    
    def add_sample(
        self,
        features: np.ndarray,
        prediction: float,
        actual: float,
        performance_metric: Optional[float] = None
    ):
        """
        Ajoute un échantillon pour la détection de drift.
        
        Args:
            features: Vecteur de features
            prediction: Prédiction du modèle
            actual: Valeur réelle
            performance_metric: Métrique de performance optionnelle
        """
        sample = {
            'features': features,
            'prediction': prediction,
            'actual': actual,
            'error': abs(prediction - actual)
        }
        
        self.current_window.append(sample)
        
        if performance_metric is not None:
            self.performance_history.append(performance_metric)
        
        self.samples_since_reset += 1
        
        # Mise à jour de la référence si première fois
        if self.reference_stats is None and len(self.current_window) >= self.min_samples:
            self._update_reference()
    
    def check_drift(self) -> Dict[str, any]:
        """
        Vérifie s'il y a un drift.
        
        Returns:
            Dict avec:
                - drift_detected: bool
                - warning_detected: bool
                - drift_type: 'feature', 'performance', 'concept', ou None
                - drift_score: float
                - details: Dict avec métriques détaillées
        """
        result = {
            'drift_detected': False,
            'warning_detected': False,
            'drift_type': None,
            'drift_score': 0.0,
            'details': {}
        }
        
        if len(self.current_window) < self.min_samples:
            return result
        
        if self.reference_stats is None:
            self._update_reference()
            return result
        
        # === FEATURE DRIFT (KL Divergence) ===
        feature_drift = self._check_feature_drift()
        result['details']['feature_drift'] = feature_drift
        
        # === PERFORMANCE DRIFT ===
        perf_drift = self._check_performance_drift()
        result['details']['performance_drift'] = perf_drift
        
        # === CONCEPT DRIFT (prediction error distribution) ===
        concept_drift = self._check_concept_drift()
        result['details']['concept_drift'] = concept_drift
        
        # Déterminer le type de drift le plus sévère
        max_drift = max(feature_drift, perf_drift, concept_drift)
        result['drift_score'] = max_drift
        
        if max_drift >= self.drift_threshold:
            result['drift_detected'] = True
            self.drift_detected = True
            self.drift_count += 1
            
            # Identifier le type
            if feature_drift >= self.drift_threshold:
                result['drift_type'] = 'feature'
            elif perf_drift >= self.drift_threshold:
                result['drift_type'] = 'performance'
            else:
                result['drift_type'] = 'concept'
            
            logger.warning(f"Drift detected! Type: {result['drift_type']}, Score: {max_drift:.4f}")
            
        elif max_drift >= self.warning_threshold:
            result['warning_detected'] = True
            self.warning_detected = True
            logger.info(f"Drift warning! Score: {max_drift:.4f}")
        
        return result
    
    def _check_feature_drift(self) -> float:
        """
        Détecte le drift dans la distribution des features.
        Utilise la divergence KL approximée.
        """
        if self.reference_stats is None:
            return 0.0
        
        # Extraire les features actuelles
        current_features = np.array([s['features'] for s in self.current_window])
        
        # Calculer les stats actuelles
        current_mean = np.mean(current_features, axis=0)
        current_std = np.std(current_features, axis=0) + 1e-8
        
        ref_mean = self.reference_stats['feature_mean']
        ref_std = self.reference_stats['feature_std']
        
        # KL divergence approximée pour gaussiennes
        # KL(P||Q) ≈ log(σ_q/σ_p) + (σ_p² + (μ_p - μ_q)²)/(2σ_q²) - 1/2
        kl_div = (
            np.log(ref_std / current_std) +
            (current_std**2 + (current_mean - ref_mean)**2) / (2 * ref_std**2) -
            0.5
        )
        
        # Moyenne sur toutes les features
        avg_kl = np.mean(np.abs(kl_div))
        
        # Normaliser (KL peut être grand)
        normalized_score = np.tanh(avg_kl / 10)
        
        return float(normalized_score)
    
    def _check_performance_drift(self) -> float:
        """
        Détecte une dégradation de performance.
        Compare la performance récente vs historique.
        """
        if len(self.performance_history) < self.min_samples * 2:
            return 0.0
        
        perf = list(self.performance_history)
        half = len(perf) // 2
        
        old_perf = np.mean(perf[:half])
        new_perf = np.mean(perf[half:])
        
        # Dégradation relative
        if old_perf > 0:
            degradation = (old_perf - new_perf) / old_perf
        else:
            degradation = 0.0
        
        # Positif = dégradation
        return float(max(0, degradation))
    
    def _check_concept_drift(self) -> float:
        """
        Détecte un changement dans la relation input-output.
        Compare la distribution des erreurs.
        """
        if self.reference_stats is None:
            return 0.0
        
        # Erreurs actuelles
        current_errors = np.array([s['error'] for s in self.current_window])
        current_error_mean = np.mean(current_errors)
        current_error_std = np.std(current_errors) + 1e-8
        
        ref_error_mean = self.reference_stats['error_mean']
        ref_error_std = self.reference_stats['error_std']
        
        # Test de Kolmogorov-Smirnov simplifié via la différence de distributions
        mean_shift = abs(current_error_mean - ref_error_mean) / (ref_error_std + 1e-8)
        std_shift = abs(current_error_std - ref_error_std) / (ref_error_std + 1e-8)
        
        # Combine les deux métriques
        concept_score = (mean_shift + std_shift) / 2
        
        # Normaliser
        normalized = np.tanh(concept_score)
        
        return float(normalized)
    
    def _update_reference(self):
        """Met à jour les statistiques de référence"""
        if len(self.current_window) < self.min_samples:
            return
        
        samples = list(self.current_window)
        
        features = np.array([s['features'] for s in samples])
        errors = np.array([s['error'] for s in samples])
        
        self.reference_stats = {
            'feature_mean': np.mean(features, axis=0),
            'feature_std': np.std(features, axis=0) + 1e-8,
            'error_mean': np.mean(errors),
            'error_std': np.std(errors) + 1e-8,
            'n_samples': len(samples)
        }
        
        # Transférer vers la fenêtre de référence
        self.reference_window.clear()
        self.reference_window.extend(samples)
        
        logger.info(f"Reference stats updated with {len(samples)} samples")
    
    def reset(self, keep_reference: bool = False):
        """
        Réinitialise le détecteur après adaptation au drift.
        
        Args:
            keep_reference: Garder les stats de référence actuelles
        """
        if not keep_reference:
            self._update_reference()
        
        self.current_window.clear()
        self.drift_detected = False
        self.warning_detected = False
        self.samples_since_reset = 0
        
        logger.info("Drift detector reset")
    
    def get_adaptation_rate(self) -> float:
        """
        Suggère un taux d'adaptation basé sur le niveau de drift.
        
        Plus le drift est important, plus le taux est élevé.
        """
        result = self.check_drift()
        drift_score = result['drift_score']
        
        # Mapping: drift_score -> learning_rate multiplier
        if drift_score < self.warning_threshold:
            return 0.1  # Apprentissage lent, peu de changement
        elif drift_score < self.drift_threshold:
            return 0.5  # Apprentissage modéré
        else:
            return 1.0  # Apprentissage rapide, adaptation urgente
    
    def get_statistics(self) -> Dict:
        """Retourne les statistiques du détecteur"""
        return {
            'reference_samples': len(self.reference_window),
            'current_samples': len(self.current_window),
            'samples_since_reset': self.samples_since_reset,
            'drift_count': self.drift_count,
            'drift_detected': self.drift_detected,
            'warning_detected': self.warning_detected,
            'last_check': self.check_drift() if len(self.current_window) >= self.min_samples else None
        }


class PageHinkleyTest:
    """
    Page-Hinkley Test pour la détection de changement de moyenne.
    
    Détecte quand la moyenne d'une série change de manière significative.
    """
    
    def __init__(
        self,
        delta: float = 0.005,
        threshold: float = 50.0,
        alpha: float = 0.9999
    ):
        """
        Args:
            delta: Magnitude minimale de changement à détecter
            threshold: Seuil pour déclencher l'alarme
            alpha: Facteur de forgetting (proche de 1 = mémoire longue)
        """
        self.delta = delta
        self.threshold = threshold
        self.alpha = alpha
        
        self.sum = 0.0
        self.mean = 0.0
        self.n = 0
        self.minimum = float('inf')
        self.maximum = float('-inf')
    
    def add(self, value: float) -> bool:
        """
        Ajoute une valeur et vérifie le drift.
        
        Returns:
            True si drift détecté
        """
        self.n += 1
        
        # Mise à jour de la moyenne avec forgetting
        self.mean = self.alpha * self.mean + (1 - self.alpha) * value
        
        # Cumulative sum pour détecter augmentation
        self.sum += value - self.mean - self.delta
        self.minimum = min(self.minimum, self.sum)
        
        # Test
        ph_value = self.sum - self.minimum
        
        if ph_value > self.threshold:
            return True
        
        return False
    
    def reset(self):
        """Réinitialise le test"""
        self.sum = 0.0
        self.minimum = float('inf')
        self.maximum = float('-inf')
