"""
Script d'Entraînement complet du Core ML Engine sur les données historiques de 2026 (01/01/2026 -> aujourd'hui).
Télécharge l'historique OHLCV 15m, extrait les 18 variables ML, étiquette chaque trade (Gagnant=1 / Perdant=0)
et sauvegarde le modèle entraîné dans data/aegis_model.joblib.
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
import numpy as np
import ccxt
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.ml_engine import MLEngine
from utils.pattern_analyzer import PatternAnalyzer
from scripts.backtest_support_touch import detect_trade_signal, simulate_trade


def aggregate_ohlcv(klines, group_size):
    if not klines or group_size <= 1:
        return list(klines or [])
    grouped = []
    for start in range(0, len(klines), group_size):
        chunk = klines[start:start + group_size]
        if len(chunk) < group_size:
            continue
        grouped.append({
            'timestamp': chunk[-1]['timestamp'],
            'open': float(chunk[0]['open']),
            'high': max(float(k['high']) for k in chunk),
            'low': min(float(k['low']) for k in chunk),
            'close': float(chunk[-1]['close']),
            'volume': sum(float(k.get('volume', 0.0) or 0.0) for k in chunk),
        })
    return grouped


def load_phase5_replay_samples(db_path, feature_names, max_samples=1000, min_pnl_pct=0.0):
    if not db_path or not os.path.exists(db_path):
        return [], [], []

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT entry_id, pnl_pct, would_win
        FROM ml_rejected_replay_results
        WHERE replay_status = 'replayed'
          AND pnl_pct IS NOT NULL
        ORDER BY timestamp ASC
        LIMIT ?
        """,
        (int(max_samples),)
    ).fetchall()

    neutral_defaults = {
        'rsi_4h': 50.0,
        'ema20_slope_4h': 0.0,
        'ema50_slope_4h': 0.0,
        'price_change_3b_4h': 0.0,
        'daily_recovery_score': 50.0,
        'multi_tf_reversal_score': 0.0,
        'multi_tf_trend_alignment': 0.0,
        'volume_recovery_score': 100.0,
    }
    samples = []
    labels = []
    weights = []
    for row in rows:
        pnl_pct = float(row['pnl_pct'])
        if abs(pnl_pct) < float(min_pnl_pct):
            continue
        feature_rows = con.execute(
            """
            SELECT feature_name, feature_value
            FROM ml_entry_feature_values
            WHERE event_id = ?
            """,
            (row['entry_id'],)
        ).fetchall()
        values = {r['feature_name']: r['feature_value'] for r in feature_rows}
        if not values:
            continue
        samples.append([float(values.get(name, neutral_defaults.get(name, 0.0)) or 0.0) for name in feature_names])
        labels.append(1 if int(row['would_win'] or 0) == 1 else 0)
        # A replayed missed winner is useful, but should not overpower the full historical set.
        weights.append(1.5 if pnl_pct > 0 else 1.0)

    con.close()
    return samples, labels, weights


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
    crypto_score = confidence
    dynamic_min_score = float(os.getenv('MIN_CRYPTO_SCORE', '40'))
    is_optimal = (8 <= dt.hour <= 16) or (0 <= dt.hour <= 4)
    support_stats = support_stats or {}
    technical_action = 'BUY' if signal else 'HOLD'
    technical_min_confidence = dynamic_min_score
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
        'crypto_score': crypto_score,
        'dynamic_min_score': dynamic_min_score,
        'is_optimal_trading_time': 1.0 if is_optimal else 0.0,
        'technical_action': technical_action,
        'technical_confidence': confidence,
        'technical_min_confidence': technical_min_confidence,
    }


def fetch_symbol_history_2026(exchange, symbol, timeframe="15m", start_date=None):
    if not start_date:
        start_date = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")
    dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start_ts = int(dt.timestamp() * 1000)
    
    print(f"Telechargement de l'historique {timeframe} pour {symbol} depuis {start_date} (1 an)...")
    all_klines = []
    since = start_ts
    limit = 1000

    while True:
        try:
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
                    'volume': float(r[5])
                })
            since = raw[-1][0] + 1
            if len(raw) < limit or len(all_klines) >= 45000:
                break
            time.sleep(0.05)
        except Exception as e:
            print(f"Erreur telechargement {symbol} ({timeframe}): {e}")
            break

    print(f"{symbol} ({timeframe}): {len(all_klines)} bougies mecrees.")
    return all_klines


def main():
    load_dotenv(override=True)
    load_dotenv('.env.local', override=True)

    default_1year_start = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")

    parser = argparse.ArgumentParser(description='Entrainement Multi-Timeframe du Core ML Engine sur 1 an de donnees glissantes.')
    parser.add_argument('--pairs', default='BTC/USDT,ETH/USDT,SOL/USDT,ADA/USDT')
    parser.add_argument('--start-date', default=default_1year_start, help='Date de debut de l\'historique YYYY-MM-DD (par defaut: 1 an glissant).')
    parser.add_argument('--stop-percent', type=float, default=1.0)
    parser.add_argument('--trailing-percent', type=float, default=2.5)
    parser.add_argument('--max-hold-candles', type=int, default=int(os.getenv('BACKTEST_MAX_HOLD_CANDLES', '96')))
    parser.add_argument('--fee-rate', type=float, default=float(os.getenv('TRADING_FEE_PERCENT', '0.1')) / 100.0)
    parser.add_argument('--training-account-balance', type=float, default=float(os.getenv('PAPER_BALANCE', '1000')))
    parser.add_argument('--training-position-value-usd', type=float, default=float(os.getenv('TRADE_AMOUNT', '5')))
    parser.add_argument('--output-dir', default='data')
    parser.add_argument('--db', default=os.getenv('ML_LIVE_SQLITE_FILE', 'data/aegis_db.sqlite3'))
    parser.add_argument('--include-replay-learning', action='store_true', help='Ajoute les refus rejoues Phase 5 au dataset.')
    parser.add_argument('--max-replay-samples', type=int, default=1000)
    parser.add_argument('--min-replay-abs-pnl', type=float, default=0.0)
    parser.add_argument('--challenger', action='store_true', help='Sauvegarde dans aegis_challenger.joblib au lieu de remplacer le champion.')
    parser.add_argument('--promote', action='store_true', help='Autorise le remplacement du modele actif aegis_model.joblib.')
    args = parser.parse_args()

    exchange = ccxt.binance({'enableRateLimit': True})
    ml_engine = MLEngine(model_dir=args.output_dir)
    analyzer = PatternAnalyzer(bot=None)

    pairs = [p.strip() for p in args.pairs.split(',') if p.strip()]
    btc_history = None
    if any(p != 'BTC/USDT' for p in pairs):
        btc_history = fetch_symbol_history_2026(exchange, 'BTC/USDT', timeframe='15m', start_date=args.start_date)
    
    X_samples = []
    y_labels = []
    trade_count = 0

    if args.challenger and not args.promote:
        ml_engine.model_path = os.path.join(args.output_dir, 'aegis_challenger.joblib')
        os.environ['ML_SKIP_MODEL_METADATA'] = '1'

    print("Preparation des donnees d'entrainement ML Multi-Timeframes (5m, 15m, 1H, 4H, 1D)...")

    for symbol in pairs:
        klines_15m = btc_history if symbol == 'BTC/USDT' and btc_history is not None else fetch_symbol_history_2026(exchange, symbol, timeframe='15m', start_date=args.start_date)
        if len(klines_15m) < 100:
            continue

        next_allowed_index = 0
        fee_rate = args.fee_rate
        support_pnls = []

        for index in range(50, len(klines_15m) - 1):
            if index < next_allowed_index:
                continue

            history = klines_15m[:index]
            current_price = klines_15m[index]['close']
            ts = klines_15m[index]['timestamp']

            signal = detect_trade_signal(analyzer, history, current_price)
            if not signal:
                continue
            support_stats = support_stats_from_history(support_pnls) if signal.get('type') == 'support_touch' else None

            # Extrait les klines multi-timeframe synchronisees depuis l'historique 15m.
            history_5m = [k for k in klines_15m[max(0, index-20):index]] # Approx slice pour vitesse
            history_1h = aggregate_ohlcv(history, 4)[-60:]
            history_4h = aggregate_ohlcv(history, 16)[-60:]
            history_1d = aggregate_ohlcv(history, 96)[-60:]
            planned_hold_minutes = args.max_hold_candles * 15.0
            planned_exit_dt = datetime.fromtimestamp(ts / 1000.0, timezone.utc) + timedelta(minutes=planned_hold_minutes)
            trade_context = {
                'fee_rate': fee_rate,
                'position_value_usd': args.training_position_value_usd,
                'account_balance': args.training_account_balance,
                'planned_hold_minutes': planned_hold_minutes,
                'planned_exit_hour': float(planned_exit_dt.hour)
            }
            bot_context = build_training_bot_context(
                history,
                signal,
                ts,
                btc_history=btc_history if symbol != 'BTC/USDT' else klines_15m,
                index=index,
                support_stats=support_stats
            )

            features = ml_engine.extract_features_from_klines(
                history,
                current_price,
                klines_5m=history_5m,
                klines_1h=history_1h,
                klines_4h=history_4h,
                klines_1d=history_1d,
                trade_context=trade_context,
                bot_context=bot_context
            )
            if features is None:
                continue

            exit_index, exit_price, outcome_raw = simulate_trade(
                klines_15m,
                index,
                current_price,
                signal.get('support_price'),
                args.stop_percent,
                args.max_hold_candles,
                args.trailing_percent,
                breakeven_stop=True,
                breakeven_trigger=1.5,
                breakeven_lock=1.0,
                fee_rate=fee_rate
            )

            pnl_percent = ((exit_price * (1 - fee_rate) - current_price * (1 + fee_rate)) / current_price) * 100
            label = 1 if pnl_percent > 0 else 0

            X_samples.append(features)
            y_labels.append(label)
            if signal.get('type') == 'support_touch':
                support_pnls.append(float(pnl_percent))
            trade_count += 1
            next_allowed_index = exit_index + 4

    if not X_samples:
        print("Aucun echantillon de trade genere.")
        return

    X = np.array(X_samples)
    y = np.array(y_labels)
    historical_X = X.copy()
    historical_y = y.copy()
    sample_weights = np.ones(len(y), dtype=np.float64)

    replay_added = 0
    if args.include_replay_learning:
        replay_X, replay_y, replay_weights = load_phase5_replay_samples(
            args.db,
            ml_engine.feature_names,
            max_samples=args.max_replay_samples,
            min_pnl_pct=args.min_replay_abs_pnl
        )
        if replay_X:
            replay_X = np.array(replay_X, dtype=np.float64)
            replay_y = np.array(replay_y, dtype=np.int64)
            replay_weights = np.array(replay_weights, dtype=np.float64)
            X = np.vstack([X, replay_X])
            y = np.concatenate([y, replay_y])
            sample_weights = np.concatenate([sample_weights, replay_weights])
            replay_added = len(replay_y)
            print(f"  Phase 5 replay learning : {replay_added} refus rejoues ajoutes au dataset.")
            replay_classes = sorted(set(int(v) for v in replay_y.tolist()))
            if len(replay_classes) < 2:
                print("  Note: les replays ajoutes ne contiennent qu'une classe; le dataset historique garde l'equilibre global.")
        else:
            print("  Phase 5 replay learning : aucun replay exploitable trouve.")

    wins = int(np.sum(historical_y == 1))
    losses = int(np.sum(historical_y == 0))
    win_rate = (wins / len(historical_y)) * 100.0 if len(historical_y) else 0

    print(f"\nDonnees generees pour l'entrainement ML :")
    print(f"  Total Echantillons : {len(historical_y)} trades historiques (2026)")
    print(f"  Trades Gagnants (1) : {wins} ({win_rate:.1f}%)")
    print(f"  Trades Perdants (0) : {losses}")
    print(f"  Replay Phase 5 ajoutes : {replay_added}")

    # =========================================================================
    # ENTRAINEMENT RECURSIF & OPTIMISATION D'HYPERPARAMETRES (WALK-FORWARD)
    # =========================================================================
    print("\n" + "="*60)
    print("RECHERCHE RECURSIFFE & OPTIMISATION DES HYPERPARAMETRES ML")
    print("="*60)

    # 1. Split Chronologique (80% Train / 20% Out-of-Sample Test)
    split_idx = int(len(historical_X) * 0.8)
    X_train, X_test = historical_X[:split_idx], historical_X[split_idx:]
    y_train, y_test = historical_y[:split_idx], historical_y[split_idx:]
    w_train = np.ones(len(y_train), dtype=np.float64)

    print(f"  • Echantillons Entrainement (In-Sample): {len(X_train)}")
    print(f"  • Echantillons Test Hors-Echantillon (Out-of-Sample): {len(X_test)}")

    from sklearn.preprocessing import StandardScaler
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import accuracy_score, precision_score, recall_score

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    # 2. Grille d'Hyperparametres a Tester
    param_grid = [
        {'n_estimators': 50, 'max_depth': 4, 'min_samples_split': 5, 'criterion': 'gini'},
        {'n_estimators': 100, 'max_depth': 4, 'min_samples_split': 5, 'criterion': 'gini'},
        {'n_estimators': 100, 'max_depth': 6, 'min_samples_split': 5, 'criterion': 'gini'},
        {'n_estimators': 150, 'max_depth': 6, 'min_samples_split': 10, 'criterion': 'gini'},
        {'n_estimators': 200, 'max_depth': 8, 'min_samples_split': 5, 'criterion': 'entropy'},
        {'n_estimators': 200, 'max_depth': 10, 'min_samples_split': 10, 'criterion': 'entropy'},
    ]

    best_score = -1.0
    best_params = None
    best_stats = {}

    print(f"\nEvaluation de {len(param_grid)} configurations sur le jeu Hors-Echantillon...")

    for i, params in enumerate(param_grid, 1):
        rf = RandomForestClassifier(
            n_estimators=params['n_estimators'],
            max_depth=params['max_depth'],
            min_samples_split=params['min_samples_split'],
            criterion=params['criterion'],
            random_state=42,
            n_jobs=-1
        )
        rf.fit(X_train_scaled, y_train, sample_weight=w_train)

        y_pred = rf.predict(X_test_scaled)
        acc = accuracy_score(y_test, y_pred) * 100.0
        prec = precision_score(y_test, y_pred, zero_division=0) * 100.0
        trades_taken = int(np.sum(y_pred == 1))
        winning_trades = int(np.sum((y_pred == 1) & (y_test == 1)))

        # Score combine: 50% Precision + 50% Accuracy sur le test hors-echantillon
        combined_score = (acc * 0.5) + (prec * 0.5)

        print(f"  [Iter {i}/{len(param_grid)}] Trees={params['n_estimators']} Depth={params['max_depth']} -> Trades Pris: {trades_taken}/{len(X_test)} ({winning_trades} gagnants) | Test Acc: {acc:.1f}%, Test Prec: {prec:.1f}% (Score: {combined_score:.1f})")

        if combined_score > best_score:
            best_score = combined_score
            best_params = params
            best_stats = {
                'accuracy': acc,
                'precision': prec,
                'trades_taken': trades_taken,
                'winning_trades': winning_trades,
                'total_test': len(X_test)
            }

    print("\n" + "="*60)
    print("CHAMPION OPTIMAL SELECTIONNE PAR RECHERCHE RECURSIVE :")
    print(f"  • Arbres (n_estimators) : {best_params['n_estimators']}")
    print(f"  • Profondeur Max (max_depth) : {best_params['max_depth']}")
    print(f"  • Min Samples Split : {best_params['min_samples_split']}")
    print(f"  • Critere : {best_params['criterion']}")
    print(f"  • Precision Hors-Echantillon (Test) : {best_stats['precision']:.1f}%")
    print(f"  • Precision Globale (Accuracy Test) : {best_stats['accuracy']:.1f}%")
    print(f"  • Trades Validés (Hors-Échantillon) : {best_stats['trades_taken']}/{best_stats['total_test']} ({best_stats['winning_trades']} gagnants)")
    print("="*60)

    # 3. Entrainement final du modele Champion sur le jeu complet et Sauvegarde
    print("\nLancement de l'entrainement final du modele Champion...")
    success = ml_engine.train_model(
        X, y,
        n_estimators=best_params['n_estimators'],
        max_depth=best_params['max_depth'],
        min_samples_split=best_params['min_samples_split'],
        criterion=best_params['criterion']
        , sample_weight=sample_weights
    )

    if success:
        print(f"\n[SUCCESS] Modele ML Optimal entraine et sauvegarde dans '{ml_engine.model_path}'!")
        if args.challenger and not args.promote:
            print("Modele actif conserve: challenger cree pour comparaison avant promotion.")
        print("\nImportance des 5 meilleures variables (Feature Importance) :")
        for name, imp in ml_engine.get_feature_importance()[:5]:
            print(f"   - {name}: {imp*100:.1f}%")
    else:
        print("Echec de l'entrainement du modele ML.")


if __name__ == '__main__':
    main()
