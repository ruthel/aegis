"""Compare historical baseline exits with Aegis' current calibrated ML exit stack.

This script is aligned with the current runtime:
- unified .env
- Kraken/USD symbol convention
- canonical SignalEngine.detect_best()
- calibrated P_win
- Expected Net PnL entry gate
- calibrated P_exit / P_continue
- timestamp-aligned BTC context

It is a model/backtest comparison, not an exchange microstructure simulator.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.ml_engine import MLEngine
from core.signal_engine import SignalEngine
from scripts.trade_signals import simulate_trade
from scripts.train_and_evaluate_ml_model import (
    aggregate_ohlcv,
    build_training_bot_context,
    fetch_symbol_history_2026,
    support_stats_from_history,
)
from utils.exit_engine import ExitDecisionEngine
from utils.pattern_analyzer import PatternAnalyzer


def _slice_until(rows, ts_value, count=60):
    rows = rows or []
    lo, hi = 0, len(rows)
    while lo < hi:
        mid = (lo + hi) // 2
        if int(rows[mid].get("timestamp", 0)) <= int(ts_value):
            lo = mid + 1
        else:
            hi = mid
    return rows[max(0, lo - count):lo], lo


def net_pnl(entry_price, exit_price, fee_rate):
    return ((exit_price * (1 - fee_rate) - entry_price * (1 + fee_rate)) / entry_price) * 100.0


def summarize(name, trades):
    if not trades:
        return {"name": name, "trades": 0}
    pnls = [float(t["pnl"]) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    pf = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    equity = peak = max_dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return {
        "name": name,
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(trades) * 100.0,
        "total_pnl": sum(pnls),
        "avg_pnl": sum(pnls) / len(pnls),
        "profit_factor": pf,
        "max_drawdown_pct_points": max_dd,
        "avg_hold_candles": sum(t["hold_candles"] for t in trades) / len(trades),
    }


def print_summary(summary):
    pf = summary.get("profit_factor", 0.0)
    pf_text = f"{pf:.2f}" if np.isfinite(pf) else "∞"
    print(
        f"{summary['name']}: trades={summary['trades']} | "
        f"WR={summary.get('win_rate', 0):.1f}% | "
        f"PnL={summary.get('total_pnl', 0):+.2f}% | "
        f"Avg={summary.get('avg_pnl', 0):+.3f}% | PF={pf_text} | "
        f"DD={summary.get('max_drawdown_pct_points', 0):.2f} | "
        f"Hold={summary.get('avg_hold_candles', 0):.1f} bougies"
    )


def simulate_ml_exit(
    symbol,
    bundle,
    btc_15m,
    entry_index,
    signal,
    entry_p_win,
    fee_rate,
    max_hold_candles,
    ml_engine,
    exit_engine,
    support_stats=None,
):
    klines = bundle["15m"]
    entry_price = float(klines[entry_index]["close"])
    highest_price = entry_price
    current_stop = entry_price * (1 - float(os.getenv("BACKTEST_STOP_PERCENT", "1.0")) / 100.0)
    if signal.get("support_price"):
        current_stop = max(
            current_stop,
            float(signal["support_price"]) * (1 - float(os.getenv("BACKTEST_STOP_PERCENT", "1.0")) / 100.0),
        )

    last_index = min(len(klines) - 1, entry_index + max_hold_candles)
    trailing_percent = float(os.getenv("TRAILING_STOP_PERCENT", "2.5"))

    for idx in range(entry_index + 1, last_index + 1):
        candle = klines[idx]
        if float(candle["low"]) <= current_stop:
            return idx, current_stop, "stop"

        if float(candle["high"]) > highest_price:
            highest_price = float(candle["high"])
            profit_pct = ((highest_price - entry_price) / entry_price) * 100.0
            if profit_pct >= 8.0:
                trail = trailing_percent * 0.4
            elif profit_pct >= 5.0:
                trail = trailing_percent * 0.6
            elif profit_pct >= 3.0:
                trail = trailing_percent * 0.8
            else:
                trail = trailing_percent
            current_stop = max(current_stop, highest_price * (1 - trail / 100.0))

        ts = int(candle["timestamp"])
        history = klines[max(0, idx - 80):idx]
        if len(history) < 30:
            continue
        current_price = float(candle["close"])
        btc_slice, btc_idx = _slice_until(btc_15m, ts, count=40)
        h1, _ = _slice_until(bundle.get("1h"), ts, 40)
        h4, _ = _slice_until(bundle.get("4h"), ts, 80)
        h1d, _ = _slice_until(bundle.get("1d"), ts, 80)
        bot_context = build_training_bot_context(
            history,
            signal,
            ts,
            btc_history=btc_15m,
            index=btc_idx,
            support_stats=support_stats,
            h1_history=h1,
            h4_history=h4,
            d1_history=h1d,
        )
        position_data = {
            "entry_price": entry_price,
            "buy_price": entry_price,
            "fee_rate": fee_rate,
            "duration_minutes": (idx - entry_index) * 15.0,
            "stop_loss_price": current_stop,
            "target_price": signal.get("resistance_price") or entry_price * 1.02,
        }
        score = exit_engine.compute_continuation_score(
            symbol, current_price, history[-30:], btc_slice, position_data
        )
        decision = ml_engine.predict_exit_decision(
            history,
            current_price,
            position_data,
            score,
            entry_p_win,
            btc_slice,
            bot_context,
        )
        if decision.get("decision") == "FORCE_EXIT":
            return idx, current_price, "ml_force_exit"

    return last_index, float(klines[last_index]["close"]), "timeout"


def build_entry_context(ml_engine, symbol, bundle, btc_15m, index, signal, fee_rate, support_stats):
    ts = int(bundle["15m"][index]["timestamp"])
    history = bundle["15m"][max(0, index - 200):index]
    current_price = float(bundle["15m"][index]["close"])
    h5, _ = _slice_until(bundle["5m"], ts, 30)
    h1, _ = _slice_until(bundle["1h"], ts, 30)
    h4, _ = _slice_until(bundle["4h"], ts, 30)
    h1d, _ = _slice_until(bundle["1d"], ts, 30)
    ctx_h1, _ = _slice_until(bundle["1h"], ts, 40)
    ctx_h4, _ = _slice_until(bundle["4h"], ts, 80)
    ctx_1d, _ = _slice_until(bundle["1d"], ts, 80)
    _, btc_idx = _slice_until(btc_15m, ts, 60)
    bot_context = build_training_bot_context(
        history,
        signal,
        ts,
        btc_history=btc_15m,
        index=btc_idx,
        support_stats=support_stats,
        h1_history=ctx_h1,
        h4_history=ctx_h4,
        d1_history=ctx_1d,
    )
    trade_context = {
        "fee_rate": fee_rate,
        "position_value_usd": 10.0,
        "account_balance": 1000.0,
        "planned_hold_minutes": 96 * 15.0,
    }
    features = ml_engine.extract_features_from_klines(
        history,
        current_price,
        klines_5m=h5,
        klines_1h=h1,
        klines_4h=h4,
        klines_1d=h1d,
        trade_context=trade_context,
        bot_context=bot_context,
    )
    p_win = ml_engine.predict_win_probability_from_features(features) if features is not None else 50.0
    edge = ml_engine.predict_expected_net_pnl(features) if features is not None else {"ml_edge_available": False}
    return p_win, edge, bot_context


def main():
    load_dotenv(".env", override=True)
    parser = argparse.ArgumentParser(description="Backtest Aegis: baseline vs ML exit/full entry stack")
    parser.add_argument("--pairs", default="BTC/USD,ETH/USD,SOL/USD,ADA/USD")
    parser.add_argument("--start-date", default=(datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d"))
    parser.add_argument("--max-hold-candles", type=int, default=int(os.getenv("ML_EXIT_MAX_HOLD_CANDLES", "960")))
    parser.add_argument("--fee-rate", type=float, default=float(os.getenv("TRADING_FEE_PERCENT", "0.4")) / 100.0)
    parser.add_argument("--entry-pwin-min", type=float, default=float(os.getenv("ML_MIN_PROBABILITY", "50.0")))
    parser.add_argument("--min-edge", type=float, default=float(os.getenv("ML_MIN_EXPECTED_NET_PNL_PCT", "0.05")))
    parser.add_argument("--expected-slippage", type=float, default=float(os.getenv("ML_EXPECTED_SLIPPAGE_PCT", "0.03")))
    args = parser.parse_args()

    ml_engine = MLEngine(model_dir="data")
    if not ml_engine.load_model():
        raise RuntimeError("Champion ML introuvable ou invalide dans data/aegis_model.joblib")
    exit_engine = ExitDecisionEngine()
    signal_engine = SignalEngine(PatternAnalyzer(bot=None))

    btc_15m = fetch_symbol_history_2026(None, "BTC/USD", "15m", args.start_date)
    baseline, same_entries_ml_exit, full_stack = [], [], []

    for symbol in [p.strip() for p in args.pairs.split(",") if p.strip()]:
        k15 = btc_15m if symbol == "BTC/USD" else fetch_symbol_history_2026(None, symbol, "15m", args.start_date)
        k5 = fetch_symbol_history_2026(None, symbol, "5m", args.start_date)
        k1 = fetch_symbol_history_2026(None, symbol, "1h", args.start_date)
        k4 = aggregate_ohlcv(k1, 4)
        k1d = fetch_symbol_history_2026(None, symbol, "1d", args.start_date)
        bundle = {"15m": k15, "5m": k5, "1h": k1, "4h": k4, "1d": k1d}
        if len(k15) < 200:
            continue

        next_allowed = 0
        support_pnls = []
        for index in range(50, len(k15) - args.max_hold_candles - 1):
            if index < next_allowed:
                continue
            history = k15[max(0, index - 200):index]
            entry_price = float(k15[index]["close"])
            signal = signal_engine.detect_best(history, entry_price)
            if not signal:
                continue

            support_stats = support_stats_from_history(support_pnls) if signal.get("type") == "support_touch" else None
            b_idx, b_price, _ = simulate_trade(
                k15,
                index,
                entry_price,
                signal.get("support_price"),
                float(os.getenv("BACKTEST_STOP_PERCENT", "1.0")),
                args.max_hold_candles,
                float(os.getenv("TRAILING_STOP_PERCENT", "2.5")),
                breakeven_stop=True,
                breakeven_trigger=float(os.getenv("BREAKEVEN_TRIGGER_PROFIT_PCT", "1.5")),
                breakeven_lock=float(os.getenv("BREAKEVEN_LOCK_PROFIT_PCT", "1.0")),
                fee_rate=args.fee_rate,
                trend_exit=True,
                trend_confirm_bars=int(os.getenv("ML_EXIT_TREND_CONFIRM_BARS", "2")),
            )
            b_pnl = net_pnl(entry_price, b_price, args.fee_rate)
            baseline.append({"symbol": symbol, "pnl": b_pnl, "hold_candles": b_idx - index})

            p_win, edge, _ = build_entry_context(
                ml_engine, symbol, bundle, btc_15m, index, signal, args.fee_rate, support_stats
            )
            m_idx, m_price, m_reason = simulate_ml_exit(
                symbol,
                bundle,
                btc_15m,
                index,
                signal,
                p_win,
                args.fee_rate,
                args.max_hold_candles,
                ml_engine,
                exit_engine,
                support_stats,
            )
            m_pnl = net_pnl(entry_price, m_price, args.fee_rate)
            same_entries_ml_exit.append(
                {"symbol": symbol, "pnl": m_pnl, "hold_candles": m_idx - index, "reason": m_reason}
            )

            effective_edge = None
            if edge.get("ml_edge_available"):
                effective_edge = float(edge.get("expected_net_pnl_pct") or 0.0) - args.expected_slippage
            if p_win >= args.entry_pwin_min and effective_edge is not None and effective_edge >= args.min_edge:
                full_stack.append(
                    {"symbol": symbol, "pnl": m_pnl, "hold_candles": m_idx - index, "reason": m_reason}
                )

            if signal.get("type") == "support_touch":
                support_pnls.append(float(b_pnl))
            next_allowed = max(b_idx, m_idx) + 4

    print("\n=== COMPARATIF SORTIES AEGIS ACTUEL ===")
    summaries = [
        summarize("Baseline technique", baseline),
        summarize("Mêmes entrées + P_exit calibré", same_entries_ml_exit),
        summarize("P_win calibré + edge + P_exit", full_stack),
    ]
    for summary in summaries:
        print_summary(summary)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
