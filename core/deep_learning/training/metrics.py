"""
Métriques pour évaluation du modèle Deep Learning
=================================================

Métriques spécifiques au trading:
- Win rate, Profit factor, Sharpe ratio
- Métriques de calibration
- Métriques par seuil de confiance
"""

import torch
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict


@dataclass
class MetricsResult:
    """Container pour les résultats de métriques"""
    metrics: Dict[str, float]
    confusion_matrix: Optional[np.ndarray] = None
    per_threshold: Optional[Dict[float, Dict[str, float]]] = None


class TradingMetrics:
    """
    Calcul des métriques spécifiques au trading.
    """
    
    def __init__(
        self,
        thresholds: List[float] = [0.5, 0.6, 0.7, 0.8],
        avg_win_pct: float = 0.01,   # 1% gain moyen
        avg_loss_pct: float = 0.005  # 0.5% perte moyenne
    ):
        """
        Args:
            thresholds: Seuils de confiance à évaluer
            avg_win_pct: Gain moyen par trade gagnant (pour Sharpe)
            avg_loss_pct: Perte moyenne par trade perdant
        """
        self.thresholds = thresholds
        self.avg_win_pct = avg_win_pct
        self.avg_loss_pct = avg_loss_pct
        
        # Accumulateurs
        self.reset()
    
    def reset(self):
        """Réinitialise les accumulateurs"""
        self.predictions = defaultdict(list)
        self.targets = defaultdict(list)
        self.n_samples = 0
    
    def update(
        self,
        predictions: Dict[str, torch.Tensor],
        targets: Dict[str, torch.Tensor]
    ):
        """
        Accumule les prédictions et labels pour calcul batch.
        
        Args:
            predictions: Dict de tensors de prédictions
            targets: Dict de tensors de labels
        """
        for key in predictions:
            pred = predictions[key].detach().cpu().numpy().flatten()
            self.predictions[key].extend(pred)
            
            if key in targets:
                tgt = targets[key].detach().cpu().numpy().flatten()
                self.targets[key].extend(tgt)
        
        self.n_samples += len(next(iter(predictions.values())))
    
    def compute(self) -> MetricsResult:
        """
        Calcule toutes les métriques.
        
        Returns:
            MetricsResult avec toutes les métriques
        """
        metrics = {}
        
        # === WIN PROBABILITY METRICS ===
        if 'win_probability' in self.predictions and 'win_probability' in self.targets:
            pred_win = np.array(self.predictions['win_probability'])
            target_win = np.array(self.targets['win_probability'])
            
            # Accuracy à différents seuils
            for thresh in self.thresholds:
                pred_binary = (pred_win >= thresh).astype(int)
                target_binary = (target_win >= 0.5).astype(int)
                
                accuracy = (pred_binary == target_binary).mean()
                metrics[f'accuracy_t{thresh}'] = accuracy
                
                # Win rate si on trade
                trades_taken = pred_binary == 1
                if trades_taken.sum() > 0:
                    win_rate = target_binary[trades_taken].mean()
                    metrics[f'win_rate_t{thresh}'] = win_rate
                    
                    # Nombre de trades
                    metrics[f'n_trades_t{thresh}'] = trades_taken.sum()
            
            # Métriques globales
            metrics['auc_roc'] = self._compute_auc(pred_win, target_win)
            metrics['brier_score'] = self._compute_brier(pred_win, target_win)
            metrics['calibration_error'] = self._compute_calibration_error(pred_win, target_win)
            
            # Confusion matrix pour threshold 0.5
            cm = self._compute_confusion_matrix(pred_win, target_win, 0.5)
            
            # Precision, Recall, F1
            precision, recall, f1 = self._compute_prf(cm)
            metrics['precision'] = precision
            metrics['recall'] = recall
            metrics['f1'] = f1
        
        # === CONTINUE PROBABILITY METRICS ===
        if 'continue_probability' in self.predictions and 'continue_probability' in self.targets:
            pred_cont = np.array(self.predictions['continue_probability'])
            target_cont = np.array(self.targets['continue_probability'])
            
            metrics['continue_mae'] = np.abs(pred_cont - target_cont).mean()
            metrics['continue_mse'] = ((pred_cont - target_cont) ** 2).mean()
        
        # === SIZING METRICS ===
        if 'optimal_sizing' in self.predictions and 'optimal_sizing' in self.targets:
            pred_size = np.array(self.predictions['optimal_sizing'])
            target_size = np.array(self.targets['optimal_sizing'])
            
            metrics['sizing_mae'] = np.abs(pred_size - target_size).mean()
            metrics['sizing_mse'] = ((pred_size - target_size) ** 2).mean()
            metrics['sizing_correlation'] = np.corrcoef(pred_size, target_size)[0, 1]
        
        # === TRADING SIMULATION METRICS ===
        if 'win_probability' in self.predictions:
            trading_metrics = self._simulate_trading(
                np.array(self.predictions['win_probability']),
                np.array(self.targets.get('win_probability', []))
            )
            metrics.update(trading_metrics)
        
        # Per-threshold metrics
        per_threshold = {}
        for thresh in self.thresholds:
            per_threshold[thresh] = {
                k.replace(f'_t{thresh}', ''): v 
                for k, v in metrics.items() 
                if f'_t{thresh}' in k
            }
        
        return MetricsResult(
            metrics=metrics,
            confusion_matrix=cm if 'win_probability' in self.predictions else None,
            per_threshold=per_threshold
        )
    
    def _compute_auc(
        self,
        predictions: np.ndarray,
        targets: np.ndarray
    ) -> float:
        """Calcule l'AUC-ROC"""
        # Tri par prédiction décroissante
        sorted_indices = np.argsort(predictions)[::-1]
        sorted_targets = targets[sorted_indices]
        
        # Calcul AUC par trapèzes
        n_pos = (targets >= 0.5).sum()
        n_neg = (targets < 0.5).sum()
        
        if n_pos == 0 or n_neg == 0:
            return 0.5
        
        tpr = np.cumsum(sorted_targets >= 0.5) / n_pos
        fpr = np.cumsum(sorted_targets < 0.5) / n_neg
        
        # Aire sous la courbe
        auc = np.trapz(tpr, fpr)
        
        return float(auc)
    
    def _compute_brier(
        self,
        predictions: np.ndarray,
        targets: np.ndarray
    ) -> float:
        """Brier Score (MSE des probabilités)"""
        binary_targets = (targets >= 0.5).astype(float)
        return float(((predictions - binary_targets) ** 2).mean())
    
    def _compute_calibration_error(
        self,
        predictions: np.ndarray,
        targets: np.ndarray,
        n_bins: int = 10
    ) -> float:
        """Expected Calibration Error"""
        bin_boundaries = np.linspace(0, 1, n_bins + 1)
        binary_targets = (targets >= 0.5).astype(float)
        
        ece = 0.0
        total_samples = len(predictions)
        
        for i in range(n_bins):
            in_bin = (predictions >= bin_boundaries[i]) & (predictions < bin_boundaries[i+1])
            n_in_bin = in_bin.sum()
            
            if n_in_bin > 0:
                avg_confidence = predictions[in_bin].mean()
                avg_accuracy = binary_targets[in_bin].mean()
                ece += (n_in_bin / total_samples) * abs(avg_confidence - avg_accuracy)
        
        return float(ece)
    
    def _compute_confusion_matrix(
        self,
        predictions: np.ndarray,
        targets: np.ndarray,
        threshold: float
    ) -> np.ndarray:
        """Calcule la matrice de confusion"""
        pred_binary = (predictions >= threshold).astype(int)
        target_binary = (targets >= 0.5).astype(int)
        
        # [[TN, FP], [FN, TP]]
        cm = np.zeros((2, 2), dtype=int)
        cm[0, 0] = ((pred_binary == 0) & (target_binary == 0)).sum()  # TN
        cm[0, 1] = ((pred_binary == 1) & (target_binary == 0)).sum()  # FP
        cm[1, 0] = ((pred_binary == 0) & (target_binary == 1)).sum()  # FN
        cm[1, 1] = ((pred_binary == 1) & (target_binary == 1)).sum()  # TP
        
        return cm
    
    def _compute_prf(
        self,
        cm: np.ndarray
    ) -> Tuple[float, float, float]:
        """Calcule Precision, Recall, F1"""
        tn, fp, fn, tp = cm[0, 0], cm[0, 1], cm[1, 0], cm[1, 1]
        
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        
        return precision, recall, f1
    
    def _simulate_trading(
        self,
        predictions: np.ndarray,
        targets: np.ndarray
    ) -> Dict[str, float]:
        """
        Simule le trading pour calculer les métriques financières.
        """
        if len(targets) == 0:
            return {}
        
        metrics = {}
        
        for thresh in self.thresholds:
            trades_taken = predictions >= thresh
            n_trades = trades_taken.sum()
            
            if n_trades == 0:
                continue
            
            # Résultats des trades pris
            trade_results = targets[trades_taken] >= 0.5
            wins = trade_results.sum()
            losses = n_trades - wins
            
            # Win rate
            win_rate = wins / n_trades
            
            # Profit Factor (simplifié)
            if losses > 0:
                profit_factor = (wins * self.avg_win_pct) / (losses * self.avg_loss_pct)
            else:
                profit_factor = float('inf') if wins > 0 else 0
            
            # Expected value par trade
            ev = win_rate * self.avg_win_pct - (1 - win_rate) * self.avg_loss_pct
            
            # Sharpe-like ratio (simplifié)
            returns = np.where(trade_results, self.avg_win_pct, -self.avg_loss_pct)
            if len(returns) > 1 and returns.std() > 0:
                sharpe = returns.mean() / returns.std() * np.sqrt(252)  # Annualisé
            else:
                sharpe = 0.0
            
            metrics[f'sim_win_rate_t{thresh}'] = win_rate
            metrics[f'sim_profit_factor_t{thresh}'] = min(profit_factor, 10.0)
            metrics[f'sim_expected_value_t{thresh}'] = ev
            metrics[f'sim_sharpe_t{thresh}'] = sharpe
            metrics[f'sim_n_trades_t{thresh}'] = n_trades
        
        return metrics


class MovingAverageMetrics:
    """
    Métriques avec moyenne mobile pour le suivi en temps réel.
    """
    
    def __init__(self, window_size: int = 100):
        self.window_size = window_size
        self.history: Dict[str, List[float]] = defaultdict(list)
    
    def update(self, metrics: Dict[str, float]):
        """Ajoute de nouvelles métriques à l'historique"""
        for key, value in metrics.items():
            self.history[key].append(value)
            
            # Garder seulement window_size valeurs
            if len(self.history[key]) > self.window_size:
                self.history[key] = self.history[key][-self.window_size:]
    
    def get_averages(self) -> Dict[str, float]:
        """Retourne les moyennes mobiles"""
        return {
            key: np.mean(values) if values else 0.0
            for key, values in self.history.items()
        }
    
    def get_trends(self) -> Dict[str, str]:
        """Retourne les tendances (up, down, stable)"""
        trends = {}
        
        for key, values in self.history.items():
            if len(values) < 10:
                trends[key] = 'stable'
                continue
            
            recent = np.mean(values[-10:])
            older = np.mean(values[:10])
            
            diff = (recent - older) / (abs(older) + 1e-8)
            
            if diff > 0.05:
                trends[key] = 'up'
            elif diff < -0.05:
                trends[key] = 'down'
            else:
                trends[key] = 'stable'
        
        return trends
