"""Compare les sorties historiques: baseline trailing vs ML sortie fusionné."""

import argparse
import os
import sys
import time
from datetime import datetime, timezone

import ccxt
import numpy as np
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.ml_engine import MLEngine
from scripts.backtest_support_touch import detect_trade_signal, simulate_trade
from scripts.train_ml_model import build_training_bot_context, support_stats_from_history
from utils.exit_engine import ExitDecisionEngine
from utils.pattern_analyzer import PatternAnalyzer


def fetch_history(exchange, symbol, timeframe, start_date):
    start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
    all_klines = []
    since = start_ts
    limit = 1000
    print(f"Fetch {symbol} {timeframe} depuis {start_date}...")
    while True:
        raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=limit)
        if not raw:
            break
        all_klines.extend({
            'timestamp': r[0],
            'open': float(r[1]),
            'high': float(r[2]),
            'low': float(r[3]),
            'close': float(r[4]),
            'volume': float(r[5]),
        } for r in raw)
        since = raw[-1][0] + 1
        if len(raw) < limit or len(all_klines) >= 30000:
            break
        time.sleep(0.05)
    print(f"  {len(all_klines)} bougies")
    return all_klines


def net_pnl(entry_price, exit_price, fee_rate):
    return ((exit_price * (1 - fee_rate) - entry_price * (1 + fee_rate)) / entry_price) * 100.0


def summarize(name, trades):
    if not trades:
        return {'name': name, 'trades': 0}
    pnls = [t['pnl'] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    return {
        'name': name,
        'trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': len(wins) / len(trades) * 100.0,
        'total_pnl': sum(pnls),
        'avg_pnl': sum(pnls) / len(pnls),
        'avg_win': sum(wins) / len(wins) if wins else 0.0,
        'avg_loss': sum(losses) / len(losses) if losses else 0.0,
        'avg_hold_candles': sum(t['hold_candles'] for t in trades) / len(trades),
    }


def print_summary(summary):
    print(
        f"{summary['name']}: trades={summary['trades']} | WR={summary.get('win_rate', 0):.1f}% | "
        f"PnL={summary.get('total_pnl', 0):+.2f}% | Avg={summary.get('avg_pnl', 0):+.3f}% | "
        f"AvgWin={summary.get('avg_win', 0):+.3f}% | AvgLoss={summary.get('avg_loss', 0):+.3f}% | "
        f"Hold={summary.get('avg_hold_candles', 0):.1f} bougies"
    )


def simulate_ml_exit(symbol, klines, entry_index, signal, args, ml_engine, exit_engine, btc_klines=None, support_stats=None):
    entry_price = klines[entry_index]['close']
    highest_price = entry_price
    current_stop = entry_price * (1 - args.trailing_percent / 100.0)
    if signal.get('support_price'):
        current_stop = max(current_stop, float(signal['support_price']) * (1 - args.stop_percent / 100.0))
    last_index = min(len(klines) - 1, entry_index + args.max_hold_candles)
    entry_history = klines[:entry_index]
    entry_bot_context = build_training_bot_context(
        entry_history,
        signal,
        klines[entry_index]['timestamp'],
        btc_history=btc_klines if btc_klines is not None else klines,
        index=entry_index,
        support_stats=support_stats
    )
    entry_p_win = ml_engine.predict_win_probability(entry_history, entry_price, bot_context=entry_bot_context)
    entry_exit_forecast = None

    for idx in range(entry_index + 1, last_index + 1):
        candle = klines[idx]
        if candle['low'] <= current_stop:
            return idx, current_stop, 'stop', entry_exit_forecast

        if candle['high'] > highest_price:
            highest_price = candle['high']
            profit_pct = ((highest_price - entry_price) / entry_price) * 100.0
            if profit_pct >= 8.0:
                percent = args.trailing_percent * 0.4
            elif profit_pct >= 5.0:
                percent = args.trailing_percent * 0.6
            elif profit_pct >= 3.0:
                percent = args.trailing_percent * 0.8
            else:
                percent = args.trailing_percent
            current_stop = max(current_stop, highest_price * (1 - percent / 100.0))

        history = klines[max(0, idx - 60):idx]
        if len(history) < 30:
            continue

        current_price = candle['close']
        position_data = {
            'buy_price': entry_price,
            'fee_rate': args.fee_rate,
            'duration_minutes': (idx - entry_index) * 15.0,
            'stop_loss_price': current_stop,
            'target_price': signal.get('resistance_price') or entry_price * 1.015,
        }
        btc_slice = None
        if btc_klines and len(btc_klines) > idx:
            btc_slice = btc_klines[max(0, idx - 30):idx]
        bot_context = build_training_bot_context(
            history,
            signal,
            candle['timestamp'],
            btc_history=btc_klines if btc_klines is not None else klines,
            index=idx,
            support_stats=support_stats
        )
        score = exit_engine.compute_continuation_score(symbol, current_price, history[-30:], btc_slice, position_data)
        ml_exit = ml_engine.predict_exit_decision(
            history, current_price, position_data, score, entry_p_win, btc_slice, bot_context
        )
        if idx == entry_index + 1:
            entry_exit_forecast = ml_exit

        decision = ml_exit.get('decision')
        if decision in ('FORCE_EXIT', 'TAKE_PROFIT'):
            return idx, current_price, decision.lower(), entry_exit_forecast
        if decision in ('TIGHTEN_STOP', 'PROTECT_BREAKEVEN'):
            breakeven = entry_price * (1 + args.fee_rate) / max(0.000001, (1 - args.fee_rate))
            gap = 0.0018 if decision == 'TIGHTEN_STOP' else 0.0008
            current_stop = max(current_stop, min(current_price * (1 - gap), breakeven if decision == 'PROTECT_BREAKEVEN' else current_price * (1 - gap)))

    return last_index, klines[last_index]['close'], 'timeout', entry_exit_forecast


def main():
    load_dotenv(override=True)
    load_dotenv('.env.local', override=True)
    parser = argparse.ArgumentParser()
    parser.add_argument('--pairs', default='BTC/USDT,ETH/USDT,SOL/USDT,ADA/USDT')
    parser.add_argument('--start-date', default='2026-01-01')
    parser.add_argument('--timeframe', default='15m')
    parser.add_argument('--max-hold-candles', type=int, default=int(os.getenv('BACKTEST_MAX_HOLD_CANDLES', '96')))
    parser.add_argument('--stop-percent', type=float, default=float(os.getenv('BACKTEST_STOP_PERCENT', '1.0')))
    parser.add_argument('--trailing-percent', type=float, default=float(os.getenv('TRAILING_STOP_PERCENT', '2.5')))
    parser.add_argument('--fee-rate', type=float, default=float(os.getenv('TRADING_FEE_PERCENT', '0.1')) / 100.0)
    parser.add_argument('--entry-pwin-min', type=float, default=float(os.getenv('ML_MIN_PROBABILITY', '65.0')))
    parser.add_argument('--entry-pcontinue-min', type=float, default=float(os.getenv('ML_EXIT_ENTRY_MIN_CONTINUE_PROB', '50.0')))
    args = parser.parse_args()

    exchange = ccxt.binance({'enableRateLimit': True})
    ml_engine = MLEngine(model_dir='data')
    exit_engine = ExitDecisionEngine()
    analyzer = PatternAnalyzer(bot=None)
    pairs = [p.strip() for p in args.pairs.split(',') if p.strip()]
    btc = fetch_history(exchange, 'BTC/USDT', args.timeframe, args.start_date)

    baseline = []
    ml_exit = []
    ml_entry_and_exit = []

    for symbol in pairs:
        klines = btc if symbol == 'BTC/USDT' else fetch_history(exchange, symbol, args.timeframe, args.start_date)
        next_allowed = 0
        support_pnls = []
        for index in range(50, len(klines) - args.max_hold_candles - 1):
            if index < next_allowed:
                continue
            history = klines[:index]
            entry_price = klines[index]['close']
            signal = detect_trade_signal(analyzer, history, entry_price)
            if not signal:
                continue
            support_stats = support_stats_from_history(support_pnls) if signal.get('type') == 'support_touch' else None

            b_exit_idx, b_exit_price, _ = simulate_trade(
                klines, index, entry_price, signal.get('support_price'), args.stop_percent,
                args.max_hold_candles, args.trailing_percent, breakeven_stop=True,
                breakeven_trigger=1.5, breakeven_lock=1.0, fee_rate=args.fee_rate
            )
            b_pnl = net_pnl(entry_price, b_exit_price, args.fee_rate)
            baseline.append({'symbol': symbol, 'pnl': b_pnl, 'hold_candles': b_exit_idx - index})

            m_exit_idx, m_exit_price, m_reason, entry_forecast = simulate_ml_exit(
                symbol, klines, index, signal, args, ml_engine, exit_engine,
                btc if symbol != 'BTC/USDT' else None,
                support_stats=support_stats
            )
            m_pnl = net_pnl(entry_price, m_exit_price, args.fee_rate)
            ml_exit.append({'symbol': symbol, 'pnl': m_pnl, 'hold_candles': m_exit_idx - index, 'reason': m_reason})

            entry_bot_context = build_training_bot_context(
                history,
                signal,
                klines[index]['timestamp'],
                btc_history=btc if symbol != 'BTC/USDT' else klines,
                index=index,
                support_stats=support_stats
            )
            entry_pwin = ml_engine.predict_win_probability(history, entry_price, bot_context=entry_bot_context)
            entry_pcontinue = (entry_forecast or {}).get('p_continue', 50.0)
            if entry_pwin >= args.entry_pwin_min and entry_pcontinue >= args.entry_pcontinue_min:
                ml_entry_and_exit.append({'symbol': symbol, 'pnl': m_pnl, 'hold_candles': m_exit_idx - index, 'reason': m_reason})

            if signal.get('type') == 'support_touch':
                support_pnls.append(float(b_pnl))
            next_allowed = b_exit_idx + 4

    print("\n=== COMPARATIF SORTIES 2026 ===")
    summaries = [
        summarize('Baseline sorties actuelles', baseline),
        summarize('Même entrées + sorties ML', ml_exit),
        summarize('Entrées filtrées ML + sorties ML', ml_entry_and_exit),
    ]
    for s in summaries:
        print_summary(s)

    if baseline and ml_exit:
        delta_wr = summaries[1]['win_rate'] - summaries[0]['win_rate']
        delta_pnl = summaries[1]['total_pnl'] - summaries[0]['total_pnl']
        print(f"\nDelta sortie ML vs baseline: WR {delta_wr:+.1f} pts | PnL {delta_pnl:+.2f}%")
    if baseline and ml_entry_and_exit:
        delta_wr = summaries[2]['win_rate'] - summaries[0]['win_rate']
        delta_pnl = summaries[2]['total_pnl'] - summaries[0]['total_pnl']
        trade_delta = summaries[2]['trades'] - summaries[0]['trades']
        print(f"Delta entrée+sortie ML vs baseline: WR {delta_wr:+.1f} pts | PnL {delta_pnl:+.2f}% | Trades {trade_delta:+d}")


if __name__ == '__main__':
    main()
