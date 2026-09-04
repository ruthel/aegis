"""
AEGIS Deep Learning Module
==========================

Système de Deep Learning avec LSTM-Attention pour prédiction de trading.
Fonctionne en mode shadow parallèlement au RandomForest existant.

Modules:
- config: Configuration et hyperparamètres
- data: Feature engineering, séquences, normalisation
- models: LSTM-Attention et composants
- training: Entraînement, loss functions, métriques
- evolution: Apprentissage continu, EWC, replay buffer
- shadow: Prédictions temps réel, comparaison avec RF
"""

from .config import DLConfig

__all__ = ['DLConfig']
