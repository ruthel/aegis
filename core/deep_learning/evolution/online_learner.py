"""
Online Learner pour l'apprentissage continu
===========================================

Combine tous les composants d'évolution:
- EWC pour protéger les connaissances
- Replay Buffer pour éviter l'oubli
- Drift Detection pour s'adapter aux changements

Gère l'apprentissage incrémental du modèle en production.
"""

import torch
import torch.nn as nn
from torch.optim import AdamW
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
import numpy as np
import logging
from datetime import datetime

from .ewc import ElasticWeightConsolidation
from .replay_buffer import PrioritizedReplayBuffer, StratifiedReplayBuffer
from .drift_detector import DriftDetector
from ..models.lstm_attention import LSTMAttentionModel
from ..training.losses import TradingLoss

logger = logging.getLogger(__name__)


class OnlineLearner:
    """
    Système d'apprentissage continu pour le modèle DL.
    
    Permet au modèle d'évoluer en production sans oublier
    les connaissances passées.
    """
    
    def __init__(
        self,
        model: LSTMAttentionModel,
        config: Dict,
        device: str = 'cuda'
    ):
        """
        Args:
            model: Modèle LSTM-Attention
            config: Configuration d'évolution
            device: Device pour le calcul
        """
        self.model = model
        self.config = config
        self.device = device
        
        self.model.to(device)
        
        # === COMPOSANTS D'ÉVOLUTION ===
        
        # EWC
        self.ewc = ElasticWeightConsolidation(
            model=model,
            ewc_lambda=config.get('ewc_lambda', 1000.0),
            gamma=config.get('ewc_gamma', 0.95),
            online=True
        )
        
        # Replay Buffer
        buffer_type = config.get('buffer_type', 'stratified')
        buffer_size = config.get('replay_buffer_size', 50000)
        
        if buffer_type == 'stratified':
            self.replay_buffer = StratifiedReplayBuffer(
                max_size=buffer_size,
                alpha=config.get('priority_alpha', 0.6),
                beta=config.get('priority_beta', 0.4)
            )
        else:
            self.replay_buffer = PrioritizedReplayBuffer(
                max_size=buffer_size,
                alpha=config.get('priority_alpha', 0.6),
                beta=config.get('priority_beta', 0.4)
            )
        
        # Drift Detector
        self.drift_detector = DriftDetector(
            window_size=config.get('drift_window_size', 1000),
            drift_threshold=config.get('drift_threshold', 0.05),
            warning_threshold=config.get('drift_threshold', 0.05) * 0.6
        )
        
        # === OPTIMISATION ===
        self.optimizer = AdamW(
            model.parameters(),
            lr=config.get('online_learning_rate', 1e-5),
            weight_decay=1e-5
        )
        
        self.criterion = TradingLoss()
        
        # === TRACKING ===
        self.update_count = 0
        self.samples_accumulated = 0
        self.update_frequency = config.get('update_frequency', 100)
        self.min_samples_update = config.get('min_samples_update', 50)
        
        # Performance tracking
        self.performance_window: List[float] = []
        self.min_performance = config.get('min_performance_threshold', 0.45)
        
        # Historique
        self.update_history: List[Dict] = []
        
        # Chemins
        self.checkpoint_dir = Path(config.get('checkpoint_path', 'data/deep_learning/checkpoints'))
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"OnlineLearner initialized with update_frequency={self.update_frequency}")
    
    def add_experience(
        self,
        sequence: np.ndarray,
        mask: np.ndarray,
        labels: Dict[str, float],
        prediction: Optional[Dict[str, float]] = None,
        timestamp: Any = None,
        actual_outcome: Optional[float] = None
    ):
        """
        Ajoute une nouvelle expérience.
        
        Args:
            sequence: Features de la séquence
            mask: Masque de validité
            labels: Labels réels
            prediction: Prédiction du modèle (pour priorité)
            timestamp: Timestamp de l'expérience
            actual_outcome: Résultat réel du trade (pour drift detection)
        """
        # Calculer la priorité basée sur l'erreur
        priority = None
        if prediction is not None:
            error = abs(prediction.get('win_probability', 0.5) - labels.get('win_probability', 0.5))
            priority = error + 0.01  # +epsilon pour éviter priorité zéro
        
        # Ajouter au replay buffer
        self.replay_buffer.add(
            sequence=sequence,
            mask=mask,
            labels=labels,
            timestamp=timestamp,
            priority=priority,
            metadata={'prediction': prediction}
        )
        
        # Ajouter au drift detector
        if prediction is not None and actual_outcome is not None:
            self.drift_detector.add_sample(
                features=sequence.mean(axis=0) if sequence.ndim > 1 else sequence,
                prediction=prediction.get('win_probability', 0.5),
                actual=actual_outcome,
                performance_metric=1.0 if (prediction.get('win_probability', 0) > 0.5) == (actual_outcome > 0.5) else 0.0
            )
        
        self.samples_accumulated += 1
        
        # Vérifier si on doit faire un update
        if self.samples_accumulated >= self.update_frequency:
            self._maybe_update()
    
    def _maybe_update(self):
        """Effectue une mise à jour si les conditions sont réunies"""
        if self.replay_buffer.size < self.min_samples_update:
            logger.debug(f"Not enough samples for update: {self.replay_buffer.size}/{self.min_samples_update}")
            return
        
        # Vérifier le drift
        drift_result = self.drift_detector.check_drift()
        
        # Adapter le learning rate selon le drift
        adaptation_rate = self.drift_detector.get_adaptation_rate()
        
        # Faire l'update
        update_result = self._perform_update(adaptation_rate, drift_result)
        
        # Enregistrer
        self.update_history.append({
            'timestamp': datetime.now().isoformat(),
            'update_count': self.update_count,
            'drift_detected': drift_result['drift_detected'],
            'drift_score': drift_result['drift_score'],
            'adaptation_rate': adaptation_rate,
            **update_result
        })
        
        self.update_count += 1
        self.samples_accumulated = 0
        
        # Checkpoint périodique
        if self.update_count % self.config.get('checkpoint_frequency', 1000) == 0:
            self._save_checkpoint()
        
        # Si drift majeur, recalculer la Fisher
        if drift_result['drift_detected']:
            self._handle_drift(drift_result)
    
    def _perform_update(
        self,
        adaptation_rate: float,
        drift_result: Dict
    ) -> Dict:
        """
        Effectue une mise à jour du modèle.
        
        Args:
            adaptation_rate: Taux d'adaptation (0-1)
            drift_result: Résultat de la détection de drift
            
        Returns:
            Dict avec métriques de l'update
        """
        self.model.train()
        
        # Ajuster le learning rate
        base_lr = self.config.get('online_learning_rate', 1e-5)
        current_lr = base_lr * adaptation_rate
        
        for param_group in self.optimizer.param_groups:
            param_group['lr'] = current_lr
        
        # === PHASE 1: Nouvelles données ===
        new_batch, weights, indices = self.replay_buffer.sample(
            batch_size=self.config.get('batch_size', 32),
            return_indices=True
        )
        
        # Convertir en tensors
        sequences = torch.tensor(new_batch['sequences'], dtype=torch.float32, device=self.device)
        masks = torch.tensor(new_batch['masks'], dtype=torch.float32, device=self.device)
        labels = {k: torch.tensor(v, dtype=torch.float32, device=self.device) 
                  for k, v in new_batch['labels'].items()}
        importance_weights = torch.tensor(weights, dtype=torch.float32, device=self.device)
        
        # Forward
        self.optimizer.zero_grad()
        predictions = self.model(sequences, masks)
        
        # Loss avec importance weighting
        base_loss, loss_dict = self.criterion(predictions, labels)
        weighted_loss = (base_loss * importance_weights.mean())
        
        # === PHASE 2: Replay (si activé) ===
        replay_loss = torch.tensor(0.0, device=self.device)
        replay_ratio = self.config.get('replay_sample_ratio', 0.3)
        
        if replay_ratio > 0 and self.replay_buffer.size > self.min_samples_update * 2:
            replay_batch = self.replay_buffer.sample_uniform(
                batch_size=int(self.config.get('batch_size', 32) * replay_ratio)
            )
            
            replay_sequences = torch.tensor(replay_batch['sequences'], dtype=torch.float32, device=self.device)
            replay_masks = torch.tensor(replay_batch['masks'], dtype=torch.float32, device=self.device)
            replay_labels = {k: torch.tensor(v, dtype=torch.float32, device=self.device) 
                          for k, v in replay_batch['labels'].items()}
            
            replay_predictions = self.model(replay_sequences, replay_masks)
            replay_loss, _ = self.criterion(replay_predictions, replay_labels)
        
        # === PHASE 3: Régularisation EWC ===
        ewc_loss = self.ewc.penalty()
        
        # === LOSS TOTALE ===
        total_loss = weighted_loss + replay_ratio * replay_loss + ewc_loss
        
        # Backward et update
        total_loss.backward()
        torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
        self.optimizer.step()
        
        # Mettre à jour les priorités
        if indices is not None:
            with torch.no_grad():
                pred_values = predictions['win_probability'].squeeze().cpu().numpy()
                target_values = labels['win_probability'].squeeze().cpu().numpy()
                td_errors = np.abs(pred_values - target_values)
                self.replay_buffer.update_priorities(indices, td_errors)
        
        return {
            'total_loss': total_loss.item(),
            'base_loss': base_loss.item(),
            'replay_loss': replay_loss.item() if isinstance(replay_loss, torch.Tensor) else replay_loss,
            'ewc_loss': ewc_loss.item() if isinstance(ewc_loss, torch.Tensor) else ewc_loss,
            'learning_rate': current_lr
        }
    
    def _handle_drift(self, drift_result: Dict):
        """Gère un drift détecté"""
        logger.warning(f"Handling drift: {drift_result['drift_type']}")
        
        # Recalculer la Fisher Information avec les données récentes
        # Créer un pseudo-dataloader depuis le replay buffer
        class BufferDataLoader:
            def __init__(self, buffer, batch_size):
                self.buffer = buffer
                self.batch_size = batch_size
                self.n_batches = buffer.size // batch_size
            
            def __iter__(self):
                for _ in range(self.n_batches):
                    batch = self.buffer.sample_uniform(self.batch_size)
                    yield batch
        
        if self.replay_buffer.size >= self.min_samples_update:
            loader = BufferDataLoader(self.replay_buffer, 32)
            self.ewc.compute_fisher_information(
                loader,
                n_samples=min(1000, self.replay_buffer.size),
                device=self.device
            )
        
        # Reset drift detector avec nouvelles références
        self.drift_detector.reset(keep_reference=False)
        
        logger.info("Drift handled: Fisher recalculated, drift detector reset")
    
    def _save_checkpoint(self):
        """Sauvegarde un checkpoint"""
        checkpoint_path = self.checkpoint_dir / f'online_checkpoint_{self.update_count}.pt'
        
        checkpoint = {
            'model_state_dict': self.model.state_dict(),
            'optimizer_state_dict': self.optimizer.state_dict(),
            'update_count': self.update_count,
            'config': self.config,
            'timestamp': datetime.now().isoformat()
        }
        
        torch.save(checkpoint, checkpoint_path)
        
        # Sauvegarder EWC et Replay Buffer
        self.ewc.save(self.checkpoint_dir / 'ewc_state.pt')
        self.replay_buffer.save(self.checkpoint_dir / 'replay_buffer.pt')
        
        # Garder seulement les N derniers checkpoints
        keep_n = self.config.get('keep_n_checkpoints', 10)
        checkpoints = sorted(self.checkpoint_dir.glob('online_checkpoint_*.pt'))
        for old_checkpoint in checkpoints[:-keep_n]:
            old_checkpoint.unlink()
        
        logger.info(f"Checkpoint saved: {checkpoint_path}")
    
    def load_checkpoint(self, path: Optional[Path] = None):
        """Charge un checkpoint"""
        if path is None:
            # Charger le plus récent
            checkpoints = sorted(self.checkpoint_dir.glob('online_checkpoint_*.pt'))
            if not checkpoints:
                logger.warning("No checkpoint found")
                return
            path = checkpoints[-1]
        
        checkpoint = torch.load(path, map_location=self.device)
        
        self.model.load_state_dict(checkpoint['model_state_dict'])
        self.optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
        self.update_count = checkpoint['update_count']
        
        # Charger EWC et Replay Buffer si disponibles
        ewc_path = self.checkpoint_dir / 'ewc_state.pt'
        if ewc_path.exists():
            self.ewc.load(ewc_path)
        
        buffer_path = self.checkpoint_dir / 'replay_buffer.pt'
        if buffer_path.exists():
            self.replay_buffer.load(buffer_path)
        
        logger.info(f"Checkpoint loaded from {path}")
    
    def evaluate_performance(self) -> Dict:
        """Évalue la performance actuelle du modèle"""
        stats = {
            'update_count': self.update_count,
            'buffer_size': self.replay_buffer.size,
            'buffer_stats': self.replay_buffer.get_statistics(),
            'drift_stats': self.drift_detector.get_statistics(),
            'ewc_n_tasks': self.ewc.n_tasks
        }
        
        # Performance récente
        if self.update_history:
            recent = self.update_history[-10:]
            stats['recent_avg_loss'] = np.mean([u['total_loss'] for u in recent])
            stats['recent_drift_rate'] = np.mean([u['drift_detected'] for u in recent])
        
        return stats
    
    def should_rollback(self) -> Tuple[bool, str]:
        """
        Détermine si on doit revenir à un checkpoint précédent.
        
        Returns:
            Tuple (should_rollback, reason)
        """
        if len(self.update_history) < 20:
            return False, "Not enough history"
        
        # Comparer performance récente vs ancienne
        recent = self.update_history[-10:]
        older = self.update_history[-20:-10]
        
        recent_loss = np.mean([u['total_loss'] for u in recent])
        older_loss = np.mean([u['total_loss'] for u in older])
        
        # Si la loss a augmenté de plus de 50%
        if recent_loss > older_loss * 1.5:
            return True, f"Performance degradation: {recent_loss:.4f} vs {older_loss:.4f}"
        
        # Si trop de drifts récents
        recent_drifts = sum(u['drift_detected'] for u in recent)
        if recent_drifts >= 5:
            return True, f"Too many drifts: {recent_drifts} in last 10 updates"
        
        return False, "Performance stable"
    
    def rollback_to_best(self):
        """Revient au meilleur checkpoint"""
        checkpoints = sorted(self.checkpoint_dir.glob('online_checkpoint_*.pt'))
        
        if not checkpoints:
            logger.warning("No checkpoints available for rollback")
            return
        
        # Trouver le checkpoint avec la meilleure loss
        best_checkpoint = None
        best_loss = float('inf')
        
        for cp_path in checkpoints:
            cp = torch.load(cp_path, map_location='cpu')
            # Estimer la loss depuis l'historique si disponible
            update_idx = cp.get('update_count', 0)
            
            if update_idx < len(self.update_history):
                loss = self.update_history[update_idx].get('total_loss', float('inf'))
                if loss < best_loss:
                    best_loss = loss
                    best_checkpoint = cp_path
        
        if best_checkpoint:
            self.load_checkpoint(best_checkpoint)
            logger.info(f"Rolled back to {best_checkpoint}")
        else:
            # Charger le plus ancien (supposé stable)
            self.load_checkpoint(checkpoints[0])
            logger.info(f"Rolled back to oldest checkpoint: {checkpoints[0]}")
