"""
Module d'évolution continue
===========================

- ewc: Elastic Weight Consolidation (protection contre l'oubli)
- replay_buffer: Buffer d'expériences pour replay
- drift_detector: Détection de drift de distribution
- online_learner: Apprentissage en ligne
"""

from .ewc import ElasticWeightConsolidation
from .replay_buffer import PrioritizedReplayBuffer
from .drift_detector import DriftDetector
from .online_learner import OnlineLearner

__all__ = ['ElasticWeightConsolidation', 'PrioritizedReplayBuffer', 'DriftDetector', 'OnlineLearner']
