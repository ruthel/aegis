"""
Replay Buffer pour l'apprentissage continu
==========================================

Stocke des expériences passées pour les rejouer pendant
l'entraînement, évitant l'oubli catastrophique.

Supporte:
- Prioritized Experience Replay
- Reservoir Sampling pour mémoire bornée
- Stratified sampling par catégorie de trade
"""

import numpy as np
import torch
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
import random
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class Experience:
    """Une expérience stockée dans le buffer"""
    sequence: np.ndarray           # Features shape (seq_len, n_features)
    mask: np.ndarray               # Mask shape (seq_len,)
    labels: Dict[str, float]       # Labels pour chaque head
    timestamp: Any                 # Timestamp de l'expérience
    priority: float = 1.0          # Priorité pour le sampling
    metadata: Dict = field(default_factory=dict)  # Métadonnées optionnelles


class PrioritizedReplayBuffer:
    """
    Buffer d'expériences avec priorité pour l'apprentissage continu.
    
    Les expériences avec une erreur de prédiction élevée sont
    échantillonnées plus fréquemment.
    """
    
    def __init__(
        self,
        max_size: int = 50000,
        alpha: float = 0.6,
        beta: float = 0.4,
        beta_increment: float = 0.001,
        epsilon: float = 1e-6
    ):
        """
        Args:
            max_size: Taille maximale du buffer
            alpha: Exposant pour la priorité (0 = uniforme, 1 = full priority)
            beta: Compensation importance sampling (augmente vers 1)
            beta_increment: Incrément de beta à chaque sample
            epsilon: Petit nombre pour éviter priorité zéro
        """
        self.max_size = max_size
        self.alpha = alpha
        self.beta = beta
        self.beta_increment = beta_increment
        self.epsilon = epsilon
        
        # Stockage
        self.buffer: List[Experience] = []
        self.priorities: np.ndarray = np.zeros(max_size, dtype=np.float32)
        
        # Index courant pour l'ajout circulaire
        self.position = 0
        self.size = 0
        
        # Stats
        self.total_added = 0
        self.total_sampled = 0
    
    def add(
        self,
        sequence: np.ndarray,
        mask: np.ndarray,
        labels: Dict[str, float],
        timestamp: Any = None,
        priority: Optional[float] = None,
        metadata: Optional[Dict] = None
    ):
        """
        Ajoute une expérience au buffer.
        
        Args:
            sequence: Features de la séquence
            mask: Masque de validité
            labels: Dict des labels
            timestamp: Timestamp optionnel
            priority: Priorité initiale (utilise max actuelle si None)
            metadata: Métadonnées optionnelles
        """
        # Priorité par défaut = max actuelle
        if priority is None:
            priority = self.priorities[:self.size].max() if self.size > 0 else 1.0
        
        experience = Experience(
            sequence=sequence.copy(),
            mask=mask.copy(),
            labels=labels.copy(),
            timestamp=timestamp,
            priority=priority,
            metadata=metadata or {}
        )
        
        if self.size < self.max_size:
            self.buffer.append(experience)
            self.size += 1
        else:
            self.buffer[self.position] = experience
        
        self.priorities[self.position] = priority ** self.alpha
        self.position = (self.position + 1) % self.max_size
        self.total_added += 1
    
    def sample(
        self,
        batch_size: int,
        return_indices: bool = False
    ) -> Tuple[Dict[str, np.ndarray], Optional[np.ndarray], Optional[np.ndarray]]:
        """
        Échantillonne un batch avec priorité.
        
        Args:
            batch_size: Taille du batch
            return_indices: Retourner les indices pour update des priorités
            
        Returns:
            Tuple (batch_dict, importance_weights, indices)
        """
        if self.size == 0:
            raise ValueError("Buffer is empty")
        
        batch_size = min(batch_size, self.size)
        
        # Probabilités de sampling
        priorities = self.priorities[:self.size]
        probabilities = priorities / priorities.sum()
        
        # Échantillonnage
        indices = np.random.choice(self.size, size=batch_size, p=probabilities, replace=False)
        
        # Importance sampling weights
        # w_i = (N * P(i))^(-beta) / max(w)
        n = self.size
        weights = (n * probabilities[indices]) ** (-self.beta)
        weights = weights / weights.max()  # Normaliser
        
        # Incrémenter beta vers 1
        self.beta = min(1.0, self.beta + self.beta_increment)
        
        # Construire le batch
        experiences = [self.buffer[i] for i in indices]
        
        batch = {
            'sequences': np.array([e.sequence for e in experiences]),
            'masks': np.array([e.mask for e in experiences]),
            'labels': {
                key: np.array([e.labels.get(key, 0) for e in experiences])
                for key in ['win_probability', 'continue_probability', 'optimal_sizing']
            }
        }
        
        self.total_sampled += batch_size
        
        if return_indices:
            return batch, weights, indices
        return batch, weights, None
    
    def update_priorities(
        self,
        indices: np.ndarray,
        td_errors: np.ndarray
    ):
        """
        Met à jour les priorités basées sur l'erreur TD.
        
        Args:
            indices: Indices des expériences à mettre à jour
            td_errors: Erreurs de prédiction (absolues)
        """
        for idx, error in zip(indices, td_errors):
            self.priorities[idx] = (abs(error) + self.epsilon) ** self.alpha
            self.buffer[idx].priority = abs(error) + self.epsilon
    
    def sample_uniform(self, batch_size: int) -> Dict[str, np.ndarray]:
        """Échantillonnage uniforme (sans priorité)"""
        indices = np.random.choice(self.size, size=min(batch_size, self.size), replace=False)
        experiences = [self.buffer[i] for i in indices]
        
        return {
            'sequences': np.array([e.sequence for e in experiences]),
            'masks': np.array([e.mask for e in experiences]),
            'labels': {
                key: np.array([e.labels.get(key, 0) for e in experiences])
                for key in ['win_probability', 'continue_probability', 'optimal_sizing']
            }
        }
    
    def get_statistics(self) -> Dict[str, Any]:
        """Retourne les statistiques du buffer"""
        if self.size == 0:
            return {'size': 0}
        
        # Distribution des priorités
        priorities = self.priorities[:self.size]
        
        # Distribution des labels
        win_labels = [e.labels.get('win_probability', 0) for e in self.buffer[:self.size]]
        
        return {
            'size': self.size,
            'max_size': self.max_size,
            'fill_ratio': self.size / self.max_size,
            'total_added': self.total_added,
            'total_sampled': self.total_sampled,
            'priority_mean': float(priorities.mean()),
            'priority_std': float(priorities.std()),
            'priority_max': float(priorities.max()),
            'win_ratio': np.mean(np.array(win_labels) > 0.5),
            'beta': self.beta
        }
    
    def save(self, path: str):
        """Sauvegarde le buffer"""
        state = {
            'buffer': self.buffer,
            'priorities': self.priorities,
            'position': self.position,
            'size': self.size,
            'alpha': self.alpha,
            'beta': self.beta,
            'total_added': self.total_added,
            'total_sampled': self.total_sampled
        }
        torch.save(state, path)
        logger.info(f"Replay buffer saved to {path} ({self.size} experiences)")
    
    def load(self, path: str):
        """Charge le buffer"""
        state = torch.load(path)
        
        self.buffer = state['buffer']
        self.priorities = state['priorities']
        self.position = state['position']
        self.size = state['size']
        self.alpha = state['alpha']
        self.beta = state['beta']
        self.total_added = state['total_added']
        self.total_sampled = state['total_sampled']
        
        logger.info(f"Replay buffer loaded from {path} ({self.size} experiences)")


class StratifiedReplayBuffer(PrioritizedReplayBuffer):
    """
    Buffer avec stratification par catégorie de trade.
    
    Maintient un équilibre entre trades gagnants et perdants,
    et entre différentes conditions de marché.
    """
    
    def __init__(
        self,
        max_size: int = 50000,
        strata: List[str] = ['win', 'loss', 'small_win', 'small_loss'],
        strata_ratios: Optional[Dict[str, float]] = None,
        **kwargs
    ):
        super().__init__(max_size, **kwargs)
        
        self.strata = strata
        self.strata_ratios = strata_ratios or {
            'win': 0.3,
            'loss': 0.3,
            'small_win': 0.2,
            'small_loss': 0.2
        }
        
        # Index par stratum
        self.strata_indices: Dict[str, List[int]] = defaultdict(list)
    
    def add(
        self,
        sequence: np.ndarray,
        mask: np.ndarray,
        labels: Dict[str, float],
        timestamp: Any = None,
        priority: Optional[float] = None,
        metadata: Optional[Dict] = None
    ):
        """Ajoute avec classification automatique du stratum"""
        # Déterminer le stratum
        win_prob = labels.get('win_probability', 0.5)
        
        if win_prob >= 0.7:
            stratum = 'win'
        elif win_prob >= 0.5:
            stratum = 'small_win'
        elif win_prob >= 0.3:
            stratum = 'small_loss'
        else:
            stratum = 'loss'
        
        # Vérifier la capacité du stratum
        max_stratum_size = int(self.max_size * self.strata_ratios.get(stratum, 0.25))
        
        if len(self.strata_indices[stratum]) >= max_stratum_size:
            # Retirer l'élément le plus ancien du stratum
            old_idx = self.strata_indices[stratum].pop(0)
            # Marquer comme à remplacer
            self.priorities[old_idx] = 0
        
        # Ajouter normalement
        super().add(sequence, mask, labels, timestamp, priority, metadata)
        
        # Enregistrer l'index dans le stratum
        idx = (self.position - 1) % self.max_size
        self.strata_indices[stratum].append(idx)
    
    def sample_stratified(self, batch_size: int) -> Dict[str, np.ndarray]:
        """Échantillonne en respectant les ratios de strata"""
        batch_experiences = []
        
        for stratum, ratio in self.strata_ratios.items():
            n_samples = int(batch_size * ratio)
            indices = self.strata_indices[stratum]
            
            if len(indices) > 0:
                sampled_indices = np.random.choice(
                    indices,
                    size=min(n_samples, len(indices)),
                    replace=False
                )
                batch_experiences.extend([self.buffer[i] for i in sampled_indices])
        
        if not batch_experiences:
            return self.sample_uniform(batch_size)
        
        return {
            'sequences': np.array([e.sequence for e in batch_experiences]),
            'masks': np.array([e.mask for e in batch_experiences]),
            'labels': {
                key: np.array([e.labels.get(key, 0) for e in batch_experiences])
                for key in ['win_probability', 'continue_probability', 'optimal_sizing']
            }
        }
