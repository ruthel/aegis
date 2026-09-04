"""
Trainer pour le modèle Deep Learning AEGIS
==========================================

Gère:
- Boucle d'entraînement complète
- Validation et early stopping
- Logging et checkpointing
- Mixed precision training
- Gradient accumulation
"""

import torch
import torch.nn as nn
from torch.optim import AdamW, Adam, SGD
from torch.optim.lr_scheduler import CosineAnnealingLR, ReduceLROnPlateau, StepLR
from torch.amp import autocast, GradScaler
from typing import Dict, Optional, Tuple, List, Callable
from pathlib import Path
import logging
import json
import time
from datetime import datetime

from ..models.lstm_attention import LSTMAttentionModel
from ..data.sequence_builder import SequenceData
from .losses import TradingLoss, MultiTaskLoss
from .metrics import TradingMetrics, MovingAverageMetrics

logger = logging.getLogger(__name__)


class DLTrainer:
    """
    Trainer complet pour le modèle LSTM-Attention.
    """
    
    def __init__(
        self,
        model: LSTMAttentionModel,
        config: dict,
        device: Optional[str] = None
    ):
        """
        Args:
            model: Instance du modèle
            config: Configuration d'entraînement
            device: 'cuda' ou 'cpu'
        """
        self.model = model
        self.config = config
        self.device = device or ('cuda' if torch.cuda.is_available() else 'cpu')
        
        self.model.to(self.device)
        
        # === OPTIMIZER ===
        self.optimizer = self._create_optimizer()
        
        # === SCHEDULER ===
        self.scheduler = self._create_scheduler()
        
        # === LOSS ===
        loss_type = config.get('loss_type', 'trading')
        if loss_type == 'multitask':
            self.criterion = MultiTaskLoss(num_tasks=3)
        else:
            self.criterion = TradingLoss(
                loss_weights=config.get('loss_weights'),
                focal_alpha=config.get('focal_alpha', 0.25),
                focal_gamma=config.get('focal_gamma', 2.0)
            )
        self.criterion.to(self.device)
        
        # === MIXED PRECISION ===
        self.use_amp = config.get('mixed_precision', True) and self.device == 'cuda'
        self.scaler = GradScaler('cuda') if self.use_amp else None
        
        # === GRADIENT ACCUMULATION ===
        self.accumulation_steps = config.get('accumulation_steps', 4)
        
        # === METRICS ===
        self.metrics = TradingMetrics()
        self.moving_metrics = MovingAverageMetrics(window_size=100)
        
        # === TRACKING ===
        self.epoch = 0
        self.global_step = 0
        self.best_val_loss = float('inf')
        self.best_val_metric = 0.0
        self.patience_counter = 0
        
        # === HISTORY ===
        self.history = {
            'train_loss': [],
            'val_loss': [],
            'val_metrics': [],
            'learning_rate': []
        }
        
        logger.info(f"Trainer initialized on {self.device}")
        logger.info(f"Mixed precision: {self.use_amp}")
        logger.info(f"Accumulation steps: {self.accumulation_steps}")
    
    def _create_optimizer(self) -> torch.optim.Optimizer:
        """Crée l'optimiseur"""
        optimizer_name = self.config.get('optimizer', 'adamw').lower()
        lr = self.config.get('learning_rate', 1e-4)
        weight_decay = self.config.get('weight_decay', 1e-5)
        
        if optimizer_name == 'adamw':
            return AdamW(
                self.model.parameters(),
                lr=lr,
                weight_decay=weight_decay,
                betas=(0.9, 0.999)
            )
        elif optimizer_name == 'adam':
            return Adam(
                self.model.parameters(),
                lr=lr,
                weight_decay=weight_decay
            )
        elif optimizer_name == 'sgd':
            return SGD(
                self.model.parameters(),
                lr=lr,
                momentum=0.9,
                weight_decay=weight_decay
            )
        else:
            raise ValueError(f"Unknown optimizer: {optimizer_name}")
    
    def _create_scheduler(self):
        """Crée le scheduler de learning rate"""
        scheduler_name = self.config.get('scheduler', 'cosine').lower()
        max_epochs = self.config.get('max_epochs', 100)
        
        if scheduler_name == 'cosine':
            return CosineAnnealingLR(
                self.optimizer,
                T_max=max_epochs,
                eta_min=1e-7
            )
        elif scheduler_name == 'plateau':
            return ReduceLROnPlateau(
                self.optimizer,
                mode='min',
                factor=0.5,
                patience=5,
                min_lr=1e-7
            )
        elif scheduler_name == 'step':
            return StepLR(
                self.optimizer,
                step_size=20,
                gamma=0.5
            )
        else:
            return None
    
    def train_epoch(
        self,
        train_data: SequenceData,
        batch_size: Optional[int] = None
    ) -> Dict[str, float]:
        """
        Entraîne pour une epoch.
        
        Args:
            train_data: Données d'entraînement
            batch_size: Taille des batches (utilise config si non spécifié)
            
        Returns:
            Dict des métriques d'entraînement
        """
        self.model.train()
        batch_size = batch_size or self.config.get('batch_size', 64)
        
        total_loss = 0.0
        total_samples = 0
        batch_losses = []
        
        n_samples = len(train_data.sequences)
        
        # === PRÉ-CHARGER TOUTES LES DONNÉES SUR GPU ===
        # Transfert unique au lieu de transfert par batch
        all_sequences = torch.tensor(
            train_data.sequences, dtype=torch.float32, device=self.device
        )
        all_masks = torch.tensor(
            train_data.masks, dtype=torch.float32, device=self.device
        )
        all_labels = {
            k: torch.tensor(v, dtype=torch.float32, device=self.device)
            for k, v in train_data.labels.items()
        }
        
        # Indices shufflés (sur GPU)
        indices = torch.randperm(n_samples, device=self.device)
        
        self.optimizer.zero_grad()
        accumulated_steps = 0
        
        for batch_idx in range(0, n_samples, batch_size):
            batch_indices = indices[batch_idx:batch_idx + batch_size]
            
            # Log progression tous les 100 batches
            batch_num = batch_idx // batch_size + 1
            total_batches = (n_samples + batch_size - 1) // batch_size
            if batch_num % 100 == 0 or batch_num == 1:
                logger.info(f"  Batch {batch_num}/{total_batches} ({100*batch_num/total_batches:.1f}%)")
            
            # Slicing direct sur GPU (ultra-rapide)
            sequences = all_sequences[batch_indices]
            masks = all_masks[batch_indices]
            labels = {k: v[batch_indices] for k, v in all_labels.items()}
            
            # Forward pass avec mixed precision
            if self.use_amp:
                with autocast('cuda'):
                    predictions = self.model(sequences, masks)
                    loss, loss_dict = self.criterion(predictions, labels)
                    
                    # Skip batch if loss is invalid
                    if not torch.isfinite(loss):
                        self.optimizer.zero_grad()
                        accumulated_steps = 0
                        continue
                    
                    loss = loss / self.accumulation_steps
                
                self.scaler.scale(loss).backward()
            else:
                predictions = self.model(sequences, masks)
                loss, loss_dict = self.criterion(predictions, labels)
                
                # Skip batch if loss is invalid
                if not torch.isfinite(loss):
                    self.optimizer.zero_grad()
                    accumulated_steps = 0
                    continue
                    
                loss = loss / self.accumulation_steps
                loss.backward()
            
            accumulated_steps += 1
            
            # Gradient accumulation step
            if accumulated_steps >= self.accumulation_steps:
                if self.use_amp:
                    self.scaler.unscale_(self.optimizer)
                    # Check for NaN gradients
                    grad_norm = torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                    if torch.isfinite(grad_norm):
                        self.scaler.step(self.optimizer)
                    self.scaler.update()
                else:
                    torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                    self.optimizer.step()
                
                self.optimizer.zero_grad()
                accumulated_steps = 0
                self.global_step += 1
            
            # Tracking - only count valid losses
            batch_loss = loss.item() * self.accumulation_steps
            if torch.isfinite(torch.tensor(batch_loss)):
                total_loss += batch_loss * len(batch_indices)
                total_samples += len(batch_indices)
                batch_losses.append(batch_loss)
            
            # Update metrics
            self.metrics.update(predictions, labels)
        
        # Dernière accumulation si incomplète
        if accumulated_steps > 0:
            if self.use_amp:
                self.scaler.step(self.optimizer)
                self.scaler.update()
            else:
                self.optimizer.step()
            self.optimizer.zero_grad()
        
        # Calculer métriques
        avg_loss = total_loss / total_samples
        metrics_result = self.metrics.compute()
        self.metrics.reset()
        
        return {
            'loss': avg_loss,
            'batch_loss_std': torch.tensor(batch_losses).std().item(),
            **{f'train_{k}': v for k, v in metrics_result.metrics.items()}
        }
    
    @torch.no_grad()
    def validate(
        self,
        val_data: SequenceData,
        batch_size: Optional[int] = None
    ) -> Dict[str, float]:
        """
        Évalue sur les données de validation.
        """
        self.model.eval()
        batch_size = batch_size or self.config.get('batch_size', 64)
        
        total_loss = 0.0
        total_samples = 0
        
        n_samples = len(val_data.sequences)
        
        for batch_idx in range(0, n_samples, batch_size):
            batch_end = min(batch_idx + batch_size, n_samples)
            
            sequences = torch.tensor(
                val_data.sequences[batch_idx:batch_end],
                dtype=torch.float32,
                device=self.device
            )
            masks = torch.tensor(
                val_data.masks[batch_idx:batch_end],
                dtype=torch.float32,
                device=self.device
            )
            labels = {
                k: torch.tensor(v[batch_idx:batch_end], dtype=torch.float32, device=self.device)
                for k, v in val_data.labels.items()
            }
            
            if self.use_amp:
                with autocast('cuda'):
                    predictions = self.model(sequences, masks)
                    loss, _ = self.criterion(predictions, labels)
            else:
                predictions = self.model(sequences, masks)
                loss, _ = self.criterion(predictions, labels)
            
            total_loss += loss.item() * (batch_end - batch_idx)
            total_samples += (batch_end - batch_idx)
            
            self.metrics.update(predictions, labels)
        
        avg_loss = total_loss / total_samples
        metrics_result = self.metrics.compute()
        self.metrics.reset()
        
        return {
            'loss': avg_loss,
            **metrics_result.metrics
        }
    
    def train(
        self,
        train_data: SequenceData,
        val_data: SequenceData,
        epochs: Optional[int] = None,
        checkpoint_dir: Optional[Path] = None,
        early_stopping_patience: Optional[int] = None,
        callbacks: Optional[List[Callable]] = None
    ) -> Dict:
        """
        Boucle d'entraînement complète.
        
        Args:
            train_data: Données d'entraînement
            val_data: Données de validation
            epochs: Nombre d'epochs (utilise config si non spécifié)
            checkpoint_dir: Répertoire pour sauvegarder les checkpoints
            early_stopping_patience: Patience pour early stopping
            callbacks: Liste de callbacks appelés après chaque epoch
            
        Returns:
            Dict avec historique d'entraînement
        """
        epochs = epochs or self.config.get('max_epochs', 100)
        early_stopping_patience = early_stopping_patience or self.config.get('early_stopping_patience', 15)
        checkpoint_dir = Path(checkpoint_dir) if checkpoint_dir else Path('data/deep_learning/checkpoints')
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Starting training for {epochs} epochs")
        logger.info(f"Train samples: {len(train_data.sequences)}, Val samples: {len(val_data.sequences)}")
        
        start_time = time.time()
        
        for epoch in range(epochs):
            self.epoch = epoch
            epoch_start = time.time()
            
            # Train
            train_metrics = self.train_epoch(train_data)
            
            # Validate
            val_metrics = self.validate(val_data)
            
            # Update scheduler
            if self.scheduler is not None:
                if isinstance(self.scheduler, ReduceLROnPlateau):
                    self.scheduler.step(val_metrics['loss'])
                else:
                    self.scheduler.step()
            
            # Current learning rate
            current_lr = self.optimizer.param_groups[0]['lr']
            
            # Log
            logger.info(
                f"Epoch {epoch+1}/{epochs} - "
                f"Train Loss: {train_metrics['loss']:.4f} - "
                f"Val Loss: {val_metrics['loss']:.4f} - "
                f"Val WinRate: {val_metrics.get('win_rate_t0.5', 0):.4f} - "
                f"LR: {current_lr:.2e} - "
                f"Time: {time.time() - epoch_start:.1f}s"
            )
            
            # History
            self.history['train_loss'].append(train_metrics['loss'])
            self.history['val_loss'].append(val_metrics['loss'])
            self.history['val_metrics'].append(val_metrics)
            self.history['learning_rate'].append(current_lr)
            
            # Moving averages
            self.moving_metrics.update(val_metrics)
            
            # Checkpointing
            is_best = False
            primary_metric = val_metrics.get('win_rate_t0.6', val_metrics.get('accuracy_t0.5', 0))
            
            if val_metrics['loss'] < self.best_val_loss:
                self.best_val_loss = val_metrics['loss']
                is_best = True
                self.patience_counter = 0
            elif primary_metric > self.best_val_metric:
                self.best_val_metric = primary_metric
                is_best = True
                self.patience_counter = 0
            else:
                self.patience_counter += 1
            
            if is_best:
                self.save_checkpoint(
                    checkpoint_dir / 'best_model.pt',
                    val_metrics
                )
            
            # Periodic checkpoint
            if (epoch + 1) % 10 == 0:
                self.save_checkpoint(
                    checkpoint_dir / f'checkpoint_epoch_{epoch+1}.pt',
                    val_metrics
                )
            
            # Callbacks
            if callbacks:
                for callback in callbacks:
                    callback(epoch, train_metrics, val_metrics, self.model)
            
            # Early stopping
            if self.patience_counter >= early_stopping_patience:
                logger.info(f"Early stopping at epoch {epoch+1}")
                break
        
        total_time = time.time() - start_time
        logger.info(f"Training completed in {total_time/60:.1f} minutes")
        
        # Sauvegarder le modèle final
        self.save_checkpoint(
            checkpoint_dir / 'final_model.pt',
            self.history['val_metrics'][-1] if self.history['val_metrics'] else {}
        )
        
        return {
            'history': self.history,
            'best_val_loss': self.best_val_loss,
            'best_val_metric': self.best_val_metric,
            'total_epochs': self.epoch + 1,
            'total_time': total_time
        }
    
    def save_checkpoint(
        self,
        path: Path,
        metrics: Optional[Dict] = None
    ):
        """Sauvegarde un checkpoint"""
        checkpoint = {
            'epoch': self.epoch,
            'global_step': self.global_step,
            'model_state_dict': self.model.state_dict(),
            'optimizer_state_dict': self.optimizer.state_dict(),
            'scheduler_state_dict': self.scheduler.state_dict() if self.scheduler else None,
            'best_val_loss': self.best_val_loss,
            'best_val_metric': self.best_val_metric,
            'config': self.config,
            'metrics': metrics,
            'timestamp': datetime.now().isoformat()
        }
        
        if self.scaler:
            checkpoint['scaler_state_dict'] = self.scaler.state_dict()
        
        torch.save(checkpoint, path)
        logger.info(f"Checkpoint saved to {path}")
    
    def load_checkpoint(self, path: Path):
        """Charge un checkpoint"""
        checkpoint = torch.load(path, map_location=self.device)
        
        self.model.load_state_dict(checkpoint['model_state_dict'])
        self.optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
        
        if self.scheduler and checkpoint.get('scheduler_state_dict'):
            self.scheduler.load_state_dict(checkpoint['scheduler_state_dict'])
        
        if self.scaler and checkpoint.get('scaler_state_dict'):
            self.scaler.load_state_dict(checkpoint['scaler_state_dict'])
        
        self.epoch = checkpoint['epoch']
        self.global_step = checkpoint['global_step']
        self.best_val_loss = checkpoint['best_val_loss']
        self.best_val_metric = checkpoint.get('best_val_metric', 0)
        
        logger.info(f"Checkpoint loaded from {path}, epoch {self.epoch}")
    
    def export_model(self, path: Path, include_optimizer: bool = False):
        """Exporte le modèle pour inférence"""
        export_dict = {
            'model_state_dict': self.model.state_dict(),
            'config': self.config,
            'input_size': self.model.input_size,
            'hidden_size': self.model.hidden_size,
            'timestamp': datetime.now().isoformat()
        }
        
        if include_optimizer:
            export_dict['optimizer_state_dict'] = self.optimizer.state_dict()
        
        torch.save(export_dict, path)
        logger.info(f"Model exported to {path}")
