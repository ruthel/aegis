"""
Entraîne le modèle ML de sortie/continuation pour Aegis.

Le modèle apprend sur des états intermédiaires de position:
continuer la position est positif si le PnL final simulé reste meilleur
que sortir immédiatement, après frais.
"""

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import ccxt
import numpy as np
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.ml_engine import MLEngine
from scripts.backtest_support_touch import detect_trade_signal, simulate_trade
from utils.exit_engine import ExitDecisionEngine
from utils.pattern_analyzer import PatternAnalyzer


def simple_regime(history):
    if len(history) < 50:
        return 'SIDEWAYS'
    closes = np.array([float(k['close']) for k in history], dtype=np.float64)
    ema20 = np.mean(closes[-20:])
    ema50 = np.mean(closes[-50:])
    if closes[-1] > ema20 > ema50:
        return 'BULL'
    if closes[-1] < ema20 < ema50:
        return 'BEAR'
    if len(closes) >= 13:
        ema10_curr = np.mean(closes[-10:])
        ema10_prev = np.mean(closes[-13:-3])
        slope = (ema10_curr - ema10_prev) / (ema10_prev + 1e-9)
        if slope < -0.0002:
            return 'SIDEWAYS_DOWN'
        if slope > 0.0002:
            return 'SIDEWAYS_UP'
    return 'SIDEWAYS'


def support_stats_from_history(pnls):
    if not pnls:
        return {'winrate': 0.0, 'total_pnl': 0.0, 'avg_pnl': 0.0}
    window = pnls[-50:]
    wins = len([p for p in window if p > 0])
    return {
        'winrate': wins / len(window) * 100.0,
        'total_pnl': float(sum(window)),
        'avg_pnl': float(sum(window) / len(window)),
    }


def build_training_bot_context(history, signal, ts, btc_history=None, index=None, support_stats=None):
    symbol_regime = simple_regime(history)
    btc_regime = None
    if btc_history is not None and index is not None:
        btc_regime = simple_regime(btc_history[:index])
    dt = datetime.fromtimestamp(ts / 1000.0, timezone.utc)
    confidence = float((signal or {}).get('confidence') or 0.0)
    dynamic_min_score = float(os.getenv('MIN_CRYPTO_SCORE', '40'))
    support_stats = support_stats or {}
    technical_action = 'BUY' if signal else 'HOLD'
    return {
        'symbol_regime': symbol_regime,
        'btc_regime': btc_regime,
        'bear_mode': symbol_regime in ('BEAR', 'SIDEWAYS_DOWN') or btc_regime in ('BEAR', 'SIDEWAYS_DOWN'),
        'reversal_confirmed': False,
        'falling_knife_active': False,
        'is_support_touch': (signal or {}).get('type') == 'support_touch',
        'support_confidence': confidence if (signal or {}).get('type') == 'support_touch' else 0.0,
        'support_rebounds': float((signal or {}).get('rebounds') or 0.0),
        'support_backtest_winrate': float(support_stats.get('winrate', 0.0) or 0.0),
        'support_backtest_total_pnl': float(support_stats.get('total_pnl', 0.0) or 0.0),
        'support_backtest_avg_pnl': float(support_stats.get('avg_pnl', 0.0) or 0.0),
        'crypto_score': confidence,
        'dynamic_min_score': dynamic_min_score,
        'is_optimal_trading_time': 1.0 if ((8 <= dt.hour <= 16) or (0 <= dt.hour <= 4)) else 0.0,
        'technical_action': technical_action,
        'technical_confidence': confidence,
        'technical_min_confidence': dynamic_min_score,
    }


def fetch_symbol_history(exchange, symbol, timeframe="15m", start_date="2026-01-01"):
    dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    since = int(dt.timestamp() * 1000)
    all_klines = []
    limit = 1000

    print(f"Téléchargement {symbol} {timeframe} depuis {start_date}...")
    while True:
        raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=limit)
        if not raw:
            break
        for r in raw:
            all_klines.append({
                'timestamp': r[0],
                'open': float(r[1]),
                'high': float(r[2]),
                'low': float(r[3]),
                'close': float(r[4]),
                'volume': float(r[5]),
            })
        since = raw[-1][0] + 1
        if len(raw) < limit or len(all_klines) >= 30000:
            break
        time.sleep(0.05)

    print(f"{symbol}: {len(all_klines)} bougies.")
    return all_klines


def kline_dt(kline):
    return datetime.fromtimestamp(kline['timestamp'] / 1000.0, timezone.utc)


def net_pnl_pct(entry_price, exit_price, fee_rate):
    return ((exit_price * (1 - fee_rate) - entry_price * (1 + fee_rate)) / entry_price) * 100.0


def main():
    load_dotenv(override=True)
    load_dotenv('.env.local', override=True)

    parser = argparse.ArgumentParser(description='Entraîne le ML de sortie/continuation.')
    parser.add_argument('--pairs', default='BTC/USDT,ETH/USDT,SOL/USDT,ADA/USDT')
    parser.add_argument('--start-date', default='2026-01-01')
    parser.add_argument('--fee-rate', type=float, default=float(os.getenv('TRADING_FEE_PERCENT', '0.1')) / 100.0)
    parser.add_argument('--stop-percent', type=float, default=float(os.getenv('BACKTEST_STOP_PERCENT', '1.0')))
    parser.add_argument('--trailing-percent', type=float, default=float(os.getenv('TRAILING_STOP_PERCENT', '2.5')))
    parser.add_argument('--max-hold-candles', type=int, default=int(os.getenv('BACKTEST_MAX_HOLD_CANDLES', '96')))
    parser.add_argument('--sample-step', type=int, default=4)
    parser.add_argument('--output-dir', default='data')
    args = parser.parse_args()

    exchange = ccxt.binance({'enableRateLimit': True})
    ml_engine = MLEngine(model_dir=args.output_dir)
    exit_engine = ExitDecisionEngine()
    analyzer = PatternAnalyzer(bot=None)

    pairs = [p.strip() for p in args.pairs.split(',') if p.strip()]
    btc_history = fetch_symbol_history(exchange, 'BTC/USDT', timeframe='15m', start_date=args.start_date)

    X_samples = []
    y_labels = []
    trade_count = 0

    for symbol in pairs:
        klines = btc_history if symbol == 'BTC/USDT' else fetch_symbol_history(exchange, symbol, timeframe='15m', start_date=args.start_date)
        if len(klines) < 150:
            continue

        next_allowed_index = 0
        support_pnls = []
        for index in range(50, len(klines) - args.max_hold_candles - 1):
            if index < next_allowed_index:
                continue

            history = klines[:index]
            entry_price = klines[index]['close']
            signal = detect_trade_signal(analyzer, history, entry_price)
            if not signal:
                continue
            support_stats = support_stats_from_history(support_pnls) if signal.get('type') == 'support_touch' else None
            entry_bot_context = build_training_bot_context(
                history,
                signal,
                klines[index]['timestamp'],
                btc_history=btc_history if symbol != 'BTC/USDT' else klines,
                index=index,
                support_stats=support_stats
            )

            exit_index, exit_price, _ = simulate_trade(
                klines,
                index,
                entry_price,
                signal.get('support_price'),
                args.stop_percent,
                args.max_hold_candles,
                args.trailing_percent,
                breakeven_stop=True,
                breakeven_trigger=1.5,
                breakeven_lock=1.0,
                fee_rate=args.fee_rate
            )
            final_net = net_pnl_pct(entry_price, exit_price, args.fee_rate)
            entry_p_win = ml_engine.predict_win_probability(history, entry_price, bot_context=entry_bot_context)

            for sample_index in range(index + 1, exit_index, max(1, args.sample_step)):
                sample_history = klines[:sample_index]
                if len(sample_history) < 30:
                    continue

                current_price = klines[sample_index]['close']
                immediate_net = net_pnl_pct(entry_price, current_price, args.fee_rate)
                remaining_edge = final_net - immediate_net
                duration_minutes = (sample_index - index) * 15.0

                btc_klines = None
                if symbol != 'BTC/USDT' and len(btc_history) > sample_index:
                    btc_klines = btc_history[max(0, sample_index - 30):sample_index]
                sample_bot_context = build_training_bot_context(
                    sample_history,
                    signal,
                    klines[sample_index]['timestamp'],
                    btc_history=btc_history if symbol != 'BTC/USDT' else klines,
                    index=sample_index,
                    support_stats=support_stats
                )

                position_data = {
                    'buy_price': entry_price,
                    'fee_rate': args.fee_rate,
                    'duration_minutes': duration_minutes,
                    'stop_loss_price': signal.get('support_price') or entry_price * (1 - args.stop_percent / 100.0),
                    'target_price': signal.get('resistance_price') or entry_price * 1.015,
                    'created_at': (kline_dt(klines[index])).isoformat(),
                }
                continuation_score = exit_engine.compute_continuation_score(
                    symbol, current_price, sample_history[-30:], btc_klines, position_data
                )
                features = ml_engine.extract_exit_features(
                    sample_history[-60:],
                    current_price,
                    position_data,
                    continuation_score,
                    entry_p_win=entry_p_win,
                    btc_klines=btc_klines,
                    bot_context=sample_bot_context
                )
                if features is None:
                    continue

                label = 1 if remaining_edge > 0.05 else 0
                X_samples.append(features)
                y_labels.append(label)

            trade_count += 1
            if signal.get('type') == 'support_touch':
                support_pnls.append(float(final_net))
            next_allowed_index = exit_index + 4

    if not X_samples:
        print("Aucun échantillon de sortie généré.")
        return

    X = np.array(X_samples)
    y = np.array(y_labels)
    keep = int(np.sum(y == 1))
    exit_now = int(np.sum(y == 0))
    print("\nDataset ML sortie:")
    print(f"  Trades simulés: {trade_count}")
    print(f"  États de position: {len(y)}")
    print(f"  Continuer profitable: {keep} ({keep / len(y) * 100:.1f}%)")
    print(f"  Sortir/protéger préférable: {exit_now}")

    from sklearn.metrics import accuracy_score, precision_score
    from sklearn.preprocessing import StandardScaler
    from sklearn.ensemble import RandomForestClassifier

    split_idx = int(len(X) * 0.8)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    param_grid = [
        {'n_estimators': 100, 'max_depth': 4, 'min_samples_split': 10, 'criterion': 'gini'},
        {'n_estimators': 150, 'max_depth': 6, 'min_samples_split': 10, 'criterion': 'gini'},
        {'n_estimators': 200, 'max_depth': 8, 'min_samples_split': 10, 'criterion': 'entropy'},
    ]

    best = None
    best_score = -1.0
    for params in param_grid:
        model = RandomForestClassifier(random_state=43, n_jobs=-1, **params)
        model.fit(X_train_scaled, y_train)
        pred = model.predict(X_test_scaled)
        acc = accuracy_score(y_test, pred) * 100.0
        prec = precision_score(y_test, pred, zero_division=0) * 100.0
        score = (acc + prec) / 2.0
        print(f"  {params} -> Acc {acc:.1f}% | Precision continue {prec:.1f}% | Score {score:.1f}")
        if score > best_score:
            best_score = score
            best = params

    success = ml_engine.train_exit_model(X, y, **best)
    if success:
        print(f"\n[SUCCESS] Modèle ML de sortie entraîné et fusionné dans {ml_engine.model_path}")
        for name, imp in (ml_engine.get_exit_feature_importance()[:8] if hasattr(ml_engine, 'get_exit_feature_importance') else []):
            print(f"   - {name}: {imp*100:.1f}%")
    else:
        print("Échec entraînement modèle ML sortie.")


if __name__ == '__main__':
    main()
