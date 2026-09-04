#!/usr/bin/env python3
"""
Migre le cache OHLCV de JSON.gz vers Parquet (10-50x plus rapide à charger).

Usage:
    python scripts/migrate_cache_to_parquet.py
    python scripts/migrate_cache_to_parquet.py --keep-json
"""

import argparse
import gzip
import json
from pathlib import Path
import pandas as pd
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

CACHE_DIR = Path("data/ohlcv_cache")


def migrate_to_parquet(keep_json: bool = False):
    """Convertit tous les fichiers JSON.gz en Parquet."""
    
    json_files = list(CACHE_DIR.glob("*.json.gz"))
    
    if not json_files:
        logger.info("No JSON.gz files found to migrate")
        return
    
    logger.info(f"Found {len(json_files)} JSON.gz files to migrate")
    
    total_json_size = 0
    total_parquet_size = 0
    
    for json_path in json_files:
        parquet_path = json_path.with_suffix('').with_suffix('.parquet')
        
        if parquet_path.exists():
            logger.info(f"  Skip {json_path.name} (parquet exists)")
            continue
        
        try:
            with gzip.open(json_path, 'rt', encoding='utf-8') as f:
                data = json.load(f)
            
            if not data:
                logger.warning(f"  Skip {json_path.name} (empty)")
                continue
            
            if isinstance(data[0], dict):
                df = pd.DataFrame(data)
            else:
                df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            df.to_parquet(parquet_path, compression='snappy', index=False)
            
            json_size = json_path.stat().st_size / 1024 / 1024
            parquet_size = parquet_path.stat().st_size / 1024 / 1024
            
            total_json_size += json_size
            total_parquet_size += parquet_size
            
            logger.info(f"  ✓ {json_path.name}: {json_size:.1f}MB -> {parquet_size:.1f}MB ({len(df)} rows)")
            
            if not keep_json:
                json_path.unlink()
                
        except Exception as e:
            logger.error(f"  ✗ {json_path.name}: {e}")
    
    logger.info(f"\nMigration complete!")
    if total_parquet_size > 0:
        logger.info(f"Total: {total_json_size:.1f}MB -> {total_parquet_size:.1f}MB")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--keep-json', action='store_true')
    args = parser.parse_args()
    migrate_to_parquet(keep_json=args.keep_json)
