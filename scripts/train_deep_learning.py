#!/usr/bin/env python3
"""
Script d'entraînement initial du modèle Deep Learning AEGIS
===========================================================

Entraîne le modèle LSTM-Attention sur les données historiques.
À exécuter une fois pour créer le modèle initial.

Usage:
    python scripts/train_deep_learning.py [options]

Options:
    --symbols       Symboles à utiliser (défaut: tous)
    --epochs        Nombre d'epochs (défaut: 100)
    --batch-size    Taille des batches (défaut: 64)
    --lr            Learning rate (défaut: 1e-4)
    --device        cuda ou cpu (défaut: auto)
    --resume        Reprendre depuis un checkpoint
    --eval-only     Évaluer seulement (pas d'entraînement)
"""

import sys
import os
import argparse
import logging
from pathlib import Path
from datetime import datetime
import uuid
import json

# Ajouter le répertoire racine au path
sys.path.insert(0, str(Path(__file__).parent.parent))

import torch
import numpy as np

from core.deep_learning.config import DLConfig
from core.deep_learning.data.data_loader import DLDataLoader
from core.deep_learning.data.sequence_builder import SequenceBuilder
from core.deep_learning.models.lstm_attention import LSTMAttentionModel, create_model
from core.deep_learning.training.trainer import DLTrainer
from core.deep_learning.training.metrics import TradingMetrics

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('data/deep_learning/training.log')
    ]
)
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description='Train AEGIS Deep Learning Model')
    
    parser.add_argument('--symbols', type=str, nargs='+', 
                       default=['BTCUSD', 'ETHUSD', 'ADAUSD', 'SOLUSD'],
                       help='Trading symbols to use')
    parser.add_argument('--epochs', type=int, default=100,
                       help='Number of training epochs')
    parser.add_argument('--batch-size', type=int, default=64,
                       help='Batch size')
    parser.add_argument('--lr', type=float, default=1e-4,
                       help='Learning rate')
    parser.add_argument('--device', type=str, default='auto',
                       help='Device: cuda, cpu, or auto')
    parser.add_argument('--resume', type=str, default=None,
                       help='Path to checkpoint to resume from')
    parser.add_argument('--eval-only', action='store_true',
                       help='Only evaluate, no training')
    parser.add_argument('--start-date', type=str, default=None,
                       help='Start date for training data (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, default=None,
                       help='End date for training data (YYYY-MM-DD)')
    parser.add_argument('--limit', type=int, default=None,
                       help='Limit number of candles per symbol (e.g., 96 for 1 day of 15m)')
    parser.add_argument('--augment', action='store_true', default=True,
                       help='Use data augmentation')
    parser.add_argument('--no-augment', action='store_false', dest='augment',
                       help='Disable data augmentation')
    
    return parser.parse_args()


def setup_directories():
    """Crée les répertoires nécessaires"""
    dirs = [
        'data/deep_learning',
        'data/deep_learning/models',
        'data/deep_learning/checkpoints',
        'data/deep_learning/logs'
    ]
    for d in dirs:
        Path(d).mkdir(parents=True, exist_ok=True)


def log_to_db(training_id: str, status: str, metrics: dict = None, error: str = None):
    """Enregistre l'état de l'entraînement dans la DB"""
    try:
        from core.db_orm import (
            DLTrainingHistory, create_session_factory, now_iso
        )
        
        db_path = 'data/aegis_db.sqlite3'
        if not Path(db_path).exists():
            logger.warning(f"Database not found at {db_path}")
            return
        
        SessionFactory = create_session_factory(db_path)
        
        with SessionFactory() as session:
            # Chercher ou créer l'entrée
            entry = session.query(DLTrainingHistory).filter_by(
                training_id=training_id
            ).first()
            
            if entry is None:
                entry = DLTrainingHistory(
                    training_id=training_id,
                    started_at=now_iso(),
                    training_type='initial',
                    status=status,
                    created_at=now_iso()
                )
                session.add(entry)
            
            entry.status = status
            entry.updated_at = now_iso()
            
            if status == 'completed':
                entry.completed_at = now_iso()
            
            if metrics:
                entry.train_loss = metrics.get('train_loss')
                entry.val_loss = metrics.get('val_loss')
                entry.test_loss = metrics.get('test_loss')
                entry.val_accuracy = metrics.get('val_accuracy')
                entry.val_win_rate = metrics.get('val_win_rate')
                entry.val_auc = metrics.get('val_auc')
                entry.epochs_completed = metrics.get('epochs')
                entry.train_samples = metrics.get('train_samples')
                entry.val_samples = metrics.get('val_samples')
                entry.model_path = metrics.get('model_path')
            
            if error:
                entry.error_message = error
            
            session.commit()
            
    except Exception as e:
        logger.error(f"Failed to log to DB: {e}")


def train(args):
    """Fonction principale d'entraînement"""
    training_id = str(uuid.uuid4())[:8]
    logger.info(f"Starting training session: {training_id}")
    
    # Setup
    setup_directories()
    
    # Device
    if args.device == 'auto':
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
    else:
        device = args.device
    
    logger.info(f"Using device: {device}")
    if device == 'cuda':
        logger.info(f"GPU: {torch.cuda.get_device_name(0)}")
    
    # Configuration
    config = DLConfig()
    config.training.batch_size = args.batch_size
    config.training.learning_rate = args.lr
    config.training.max_epochs = args.epochs
    config.training.device = device
    
    # Log start
    log_to_db(training_id, 'starting')
    
    try:
        # =====================================================================
        # CHARGEMENT DES DONNÉES
        # =====================================================================
        logger.info("Loading data...")
        
        data_loader = DLDataLoader(
            db_path='data/aegis_db.sqlite3',
            sequence_length=config.model.sequence_length,
            batch_size=args.batch_size,
            validation_split=config.training.validation_split,
            test_split=config.training.test_split
        )
        
        # Statistiques des données
        data_stats = data_loader.get_data_statistics()
        logger.info(f"Available symbols: {data_stats.get('symbols', [])}")
        logger.info(f"Total trades in DB: {data_stats.get('n_trades', 0)}")
        
        # Charger et préparer les données
        train_data, val_data, test_data = data_loader.prepare_training_data(
            symbols=args.symbols,
            start_date=args.start_date,
            end_date=args.end_date,
            use_trades_labels=True,
            limit=args.limit
        )
        
        logger.info(f"Train samples: {train_data.metadata['n_sequences']}")
        logger.info(f"Val samples: {val_data.metadata['n_sequences']}")
        logger.info(f"Test samples: {test_data.metadata['n_sequences']}")
        
        # Augmentation des données
        if args.augment and train_data.metadata['n_sequences'] > 0:
            logger.info("Augmenting training data...")
            sequence_builder = SequenceBuilder(
                sequence_length=config.model.sequence_length
            )
            train_data = sequence_builder.augment_sequences(
                train_data,
                noise_std=config.training.noise_std,
                time_warp_prob=config.training.time_warp_prob,
                augmentation_factor=2
            )
            logger.info(f"Augmented train samples: {train_data.metadata['n_sequences']}")
        
        # =====================================================================
        # CRÉATION DU MODÈLE
        # =====================================================================
        logger.info("Creating model...")
        
        model_config = {
            'input_size': config.model.input_size,
            'hidden_size': config.model.hidden_size,
            'num_lstm_layers': config.model.num_lstm_layers,
            'num_attention_heads': config.model.num_attention_heads,
            'dropout': config.model.dropout,
            'lstm_dropout': config.model.lstm_dropout,
            'attention_dropout': config.model.attention_dropout,
            'bidirectional': config.model.bidirectional,
            'use_layer_norm': config.model.layer_norm,
            'use_residual': config.model.residual_connections,
            'use_positional_encoding': config.model.use_positional_encoding,
        }
        
        model = create_model(model_config)
        
        n_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
        logger.info(f"Model parameters: {n_params:,}")
        
        # =====================================================================
        # ENTRAÎNEMENT
        # =====================================================================
        if not args.eval_only:
            logger.info("Starting training...")
            log_to_db(training_id, 'running')
            
            trainer_config = {
                'learning_rate': args.lr,
                'weight_decay': config.training.weight_decay,
                'optimizer': config.training.optimizer,
                'scheduler': config.training.scheduler,
                'batch_size': args.batch_size,
                'accumulation_steps': config.training.accumulation_steps,
                'max_epochs': args.epochs,
                'early_stopping_patience': config.training.early_stopping_patience,
                'loss_weights': config.training.loss_weights,
                'focal_alpha': config.training.focal_alpha,
                'focal_gamma': config.training.focal_gamma,
                'mixed_precision': config.training.mixed_precision,
            }
            
            trainer = DLTrainer(model, trainer_config, device)
            
            # Reprendre si checkpoint spécifié
            if args.resume:
                logger.info(f"Resuming from {args.resume}")
                trainer.load_checkpoint(Path(args.resume))
            
            # Lancer l'entraînement
            checkpoint_dir = Path('data/deep_learning/checkpoints') / training_id
            
            result = trainer.train(
                train_data=train_data,
                val_data=val_data,
                epochs=args.epochs,
                checkpoint_dir=checkpoint_dir,
                early_stopping_patience=config.training.early_stopping_patience
            )
            
            logger.info(f"Training completed!")
            logger.info(f"Best val loss: {result['best_val_loss']:.4f}")
            logger.info(f"Total epochs: {result['total_epochs']}")
            logger.info(f"Total time: {result['total_time']/60:.1f} minutes")
            
            # Sauvegarder le modèle final
            model_path = Path('data/deep_learning/models') / f'model_{training_id}.pt'
            trainer.export_model(model_path)
            
            # Sauvegarder le normalizer
            normalizer_path = Path('data/deep_learning/models') / 'normalizer.json'
            data_loader.normalizer.save(normalizer_path)
            
            # Sauvegarder la config
            config_path = Path('data/deep_learning/models') / 'config.json'
            with open(config_path, 'w') as f:
                json.dump(model_config, f, indent=2)
        
        # =====================================================================
        # ÉVALUATION FINALE
        # =====================================================================
        logger.info("Evaluating on test set...")
        
        if args.eval_only and args.resume:
            # Charger le modèle pour évaluation
            checkpoint = torch.load(args.resume, map_location=device)
            model.load_state_dict(checkpoint['model_state_dict'])
        
        model.eval()
        model.to(device)
        
        # Évaluation
        metrics = TradingMetrics()
        
        with torch.no_grad():
            for batch_idx in range(0, len(test_data.sequences), args.batch_size):
                batch_end = min(batch_idx + args.batch_size, len(test_data.sequences))
                
                sequences = torch.tensor(
                    test_data.sequences[batch_idx:batch_end],
                    dtype=torch.float32,
                    device=device
                )
                masks = torch.tensor(
                    test_data.masks[batch_idx:batch_end],
                    dtype=torch.float32,
                    device=device
                )
                labels = {
                    k: torch.tensor(v[batch_idx:batch_end], dtype=torch.float32, device=device)
                    for k, v in test_data.labels.items()
                }
                
                predictions = model(sequences, masks)
                metrics.update(predictions, labels)
        
        test_metrics = metrics.compute()
        
        logger.info("=" * 60)
        logger.info("TEST RESULTS")
        logger.info("=" * 60)
        logger.info(f"Accuracy (t=0.5): {test_metrics.metrics.get('accuracy_t0.5', 0):.4f}")
        logger.info(f"Win Rate (t=0.5): {test_metrics.metrics.get('win_rate_t0.5', 0):.4f}")
        logger.info(f"Win Rate (t=0.6): {test_metrics.metrics.get('win_rate_t0.6', 0):.4f}")
        logger.info(f"Win Rate (t=0.7): {test_metrics.metrics.get('win_rate_t0.7', 0):.4f}")
        logger.info(f"AUC-ROC: {test_metrics.metrics.get('auc_roc', 0):.4f}")
        logger.info(f"Brier Score: {test_metrics.metrics.get('brier_score', 0):.4f}")
        logger.info(f"Calibration Error: {test_metrics.metrics.get('calibration_error', 0):.4f}")
        logger.info(f"Precision: {test_metrics.metrics.get('precision', 0):.4f}")
        logger.info(f"Recall: {test_metrics.metrics.get('recall', 0):.4f}")
        logger.info(f"F1: {test_metrics.metrics.get('f1', 0):.4f}")
        
        # Trading simulation metrics
        logger.info("-" * 40)
        logger.info("TRADING SIMULATION")
        for thresh in [0.5, 0.6, 0.7, 0.8]:
            wr = test_metrics.metrics.get(f'sim_win_rate_t{thresh}', 0)
            pf = test_metrics.metrics.get(f'sim_profit_factor_t{thresh}', 0)
            ev = test_metrics.metrics.get(f'sim_expected_value_t{thresh}', 0)
            nt = test_metrics.metrics.get(f'sim_n_trades_t{thresh}', 0)
            logger.info(f"  t={thresh}: WinRate={wr:.2%}, PF={pf:.2f}, EV={ev:.4f}, Trades={nt}")
        
        # Log success to DB
        log_to_db(training_id, 'completed', {
            'train_loss': result['history']['train_loss'][-1] if not args.eval_only else None,
            'val_loss': result['best_val_loss'] if not args.eval_only else None,
            'test_loss': test_metrics.metrics.get('brier_score'),
            'val_accuracy': test_metrics.metrics.get('accuracy_t0.5'),
            'val_win_rate': test_metrics.metrics.get('win_rate_t0.6'),
            'val_auc': test_metrics.metrics.get('auc_roc'),
            'epochs': result['total_epochs'] if not args.eval_only else 0,
            'train_samples': train_data.metadata['n_sequences'],
            'val_samples': val_data.metadata['n_sequences'],
            'model_path': str(model_path) if not args.eval_only else args.resume
        })
        
        # Sauvegarder les métriques
        metrics_path = Path('data/deep_learning/logs') / f'test_metrics_{training_id}.json'
        with open(metrics_path, 'w') as f:
            json.dump(test_metrics.metrics, f, indent=2, default=str)
        
        logger.info(f"Metrics saved to {metrics_path}")
        logger.info(f"Training session {training_id} completed successfully!")
        
        return 0
        
    except Exception as e:
        logger.error(f"Training failed: {e}", exc_info=True)
        log_to_db(training_id, 'failed', error=str(e))
        return 1


if __name__ == '__main__':
    args = parse_args()
    sys.exit(train(args))
