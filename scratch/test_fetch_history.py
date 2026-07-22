import sys, os, time, ccxt, numpy as np
from datetime import datetime, timezone

sys.path.insert(0, os.getcwd())
from core.ml_engine import MLEngine
from utils.pattern_analyzer import PatternAnalyzer
from scripts.backtest_support_touch import detect_trade_signal, simulate_trade

exchange = ccxt.kraken({'enableRateLimit': True})
exchange.load_markets()

symbol = 'ETH/USD'
start_ts = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
print(f"Fetching historical klines for {symbol} since 2026-01-01 ({start_ts})...")

all_klines = []
since = start_ts
limit = 720

while True:
    try:
        raw = exchange.fetch_ohlcv(symbol, timeframe='15m', since=since, limit=limit)
        if not raw:
            break
        for r in raw:
            all_klines.append({
                'timestamp': r[0],
                'open': float(r[1]),
                'high': float(r[2]),
                'low': float(r[3]),
                'close': float(r[4]),
                'volume': float(r[5])
            })
        print(f"Fetched {len(raw)} candles (total: {len(all_klines)}). Last date: {datetime.fromtimestamp(raw[-1][0]/1000, timezone.utc).isoformat()}")
        since = raw[-1][0] + 1
        if len(raw) < limit or len(all_klines) >= 15000:
            break
        time.sleep(0.2)
    except Exception as e:
        print(f"Error fetching klines: {e}")
        break

print(f"\n[SUCCESS] Downloaded {len(all_klines)} historical 15m candles from 2026-01-01 to today!")
