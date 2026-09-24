"""
Validation walk-forward temporelle du modèle ML Aegis.

- Fenêtres train/test chronologiques glissantes.
- Données multi-timeframe réelles.
- Aucun mélange aléatoire passé/futur.
- PnL mesuré à partir des résultats simulés réels, pas d'hypothèse +1.5/-1.0.
"""
import os
import sys
import argparse
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
)


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

        samples, labels, metadata = generate_samples_from_klines(
            {
                '15m': klines_15m,
                '5m': klines_5m,
                '1h': klines_1h,
                '4h': klines_4h,
                '1d': klines_1d,
            },
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

    if not all_samples:
        print("❌ Aucune donnée générée pour la validation walk-forward.")
        return False

    ml_engine = MLEngine(model_dir='data')
    feature_names = ml_engine.feature_names

    X_matrix = np.array([
        [float(sample.get(name, 0.0) or 0.0) for name in feature_names]
        for sample in all_samples
    ], dtype=np.float64)
    y_array = np.asarray(all_labels, dtype=np.int64)
    ts_array = np.asarray(all_timestamps, dtype=np.float64)
    pnl_array = np.asarray(all_pnls, dtype=np.float64)

    # Mélange des symboles interdit: ordre chronologique global avant toute fenêtre.
    order = np.argsort(ts_array, kind='stable')
    X_matrix = X_matrix[order]
    y_array = y_array[order]
    ts_array = ts_array[order]
    pnl_array = pnl_array[order]

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
        pnl_test = pnl_array[test_mask]

        if len(X_train) < 100 or len(X_test) < 20 or len(np.unique(y_train)) < 2:
            current_start += step_days * 86400
            continue

        temp_engine = MLEngine(model_dir='data')
        if not temp_engine.train_model(
            X_train,
            y_train,
            n_estimators=100,
            max_depth=6,
            use_lightgbm=os.getenv('ML_USE_LIGHTGBM', 'true').lower() == 'true',
        ):
            current_start += step_days * 86400
            continue

        X_eval = temp_engine.scaler.transform(X_test) if temp_engine.scaler is not None else X_test
        raw_probs = temp_engine.model.predict_proba(X_eval)
        probs = raw_probs[:, 1] * 100.0 if raw_probs.shape[1] > 1 else np.full(len(X_test), 50.0)

        selected = probs >= decision_threshold
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

        start_str = datetime.fromtimestamp(current_start, timezone.utc).strftime('%Y-%m-%d')
        test_str = datetime.fromtimestamp(train_end, timezone.utc).strftime('%Y-%m-%d')
        pf_text = f"{profit_factor:.2f}" if np.isfinite(profit_factor) else "∞"

        print(
            f"  • #{step_idx} [{start_str} -> {test_str}] "
            f"Train:{len(X_train)} Test:{len(X_test)} Trades:{trades_taken} "
            f"WR:{win_rate:.1f}% PnL:{total_pnl:+.2f}% PF:{pf_text} "
            f"DD:{max_dd:.2f}% Brier:{brier:.4f}"
        )

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
