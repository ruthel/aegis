#!/usr/bin/env python3
"""
Pré-calcule et sauvegarde les features DL pour accélérer le training.
Lance ce script une fois, puis les trainings suivants seront instantanés.

Usage:
    python scripts/precompute_features.py
    python scripts/precompute_features.py --limit 10000
"""

import argparse
import sys
from pathlib import Path
import numpy as np
import logging
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.deep_learning.data.data_loader import DLDataLoader
from core.deep_learning.data.feature_engineer import FeatureEngineer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

CACHE_DIR = Path("data/deep_learning/feature_cache")


def precompute_features(symbols: list, limit: int = None):
    """Pré-calcule les features pour tous les symboles."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    
    loader = DLDataLoader()
    feature_engineer = FeatureEngineer()
    
    # Charger BTC pour corrélations
    btc_df = loader.load_historical_data('BTCUSD', '15m', limit=limit)
    logger.info(f"Loaded BTC reference: {len(btc_df)} rows")
    
    for symbol in symbols:
        logger.info(f"\n{'='*50}")
        logger.info(f"Processing {symbol}...")
        
        start_time = datetime.now()
        
        # Charger données principales
        df = loader.load_historical_data(symbol, '15m', limit=limit)
        if len(df) < 120:
            logger.warning(f"Not enough data for {symbol}")
            continue
        
        logger.info(f"  Loaded {len(df)} rows")
        
        # Charger multi-TF
        mtf_data = loader.load_multi_timeframe_data(symbol, limit=limit)
        logger.info(f"  Loaded MTF: {list(mtf_data.keys())}")
        
        # Calculer features
        logger.info(f"  Computing features...")
        feature_result = feature_engineer.compute_all_features(
            df,
            btc_df if symbol not in ['BTCUSD', 'BTCUSDT'] else None,
            timeframes=mtf_data
        )
        
        # Sauvegarder
        cache_file = CACHE_DIR / f"{symbol}_features.npz"
        np.savez_compressed(
            cache_file,
            features=feature_result.features,
            timestamps=df['timestamp'].values,
            close=df['close'].values,
            feature_names=feature_result.feature_names
        )
        
        elapsed = (datetime.now() - start_time).total_seconds()
        size_mb = cache_file.stat().st_size / 1024 / 1024
        
        logger.info(f"  ✓ Saved to {cache_file}")
        logger.info(f"  ✓ Shape: {feature_result.features.shape}")
        logger.info(f"  ✓ Size: {size_mb:.1f} MB")
        logger.info(f"  ✓ Time: {elapsed:.1f}s")
    
    logger.info(f"\n{'='*50}")
    logger.info("Feature precomputation complete!")
    logger.info(f"Cache directory: {CACHE_DIR}")


def main():
    parser = argparse.ArgumentParser(description='Precompute DL features')
    parser.add_argument('--limit', type=int, help='Limit rows per symbol')
    parser.add_argument('--symbols', nargs='+', default=['BTCUSD', 'ETHUSD', 'ADAUSD', 'SOLUSD'])
    args = parser.parse_args()
    
    precompute_features(args.symbols, args.limit)


if __name__ == "__main__":
    main()
