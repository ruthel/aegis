"""Backtest public-data for the Support Touch Pro entry rule.

Usage:
    python scripts/backtest_support_touch.py

Optional:
    python scripts/backtest_support_touch.py --pairs BTC/USDT,ETH/USDT --limit 1000
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

import ccxt
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.pattern_analyzer import PatternAnalyzer


def normalize_symbol(pair):
    pair = pair.strip()
    if '/' in pair:
        return pair
    if pair.endswith('USDT'):
        return f"{pair[:-4]}/USDT"
    return pair


def to_kline(row):
    return {
        'timestamp': row[0],
        'open': float(row[1]),
        'high': float(row[2]),
        'low': float(row[3]),
        'close': float(row[4]),
        'volume': float(row[5]),
    }


def create_public_exchange(exchange_name):
    exchange_class = getattr(ccxt, exchange_name)
    exchange = exchange_class({'enableRateLimit': True})
    exchange.load_markets()
    return exchange


def detect_support_touch(pattern_analyzer, history, current_price):
    levels = pattern_analyzer.find_support_resistance_levels(history)
    for support in levels.get('support_levels', [])[:3]:
        support_price = float(support['price'])
        rebounds = int(support.get('strength', 1))
        if current_price <= support_price * 1.001 and rebounds >= 2:
            confidence = min(85, 60 + (rebounds - 2) * 10)
            return {
                'support_price': support_price,
                'rebounds': rebounds,
                'confidence': confidence,
                'reason': f"Support {rebounds} rebonds @ {support_price:.2f}",
            }
    return None


def simulate_trade(klines, entry_index, entry_price, target_percent, stop_percent, max_hold):
    target_price = entry_price * (1 + target_percent / 100)
    stop_price = entry_price * (1 - stop_percent / 100)
    last_index = min(len(klines) - 1, entry_index + max_hold)

    for exit_index in range(entry_index + 1, last_index + 1):
        candle = klines[exit_index]
        hit_stop = candle['low'] <= stop_price
        hit_target = candle['high'] >= target_price

        if hit_stop and hit_target:
            return exit_index, stop_price, 'loss'
        if hit_stop:
            return exit_index, stop_price, 'loss'
        if hit_target:
            return exit_index, target_price, 'win'

    exit_price = klines[last_index]['close']
    outcome = 'win' if exit_price > entry_price else 'loss'
    return last_index, exit_price, outcome


def backtest_symbol(exchange, symbol, args):
    raw = exchange.fetch_ohlcv(symbol, args.timeframe, limit=args.limit)
    klines = [to_kline(row) for row in raw]
    analyzer = PatternAnalyzer(bot=None)
    trades = []
    next_allowed_index = args.lookback

    for index in range(args.lookback, len(klines) - 1):
        if index < next_allowed_index:
            continue

        history = klines[index - args.lookback:index]
        current_price = klines[index]['close']
        signal = detect_support_touch(analyzer, history, current_price)
        if not signal:
            continue

        exit_index, exit_price, outcome = simulate_trade(
            klines,
            index,
            current_price,
            args.target_percent,
            args.stop_percent,
            args.max_hold_candles,
        )
        pnl_percent = ((exit_price - current_price) / current_price) * 100
        trades.append({
            'entry_time': datetime.fromtimestamp(klines[index]['timestamp'] / 1000, timezone.utc).isoformat(),
            'exit_time': datetime.fromtimestamp(klines[exit_index]['timestamp'] / 1000, timezone.utc).isoformat(),
            'entry_price': current_price,
            'exit_price': exit_price,
            'pnl_percent': pnl_percent,
            'outcome': outcome,
            'hold_candles': exit_index - index,
            **signal,
        })
        next_allowed_index = exit_index + args.cooldown_candles

    wins = [trade for trade in trades if trade['outcome'] == 'win']
    losses = [trade for trade in trades if trade['outcome'] != 'win']
    total_pnl = sum(trade['pnl_percent'] for trade in trades)
    return {
        'symbol': symbol,
        'timeframe': args.timeframe,
        'candles': len(klines),
        'trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': (len(wins) / len(trades) * 100) if trades else 0,
        'total_pnl_percent': total_pnl,
        'avg_pnl_percent': (total_pnl / len(trades)) if trades else 0,
        'best_trade_percent': max((trade['pnl_percent'] for trade in trades), default=0),
        'worst_trade_percent': min((trade['pnl_percent'] for trade in trades), default=0),
        'trades_detail': trades[-20:],
    }


def parse_args():
    load_dotenv(override=True)
    load_dotenv('.env.local', override=True)

    parser = argparse.ArgumentParser(description='Backtest Support Touch Pro.')
    parser.add_argument('--exchange', default=os.getenv('EXCHANGE', 'kraken').lower())
    parser.add_argument('--pairs', default=os.getenv('TRADING_PAIRS', 'BTCUSDT,ETHUSDT'))
    parser.add_argument('--timeframe', default=os.getenv('BACKTEST_TIMEFRAME', '15m'))
    parser.add_argument('--limit', type=int, default=int(os.getenv('BACKTEST_LIMIT', '720')))
    parser.add_argument('--lookback', type=int, default=int(os.getenv('BACKTEST_LOOKBACK', '50')))
    parser.add_argument('--max-hold-candles', type=int, default=int(os.getenv('BACKTEST_MAX_HOLD_CANDLES', '24')))
    parser.add_argument('--target-percent', type=float, default=float(os.getenv('BACKTEST_TARGET_PERCENT', '1.5')))
    parser.add_argument('--stop-percent', type=float, default=float(os.getenv('BACKTEST_STOP_PERCENT', '1.0')))
    parser.add_argument('--cooldown-candles', type=int, default=int(os.getenv('BACKTEST_COOLDOWN_CANDLES', '4')))
    parser.add_argument('--output', default='data/support_touch_backtest.json')
    return parser.parse_args()


def main():
    args = parse_args()
    exchange = create_public_exchange(args.exchange)
    symbols = [normalize_symbol(pair) for pair in args.pairs.split(',') if pair.strip()]

    results = []
    for symbol in symbols:
        try:
            if symbol not in exchange.markets:
                print(f"SKIP {symbol}: market not found on {args.exchange}")
                continue
            result = backtest_symbol(exchange, symbol, args)
            results.append(result)
            print(
                f"{symbol}: {result['trades']} trades | "
                f"win {result['win_rate']:.1f}% | "
                f"avg {result['avg_pnl_percent']:+.2f}% | "
                f"total {result['total_pnl_percent']:+.2f}%"
            )
        except Exception as exc:
            print(f"ERROR {symbol}: {exc}")

    summary = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'exchange': args.exchange,
        'settings': {
            'timeframe': args.timeframe,
            'limit': args.limit,
            'lookback': args.lookback,
            'max_hold_candles': args.max_hold_candles,
            'target_percent': args.target_percent,
            'stop_percent': args.stop_percent,
            'cooldown_candles': args.cooldown_candles,
        },
        'results': results,
    }

    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as file:
        json.dump(summary, file, indent=2)

    total_trades = sum(item['trades'] for item in results)
    total_wins = sum(item['wins'] for item in results)
    total_pnl = sum(item['total_pnl_percent'] for item in results)
    print(
        f"TOTAL: {total_trades} trades | "
        f"win {(total_wins / total_trades * 100) if total_trades else 0:.1f}% | "
        f"total {total_pnl:+.2f}%"
    )
    print(f"Saved: {args.output}")


if __name__ == '__main__':
    main()
