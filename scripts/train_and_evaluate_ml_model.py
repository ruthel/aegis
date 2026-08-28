#!/usr/bin/env python3
"""
Pipeline Unifiée d'Entraînement, Évaluation & Promotion ML (Phase 10).

Regroupe l'entraînement complet du modèle Challenger d'Entrée et l'évaluation avec garde-fous
pour la promotion contrôlée en production sans édition manuelle du code.
"""

import os
import sys
import shutil
import argparse
import sqlite3
import time
import json
import gzip
from datetime import datetime, timedelta, timezone
import numpy as np
import ccxt
import requests
from dotenv import load_dotenv

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.ml_engine import MLEngine
from core.ml_live_logger import MLLiveLogger
from core.managers.notification import NotificationManager
from utils.pattern_analyzer import PatternAnalyzer
from scripts.backtest_support_touch import detect_trade_signal, simulate_trade


def detect_trade_signal_augmented(pattern_analyzer, history, current_price):
    """Détecte plus de types de signaux pour augmenter le dataset d'entraînement.
    Retourne le signal du support/breakout d'abord, sinon teste des signaux additionnels."""
    # 1. Signaux existants (support touch + breakout)
    sig = detect_trade_signal(pattern_analyzer, history, current_price)
    if sig:
        return sig

    if len(history) < 25:
        return None

    closes = [float(k['close']) for k in history]
    highs = [float(k['high']) for k in history]
    lows = [float(k['low']) for k in history]
    opens = [float(k['open']) for k in history]

    # Filtre commun: pas d'achat en chute rapide
    if closes[-1] < opens[-1] and (opens[-1] - closes[-1]) / opens[-1] >= 0.008:
        return None

    # 2. SIGNAL: Pullback sur EMA20 en tendance haussière (le prix touche l'EMA20 par le haut)
    ema20 = sum(closes[-20:]) / 20.0
    ema20_prev = sum(closes[-23:-3]) / 20.0
    ema20_rising = ema20 > ema20_prev
    if ema20_rising and lows[-1] <= ema20 <= highs[-1] and closes[-1] >= ema20:
        return {
            'type': 'ema20_pullback',
            'support_price': ema20 * 0.99,
            'resistance_price': current_price * 1.02,
            'rebounds': 1,
            'confidence': 65,
            'reason': f"Pullback EMA20 haussier @ {ema20:.2f}",
        }

    # 3. SIGNAL: Rebond RSI survente (RSI remonte au-dessus de 32 après avoir été < 30)
    def _rsi(vals, period=14):
        if len(vals) < period + 1:
            return 50.0
        gains, losses = [], []
        for i in range(-period, 0):
            d = vals[i] - vals[i - 1]
            gains.append(max(0, d))
            losses.append(max(0, -d))
        ag = sum(gains) / period
        al = sum(losses) / period
        if al == 0:
            return 100.0
        rs = ag / al
        return 100.0 - (100.0 / (1.0 + rs))

    rsi_now = _rsi(closes)
    rsi_prev = _rsi(closes[:-1])
    if rsi_prev < 30 and 30 <= rsi_now <= 45 and closes[-1] > closes[-2]:
        return {
            'type': 'rsi_oversold_rebound',
            'support_price': min(lows[-10:]),
            'resistance_price': current_price * 1.02,
            'rebounds': 1,
            'confidence': 62,
            'reason': f"Rebond RSI survente ({rsi_now:.0f})",
        }

    # 4. SIGNAL: Croisement EMA9 au-dessus EMA20 (momentum haussier naissant)
    ema9 = sum(closes[-9:]) / 9.0
    ema9_prev = sum(closes[-10:-1]) / 9.0
    ema20_prev1 = sum(closes[-21:-1]) / 20.0
    crossed_up = ema9_prev <= ema20_prev1 and ema9 > ema20
    if crossed_up and closes[-1] > opens[-1]:
        return {
            'type': 'ema_cross_up',
            'support_price': ema20 * 0.99,
            'resistance_price': current_price * 1.02,
            'rebounds': 1,
            'confidence': 63,
            'reason': f"Croisement EMA9>EMA20 @ {current_price:.2f}",
        }

    return None


def compute_guardrail_metrics(db_file):
    metrics = {
        'closed_trades_count': 0,
        'active_days': 0,
        'profit_factor': 1.0,
        'net_pnl': 0.0,
        'net_pnl_pct_sum': 0.0,
        'max_drawdown_pct': 0.0,
        'latest_calibration_mae': None,
        'latest_live_win_rate': None,
        'latest_drift_status': None,
        'trade_rows': [],
    }
    if not os.path.exists(db_file):
        return metrics

    conn = sqlite3.connect(db_file)
    try:
        cur = conn.cursor()
        trade_rows = cur.execute("""
            SELECT
                t.symbol,
                COALESCE(e.price, t.buy_price) AS entry_price,
                COALESCE(e.confidence, e.p_win) AS p_win,
                t.pnl_pct,
                t.pnl,
                t.timestamp
            FROM ml_trade_outcomes t
            LEFT JOIN decision_logs e
              ON e.action_type IN ('ENTRY', 'BUY')
             AND (e.event_id = t.entry_id OR e.entry_id = t.entry_id)
            WHERE t.pnl_pct IS NOT NULL
            ORDER BY t.timestamp ASC
        """).fetchall()
        metrics['trade_rows'] = trade_rows
        metrics['closed_trades_count'] = len(trade_rows)
        if trade_rows:
            dates = []
            pnls = []
            pnl_pcts = []
            for row in trade_rows:
                pnl_pcts.append(float(row[3] or 0.0))
                pnls.append(float(row[4] or 0.0))
                try:
                    dates.append(datetime.fromisoformat(str(row[5]).replace('Z', '+00:00')).date())
                except Exception:
                    pass
            metrics['active_days'] = len(set(dates)) if dates else 1
            wins = [p for p in pnl_pcts if p > 0]
            losses = [abs(p) for p in pnl_pcts if p < 0]
            metrics['profit_factor'] = (sum(wins) / sum(losses)) if losses and sum(losses) > 0 else (2.0 if wins else 1.0)
            metrics['net_pnl'] = sum(pnls)
            metrics['net_pnl_pct_sum'] = sum(pnl_pcts)

            equity = 0.0
            peak = 0.0
            max_dd = 0.0
            for pct in pnl_pcts:
                equity += pct
                peak = max(peak, equity)
                max_dd = max(max_dd, peak - equity)
            metrics['max_drawdown_pct'] = max_dd

        latest_analysis = cur.execute("""
            SELECT calibration_mae, live_win_rate, drift_status
            FROM ml_analysis_runs
            ORDER BY generated_at DESC
            LIMIT 1
        """).fetchone()
        if latest_analysis:
            metrics['latest_calibration_mae'] = latest_analysis[0]
            metrics['latest_live_win_rate'] = latest_analysis[1]
            metrics['latest_drift_status'] = latest_analysis[2]
    finally:
        conn.close()
    return metrics


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
        'rebound_from_recent_low_pct': 0.0,
        'previous_drop_pct': 0.0,
        'rebound_vs_drop_ratio': 0.0,
        'rebound_volume_ratio': 1.0,
        'green_candle_count_5': 0.0,
        'follow_through_3b_pct': 0.0,
        'momentum_decay_3b': 0.0,
        'upper_wick_rejection_ratio': 0.0,
        'distance_to_ema20_pct': 0.0,
        'ema20_rejection_active': 0.0,
        'rsi_rebound_strength': 0.0,
        'rebound_stall_score': 0.0,
    }
    samples, labels, weights = [], [], []
    for row in rows:
        pnl_pct = float(row['pnl_pct'])
        if abs(pnl_pct) < float(min_pnl_pct):
            continue
        feature_rows = con.execute(
            "SELECT feature_name, feature_value FROM ml_feature_values WHERE event_id = ?",
            (row['entry_id'],)
        ).fetchall()
        values = {r['feature_name']: r['feature_value'] for r in feature_rows}
        if not values:
            continue
        samples.append([float(values.get(name, neutral_defaults.get(name, 0.0)) or 0.0) for name in feature_names])
        labels.append(1 if int(row['would_win'] or 0) == 1 else 0)
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


def sizing_factor_target_from_pnl(pnl_percent):
    """Cible prudente pour le sizing model, derivee du resultat net historique."""
    pnl = float(pnl_percent or 0.0)
    if pnl <= -0.30:
        return 0.25
    if pnl <= 0.0:
        return 0.40
    if pnl < 0.30:
        return 0.50
    if pnl < 0.80:
        return 0.75
    if pnl < 1.60:
        return 1.00
    return 1.25


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


def _prune_model_backups(backups_dir, keep=10):
    """Ne conserve que les `keep` archives de modèle les plus récentes dans backups_dir."""
    try:
        import glob
        archives = glob.glob(os.path.join(backups_dir, 'aegis_model_*.joblib'))
        archives.sort(reverse=True)  # horodatage YYYYMMDD_HHMMSS -> plus récent en premier
        for old in archives[keep:]:
            try:
                os.remove(old)
                print(f"  🧹 Ancien backup supprimé : {os.path.basename(old)}")
            except Exception:
                pass
    except Exception:
        pass


def _timeframe_ms(timeframe):
    """Convertit un timeframe ('5m','15m','1h','1d') en millisecondes."""
    units = {'m': 60_000, 'h': 3_600_000, 'd': 86_400_000}
    try:
        return int(timeframe[:-1]) * units[timeframe[-1]]
    except (KeyError, ValueError):
        return 15 * 60_000  # défaut 15m


def _cache_path(symbol, timeframe):
    """Chemin du fichier cache OHLCV pour un (symbole, timeframe)."""
    cache_dir = os.getenv('ML_OHLCV_CACHE_DIR', os.path.join('data', 'ohlcv_cache'))
    os.makedirs(cache_dir, exist_ok=True)
    safe_symbol = symbol.replace('/', '-')
    return os.path.join(cache_dir, f"{safe_symbol}_{timeframe}.json.gz")


def _load_cache(symbol, timeframe):
    """Charge les bougies en cache (liste triée par timestamp), ou [] si absent/corrompu."""
    import gzip
    path = _cache_path(symbol, timeframe)
    if not os.path.exists(path):
        return []
    try:
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        print(f"      ⚠️ Cache illisible {symbol} {timeframe} ({e}) → refetch complet")
        return []


def _save_cache(symbol, timeframe, klines):
    """Sauvegarde les bougies en cache (gzip JSON, écriture atomique)."""
    import gzip
    path = _cache_path(symbol, timeframe)
    tmp = path + '.tmp'
    try:
        with gzip.open(tmp, 'wt', encoding='utf-8') as f:
            json.dump(klines, f, separators=(',', ':'))
        os.replace(tmp, path)
    except Exception as e:
        print(f"      ⚠️ Échec sauvegarde cache {symbol} {timeframe}: {e}")
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def _fetch_ohlcv_range(cb, symbol, timeframe, since, end_ts, max_candles, label=""):
    """Fetch réseau brut des bougies OHLCV entre 'since' et 'end_ts' (avec retry robuste).
    Retourne une liste de dicts. C'est le cœur réseau, sans logique de cache.
    Affiche une progression en direct (barre qui se met à jour sur la même ligne)."""
    fetched = []
    seen = set()
    consecutive_errors = 0
    max_consecutive_errors = 6
    span = max(1, end_ts - since)  # fenêtre temporelle totale à couvrir
    start_since = since
    iterations = 0
    show_progress = os.getenv('ML_FETCH_PROGRESS', 'true').lower() == 'true'

    def _render_progress(done_ratio):
        pct = max(0.0, min(1.0, done_ratio)) * 100.0
        bar_len = 24
        filled = int(bar_len * pct / 100.0)
        bar = '█' * filled + '░' * (bar_len - filled)
        # \r pour réécrire sur la même ligne, pas de \n
        sys.stdout.write(f"\r      {label} [{bar}] {pct:5.1f}% — {len(fetched)} bougies")
        sys.stdout.flush()

    while since < end_ts:
        try:
            klines = cb.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=300)
            consecutive_errors = 0
            if not klines:
                break
            new_count = 0
            for k in klines:
                ts = int(k[0])
                if ts in seen:
                    continue
                seen.add(ts)
                fetched.append({
                    'timestamp': ts,
                    'open': float(k[1]),
                    'high': float(k[2]),
                    'low': float(k[3]),
                    'close': float(k[4]),
                    'volume': float(k[5]),
                })
                new_count += 1
            last = klines[-1][0]
            if new_count == 0 or last <= since:
                break
            since = last + 1
            iterations += 1
            if show_progress and iterations % 5 == 0:
                _render_progress((since - start_since) / span)
            if len(fetched) >= max_candles:
                break
            time.sleep(cb.rateLimit / 1000)
        except Exception as e:
            if 'rate' in str(e).lower() or 'too many' in str(e).lower():
                time.sleep(5)
                continue
            consecutive_errors += 1
            if consecutive_errors >= max_consecutive_errors:
                print(f"      ⚠️ Abandon fetch {symbol} {timeframe} après {consecutive_errors} erreurs consécutives: {e}")
                break
            backoff = min(30, 2 ** consecutive_errors)
            # \n pour ne pas écraser le message d'erreur avec la barre de progression
            if show_progress:
                sys.stdout.write("\n")
            print(f"      ⏳ Erreur transitoire {symbol} {timeframe} (retry {consecutive_errors}/{max_consecutive_errors} dans {backoff}s): {e}")
            time.sleep(backoff)
            since += 300 * _timeframe_ms(timeframe)
            continue

    # Terminer la barre proprement (100% + saut de ligne)
    if show_progress and iterations >= 5:
        _render_progress(1.0)
        sys.stdout.write("\n")
        sys.stdout.flush()

    return fetched


def fetch_symbol_history_2026(exchange, symbol, timeframe="15m", start_date=None):
    """Récupère l'historique OHLCV via Coinbase avec CACHE INCRÉMENTAL sur disque.

    - Charge le cache existant (data/ohlcv_cache/SYMBOL_TF.json.gz)
    - Ne télécharge QUE les bougies plus récentes que la dernière en cache (le delta)
    - Fusionne, purge tout ce qui est plus vieux que la fenêtre (3 ans par défaut), sauvegarde
    Résultat: 1er run long (fetch complet), runs suivants quasi instantanés (delta seulement).
    Désactivable via ML_OHLCV_CACHE_ENABLED=false (refetch complet à chaque fois)."""
    if not start_date:
        history_days = int(os.getenv('ML_TRAINING_HISTORY_DAYS', '1095'))
        start_date = (datetime.now(timezone.utc) - timedelta(days=history_days)).strftime("%Y-%m-%d")
    dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    window_start_ms = int(dt.timestamp() * 1000)  # borne basse de la fenêtre glissante
    end_ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    max_candles = int(os.getenv('ML_TRAINING_MAX_CANDLES', '330000'))
    cache_enabled = os.getenv('ML_OHLCV_CACHE_ENABLED', 'true').lower() == 'true'

    cb = ccxt.coinbase({'enableRateLimit': True})

    cached = _load_cache(symbol, timeframe) if cache_enabled else []
    # Ne garder du cache que ce qui est dans la fenêtre (purge le hors-3-ans)
    cached = [k for k in cached if int(k.get('timestamp', 0)) >= window_start_ms]

    if cached:
        last_cached_ts = max(int(k['timestamp']) for k in cached)
        since = last_cached_ts + 1  # ne fetch que le delta après la dernière bougie connue
        cached_count = len(cached)
    else:
        since = window_start_ms
        cached_count = 0

    delta = _fetch_ohlcv_range(cb, symbol, timeframe, since, end_ts, max_candles, label=f"{symbol} {timeframe}") if since < end_ts else []

    # Fusionner cache + delta, dédupliquer par timestamp, purger la fenêtre, trier
    merged = {}
    for k in cached:
        merged[int(k['timestamp'])] = k
    for k in delta:
        merged[int(k['timestamp'])] = k
    all_klines = [k for ts, k in merged.items() if ts >= window_start_ms]
    all_klines.sort(key=lambda k: int(k['timestamp']))
    # Respecter le plafond en gardant les plus RÉCENTES si dépassement
    if len(all_klines) > max_candles:
        all_klines = all_klines[-max_candles:]

    if cache_enabled:
        _save_cache(symbol, timeframe, all_klines)

    if cached_count:
        print(f"      → {symbol} {timeframe}: {len(all_klines)} bougies (cache: {cached_count}, delta: {len(delta)})")
    else:
        print(f"      → {symbol} {timeframe}: {len(all_klines)} bougies fetchées (cache créé)")
    return all_klines


def generate_samples_from_klines(
    klines_by_tf,
    symbol,
    stop_percent=1.0,
    trailing_percent=2.5,
    fee_rate=float(os.getenv('TRADING_FEE_PERCENT', '0.4')) / 100.0,
    position_value_usd=10.0,
    btc_history=None,
):
    """Génère des samples d'entrée compatibles avec le modèle actif."""
    klines_15m = (klines_by_tf or {}).get('15m') or []
    if len(klines_15m) < 100:
        return [], [], []

    ml_engine = MLEngine(model_dir='data')
    analyzer = PatternAnalyzer(bot=None)
    samples, labels, metadata = [], [], []
    support_pnls = []
    next_allowed_index = 0

    for index in range(50, len(klines_15m) - 1):
        if index < next_allowed_index:
            continue

        history = klines_15m[:index]
        current_price = float(klines_15m[index]['close'])
        ts = klines_15m[index]['timestamp']
        signal = detect_trade_signal(analyzer, history, current_price)
        if not signal:
            continue

        support_stats = support_stats_from_history(support_pnls) if signal.get('type') == 'support_touch' else None
        history_5m = (klines_by_tf or {}).get('5m') or klines_15m[max(0, index - 20):index]
        history_1h = (klines_by_tf or {}).get('1h') or aggregate_ohlcv(history, 4)[-60:]
        history_4h = (klines_by_tf or {}).get('4h') or aggregate_ohlcv(history, 16)[-60:]
        history_1d = (klines_by_tf or {}).get('1d') or aggregate_ohlcv(history, 96)[-60:]

        planned_hold_minutes = 96 * 15.0
        planned_exit_dt = datetime.fromtimestamp(ts / 1000.0, timezone.utc) + timedelta(minutes=planned_hold_minutes)
        trade_context = {
            'fee_rate': fee_rate,
            'position_value_usd': position_value_usd,
            'account_balance': 1000.0,
            'planned_hold_minutes': planned_hold_minutes,
            'planned_exit_hour': float(planned_exit_dt.hour),
        }
        bot_context = build_training_bot_context(
            history,
            signal,
            ts,
            btc_history=btc_history,
            index=index,
            support_stats=support_stats,
        )
        features = ml_engine.extract_features_from_klines(
            history,
            current_price,
            klines_5m=history_5m,
            klines_1h=history_1h,
            klines_4h=history_4h,
            klines_1d=history_1d,
            trade_context=trade_context,
            bot_context=bot_context,
        )
        if not isinstance(features, dict):
            continue

        exit_index, exit_price, _ = simulate_trade(
            klines_15m,
            index,
            current_price,
            signal.get('support_price'),
            stop_percent,
            96,
            trailing_percent,
            breakeven_stop=True,
            breakeven_trigger=1.5,
            breakeven_lock=1.0,
            fee_rate=fee_rate,
        )
        pnl_percent = ((exit_price * (1 - fee_rate) - current_price * (1 + fee_rate)) / current_price) * 100.0

        samples.append(features)
        labels.append(1 if pnl_percent > 0 else 0)
        metadata.append({'symbol': symbol, 'timestamp': ts, 'pnl_pct': pnl_percent})
        if signal.get('type') == 'support_touch':
            support_pnls.append(float(pnl_percent))
        next_allowed_index = exit_index + 4

    return samples, labels, metadata


def train_challenger_model(output_dir='data', db_file=None, fast_mode=False):
    """Entraîne le modèle Challenger d'Entrée sur 1 an de données et le sauvegarde dans aegis_challenger.joblib."""
    try:
        challenger_path = os.path.join(output_dir, 'aegis_challenger.joblib')
        champion_path = os.path.join(output_dir, 'aegis_model.joblib')

        if fast_mode and os.path.exists(champion_path):
            shutil.copy2(champion_path, challenger_path)
            return True

        # Fetch historique via API REST Kraken directe (paires USD réelles), frais 0.4%
        exchange = None  # plus utilisé pour le fetch, on passe par requests
        ml_engine = MLEngine(model_dir=output_dir)
        ml_engine.model_path = challenger_path
        analyzer = PatternAnalyzer(bot=None)

        pairs = ['BTC/USD', 'ETH/USD', 'SOL/USD', 'ADA/USD']
        history_days = int(os.getenv('ML_TRAINING_HISTORY_DAYS', '1095'))
        start_date = (datetime.now(timezone.utc) - timedelta(days=history_days)).strftime("%Y-%m-%d")
        btc_history = fetch_symbol_history_2026(exchange, 'BTC/USD', timeframe='15m', start_date=start_date)
        btc_history_1h = fetch_symbol_history_2026(exchange, 'BTC/USD', timeframe='1h', start_date=start_date)

        X_samples, y_labels, sizing_targets, target_labels = [], [], [], []
        for symbol in pairs:
            print(f"  📊 Fetch {symbol} (15m, 5m, 1h, 4h, 1d)...")
            klines_15m = btc_history if symbol == 'BTC/USD' and btc_history else fetch_symbol_history_2026(exchange, symbol, timeframe='15m', start_date=start_date)
            if len(klines_15m) < 100:
                continue
            # Fetch real multi-TF klines via Kraken REST
            klines_5m_full = fetch_symbol_history_2026(exchange, symbol, timeframe='5m', start_date=start_date)
            klines_1h_full = btc_history_1h if symbol == 'BTC/USD' else fetch_symbol_history_2026(exchange, symbol, timeframe='1h', start_date=start_date)
            # Coinbase ne supporte pas '4h' -> on l'agrège depuis le 1h (4 bougies 1h = 1 bougie 4h)
            klines_4h_full = aggregate_ohlcv(klines_1h_full, 4)
            klines_1d_full = fetch_symbol_history_2026(exchange, symbol, timeframe='1d', start_date=start_date)
            print(f"    (4h agrégé depuis 1h: {len(klines_4h_full)} bougies)")
            print(f"    15m: {len(klines_15m)} | 5m: {len(klines_5m_full)} | 1h: {len(klines_1h_full)} | 4h: {len(klines_4h_full)} | 1d: {len(klines_1d_full)}")

            next_allowed_index = 0
            fee_rate = float(os.getenv('TRADING_FEE_PERCENT', '0.4')) / 100.0
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

                # Utiliser les vraies klines multi-TF (lookup par timestamp)
                candle_ts = klines_15m[index]['timestamp']
                history_5m = [k for k in klines_5m_full if k['timestamp'] <= candle_ts][-30:]
                history_1h = [k for k in klines_1h_full if k['timestamp'] <= candle_ts][-30:]
                history_4h = [k for k in klines_4h_full if k['timestamp'] <= candle_ts][-30:]
                history_1d = [k for k in klines_1d_full if k['timestamp'] <= candle_ts][-30:]
                planned_hold_minutes = 96 * 15.0
                planned_exit_dt = datetime.fromtimestamp(ts / 1000.0, timezone.utc) + timedelta(minutes=planned_hold_minutes)

                trade_context = {
                    'fee_rate': fee_rate,
                    'position_value_usd': 5.0,
                    'account_balance': 1000.0,
                    'planned_hold_minutes': planned_hold_minutes,
                    'planned_exit_hour': float(planned_exit_dt.hour)
                }
                bot_context = build_training_bot_context(history, signal, ts, btc_history=btc_history, index=index, support_stats=support_stats)

                features = ml_engine.extract_features_from_klines(
                    history, current_price,
                    klines_5m=history_5m, klines_1h=history_1h, klines_4h=history_4h, klines_1d=history_1d,
                    trade_context=trade_context, bot_context=bot_context
                )
                if features is None:
                    continue

                exit_index, exit_price, _ = simulate_trade(
                    klines_15m, index, current_price, signal.get('support_price'), 1.0, 96, 2.5,
                    breakeven_stop=True, breakeven_trigger=1.5, breakeven_lock=1.0, fee_rate=fee_rate
                )

                pnl_percent = ((exit_price * (1 - fee_rate) - current_price * (1 + fee_rate)) / current_price) * 100
                label = 1 if pnl_percent > 0 else 0

                # Label P_target: gain net maximum réellement atteignable pendant le hold
                # (max favorable excursion). C'est ce qu'un take-profit parfait aurait capturé.
                # On prend le plus haut atteint entre l'entrée et la sortie, net des frais A/R.
                highest_high = current_price
                for j in range(index + 1, min(exit_index + 1, len(klines_15m))):
                    hj = float(klines_15m[j]['high'])
                    if hj > highest_high:
                        highest_high = hj
                max_net_gain_pct = ((highest_high * (1 - fee_rate) - current_price * (1 + fee_rate)) / current_price) * 100
                # Un take-profit ne peut viser qu'un gain positif; borne inférieure à 0
                target_label = max(0.0, max_net_gain_pct)

                X_samples.append(features)
                y_labels.append(label)
                sizing_targets.append(sizing_factor_target_from_pnl(pnl_percent))
                target_labels.append(target_label)
                if signal.get('type') == 'support_touch':
                    support_pnls.append(float(pnl_percent))
                next_allowed_index = exit_index + 4

        if not X_samples and os.path.exists(champion_path):
            shutil.copy2(champion_path, challenger_path)
            return True

        X, y = np.array(X_samples), np.array(y_labels)
        y_sizing = np.array(sizing_targets, dtype=np.float64)
        y_target = np.array(target_labels, dtype=np.float64)
        
        # Stats du dataset d'entraînement
        n_wins = int(np.sum(y == 1))
        n_losses = int(np.sum(y == 0))
        print(f"\n  📊 Dataset Entrée: {len(X)} samples | Wins: {n_wins} ({n_wins/len(y)*100:.1f}%) | Losses: {n_losses} ({n_losses/len(y)*100:.1f}%)")
        print(f"  📊 Features: {X.shape[1]} | Fee rate: {fee_rate*100:.2f}%")
        
        success = ml_engine.train_model(X, y, n_estimators=100, max_depth=6, min_samples_split=5)
        if success:
            # Entraînement du modèle de Sortie avec les VRAIES features exit
            # Label amélioré: "rester est-il mieux que sortir maintenant ?"
            try:
                X_exit_samples, y_exit_labels = [], []
                for index in range(50, len(klines_15m) - 10):
                    if len(X_exit_samples) >= 8000:
                        break
                    history = klines_15m[:index]
                    entry_price = float(klines_15m[index]['close'])
                    ts = klines_15m[index]['timestamp']
                    
                    # Simuler le trade pour connaitre l'issue
                    exit_index, exit_price, _ = simulate_trade(
                        klines_15m, index, entry_price, None, 1.0, 96, 2.5,
                        breakeven_stop=True, breakeven_trigger=1.5, breakeven_lock=1.0, fee_rate=fee_rate
                    )
                    final_pnl = ((exit_price * (1 - fee_rate) - entry_price * (1 + fee_rate)) / entry_price) * 100
                    
                    # Generer des samples a differents moments pendant le hold
                    checkpoints = [index + 4, index + 8, index + 16, index + 32]
                    for cp in checkpoints:
                        if cp >= len(klines_15m) or cp >= exit_index:
                            break
                        cp_price = float(klines_15m[cp]['close'])
                        cp_history = klines_15m[:cp]
                        if len(cp_history) < 20:
                            continue
                        
                        duration_minutes = (cp - index) * 15.0
                        position_data = {
                            'entry_price': entry_price,
                            'buy_price': entry_price,
                            'fee_rate': fee_rate,
                            'duration_minutes': duration_minutes,
                            'stop_price': entry_price * 0.99,
                            'target_price': entry_price * 1.02,
                        }
                        
                        # Label amélioré: "rester rapporte-t-il plus que sortir maintenant ?"
                        pnl_now = ((cp_price * (1 - fee_rate) - entry_price * (1 + fee_rate)) / entry_price) * 100
                        pnl_if_stay = final_pnl
                        # Marge de tolérance: si la différence < 0.05%, considérer comme équivalent (HOLD)
                        exit_label = 1 if (pnl_if_stay - pnl_now) > -0.05 else 0
                        
                        bot_ctx = build_training_bot_context(cp_history, None, ts, btc_history=btc_history, index=cp)
                        exit_features = ml_engine.extract_exit_features(
                            cp_history, cp_price, position_data,
                            continuation_score=50.0,
                            entry_p_win=50.0,
                            btc_klines=btc_history[max(0, cp-30):cp] if btc_history else None,
                            bot_context=bot_ctx
                        )
                        if exit_features is not None:
                            X_exit_samples.append(exit_features)
                            y_exit_labels.append(exit_label)
                
                if len(X_exit_samples) >= 30:
                    X_exit = np.array(X_exit_samples)
                    y_exit = np.array(y_exit_labels)
                    ml_engine.train_exit_model(X_exit, y_exit, n_estimators=150, max_depth=6, min_samples_split=10)
                    n_continue = sum(y_exit_labels)
                    n_exit = len(y_exit_labels) - n_continue
                    print(f"  ✅ Modèle de Sortie entraîné avec {len(X_exit_samples)} samples (continue:{n_continue}, exit:{n_exit})")
                else:
                    print(f"  ⚠️ Pas assez de samples exit ({len(X_exit_samples)}), modèle sortie non entraîné")
            except Exception as ex:
                print(f"  ⚠️ Note entraînement modèle sortie: {ex}")
            try:
                ml_engine.train_sizing_model(X, y_sizing, n_estimators=120, max_depth=6, min_samples_split=10)
                print(f"  ✅ Modèle de Sizing entraîné et fusionné dans Challenger")
            except Exception as ex:
                print(f"  ⚠️ Note entraînement modèle sizing: {ex}")

            try:
                ml_engine.train_target_model(X, y_target, n_estimators=120, max_depth=8, min_samples_split=10)
                avg_target = float(np.mean(y_target)) if len(y_target) else 0.0
                med_target = float(np.median(y_target)) if len(y_target) else 0.0
                print(f"  ✅ Modèle P_target entraîné (gain cible moyen: {avg_target:.2f}%, médian: {med_target:.2f}%)")
            except Exception as ex:
                print(f"  ⚠️ Note entraînement modèle P_target: {ex}")

            print(f"  ✅ Challenger Entrée, Sortie, Sizing & P_target entraîné et sauvegardé dans {challenger_path}")
            return True
        elif os.path.exists(champion_path):
            shutil.copy2(champion_path, challenger_path)
            return True
        return False
    except Exception as e:
        print(f"  ⚠️ Entraînement Challenger autonome: {e}")
        if os.path.exists(os.path.join(output_dir, 'aegis_model.joblib')):
            shutil.copy2(os.path.join(output_dir, 'aegis_model.joblib'), os.path.join(output_dir, 'aegis_challenger.joblib'))
            return True
        return False


def run_pipeline(model_dir='data', db_file=None, check_only=False, trigger_type='auto', fast_mode=False):
    load_dotenv('.env.local', override=True)
    load_dotenv('.env.ui', override=True)

    db_file = db_file or os.getenv('ML_LIVE_SQLITE_FILE', 'data/aegis_db.sqlite3')
    logger = MLLiveLogger(data_dir=model_dir, sqlite_file=db_file)
    logger.record_governance_event('train_started', trigger_type=trigger_type, reason='Pipeline unifiée démarrée')

    print("=" * 70)
    print("🚀 PIPELINE UNIFIÉE ML : ENTRAÎNEMENT & GOUVERNANCE (PHASE 10)")
    print("=" * 70)

    # Step 1: Entraînement du Challenger
    print("\n📦 1. Entraînement du modèle Challenger...")
    challenger_path = os.path.join(model_dir, 'aegis_challenger.joblib')
    champion_path = os.path.join(model_dir, 'aegis_model.joblib')
    backup_path = os.path.join(model_dir, 'aegis_model_backup.joblib')

    train_challenger_model(output_dir=model_dir, db_file=db_file, fast_mode=fast_mode)

    if not os.path.exists(challenger_path) and os.path.exists(champion_path):
        shutil.copy2(champion_path, challenger_path)

    if not os.path.exists(challenger_path):
        msg = "Échec de création du modèle Challenger."
        print(f"❌ {msg}")
        logger.record_governance_event('promotion_rejected', trigger_type=trigger_type, reason=msg)
        logger.close()
        return False

    # Step 2: Évaluation Champion vs Challenger
    print("\n⚔️ 2. Évaluation des garde-fous de promotion...")
    
    guardrail_metrics = compute_guardrail_metrics(db_file)
    trade_rows = guardrail_metrics['trade_rows']
    closed_trades_count = guardrail_metrics['closed_trades_count']
    print(f"📊 Trades fermés réels dans le dataset : {closed_trades_count}")

    champ_engine = MLEngine(model_dir=model_dir)
    if os.path.exists(champion_path):
        champ_engine.model_path = champion_path
        champ_engine.load_model()

    chall_engine = MLEngine(model_dir=model_dir)
    chall_engine.model_path = challenger_path
    chall_engine.load_model()

    champ_meta = getattr(champ_engine, 'model_metadata', {}) or {}
    chall_meta = getattr(chall_engine, 'model_metadata', {}) or {}

    champ_prec = float(champ_meta.get('test_precision', 50.0))
    chall_prec = float(chall_meta.get('test_precision', 50.0))

    champ_acc = float(champ_meta.get('test_accuracy', 50.0))
    chall_acc = float(chall_meta.get('test_accuracy', 50.0))

    # Logs détaillés des modèles
    print("\n" + "=" * 70)
    print("📊 ÉVALUATION DÉTAILLÉE DES MODÈLES")
    print("=" * 70)
    print("\n  🏆 CHAMPION (modèle actuel en production):")
    print(f"    Precision (test):     {champ_prec:.1f}%")
    print(f"    Accuracy (test):      {champ_acc:.1f}%")
    print(f"    Features entrée:      {champ_meta.get('n_features', 'n/a')}")
    print(f"    Features sortie:      {champ_meta.get('exit_n_features', 'n/a')}")
    print(f"    Entraîné le:          {champ_meta.get('trained_at', 'n/a')}")
    print(f"    Samples entraînement: {champ_meta.get('train_samples', 'n/a')}")
    print(f"    Win rate dataset:     {champ_meta.get('train_win_rate', 'n/a')}")
    for key in ('test_recall', 'test_f1', 'train_accuracy', 'oob_score'):
        val = champ_meta.get(key)
        if val is not None:
            print(f"    {key:22s}: {val}")

    print(f"\n  ⚔️ CHALLENGER (nouveau modèle candidat):")
    print(f"    Precision (test):     {chall_prec:.1f}%")
    print(f"    Accuracy (test):      {chall_acc:.1f}%")
    print(f"    Features entrée:      {chall_meta.get('n_features', 'n/a')}")
    print(f"    Features sortie:      {chall_meta.get('exit_n_features', 'n/a')}")
    print(f"    Entraîné le:          {chall_meta.get('trained_at', 'n/a')}")
    print(f"    Samples entraînement: {chall_meta.get('train_samples', 'n/a')}")
    print(f"    Win rate dataset:     {chall_meta.get('train_win_rate', 'n/a')}")
    for key in ('test_recall', 'test_f1', 'train_accuracy', 'oob_score'):
        val = chall_meta.get(key)
        if val is not None:
            print(f"    {key:22s}: {val}")

    print(f"\n  📈 COMPARAISON:")
    prec_delta = chall_prec - champ_prec
    acc_delta = chall_acc - champ_acc
    print(f"    Precision delta:      {prec_delta:+.1f}% {'✅' if prec_delta >= -0.5 else '❌'}")
    print(f"    Accuracy delta:       {acc_delta:+.1f}% {'✅' if acc_delta >= -1.0 else '❌'}")
    print("=" * 70)

    min_trades = int(os.getenv('ML_PROMOTION_MIN_CLOSED_TRADES', '30'))
    min_days = int(os.getenv('ML_PROMOTION_MIN_ACTIVE_DAYS', '3'))
    max_drawdown_pct = float(os.getenv('ML_PROMOTION_MAX_DRAWDOWN_PCT', '8.0'))
    min_profit_factor = float(os.getenv('ML_PROMOTION_MIN_PROFIT_FACTOR', '1.10'))
    min_precision_delta = float(os.getenv('ML_PROMOTION_MIN_PRECISION_DELTA', '-0.5'))
    min_accuracy_delta = float(os.getenv('ML_PROMOTION_MIN_ACCURACY_DELTA', '-1.0'))
    max_calibration_mae = float(os.getenv('ML_PROMOTION_MAX_CALIBRATION_MAE', '20.0'))
    require_calibration = os.getenv('ML_PROMOTION_REQUIRE_CALIBRATION', 'false').lower() == 'true'
    allowed_drift_statuses = {
        item.strip().lower()
        for item in os.getenv('ML_PROMOTION_ALLOWED_DRIFT_STATUSES', 'ok,insufficient_live_outcomes').split(',')
        if item.strip()
    }

    profit_factor = float(guardrail_metrics['profit_factor'])
    active_days = int(guardrail_metrics['active_days'])
    net_pnl = float(guardrail_metrics['net_pnl'])
    max_dd = float(guardrail_metrics['max_drawdown_pct'])
    calibration_mae = guardrail_metrics.get('latest_calibration_mae')
    drift_status_value = str(guardrail_metrics.get('latest_drift_status') or 'unknown').lower()

    g1_min_trades = closed_trades_count >= min_trades
    g2_min_days = active_days >= min_days
    g3_better_perf = (chall_prec >= champ_prec + min_precision_delta) and (chall_acc >= champ_acc + min_accuracy_delta)
    g4_drawdown = max_dd <= max_drawdown_pct
    g5_profit_factor = profit_factor >= min_profit_factor
    g6_net_pnl = net_pnl > 0
    g7_calibration = (
        calibration_mae is not None and float(calibration_mae) <= max_calibration_mae
    ) if require_calibration else (
        calibration_mae is None or float(calibration_mae) <= max_calibration_mae
    )
    g8_drift = drift_status_value in allowed_drift_statuses

    print("\n🛡️ GARDE-FOUS DE PROMOTION :")
    print(f"  [1] Trades fermés ({closed_trades_count}) >= {min_trades} : {'✅' if g1_min_trades else '❌'}")
    print(f"  [2] Jours actifs ({active_days}) >= {min_days} : {'✅' if g2_min_days else '❌'}")
    print(f"  [3] Challenger Precision/Accuracy vs Champion : {'✅' if g3_better_perf else '❌'}")
    print(f"  [4] Max Drawdown ({max_dd:.2f}%) <= {max_drawdown_pct:.2f}% : {'✅' if g4_drawdown else '❌'}")
    print(f"  [5] Profit Factor ({profit_factor:.2f}) >= {min_profit_factor:.2f} : {'✅' if g5_profit_factor else '❌'}")
    print(f"  [6] PnL net ({net_pnl:.2f} USD) > 0 : {'✅' if g6_net_pnl else '❌'}")
    print(f"  [7] Calibration MAE ({calibration_mae if calibration_mae is not None else 'n/a'}) <= {max_calibration_mae:.1f} : {'✅' if g7_calibration else '❌'}")
    print(f"  [8] Drift status ({drift_status_value}) autorisé : {'✅' if g8_drift else '❌'}")

    all_passed = all([
        g1_min_trades,
        g2_min_days,
        g3_better_perf,
        g4_drawdown,
        g5_profit_factor,
        g6_net_pnl,
        g7_calibration,
        g8_drift,
    ])
    metrics_data = {
        'closed_trades_count': closed_trades_count,
        'active_days': active_days,
        'champion_precision': champ_prec,
        'challenger_precision': chall_prec,
        'champion_accuracy': champ_acc,
        'challenger_accuracy': chall_acc,
        'profit_factor': profit_factor,
        'net_pnl': net_pnl,
        'max_drawdown_pct': max_dd,
        'calibration_mae': calibration_mae,
        'drift_status': drift_status_value,
        'guardrails': {
            'min_trades': g1_min_trades,
            'min_days': g2_min_days,
            'better_perf': g3_better_perf,
            'drawdown': g4_drawdown,
            'profit_factor': g5_profit_factor,
            'net_pnl': g6_net_pnl,
            'calibration': g7_calibration,
            'drift': g8_drift,
        },
        'all_guardrails_passed': all_passed
    }
    logger.record_governance_event(
        'promotion_guardrails_evaluated',
        source_model='challenger',
        target_model='champion',
        metrics=metrics_data,
        trigger_type=trigger_type,
        reason='Evaluation complete des garde-fous de promotion'
    )

    if not all_passed:
        failed = [name for name, passed in metrics_data['guardrails'].items() if not passed]
        reason = f"Garde-fous non satisfaits: {', '.join(failed)}"
        print(f"\n⛔ PROMOTION REFUSÉE : {reason}")
        logger.record_governance_event('promotion_rejected', source_model='challenger', target_model='champion', metrics=metrics_data, trigger_type=trigger_type, reason=reason)
        logger.close()
        return False

    if check_only:
        print("\n🔍 Mode --check-only : Promotion validée mais non appliquée.")
        logger.record_governance_event('promotion_checked', source_model='challenger', target_model='champion', metrics=metrics_data, trigger_type=trigger_type, reason="Validation sans promotion")
        logger.close()
        return True

    # Step 3: Promotion
    print("\n🏆 PROMOTION DU CHALLENGER EN CHAMPION !")
    if os.path.exists(champion_path):
        backups_dir = os.path.join(model_dir, 'backups')
        os.makedirs(backups_dir, exist_ok=True)
        ts_backup_path = os.path.join(backups_dir, f"aegis_model_{datetime.now().strftime('%Y%m%d_%H%M%S')}.joblib")
        shutil.copy2(champion_path, ts_backup_path)
        print(f"  📦 Archive horodatée créée dans backups/ : {ts_backup_path}")
        _prune_model_backups(backups_dir, keep=10)
        # Pas de backup redondant dans data/: l'archive horodatée fait foi
        if os.path.exists(backup_path):
            try:
                os.remove(backup_path)
            except Exception:
                pass

    shutil.copy2(challenger_path, champion_path)
    print(f"  ✅ NOUVEAU CHAMPION PROMU AVEC SUCCÈS : {champion_path}")

    reason = f"Promotion validée (Precision {chall_prec:.1f}%, Acc {chall_acc:.1f}%)"
    logger.record_governance_event('promotion', source_model='challenger', target_model='champion', metrics=metrics_data, trigger_type=trigger_type, reason=reason)

    try:
        notifier = NotificationManager()
        notifier.notify(f"🏆 **NOUVEAU CHAMPION ML PROMU**\n\nPrecision: {chall_prec:.1f}%\nAccuracy: {chall_acc:.1f}%\nBackup créé: OK")
    except Exception:
        pass

    logger.close()
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Pipeline unifiée ML Aegis")
    parser.add_argument('--dir', default='data', help="Répertoire des modèles")
    parser.add_argument('--db', default=os.getenv('ML_LIVE_SQLITE_FILE', 'data/aegis_db.sqlite3'))
    parser.add_argument('--check-only', action='store_true', help="Vérifie les garde-fous sans promouvoir")
    parser.add_argument('--trigger', default='manual', help="auto ou manual")
    parser.add_argument('--fast', action='store_true', help="Mode rapide de test")
    args = parser.parse_args()

    run_pipeline(model_dir=args.dir, db_file=args.db, check_only=args.check_only, trigger_type=args.trigger, fast_mode=args.fast)
