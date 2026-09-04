"""
Loss Functions pour le modèle Deep Learning
==========================================

- FocalLoss: Gère le déséquilibre de classes
- TradingLoss: Loss combinée avec métriques trading
- MultiTaskLoss: Pondération automatique multi-tâches
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Dict, Optional, Tuple
import math


class FocalLoss(nn.Module):
    """
    Focal Loss pour gérer le déséquilibre de classes.
    
    Réduit le poids des exemples faciles pour se concentrer
    sur les exemples difficiles.
    
    FL(p_t) = -alpha_t * (1 - p_t)^gamma * log(p_t)
    """
    
    def __init__(
        self,
        alpha: float = 0.25,
        gamma: float = 2.0,
        reduction: str = 'mean'
    ):
        """
        Args:
            alpha: Poids pour la classe positive (défaut 0.25)
            gamma: Facteur de focus (défaut 2.0, plus grand = plus focus sur difficiles)
            reduction: 'mean', 'sum', ou 'none'
        """
        super().__init__()
        self.alpha = alpha
        self.gamma = gamma
        self.reduction = reduction
    
    def forward(
        self,
        inputs: torch.Tensor,
        targets: torch.Tensor
    ) -> torch.Tensor:
        """
        Args:
            inputs: Prédictions (logits ou probabilités après sigmoid)
            targets: Labels (0 ou 1)
        """
        # Utiliser binary_cross_entropy_with_logits pour compatibilité AMP
        # Cette version est numériquement stable et compatible avec autocast
        
        # Si inputs sont des probabilités (après sigmoid), les reconvertir en logits
        if inputs.min() >= 0 and inputs.max() <= 1:
            # Clamp pour éviter log(0) ou log(inf)
            inputs_clamped = inputs.clamp(min=1e-7, max=1 - 1e-7)
            # Inverse sigmoid: logit = log(p / (1-p))
            logits = torch.log(inputs_clamped / (1 - inputs_clamped))
        else:
            logits = inputs
        
        # Binary cross entropy with logits (AMP-safe)
        ce_loss = F.binary_cross_entropy_with_logits(logits, targets, reduction='none')
        
        # Calculer les probabilités pour focal weight
        probs = torch.sigmoid(logits)
        
        # Calcul p_t
        p_t = probs * targets + (1 - probs) * (1 - targets)
        
        # Focal weight
        focal_weight = (1 - p_t) ** self.gamma
        
        # Alpha weighting
        alpha_t = self.alpha * targets + (1 - self.alpha) * (1 - targets)
        
        # Focal loss
        focal_loss = alpha_t * focal_weight * ce_loss
        
        if self.reduction == 'mean':
            return focal_loss.mean()
        elif self.reduction == 'sum':
            return focal_loss.sum()
        return focal_loss


class LabelSmoothingLoss(nn.Module):
    """
    Label Smoothing pour éviter l'overconfidence.
    
    Au lieu de labels durs (0, 1), utilise (smoothing, 1-smoothing).
    """
    
    def __init__(self, smoothing: float = 0.1):
        super().__init__()
        self.smoothing = smoothing
    
    def forward(
        self,
        inputs: torch.Tensor,
        targets: torch.Tensor
    ) -> torch.Tensor:
        # Smooth labels
        targets_smooth = targets * (1 - self.smoothing) + 0.5 * self.smoothing
        
        return F.binary_cross_entropy_with_logits(inputs, targets_smooth)


class TradingLoss(nn.Module):
    """
    Loss function combinée optimisée pour le trading.
    
    Combine:
    - Focal loss pour la classification (win/lose)
    - MSE pour le sizing
    - Pénalités pour métriques trading (profit factor, Sharpe)
    """
    
    def __init__(
        self,
        loss_weights: Optional[Dict[str, float]] = None,
        focal_alpha: float = 0.25,
        focal_gamma: float = 2.0,
        profit_factor_weight: float = 0.3,
        sharpe_weight: float = 0.2,
        consistency_weight: float = 0.1
    ):
        """
        Args:
            loss_weights: Poids pour chaque head {'win_probability': 1.0, ...}
            focal_alpha: Alpha pour focal loss
            focal_gamma: Gamma pour focal loss
            profit_factor_weight: Poids de la pénalité profit factor
            sharpe_weight: Poids de la pénalité Sharpe
            consistency_weight: Poids pour la cohérence temporelle
        """
        super().__init__()
        
        self.loss_weights = loss_weights or {
            'win_probability': 1.0,
            'continue_probability': 0.5,
            'optimal_sizing': 0.3
        }
        
        self.focal_loss = FocalLoss(alpha=focal_alpha, gamma=focal_gamma)
        self.mse_loss = nn.MSELoss()
        self.bce_loss = nn.BCEWithLogitsLoss()  # AMP-safe version
        
        self.profit_factor_weight = profit_factor_weight
        self.sharpe_weight = sharpe_weight
        self.consistency_weight = consistency_weight
    
    def forward(
        self,
        predictions: Dict[str, torch.Tensor],
        targets: Dict[str, torch.Tensor],
        prices: Optional[torch.Tensor] = None
    ) -> Tuple[torch.Tensor, Dict[str, torch.Tensor]]:
        """
        Calcule la loss totale et les loss individuelles.
        
        Args:
            predictions: Dict avec prédictions par head
            targets: Dict avec labels par head
            prices: Optional tensor de prix pour métriques trading
            
        Returns:
            Tuple (total_loss, dict_of_individual_losses)
        """
        losses = {}
        
        # === WIN PROBABILITY (Focal Loss) ===
        if 'win_probability' in predictions and 'win_probability' in targets:
            pred_win = predictions['win_probability'].squeeze()
            target_win = targets['win_probability'].squeeze()
            
            losses['win_probability'] = self.focal_loss(pred_win, target_win)
        
        # === CONTINUE PROBABILITY (BCE with logits) ===
        if 'continue_probability' in predictions and 'continue_probability' in targets:
            pred_cont = predictions['continue_probability'].squeeze()
            target_cont = targets['continue_probability'].squeeze()
            
            # Convertir probabilités en logits si nécessaire (pour AMP compatibility)
            if pred_cont.min() >= 0 and pred_cont.max() <= 1:
                pred_cont_clamped = pred_cont.clamp(min=1e-7, max=1 - 1e-7)
                pred_cont_logits = torch.log(pred_cont_clamped / (1 - pred_cont_clamped))
            else:
                pred_cont_logits = pred_cont
            
            losses['continue_probability'] = self.bce_loss(pred_cont_logits, target_cont)
        
        # === OPTIMAL SIZING (MSE) ===
        if 'optimal_sizing' in predictions and 'optimal_sizing' in targets:
            pred_size = predictions['optimal_sizing'].squeeze()
            target_size = targets['optimal_sizing'].squeeze()
            
            losses['optimal_sizing'] = self.mse_loss(pred_size, target_size)
        
        # === TRADING METRICS PENALTIES ===
        if prices is not None and 'win_probability' in predictions:
            trading_penalty = self._compute_trading_penalty(
                predictions, targets, prices
            )
            losses['trading_penalty'] = trading_penalty
        
        # === CONSISTENCY PENALTY ===
        if self.consistency_weight > 0:
            consistency_loss = self._compute_consistency_loss(predictions)
            losses['consistency'] = consistency_loss * self.consistency_weight
        
        # === TOTAL LOSS ===
        total_loss = torch.tensor(0.0, device=next(iter(predictions.values())).device)
        
        for key, loss in losses.items():
            weight = self.loss_weights.get(key, 1.0)
            total_loss = total_loss + weight * loss
        
        return total_loss, losses
    
    def _compute_trading_penalty(
        self,
        predictions: Dict[str, torch.Tensor],
        targets: Dict[str, torch.Tensor],
        prices: torch.Tensor
    ) -> torch.Tensor:
        """
        Calcule une pénalité basée sur les métriques trading.
        
        Pénalise les prédictions qui mèneraient à un mauvais profit factor.
        """
        pred_win = predictions['win_probability'].squeeze()
        target_win = targets['win_probability'].squeeze()
        
        # Simuler les gains/pertes
        # Prédiction > 0.5 = trade pris
        trade_taken = (pred_win > 0.5).float()
        
        # Résultat réel
        actual_win = target_win > 0.5
        
        # Gains et pertes simulés
        wins = (trade_taken * actual_win.float()).sum()
        losses = (trade_taken * (~actual_win).float()).sum()
        
        # Profit factor approximatif
        # On veut maximiser wins / (losses + eps)
        profit_factor = wins / (losses + 1.0)
        
        # Pénalité: on veut profit factor > 1.5
        target_pf = 1.5
        pf_penalty = F.relu(target_pf - profit_factor)
        
        return pf_penalty * self.profit_factor_weight
    
    def _compute_consistency_loss(
        self,
        predictions: Dict[str, torch.Tensor]
    ) -> torch.Tensor:
        """
        Pénalise les incohérences entre les prédictions.
        
        Ex: haute win_probability devrait corréler avec sizing plus élevé.
        """
        if 'win_probability' not in predictions or 'optimal_sizing' not in predictions:
            return torch.tensor(0.0)
        
        win_prob = predictions['win_probability'].squeeze()
        sizing = predictions['optimal_sizing'].squeeze()
        
        # La corrélation devrait être positive
        # Pénaliser si win_prob élevé mais sizing bas (et vice versa)
        expected_sizing = win_prob * 0.5 + 0.25  # Mapping simple
        
        consistency_error = F.mse_loss(sizing, expected_sizing)
        
        return consistency_error


class MultiTaskLoss(nn.Module):
    """
    Multi-Task Learning avec pondération automatique des losses.
    
    Utilise l'uncertainty weighting (Kendall et al.) pour
    apprendre automatiquement les poids des tâches.
    """
    
    def __init__(self, num_tasks: int = 3):
        """
        Args:
            num_tasks: Nombre de tâches/heads
        """
        super().__init__()
        
        # Log variance pour chaque tâche (paramètres apprenables)
        self.log_vars = nn.Parameter(torch.zeros(num_tasks))
        
        self.focal_loss = FocalLoss()
        self.mse_loss = nn.MSELoss()
        self.bce_loss = nn.BCEWithLogitsLoss()  # AMP-safe version
    
    def forward(
        self,
        predictions: Dict[str, torch.Tensor],
        targets: Dict[str, torch.Tensor]
    ) -> Tuple[torch.Tensor, Dict[str, torch.Tensor]]:
        """
        Calcule la loss avec pondération automatique.
        """
        losses = {}
        weighted_losses = []
        
        task_idx = 0
        
        # Win probability
        if 'win_probability' in predictions:
            loss = self.focal_loss(
                predictions['win_probability'].squeeze(),
                targets['win_probability'].squeeze()
            )
            losses['win_probability'] = loss
            
            # Uncertainty weighting: L_i / (2 * sigma_i^2) + log(sigma_i)
            precision = torch.exp(-self.log_vars[task_idx])
            weighted_loss = precision * loss + self.log_vars[task_idx]
            weighted_losses.append(weighted_loss)
            task_idx += 1
        
        # Continue probability
        if 'continue_probability' in predictions:
            pred_cont = predictions['continue_probability'].squeeze()
            target_cont = targets['continue_probability'].squeeze()
            
            # Convertir probabilités en logits si nécessaire (pour AMP compatibility)
            if pred_cont.min() >= 0 and pred_cont.max() <= 1:
                pred_cont_clamped = pred_cont.clamp(min=1e-7, max=1 - 1e-7)
                pred_cont_logits = torch.log(pred_cont_clamped / (1 - pred_cont_clamped))
            else:
                pred_cont_logits = pred_cont
            
            loss = self.bce_loss(pred_cont_logits, target_cont)
            losses['continue_probability'] = loss
            
            precision = torch.exp(-self.log_vars[task_idx])
            weighted_loss = precision * loss + self.log_vars[task_idx]
            weighted_losses.append(weighted_loss)
            task_idx += 1
        
        # Optimal sizing
        if 'optimal_sizing' in predictions:
            loss = self.mse_loss(
                predictions['optimal_sizing'].squeeze(),
                targets['optimal_sizing'].squeeze()
            )
            losses['optimal_sizing'] = loss
            
            precision = torch.exp(-self.log_vars[task_idx])
            weighted_loss = precision * loss + self.log_vars[task_idx]
            weighted_losses.append(weighted_loss)
        
        total_loss = sum(weighted_losses)
        
        # Ajouter les poids appris aux losses pour monitoring
        losses['learned_weights'] = torch.exp(-self.log_vars).detach()
        
        return total_loss, losses


class AsymmetricLoss(nn.Module):
    """
    Loss asymétrique qui pénalise différemment les faux positifs
    et faux négatifs.
    
    Utile en trading où manquer un bon trade (FN) peut être
    moins grave que prendre un mauvais trade (FP).
    """
    
    def __init__(
        self,
        fp_weight: float = 2.0,  # Poids faux positifs
        fn_weight: float = 1.0   # Poids faux négatifs
    ):
        super().__init__()
        self.fp_weight = fp_weight
        self.fn_weight = fn_weight
    
    def forward(
        self,
        inputs: torch.Tensor,
        targets: torch.Tensor
    ) -> torch.Tensor:
        probs = torch.sigmoid(inputs) if inputs.min() < 0 else inputs
        probs = probs.clamp(min=1e-7, max=1 - 1e-7)
        
        # Positive samples (target = 1): pénalise FN
        pos_loss = -self.fn_weight * targets * torch.log(probs)
        
        # Negative samples (target = 0): pénalise FP
        neg_loss = -self.fp_weight * (1 - targets) * torch.log(1 - probs)
        
        return (pos_loss + neg_loss).mean()
