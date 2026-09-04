"""
Module d'entraînement Deep Learning
===================================

- trainer: Boucle d'entraînement complète
- losses: Focal loss et loss combinée trading
- metrics: Métriques spécifiques trading
"""

from .trainer import DLTrainer
from .losses import FocalLoss, TradingLoss
from .metrics import TradingMetrics

__all__ = ['DLTrainer', 'FocalLoss', 'TradingLoss', 'TradingMetrics']
