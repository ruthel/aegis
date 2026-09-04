#!/usr/bin/env python3
"""
Script d'évolution continue du modèle Deep Learning AEGIS
=========================================================

Met à jour le modèle de manière incrémentale avec les nouvelles données.
Utilise EWC, Replay Buffer, et Drift Detection pour éviter l'oubli.

Usage:
    python scripts/evolve_deep_learning.py [options]

Options:
    --model-path    Chemin vers le modèle à faire évoluer
    --n-updates     Nombre d'updates à effectuer (défaut: 100)
    --force-update  Forcer un update même sans nouvelles données
    --check-drift   Vérifier le drift seulement (pas d'update)
"""

import sys
import os
import argparse
import logging
from pathlib import Path
from datetime import datetime, timedelta
import uuid
import json

# Ajouter le répertoire racine au path
sys.path.insert(0, str(Path(__file__).parent.parent))

import torch
import numpy as np

from core.deep_learning.config import DLConfig
from core.deep_learning.data.data_loader import DLDataLoader
from core.deep_learning.data.feature_engineer import FeatureEngineer
from core.deep_learning.data.normalizer import AdaptiveNormalizer
from core.deep_learning.models.lstm_attention import LSTMAttentionModel, create_model
from core.deep_learning.evolution.online_learner import OnlineLearner
from core.deep_learning.evolution.ewc import ElasticWeightConsolidation
from core.deep_learning.evolution.replay_buffer import StratifiedReplayBuffer
from core.deep_learning.evolution.drift_detector import DriftDetector

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('data/deep_learning/evolution.log')
    ]
)
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description='Evolve AEGIS Deep Learning Model')
    
    parser.add_argument('--model-path', type=str, 
                       default='data/deep_learning/models/model_latest.pt',
                       help='Path to model to evolve')
    parser.add_argument('--n-updates', type=int, default=100,
                       help='Number of evolution updates')
    parser.add_argument('--force-update', action='store_true',
                       help='Force update even without new data')
    parser.add_argument('--check-drift', action='store_true',
                       help='Only check drift, no update')
    parser.add_argument('--lookback-hours', type=int, default=24,
                       help='Hours of recent data to use')
    parser.add_argument('--device', type=str, default='auto',
                       help='Device: cuda, cpu, or auto')
    parser.add_argument('--report', action='store_true',
                       help='Generate evolution report')
    
    return parser.parse_args()


def log_evolution_to_db(metric_id: str, metrics: dict):
    """Enregistre les métriques d'évolution dans la DB"""
    try:
        from core.db_orm import (
            DLEvolutionMetrics, create_session_factory, now_iso
        )
        
        db_path = 'data/aegis_db.sqlite3'
        if not Path(db_path).exists():
            return
        
        SessionFactory = create_session_factory(db_path)
        
        with SessionFactory() as session:
            entry = DLEvolutionMetrics(
                metric_id=metric_id,
                timestamp=now_iso(),
                update_count=metrics.get('update_count'),
                samples_processed=metrics.get('samples_processed'),
                total_loss=metrics.get('total_loss'),
                base_loss=metrics.get('base_loss'),
                replay_loss=metrics.get('replay_loss'),
                ewc_loss=metrics.get('ewc_loss'),
                drift_detected=1 if metrics.get('drift_detected') else 0,
                drift_score=metrics.get('drift_score'),
                drift_type=metrics.get('drift_type'),
                adaptation_rate=metrics.get('adaptation_rate'),
                learning_rate=metrics.get('learning_rate'),
                replay_buffer_size=metrics.get('buffer_size'),
                replay_buffer_fill_ratio=metrics.get('buffer_fill_ratio'),
                rolling_win_rate=metrics.get('rolling_win_rate'),
                rolling_pnl=metrics.get('rolling_pnl'),
                created_at=now_iso()
            )
            session.add(entry)
            session.commit()
            
    except Exception as e:
        logger.error(f"Failed to log evolution metrics: {e}")


def load_recent_trades(hours: int = 24):
    """Charge les trades récents depuis la DB"""
    try:
        import sqlite3
        import pandas as pd
        
        db_path = 'data/aegis_db.sqlite3'
        if not Path(db_path).exists():
            return []
        
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        
        with sqlite3.connect(db_path) as conn:
            # Charger les décisions récentes
            query = """
                SELECT 
                    d.event_id, d.timestamp, d.symbol, d.decision, 
                    d.p_win, d.confidence, d.net_pnl_pct,
                    d.action_type, d.mode
                FROM decision_logs d
                WHERE d.timestamp >= ?
                ORDER BY d.timestamp ASC
            """
            df = pd.read_sql_query(query, conn, params=[cutoff])
        
        # Convertir en liste de dicts
        trades = df.to_dict('records')
        logger.info(f"Loaded {len(trades)} recent decisions")
        return trades
        
    except Exception as e:
        logger.error(f"Failed to load recent trades: {e}")
        return []


def load_recent_ohlcv(symbol: str, hours: int = 24):
    """Charge les données OHLCV récentes"""
    try:
        import sqlite3
        import pandas as pd
        
        db_path = 'data/aegis_db.sqlite3'
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        
        with sqlite3.connect(db_path) as conn:
            query = """
                SELECT timestamp, open, high, low, close, volume
                FROM ohlcv_data
                WHERE symbol = ? AND timestamp >= ?
                ORDER BY timestamp ASC
            """
            df = pd.read_sql_query(query, conn, params=[symbol, cutoff])
        
        return df
        
    except Exception as e:
        logger.error(f"Failed to load OHLCV for {symbol}: {e}")
        return None


def evolve(args):
    """Fonction principale d'évolution"""
    session_id = str(uuid.uuid4())[:8]
    logger.info(f"Starting evolution session: {session_id}")
    
    # Device
    if args.device == 'auto':
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
    else:
        device = args.device
    
    logger.info(f"Using device: {device}")
    
    # Configuration
    config = DLConfig()
    
    # =========================================================================
    # CHARGEMENT DU MODÈLE
    # =========================================================================
    model_path = Path(args.model_path)
    
    if not model_path.exists():
        logger.error(f"Model not found: {model_path}")
        return 1
    
    logger.info(f"Loading model from {model_path}")
    
    checkpoint = torch.load(model_path, map_location=device)
    
    # Charger la config du modèle
    config_path = model_path.parent / 'config.json'
    if config_path.exists():
        with open(config_path, 'r') as f:
            model_config = json.load(f)
    else:
        model_config = {
            'input_size': config.model.input_size,
            'hidden_size': config.model.hidden_size,
            'num_lstm_layers': config.model.num_lstm_layers,
            'num_attention_heads': config.model.num_attention_heads,
            'dropout': 0.0,  # Pas de dropout pour évolution
            'bidirectional': config.model.bidirectional,
        }
    
    model = create_model(model_config)
    model.load_state_dict(checkpoint['model_state_dict'])
    model.to(device)
    
    logger.info(f"Model loaded: {sum(p.numel() for p in model.parameters()):,} parameters")
    
    # Charger le normalizer
    normalizer_path = model_path.parent / 'normalizer.json'
    if normalizer_path.exists():
        normalizer = AdaptiveNormalizer.load(normalizer_path)
    else:
        logger.warning("Normalizer not found, creating new one")
        normalizer = AdaptiveNormalizer(n_features=78)
    
    # =========================================================================
    # CRÉER L'ONLINE LEARNER
    # =========================================================================
    evolution_config = {
        'ewc_lambda': config.evolution.ewc_lambda,
        'ewc_gamma': config.evolution.ewc_gamma,
        'replay_buffer_size': config.evolution.replay_buffer_size,
        'replay_sample_ratio': config.evolution.replay_sample_ratio,
        'priority_alpha': config.evolution.priority_alpha,
        'priority_beta': config.evolution.priority_beta,
        'drift_window_size': config.evolution.drift_window_size,
        'drift_threshold': config.evolution.drift_threshold,
        'online_learning_rate': config.evolution.online_learning_rate,
        'update_frequency': config.evolution.update_frequency,
        'min_samples_update': config.evolution.min_samples_update,
        'checkpoint_frequency': config.evolution.checkpoint_frequency,
        'checkpoint_path': str(Path('data/deep_learning/checkpoints') / session_id),
        'batch_size': 32,
    }
    
    online_learner = OnlineLearner(model, evolution_config, device)
    
    # Charger l'état précédent si disponible
    ewc_path = model_path.parent / 'ewc_state.pt'
    if ewc_path.exists():
        online_learner.ewc.load(ewc_path)
        logger.info("Loaded previous EWC state")
    
    buffer_path = model_path.parent / 'replay_buffer.pt'
    if buffer_path.exists():
        online_learner.replay_buffer.load(buffer_path)
        logger.info(f"Loaded replay buffer: {online_learner.replay_buffer.size} experiences")
    
    # =========================================================================
    # CHARGER LES DONNÉES RÉCENTES
    # =========================================================================
    logger.info(f"Loading recent data (last {args.lookback_hours}h)...")
    
    recent_trades = load_recent_trades(args.lookback_hours)
    
    if not recent_trades and not args.force_update:
        logger.info("No recent trades, nothing to evolve")
        return 0
    
    # Feature engineer
    feature_engineer = FeatureEngineer()
    
    # Symboles à traiter
    symbols = list(set(t['symbol'] for t in recent_trades if t.get('symbol')))
    if not symbols:
        symbols = ['BTCUSDT', 'ETHUSDT']
    
    logger.info(f"Processing symbols: {symbols}")
    
    # =========================================================================
    # CHECK DRIFT ONLY
    # =========================================================================
    if args.check_drift:
        logger.info("Checking for drift...")
        
        for symbol in symbols:
            df = load_recent_ohlcv(symbol, args.lookback_hours)
            if df is None or len(df) < 100:
                continue
            
            # Calculer features
            features = feature_engineer.compute_all_features(df)
            
            # Ajouter au drift detector
            for i in range(len(features.features)):
                online_learner.drift_detector.add_sample(
                    features=features.features[i],
                    prediction=0.5,  # Placeholder
                    actual=0.5,
                    performance_metric=None
                )
        
        # Vérifier le drift
        drift_result = online_learner.drift_detector.check_drift()
        
        logger.info("=" * 60)
        logger.info("DRIFT CHECK RESULTS")
        logger.info("=" * 60)
        logger.info(f"Drift detected: {drift_result['drift_detected']}")
        logger.info(f"Warning detected: {drift_result['warning_detected']}")
        logger.info(f"Drift score: {drift_result['drift_score']:.4f}")
        logger.info(f"Drift type: {drift_result.get('drift_type', 'none')}")
        logger.info(f"Feature drift: {drift_result['details'].get('feature_drift', 0):.4f}")
        logger.info(f"Performance drift: {drift_result['details'].get('performance_drift', 0):.4f}")
        logger.info(f"Concept drift: {drift_result['details'].get('concept_drift', 0):.4f}")
        
        return 0
    
    # =========================================================================
    # ÉVOLUTION
    # =========================================================================
    logger.info(f"Starting evolution with {args.n_updates} updates...")
    
    n_experiences_added = 0
    
    # Ajouter les expériences récentes
    for trade in recent_trades:
        symbol = trade.get('symbol')
        if not symbol:
            continue
        
        # Charger les données autour du trade
        df = load_recent_ohlcv(symbol, 2)  # 2h autour du trade
        if df is None or len(df) < 60:
            continue
        
        # Calculer features
        try:
            features = feature_engineer.compute_all_features(df)
            normalized = normalizer.transform(features.features)
            
            # Dernière séquence
            if len(normalized) >= 60:
                sequence = normalized[-60:]
                mask = np.ones(60, dtype=np.float32)
                
                # Labels
                pnl = trade.get('net_pnl_pct', 0) or 0
                labels = {
                    'win_probability': 1.0 if pnl > 0 else 0.0,
                    'continue_probability': 0.5,
                    'optimal_sizing': 0.5
                }
                
                # Prédiction du modèle
                model.eval()
                with torch.no_grad():
                    seq_tensor = torch.tensor(sequence[np.newaxis, ...], dtype=torch.float32, device=device)
                    mask_tensor = torch.tensor(mask[np.newaxis, ...], dtype=torch.float32, device=device)
                    pred = model(seq_tensor, mask_tensor)
                    prediction = {
                        'win_probability': pred['win_probability'].item(),
                        'continue_probability': pred['continue_probability'].item(),
                        'optimal_sizing': pred['optimal_sizing'].item()
                    }
                
                # Ajouter l'expérience
                online_learner.add_experience(
                    sequence=sequence,
                    mask=mask,
                    labels=labels,
                    prediction=prediction,
                    timestamp=trade.get('timestamp'),
                    actual_outcome=1.0 if pnl > 0 else 0.0
                )
                
                n_experiences_added += 1
                
        except Exception as e:
            logger.debug(f"Failed to process trade: {e}")
            continue
    
    logger.info(f"Added {n_experiences_added} experiences to buffer")
    
    # Forcer les updates si demandé
    if args.force_update:
        for _ in range(args.n_updates):
            if online_learner.replay_buffer.size >= online_learner.min_samples_update:
                online_learner._maybe_update()
    
    # =========================================================================
    # RAPPORT
    # =========================================================================
    stats = online_learner.evaluate_performance()
    
    logger.info("=" * 60)
    logger.info("EVOLUTION SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Update count: {stats['update_count']}")
    logger.info(f"Buffer size: {stats['buffer_size']}")
    logger.info(f"Buffer fill: {stats['buffer_stats'].get('fill_ratio', 0):.1%}")
    logger.info(f"EWC tasks: {stats['ewc_n_tasks']}")
    
    if 'recent_avg_loss' in stats:
        logger.info(f"Recent avg loss: {stats['recent_avg_loss']:.4f}")
    if 'recent_drift_rate' in stats:
        logger.info(f"Recent drift rate: {stats['recent_drift_rate']:.1%}")
    
    drift_stats = stats.get('drift_stats', {})
    if drift_stats:
        logger.info(f"Samples since reset: {drift_stats.get('samples_since_reset', 0)}")
        logger.info(f"Total drift events: {drift_stats.get('drift_count', 0)}")
    
    # Vérifier si rollback nécessaire
    should_rollback, reason = online_learner.should_rollback()
    if should_rollback:
        logger.warning(f"Rollback recommended: {reason}")
        user_input = input("Rollback to best checkpoint? (y/n): ")
        if user_input.lower() == 'y':
            online_learner.rollback_to_best()
            logger.info("Rolled back to best checkpoint")
    
    # Sauvegarder l'état
    logger.info("Saving evolution state...")
    
    # Sauvegarder le modèle évolué
    evolved_model_path = model_path.parent / 'model_evolved.pt'
    torch.save({
        'model_state_dict': model.state_dict(),
        'config': model_config,
        'evolution_session': session_id,
        'update_count': stats['update_count']
    }, evolved_model_path)
    
    # Sauvegarder EWC et buffer
    online_learner.ewc.save(model_path.parent / 'ewc_state.pt')
    online_learner.replay_buffer.save(model_path.parent / 'replay_buffer.pt')
    
    # Mettre à jour le normalizer
    normalizer.save(normalizer_path)
    
    # Log to DB
    log_evolution_to_db(str(uuid.uuid4())[:8], {
        'update_count': stats['update_count'],
        'samples_processed': n_experiences_added,
        'buffer_size': stats['buffer_size'],
        'buffer_fill_ratio': stats['buffer_stats'].get('fill_ratio'),
        'drift_detected': drift_stats.get('drift_detected', False),
        'drift_score': drift_stats.get('last_check', {}).get('drift_score') if drift_stats.get('last_check') else None,
    })
    
    logger.info(f"Evolution session {session_id} completed!")
    
    # Générer rapport si demandé
    if args.report:
        report_path = Path('data/deep_learning/logs') / f'evolution_report_{session_id}.txt'
        with open(report_path, 'w') as f:
            f.write("AEGIS Deep Learning Evolution Report\n")
            f.write("=" * 60 + "\n")
            f.write(f"Session: {session_id}\n")
            f.write(f"Date: {datetime.now().isoformat()}\n")
            f.write(f"Model: {model_path}\n")
            f.write("\n")
            f.write(json.dumps(stats, indent=2, default=str))
        
        logger.info(f"Report saved to {report_path}")
    
    return 0


if __name__ == '__main__':
    args = parse_args()
    sys.exit(evolve(args))
