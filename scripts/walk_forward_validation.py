"""
Validation walk-forward temporelle du modèle ML Aegis.

- Fenêtres train/test chronologiques glissantes.
- Données multi-timeframe réelles.
- Aucun mélange aléatoire passé/futur.
- PnL mesuré à partir des résultats simulés réels, pas d'hypothèse +1.5/-1.0.
- P_win calibré + filtre Expected Net PnL, comme le chemin d'entrée live.
- Modèles de fenêtre isolés en répertoire temporaire: aucun risque d'écraser le champion.
"""
import os
import sys
import argparse
import tempfile
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
import numpy as np

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.ml_engine import MLEngine
from scripts.train_and_evaluate_ml_model import (
    fetch_symbol_history_2026,
    generate_samples_from_klines,
    aggregate_ohlcv,
    build_training_bot_context,
    generate_exit_training_samples,
)
from core.signal_engine import SignalEngine
from utils.pattern_analyzer import PatternAnalyzer
from utils.exit_engine import ExitDecisionEngine


def _to_epoch_seconds(value):
    value = float(value)
    return value / 1000.0 if value > 1e12 else value


def _max_drawdown_from_pnls(pnls):
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnls:
        equity += float(pnl)
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _slice_until(rows, ts_value, count=80):
    rows = rows or []
    lo, hi = 0, len(rows)
    while lo < hi:
        mid = (lo + hi) // 2
        if int(rows[mid].get('timestamp', 0)) <= int(ts_value):
            lo = mid + 1
        else:
            hi = mid
    return rows[max(0, lo - count):lo], lo


def _truncate_bundle(bundle, end_ts_sec):
    limit_ms = int(float(end_ts_sec) * 1000.0)
    out = {}
    for key, rows in (bundle or {}).items():
        out[key] = [
            row for row in (rows or [])
            if int(row.get('timestamp', 0) or 0) < limit_ms
        ]
    return out


def _historical_spread_pct(candle):
    """Use archived bid/ask when available, otherwise an explicit conservative fallback."""
    candle = candle or {}
    try:
        value = float(candle.get('spread_pct') or candle.get('spread_percent') or 0.0)
        if value > 0:
            return value
    except Exception:
        pass
    try:
        bid = float(candle.get('bid') or 0.0)
        ask = float(candle.get('ask') or 0.0)
        mid = (bid + ask) / 2.0
        if bid > 0 and ask > bid and mid > 0:
            return ((ask - bid) / mid) * 100.0
    except Exception:
        pass
    return max(0.0, float(os.getenv('FULL_STRATEGY_FALLBACK_SPREAD_PCT', '0.04')))


def _simulate_full_strategy_trade(
    ml_engine,
    exit_engine,
    bundle,
    btc_history,
    metadata,
    entry_p_win,
    fee_rate,
    test_end_ts,
):
    """Replay P_exit + physical safety on unseen candles."""
    klines = list((bundle or {}).get('15m') or [])
    index = int(metadata.get('entry_index', -1))
    if index < 0 or index >= len(klines) - 1:
        return None

    entry_raw = float(metadata.get('entry_price') or klines[index]['close'])
    entry_ts = int(klines[index]['timestamp'])
    signal = metadata.get('signal') or {}
    stop_pct = float(os.getenv('FULL_STRATEGY_STOP_PERCENT', os.getenv('BACKTEST_STOP_PERCENT', '1.0')))
    trailing_pct = float(os.getenv('TRAILING_STOP_PERCENT', '2.5'))
    breakeven_trigger = float(os.getenv('BREAKEVEN_TRIGGER_PROFIT_PCT', '1.5'))
    breakeven_lock = float(os.getenv('BREAKEVEN_LOCK_PROFIT_PCT', '1.0'))
    max_hold = int(os.getenv('ML_EXIT_MAX_HOLD_CANDLES', '960'))
    slippage_pct = max(0.0, float(os.getenv('FULL_STRATEGY_ROUNDTRIP_SLIPPAGE_PCT', '0.06'))) / 2.0
    entry_spread_pct = _historical_spread_pct(klines[index])

    entry_order_type = 'limit' if float(entry_p_win) < 80.0 else 'market'
    entry_fee = fee_rate * 0.9 if entry_order_type == 'limit' else fee_rate
    exit_fee = fee_rate
    # Maker entry assumes the posted limit is filled at the candidate price.
    # Market entry pays half-spread + modeled slippage.
    entry_drag_pct = 0.0 if entry_order_type == 'limit' else (entry_spread_pct / 2.0 + slippage_pct)
    entry_exec = entry_raw * (1.0 + entry_drag_pct / 100.0)

    hard_stop = entry_raw * (1.0 - stop_pct / 100.0)
    support_price = float(signal.get('support_price') or 0.0)
    if support_price > 0:
        hard_stop = max(hard_stop, support_price * (1.0 - stop_pct / 100.0))
    current_stop = hard_stop
    highest = entry_raw
    last_idx = min(len(klines) - 1, index + max_hold)
    exit_price = float(klines[last_idx]['close'])
    exit_reason = 'timeout'
    exit_idx = last_idx

    for cp in range(index + 1, last_idx + 1):
        candle = klines[cp]
        cp_ts_raw = float(candle['timestamp'])
        cp_ts_sec = cp_ts_raw / 1000.0 if cp_ts_raw > 1e12 else cp_ts_raw
        if cp_ts_sec >= float(test_end_ts):
            exit_idx = max(index + 1, cp - 1)
            exit_price = float(klines[exit_idx]['close'])
            exit_reason = 'test_window_end'
            break

        low = float(candle['low'])
        high = float(candle['high'])
        close = float(candle['close'])

        if low <= current_stop:
            exit_idx = cp
            exit_price = current_stop
            exit_reason = 'stop'
            break

        if high > highest:
            highest = high
            profit_pct = ((highest - entry_raw) / max(entry_raw, 1e-9)) * 100.0
            current_stop = max(current_stop, highest * (1.0 - trailing_pct / 100.0))
            if profit_pct >= breakeven_trigger:
                current_stop = max(
                    current_stop,
                    entry_raw * (1.0 + breakeven_lock / 100.0),
                )

        if cp - index < 4 or not ml_engine.is_exit_trained:
            continue

        cp_ts = int(candle['timestamp'])
        history = klines[max(0, cp - 200):cp]
        h1, _ = _slice_until(bundle.get('1h'), cp_ts, 40)
        h4, _ = _slice_until(bundle.get('4h'), cp_ts, 80)
        d1, _ = _slice_until(bundle.get('1d'), cp_ts, 80)
        btc_slice, btc_idx = _slice_until(btc_history, cp_ts, 40)
        bot_context = build_training_bot_context(
            history,
            None,
            cp_ts,
            btc_history=btc_history,
            index=btc_idx,
            h1_history=h1,
            h4_history=h4,
            d1_history=d1,
        )
        position_data = {
            'entry_price': entry_raw,
            'buy_price': entry_raw,
            'fee_rate': fee_rate,
            'duration_minutes': (cp - index) * 15.0,
            'stop_price': current_stop,
            'stop_loss_price': current_stop,
            'target_price': entry_raw * 1.02,
        }
        continuation_score = exit_engine.compute_continuation_score(
            metadata.get('symbol'),
            close,
            history[-30:],
            btc_slice,
            position_data,
        )
        decision = ml_engine.predict_exit_decision(
            history,
            close,
            position_data,
            continuation_score,
            entry_p_win,
            btc_slice,
            bot_context,
        )
        if decision.get('decision') == 'FORCE_EXIT':
            exit_idx = cp
            exit_price = close
            exit_reason = decision.get('reason') or 'p_exit'
            break

    exit_spread_pct = _historical_spread_pct(klines[exit_idx])
    exit_drag_pct = exit_spread_pct / 2.0 + slippage_pct
    exit_exec = float(exit_price) * (1.0 - exit_drag_pct / 100.0)
    net_pct = (
        (exit_exec * (1.0 - exit_fee) - entry_exec * (1.0 + entry_fee))
        / max(entry_exec, 1e-9)
    ) * 100.0
    return {
        'pnl_pct': float(net_pct),
        'exit_index': int(exit_idx),
        'exit_price': float(exit_price),
        'reason': exit_reason,
        'entry_order_type': entry_order_type,
        'entry_spread_pct': round(float(entry_spread_pct), 5),
        'exit_spread_pct': round(float(exit_spread_pct), 5),
        'entry_execution_drag_pct': round(float(entry_drag_pct), 5),
        'exit_execution_drag_pct': round(float(exit_drag_pct), 5),
    }


def run_walk_forward_validation(pairs, train_days=90, test_days=30, step_days=30):
    load_dotenv('.env', override=True)

    print("=" * 70)
    print("🚀 VALIDATION WALK-FORWARD TEMPORELLE")
    print(f"  • Paires : {', '.join(pairs)}")
    print(f"  • Train : {train_days} jours | Test : {test_days} jours | Pas : {step_days} jours")
    print("=" * 70)

    total_history_days = train_days + max(180, test_days + step_days * 3)
    start_date = (datetime.now(timezone.utc) - timedelta(days=total_history_days)).strftime("%Y-%m-%d")
    fee_rate = float(os.getenv('TRADING_FEE_PERCENT', '0.4')) / 100.0
    decision_threshold = float(os.getenv('ML_MIN_PROBABILITY', '50.0'))

    btc_history = fetch_symbol_history_2026(
        None, 'BTC/USD', timeframe='15m', start_date=start_date
    )

    all_samples = []
    all_labels = []
    all_timestamps = []
    all_pnls = []
    all_metadata = []
    market_bundles = {}

    for symbol in pairs:
        print(f"📥 {symbol}: chargement multi-timeframe...")
        klines_15m = btc_history if symbol == 'BTC/USD' else fetch_symbol_history_2026(
            None, symbol, timeframe='15m', start_date=start_date
        )
        if len(klines_15m) < 200:
            print(f"  ⚠️ {symbol}: historique insuffisant")
            continue

        klines_5m = fetch_symbol_history_2026(None, symbol, timeframe='5m', start_date=start_date)
        klines_1h = fetch_symbol_history_2026(None, symbol, timeframe='1h', start_date=start_date)
        klines_4h = aggregate_ohlcv(klines_1h, 4)
        klines_1d = fetch_symbol_history_2026(None, symbol, timeframe='1d', start_date=start_date)

        bundle = {
            '15m': klines_15m,
            '5m': klines_5m,
            '1h': klines_1h,
            '4h': klines_4h,
            '1d': klines_1d,
        }
        market_bundles[symbol] = bundle

        samples, labels, metadata = generate_samples_from_klines(
            bundle,
            symbol,
            stop_percent=1.0,
            trailing_percent=2.5,
            fee_rate=fee_rate,
            position_value_usd=10.0,
            btc_history=btc_history,
        )

        for sample, label, meta in zip(samples, labels, metadata):
            all_samples.append(sample)
            all_labels.append(int(label))
            all_timestamps.append(_to_epoch_seconds(meta['timestamp']))
            all_pnls.append(float(meta['pnl_pct']))
            all_metadata.append(dict(meta))

    if not all_samples:
        print("❌ Aucune donnée générée pour la validation walk-forward.")
        return False

    with tempfile.TemporaryDirectory(prefix='aegis_walkforward_schema_') as schema_tmp:
        schema_engine = MLEngine(model_dir=schema_tmp)
        feature_names = list(schema_engine.feature_names)

    X_matrix = np.array([
        [float(sample.get(name, 0.0) or 0.0) for name in feature_names]
        for sample in all_samples
    ], dtype=np.float64)
    y_array = np.asarray(all_labels, dtype=np.int64)
    ts_array = np.asarray(all_timestamps, dtype=np.float64)
    pnl_array = np.asarray(all_pnls, dtype=np.float64)
    metadata_array = np.asarray(all_metadata, dtype=object)

    # Mélange des symboles interdit: ordre chronologique global avant toute fenêtre.
    order = np.argsort(ts_array, kind='stable')
    X_matrix = X_matrix[order]
    y_array = y_array[order]
    ts_array = ts_array[order]
    pnl_array = pnl_array[order]
    metadata_array = metadata_array[order]

    min_ts = float(np.min(ts_array))
    max_ts = float(np.max(ts_array))
    total_duration_days = (max_ts - min_ts) / 86400.0
    print(f"📊 Dataset : {len(X_matrix)} échantillons sur {total_duration_days:.1f} jours.")

    window_results = []
    current_start = min_ts
    step_idx = 1

    while current_start + (train_days + test_days) * 86400 <= max_ts:
        train_end = current_start + train_days * 86400
        test_end = train_end + test_days * 86400

        train_mask = (ts_array >= current_start) & (ts_array < train_end)
        test_mask = (ts_array >= train_end) & (ts_array < test_end)

        X_train, y_train = X_matrix[train_mask], y_array[train_mask]
        X_test, y_test = X_matrix[test_mask], y_array[test_mask]
        pnl_train = pnl_array[train_mask]
        pnl_test = pnl_array[test_mask]
        meta_train = metadata_array[train_mask]
        meta_test = metadata_array[test_mask]

        if len(X_train) < 100 or len(X_test) < 20 or len(np.unique(y_train)) < 2:
            current_start += step_days * 86400
            continue

        # Le walk-forward ne doit JAMAIS écrire dans data/aegis_model.joblib.
        # Chaque fenêtre utilise un répertoire temporaire isolé.
        with tempfile.TemporaryDirectory(prefix='aegis_walkforward_') as tmpdir:
            temp_engine = MLEngine(model_dir=tmpdir)
            temp_engine.model_path = os.path.join(tmpdir, 'window_model.joblib')
            use_lightgbm = os.getenv('ML_USE_LIGHTGBM', 'true').lower() == 'true'
            if not temp_engine.train_model(
                X_train,
                y_train,
                n_estimators=100,
                max_depth=6,
                use_lightgbm=use_lightgbm,
            ):
                current_start += step_days * 86400
                continue

            # Entraîner également l'edge model sur le passé uniquement.
            temp_engine.train_edge_model(
                X_train,
                pnl_train,
                use_lightgbm=use_lightgbm,
            )

            full_strategy = os.getenv('FULL_STRATEGY_WALK_FORWARD', 'True').lower() == 'true'
            exit_engine = ExitDecisionEngine()
            if full_strategy:
                sizing_targets = np.asarray(
                    [float(meta.get('sizing_target', 1.0)) for meta in meta_train],
                    dtype=np.float64,
                )
                temp_engine.train_sizing_model(
                    X_train,
                    sizing_targets,
                    use_lightgbm=use_lightgbm,
                )

                train_bundles = {
                    symbol: _truncate_bundle(bundle, train_end)
                    for symbol, bundle in market_bundles.items()
                }
                btc_train = [
                    row for row in btc_history
                    if _to_epoch_seconds(row.get('timestamp', 0)) < train_end
                ]
                wf_signal_engine = SignalEngine(PatternAnalyzer(bot=None))
                X_exit, y_exit, ts_exit = generate_exit_training_samples(
                    ml_engine=temp_engine,
                    signal_engine=wf_signal_engine,
                    training_histories=train_bundles,
                    btc_history=btc_train,
                    fee_rate=fee_rate,
                    start_ts=current_start,
                    end_ts=train_end,
                    exit_max_hold=int(os.getenv('ML_EXIT_MAX_HOLD_CANDLES', '960')),
                    max_samples=int(os.getenv('FULL_STRATEGY_EXIT_MAX_SAMPLES', '6000')),
                )
                if len(X_exit) >= 30 and len(np.unique(y_exit)) >= 2:
                    temp_engine.train_exit_model(
                        X_exit,
                        y_exit,
                        timestamps=ts_exit,
                        n_estimators=120,
                        max_depth=6,
                        min_samples_split=10,
                        use_lightgbm=use_lightgbm,
                    )

            probs = np.array([
                temp_engine.predict_win_probability_from_features(row)
                for row in X_test
            ], dtype=np.float64)

            edge_values = np.array([
                float(
                    temp_engine.predict_expected_net_pnl(row).get('expected_net_pnl_pct')
                    if temp_engine.predict_expected_net_pnl(row).get('ml_edge_available')
                    else 0.0
                )
                for row in X_test
            ], dtype=np.float64)

        min_edge = float(os.getenv('ML_MIN_EXPECTED_NET_PNL_PCT', '0.05'))
        expected_slippage = float(os.getenv('ML_EXPECTED_SLIPPAGE_PCT', '0.03'))
        effective_edge = edge_values - expected_slippage
        selected = (probs >= decision_threshold) & (effective_edge >= min_edge)

        reference_notional = float(os.getenv('FULL_STRATEGY_REFERENCE_NOTIONAL_USD', '100.0'))
        full_strategy_pnl_usd = 0.0
        if full_strategy:
            replayed_pnls = []
            for test_pos in np.where(selected)[0]:
                features = X_test[test_pos]
                meta = dict(meta_test[test_pos])
                symbol = str(meta.get('symbol') or '')
                bundle = market_bundles.get(symbol)
                if not bundle:
                    continue

                sizing_info = temp_engine.predict_position_size_factor(features=features)
                sizing_factor = float(sizing_info.get('sizing_factor') or 1.0)
                replay = _simulate_full_strategy_trade(
                    ml_engine=temp_engine,
                    exit_engine=exit_engine,
                    bundle=bundle,
                    btc_history=btc_history,
                    metadata=meta,
                    entry_p_win=float(probs[test_pos]),
                    fee_rate=fee_rate,
                    test_end_ts=test_end,
                )
                if replay is None:
                    pnl_pct = float(pnl_test[test_pos])
                else:
                    pnl_pct = float(replay['pnl_pct'])

                weighted_pnl_pct = pnl_pct * sizing_factor
                replayed_pnls.append(weighted_pnl_pct)
                full_strategy_pnl_usd += (
                    reference_notional * sizing_factor * pnl_pct / 100.0
                )

            selected_pnls = np.asarray(replayed_pnls, dtype=np.float64)
            trades_taken = int(len(selected_pnls))
            winning_trades = int(np.sum(selected_pnls > 0)) if trades_taken else 0
        else:
            selected_pnls = pnl_test[selected]
            selected_labels = y_test[selected]
            trades_taken = int(np.sum(selected))
            winning_trades = int(np.sum(selected_labels == 1)) if trades_taken else 0

        win_rate = (winning_trades / trades_taken * 100.0) if trades_taken else 0.0
        total_pnl = float(np.sum(selected_pnls)) if trades_taken else 0.0

        gross_profit = float(np.sum(selected_pnls[selected_pnls > 0])) if trades_taken else 0.0
        gross_loss = abs(float(np.sum(selected_pnls[selected_pnls < 0]))) if trades_taken else 0.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float('inf') if gross_profit > 0 else 0.0)
        max_dd = _max_drawdown_from_pnls(selected_pnls)
        brier = float(np.mean(((probs / 100.0) - y_test) ** 2))
        avg_expected_edge = float(np.mean(effective_edge[selected])) if trades_taken else 0.0

        start_str = datetime.fromtimestamp(current_start, timezone.utc).strftime('%Y-%m-%d')
        test_str = datetime.fromtimestamp(train_end, timezone.utc).strftime('%Y-%m-%d')
        pf_text = f"{profit_factor:.2f}" if np.isfinite(profit_factor) else "∞"

        print(
            f"  • #{step_idx} [{start_str} -> {test_str}] "
            f"Train:{len(X_train)} Test:{len(X_test)} Trades:{trades_taken} "
            f"WR:{win_rate:.1f}% PnL:{total_pnl:+.2f}% PF:{pf_text} "
            f"DD:{max_dd:.2f}% Brier:{brier:.4f} Edge:{avg_expected_edge:+.3f}% "
            f"Mode:{'FULL' if full_strategy else 'ENTRY'}"
        )
        if full_strategy:
            print(f"      ↳ PnL capital simulé ({reference_notional:.0f}$ notionnel/trade): {full_strategy_pnl_usd:+.2f}$")

        window_results.append({
            'step': step_idx,
            'start_date': start_str,
            'test_date': test_str,
            'trades_taken': trades_taken,
            'win_rate': win_rate,
            'pnl_net_pct': total_pnl,
            'profit_factor': profit_factor,
            'max_drawdown_pct': max_dd,
            'brier_score': brier,
            'avg_expected_edge_pct': avg_expected_edge,
            'full_strategy': bool(full_strategy),
            'capital_pnl_usd': round(float(full_strategy_pnl_usd), 4) if full_strategy else None,
        })

        current_start += step_days * 86400
        step_idx += 1

    if not window_results:
        print("⚠️ Pas assez de fenêtres temporelles pour effectuer le walk-forward.")
        return True

    nonempty = [w for w in window_results if w['trades_taken'] > 0]
    avg_win_rate = float(np.mean([w['win_rate'] for w in nonempty])) if nonempty else 0.0
    total_pnl = float(sum(w['pnl_net_pct'] for w in window_results))
    avg_brier = float(np.mean([w['brier_score'] for w in window_results]))

    print("\n" + "=" * 70)
    print("📈 RÉSULTATS WALK-FORWARD")
    print(f"  • Fenêtres : {len(window_results)}")
    print(f"  • Win Rate moyen : {avg_win_rate:.1f}%")
    print(f"  • PnL net cumulé des fenêtres : {total_pnl:+.2f}%")
    print(f"  • Brier moyen : {avg_brier:.4f}")
    print("=" * 70 + "\n")
    return True


def main():
    parser = argparse.ArgumentParser(description='Walk-Forward Validation Aegis')
    parser.add_argument('--pairs', default='BTC/USD,ETH/USD,SOL/USD,ADA/USD')
    parser.add_argument('--train-days', type=int, default=90)
    parser.add_argument('--test-days', type=int, default=30)
    parser.add_argument('--step-days', type=int, default=30)
    args = parser.parse_args()

    pairs = [p.strip() for p in args.pairs.split(',') if p.strip()]
    run_walk_forward_validation(
        pairs,
        train_days=args.train_days,
        test_days=args.test_days,
        step_days=args.step_days,
    )


if __name__ == '__main__':
    main()
