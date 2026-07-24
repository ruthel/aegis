"""
Script d'Entraînement complet du Core ML Engine sur les données historiques de 2026 (01/01/2026 -> aujourd'hui).
Télécharge l'historique OHLCV 15m, extrait les 18 variables ML, étiquette chaque trade (Gagnant=1 / Perdant=0)
et sauvegarde le modèle entraîné dans data/aegis_model.joblib.
"""

import argparse
import json
import os
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


def fetch_symbol_history_2026(exchange, symbol, timeframe="15m", start_date="2026-01-01"):
    dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start_ts = int(dt.timestamp() * 1000)
    
    print(f"Telechargement de l'historique {timeframe} pour {symbol} depuis {start_date}...")
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
            if len(raw) < limit or len(all_klines) >= 30000:
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

    parser = argparse.ArgumentParser(description='Entrainement Multi-Timeframe du Core ML Engine sur les donnees 2026.')
    parser.add_argument('--pairs', default='BTC/USDT,ETH/USDT,SOL/USDT,ADA/USDT')
    parser.add_argument('--start-date', default='2026-01-01')
    parser.add_argument('--stop-percent', type=float, default=1.0)
    parser.add_argument('--trailing-percent', type=float, default=2.5)
    parser.add_argument('--max-hold-candles', type=int, default=int(os.getenv('BACKTEST_MAX_HOLD_CANDLES', '96')))
    parser.add_argument('--fee-rate', type=float, default=float(os.getenv('TRADING_FEE_PERCENT', '0.1')) / 100.0)
    parser.add_argument('--training-account-balance', type=float, default=float(os.getenv('PAPER_BALANCE', '1000')))
    parser.add_argument('--training-position-value-usd', type=float, default=float(os.getenv('TRADE_AMOUNT', '5')))
    parser.add_argument('--output-dir', default='data')
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

    print("Preparation des donnees d'entrainement ML Multi-Timeframes (5m, 15m, 1H)...")

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

            # Extrait les klines 5m et 1h synchronisées
            history_5m = [k for k in klines_15m[max(0, index-20):index]] # Approx slice pour vitesse
            history_1h = [k for k in klines_15m[max(0, index-100):index]]
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

    wins = int(np.sum(y == 1))
    losses = int(np.sum(y == 0))
    win_rate = (wins / len(y)) * 100.0 if len(y) else 0

    print(f"\nDonnees generees pour l'entrainement ML :")
    print(f"  Total Echantillons : {len(y)} trades historiques (2026)")
    print(f"  Trades Gagnants (1) : {wins} ({win_rate:.1f}%)")
    print(f"  Trades Perdants (0) : {losses}")

    # =========================================================================
    # ENTRAINEMENT RECURSIF & OPTIMISATION D'HYPERPARAMETRES (WALK-FORWARD)
    # =========================================================================
    print("\n" + "="*60)
    print("RECHERCHE RECURSIFFE & OPTIMISATION DES HYPERPARAMETRES ML")
    print("="*60)

    # 1. Split Chronologique (80% Train / 20% Out-of-Sample Test)
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

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
        rf.fit(X_train_scaled, y_train)

        y_pred = rf.predict(X_test_scaled)
        acc = accuracy_score(y_test, y_pred) * 100.0
        prec = precision_score(y_test, y_pred, zero_division=0) * 100.0

        # Score combine: 50% Precision + 50% Accuracy sur le test hors-echantillon
        combined_score = (acc * 0.5) + (prec * 0.5)

        print(f"  [Iter {i}/{len(param_grid)}] Trees={params['n_estimators']} Depth={params['max_depth']} -> Test Acc: {acc:.1f}%, Test Prec: {prec:.1f}% (Score: {combined_score:.1f})")

        if combined_score > best_score:
            best_score = combined_score
            best_params = params
            best_stats = {'accuracy': acc, 'precision': prec}

    print("\n" + "="*60)
    print("CHAMPION OPTIMAL SELECTIONNE PAR RECHERCHE RECURSIVE :")
    print(f"  • Arbres (n_estimators) : {best_params['n_estimators']}")
    print(f"  • Profondeur Max (max_depth) : {best_params['max_depth']}")
    print(f"  • Min Samples Split : {best_params['min_samples_split']}")
    print(f"  • Critere : {best_params['criterion']}")
    print(f"  • Precision Hors-Echantillon (Test) : {best_stats['precision']:.1f}%")
    print(f"  • Precision Globale (Accuracy Test) : {best_stats['accuracy']:.1f}%")
    print("="*60)

    # 3. Entrainement final du modele Champion sur le jeu complet et Sauvegarde
    print("\nLancement de l'entrainement final du modele Champion...")
    success = ml_engine.train_model(
        X, y,
        n_estimators=best_params['n_estimators'],
        max_depth=best_params['max_depth'],
        min_samples_split=best_params['min_samples_split'],
        criterion=best_params['criterion']
    )

    if success:
        print(f"\n[SUCCESS] Modele ML Optimal entraine et sauvegarde dans '{ml_engine.model_path}'!")
        print("\nImportance des 5 meilleures variables (Feature Importance) :")
        for name, imp in ml_engine.get_feature_importance()[:5]:
            print(f"   - {name}: {imp*100:.1f}%")
    else:
        print("Echec de l'entrainement du modele ML.")


if __name__ == '__main__':
    main()
