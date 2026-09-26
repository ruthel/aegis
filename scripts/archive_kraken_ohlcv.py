"""Incrementally archive Kraken OHLCV for exchange-specific ML features.

Kraken public OHLCV exposes a limited recent window. Running this script periodically
builds a local, growing Kraken-native dataset so volume/VWAP/microstructure-adjacent
features can eventually be trained on the same venue used live.
"""
import argparse
import gzip
import json
import os
import sys
from datetime import datetime, timezone

import ccxt
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.currency import make_symbol


def _path(root, symbol, timeframe):
    os.makedirs(root, exist_ok=True)
    return os.path.join(root, f"{symbol.replace('/', '-')}_{timeframe}.json.gz")


def _load(path):
    if not os.path.exists(path):
        return []
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(path, rows):
    tmp = path + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(rows, fh, separators=(",", ":"))
    os.replace(tmp, path)


def archive_symbol(exchange, root, symbol, timeframe, keep=330000):
    path = _path(root, symbol, timeframe)
    existing = _load(path)
    merged = {int(row["timestamp"]): row for row in existing if row.get("timestamp") is not None}

    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=720)
    for row in raw or []:
        merged[int(row[0])] = {
            "timestamp": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        }

    rows = sorted(merged.values(), key=lambda x: int(x["timestamp"]))
    if len(rows) > keep:
        rows = rows[-keep:]
    _save(path, rows)
    first = datetime.fromtimestamp(rows[0]["timestamp"] / 1000, timezone.utc).isoformat() if rows else "n/a"
    last = datetime.fromtimestamp(rows[-1]["timestamp"] / 1000, timezone.utc).isoformat() if rows else "n/a"
    print(f"{symbol} {timeframe}: {len(rows)} bougies | {first} -> {last}")


def archive_universe(pairs=None, timeframes=None, root=None, keep=None):
    """Archive Kraken for a universe; safe to call before training.

    Public OHLCV only, rate limiting delegated to CCXT. Failures are isolated per
    symbol/timeframe so an unavailable market never aborts model training.
    """
    pairs = pairs or [make_symbol(base) for base in ("BTC", "ETH", "SOL", "ADA")]
    timeframes = timeframes or ["5m", "15m", "1h", "4h", "1d"]
    root = root or os.getenv("ML_KRAKEN_ARCHIVE_DIR", "data/kraken_ohlcv")
    keep = int(keep or os.getenv("ML_TRAINING_MAX_CANDLES", "330000"))
    exchange = ccxt.kraken({"enableRateLimit": True})
    exchange.load_markets()

    summary = {"updated": 0, "failed": 0}
    for symbol in pairs:
        if symbol not in exchange.markets:
            summary["failed"] += len(timeframes)
            continue
        for timeframe in timeframes:
            try:
                archive_symbol(exchange, root, symbol, timeframe, keep=keep)
                summary["updated"] += 1
            except Exception as exc:
                summary["failed"] += 1
                print(f"⚠️ {symbol} {timeframe}: {exc}")
    return summary


def main():
    load_dotenv(".env", override=True)
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", default=",".join(make_symbol(base) for base in ("BTC", "ETH", "SOL", "ADA")))
    parser.add_argument("--timeframes", default="5m,15m,1h,4h,1d")
    args = parser.parse_args()

    pairs = [x.strip() for x in args.pairs.split(",") if x.strip()]
    timeframes = [x.strip() for x in args.timeframes.split(",") if x.strip()]
    summary = archive_universe(pairs=pairs, timeframes=timeframes)
    print(f"Kraken archive: {summary['updated']} flux mis à jour, {summary['failed']} échecs")


if __name__ == "__main__":
    main()
