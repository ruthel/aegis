#!/usr/bin/env python3
"""
Pipeline d'entraînement du Challenger Aegis.

Le training construit les modèles Challenger (entrée, edge, sortie, sizing, target).
La politique de promotion est volontairement centralisée dans scripts/promote_challenger.py
afin que le manuel et l'auto-retraining utilisent exactement les mêmes garde-fous.
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
from core.signal_engine import SignalEngine
from utils.pattern_analyzer import PatternAnalyzer
from utils.market_structure import detect_falling_knife, detect_reversal_confirmation
from scripts.trade_signals import simulate_trade


def _advance_cursor(klines_full, cursor, candle_ts):
    """Avance un curseur tant que la bougie suivante a un timestamp <= candle_ts.
    Retourne le nouveau curseur = index de la DERNIÈRE bougie avec ts <= candle_ts (+1).
    O(1) amorti car candle_ts ne fait qu'augmenter d'un appel à l'autre (curseur monotone).
    Remplace le filtrage O(n) [k for k in klines_full if k['timestamp'] <= candle_ts]."""
    n = len(klines_full)
    while cursor < n and int(klines_full[cursor]['timestamp']) <= candle_ts:
        cursor += 1
    return cursor


def _cursor_at_or_before(klines, candle_ts):
    """Return the exclusive cursor after the last candle with timestamp <= candle_ts."""
    rows = klines or []
    lo, hi = 0, len(rows)
    while lo < hi:
        mid = (lo + hi) // 2
        if int(rows[mid].get('timestamp', 0)) <= int(candle_ts):
            lo = mid + 1
        else:
            hi = mid
    return lo


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
        return [], [], [], [], []

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT entry_id, pnl_pct, would_win, timestamp
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
    samples, labels, weights, timestamps, pnls = [], [], [], [], []
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
        raw_ts = row['timestamp']
        try:
            if isinstance(raw_ts, (int, float)):
                ts_value = float(raw_ts)
                if ts_value > 1e12:
                    ts_value /= 1000.0
            else:
                ts_value = datetime.fromisoformat(str(raw_ts).replace('Z', '+00:00')).timestamp()
        except Exception:
            ts_value = time.time()
        timestamps.append(ts_value)
        pnls.append(pnl_pct)

    con.close()
    return samples, labels, weights, timestamps, pnls


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


def build_training_bot_context(history, signal, ts, btc_history=None, index=None, support_stats=None, h1_history=None, h4_history=None, d1_history=None):
    symbol_regime = simple_regime(history)
    btc_regime = None
    if btc_history is not None and index is not None:
        # Borné aux ~60 dernières bougies avant index (simple_regime n'utilise que les 50
        # dernières). Évite de copier btc_history[:index] qui grandit à chaque itération.
        btc_win_start = max(0, index - 60)
        btc_regime = simple_regime(btc_history[btc_win_start:index])
    dt = datetime.fromtimestamp(ts / 1000.0, timezone.utc)
    confidence = float((signal or {}).get('confidence') or 0.0)
    crypto_score = confidence
    dynamic_min_score = float(os.getenv('MIN_CRYPTO_SCORE', '40'))
    is_optimal = (8 <= dt.hour <= 16) or (0 <= dt.hour <= 4)
    support_stats = support_stats or {}
    technical_action = 'BUY' if signal else 'HOLD'
    technical_min_confidence = dynamic_min_score
    falling = detect_falling_knife(d1_history or [], h4_history or [])
    reversal = detect_reversal_confirmation(h1_history or [])
    return {
        'symbol_regime': symbol_regime,
        'btc_regime': btc_regime,
        'bear_mode': symbol_regime in ('BEAR', 'SIDEWAYS_DOWN') or btc_regime in ('BEAR', 'SIDEWAYS_DOWN'),
        'reversal_confirmed': bool(reversal.get('confirmed')),
        'falling_knife_active': bool(falling.get('is_falling')),
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


def _timeframe_ms(timeframe):
    """Convertit un timeframe ('5m','15m','1h','1d') en millisecondes."""
    units = {'m': 60_000, 'h': 3_600_000, 'd': 86_400_000}
    try:
        return int(timeframe[:-1]) * units[timeframe[-1]]
    except (KeyError, ValueError):
        return 15 * 60_000  # défaut 15m


def _cache_path(symbol, timeframe, prefer_parquet=True):
    """Chemin du fichier cache (Parquet prioritaire, 10x plus rapide)."""
    cache_dir = os.getenv('ML_OHLCV_CACHE_DIR', os.path.join('data', 'ohlcv_cache'))
    os.makedirs(cache_dir, exist_ok=True)
    safe_symbol = symbol.replace('/', '-')
    
    parquet_path = os.path.join(cache_dir, f"{safe_symbol}_{timeframe}.parquet")
    json_path = os.path.join(cache_dir, f"{safe_symbol}_{timeframe}.json.gz")
    
    if prefer_parquet and os.path.exists(parquet_path):
        return parquet_path
    return json_path


def _load_cache(symbol, timeframe):
    """Charge les bougies (Parquet ou JSON.gz)."""
    import gzip
    path = _cache_path(symbol, timeframe)
    if not os.path.exists(path):
        return []
    try:
        if path.endswith('.parquet'):
            import pandas as pd
            df = pd.read_parquet(path)
            return df.to_dict('records')
        
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"      ⚠️ Cache illisible {symbol} {timeframe} ({e}) → refetch complet")
        return []


def _save_cache(symbol, timeframe, klines):
    """Sauvegarde en Parquet (rapide) avec fallback JSON.gz."""
    import gzip
    cache_dir = os.getenv('ML_OHLCV_CACHE_DIR', os.path.join('data', 'ohlcv_cache'))
    safe_symbol = symbol.replace('/', '-')
    
    # Essayer Parquet d'abord
    try:
        import pandas as pd
        path = os.path.join(cache_dir, f"{safe_symbol}_{timeframe}.parquet")
        df = pd.DataFrame(klines)
        df.to_parquet(path, compression='snappy', index=False)
        # Supprimer ancien JSON si existe
        json_path = os.path.join(cache_dir, f"{safe_symbol}_{timeframe}.json.gz")
        if os.path.exists(json_path):
            os.remove(json_path)
        return
    except Exception:
        pass
    
    # Fallback JSON.gz
    path = os.path.join(cache_dir, f"{safe_symbol}_{timeframe}.json.gz")
    tmp = path + '.tmp'
    try:
        with gzip.open(tmp, 'wt', encoding='utf-8') as f:
            json.dump(klines, f, separators=(',', ':'))
        os.replace(tmp, path)
    except Exception as e:
        print(f"      ⚠️ Échec sauvegarde cache {symbol} {timeframe}: {e}")


def _fetch_one_window(cb, symbol, timeframe, win_since, limit=300, max_retries=5):
    """Fetch UNE fenêtre de bougies à partir de win_since. Retry avec backoff.
    Retourne (liste de dicts, ok). Utilisé par le fetch parallèle par batches."""
    attempt = 0
    while attempt <= max_retries:
        try:
            klines = cb.fetch_ohlcv(symbol, timeframe=timeframe, since=win_since, limit=limit)
            out = []
            for k in klines or []:
                out.append({
                    'timestamp': int(k[0]),
                    'open': float(k[1]),
                    'high': float(k[2]),
                    'low': float(k[3]),
                    'close': float(k[4]),
                    'volume': float(k[5]),
                })
            return out, True
        except Exception as e:
            msg = str(e).lower()
            attempt += 1
            wait = 5 if ('rate' in msg or 'too many' in msg or '429' in msg) else min(20, 2 ** attempt)
            if attempt > max_retries:
                return [], False
            time.sleep(wait)
    return [], False


def _fetch_ohlcv_range(cb, symbol, timeframe, since, end_ts, max_candles, label=""):
    """Fetch réseau des bougies OHLCV entre 'since' et 'end_ts' par BATCHES PARALLÈLES.

    On calcule toutes les fenêtres 'since' à l'avance (le pas temporel est connu),
    puis on lance ML_FETCH_CONCURRENCY appels en parallèle par batch, en respectant
    la limite Coinbase (3 req/s soutenu, 6 en burst). Gain ~2-3x sur un fetch complet.
    Robuste: retry par fenêtre, dédup, progression en direct."""
    from concurrent.futures import ThreadPoolExecutor

    show_progress = os.getenv('ML_FETCH_PROGRESS', 'true').lower() == 'true'
    concurrency = max(1, min(6, int(os.getenv('ML_FETCH_CONCURRENCY', '5'))))
    limit = 300
    tf_ms = _timeframe_ms(timeframe)
    step_ms = limit * tf_ms  # durée couverte par un appel (300 bougies)

    windows = []
    s = since
    while s < end_ts:
        windows.append(s)
        s += step_ms
    total_windows = len(windows)
    if total_windows == 0:
        return []

    merged = {}
    done = 0

    def _render_progress():
        pct = min(1.0, done / max(1, total_windows)) * 100.0
        bar_len = 24
        filled = int(bar_len * pct / 100.0)
        bar = '█' * filled + '░' * (bar_len - filled)
        sys.stdout.write(f"\r      {label} [{bar}] {pct:5.1f}% — {len(merged)} bougies")
        sys.stdout.flush()

    for i in range(0, total_windows, concurrency):
        batch = windows[i:i + concurrency]
        batch_start = time.time()
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            results = list(executor.map(
                lambda w: _fetch_one_window(cb, symbol, timeframe, w, limit),
                batch
            ))
        for candles, ok in results:
            for k in candles:
                ts = int(k['timestamp'])
                if since <= ts < end_ts:
                    merged[ts] = k
        done += len(batch)
        if show_progress:
            _render_progress()
        if len(merged) >= max_candles:
            break
        # Pacing: un batch de N requêtes ne s'exécute pas en moins de N/6 s (<= 6 req/s)
        min_batch_duration = len(batch) / 6.0
        elapsed = time.time() - batch_start
        if elapsed < min_batch_duration:
            time.sleep(min_batch_duration - elapsed)

    if show_progress:
        _render_progress()
        sys.stdout.write("\n")
        sys.stdout.flush()

    fetched = sorted(merged.values(), key=lambda k: k['timestamp'])
    if len(fetched) > max_candles:
        fetched = fetched[-max_candles:]
    return fetched


_KRAKEN_ARCHIVE_READY_CACHE = {}


def _kraken_archive_symbol_ready(symbol, start_ms):
    """Use Kraken-native data only when ALL model timeframes cover the requested window.

    This prevents mixing a short Kraken history on one timeframe with a long Coinbase
    history on another timeframe, and prevents silently shrinking a 3-year training
    request to only ~90 days because Kraken's local archive is still young.
    """
    if os.getenv('ML_KRAKEN_ARCHIVE_REQUIRE_ALL_TIMEFRAMES', 'true').lower() != 'true':
        return True

    root = os.getenv('ML_KRAKEN_ARCHIVE_DIR', os.path.join('data', 'kraken_ohlcv'))
    required = tuple(
        item.strip()
        for item in os.getenv('ML_KRAKEN_ARCHIVE_REQUIRED_TIMEFRAMES', '5m,15m,1h,4h,1d').split(',')
        if item.strip()
    )
    min_ratio = max(0.0, min(1.0, float(os.getenv('ML_KRAKEN_ARCHIVE_MIN_COVERAGE_RATIO', '0.95'))))
    key = (root, symbol, int(start_ms), required, min_ratio)
    if key in _KRAKEN_ARCHIVE_READY_CACHE:
        return _KRAKEN_ARCHIVE_READY_CACHE[key]

    import gzip
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    requested_span = max(1, now_ms - int(start_ms))
    ok = True
    for tf in required:
        path = os.path.join(root, f"{symbol.replace('/', '-')}_{tf}.json.gz")
        if not os.path.exists(path):
            ok = False
            break
        try:
            with gzip.open(path, 'rt', encoding='utf-8') as fh:
                rows = json.load(fh)
            if not rows:
                ok = False
                break
            rows.sort(key=lambda x: int(x.get('timestamp', 0) or 0))
            first_ts = int(rows[0].get('timestamp', 0) or 0)
            last_ts = int(rows[-1].get('timestamp', 0) or 0)
            coverage_ratio = max(0.0, min(1.0, (last_ts - first_ts) / requested_span))
            freshness_ms = int(os.getenv('ML_KRAKEN_ARCHIVE_MAX_STALENESS_CANDLES', '3')) * _timeframe_ms(tf)
            if coverage_ratio < min_ratio or now_ms - last_ts > freshness_ms:
                ok = False
                break
        except Exception:
            ok = False
            break

    _KRAKEN_ARCHIVE_READY_CACHE[key] = ok
    return ok


def _load_kraken_archive_for_training(symbol, timeframe, start_ms):
    """Use the local Kraken-native archive only when it has enough fresh coverage."""
    if os.getenv('ML_PREFER_KRAKEN_ARCHIVE', 'false').lower() != 'true':
        return []
    if not _kraken_archive_symbol_ready(symbol, start_ms):
        return []
    root = os.getenv('ML_KRAKEN_ARCHIVE_DIR', os.path.join('data', 'kraken_ohlcv'))
    path = os.path.join(root, f"{symbol.replace('/', '-')}_{timeframe}.json.gz")
    if not os.path.exists(path):
        return []
    try:
        import gzip
        with gzip.open(path, 'rt', encoding='utf-8') as fh:
            rows = json.load(fh)
        rows = [
            row for row in (rows or [])
            if int(row.get('timestamp', 0) or 0) >= int(start_ms)
        ]
        if not rows:
            return []
        rows.sort(key=lambda x: int(x.get('timestamp', 0) or 0))
        coverage_days = (
            int(rows[-1]['timestamp']) - int(rows[0]['timestamp'])
        ) / 86_400_000.0
        tf_ms = _timeframe_ms(timeframe)
        freshness_ms = int(os.getenv('ML_KRAKEN_ARCHIVE_MAX_STALENESS_CANDLES', '3')) * tf_ms
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        if now_ms - int(rows[-1]['timestamp']) > freshness_ms:
            return []
        print(
            f"      → {symbol} {timeframe}: {len(rows)} bougies Kraken archive "
            f"({coverage_days:.1f} jours, univers Kraken complet prêt)"
        )
        return rows
    except Exception:
        return []


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

    kraken_archive = _load_kraken_archive_for_training(symbol, timeframe, window_start_ms)
    if kraken_archive:
        return kraken_archive[-max_candles:]

    # Long-history fallback. Coinbase is used only when a sufficiently deep Kraken
    # archive is not yet available; the local Kraken archive is built incrementally.
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
    signal_engine = SignalEngine(analyzer)
    samples, labels, metadata = [], [], []
    support_pnls = []
    next_allowed_index = 0

    for index in range(50, len(klines_15m) - 1):
        if index < next_allowed_index:
            continue

        hist_window = int(os.getenv('ML_GEN_HISTORY_WINDOW', '200'))
        history = klines_15m[max(0, index - hist_window):index]
        current_price = float(klines_15m[index]['close'])
        ts = klines_15m[index]['timestamp']
        signal = signal_engine.detect_best(history[-200:], current_price)
        if not signal:
            continue

        support_stats = support_stats_from_history(support_pnls) if signal.get('type') == 'support_touch' else None

        # Important: ne jamais laisser une feature multi-timeframe voir une bougie future.
        def _history_until(key, fallback):
            data = (klines_by_tf or {}).get(key) or []
            if not data:
                return fallback
            cursor = _cursor_at_or_before(data, ts)
            return data[max(0, cursor - 60):cursor]

        history_5m = _history_until('5m', klines_15m[max(0, index - 20):index])
        history_1h = _history_until('1h', aggregate_ohlcv(history, 4)[-60:])
        history_4h = _history_until('4h', aggregate_ohlcv(history, 16)[-60:])
        history_1d = _history_until('1d', aggregate_ohlcv(history, 96)[-60:])

        planned_hold_minutes = 96 * 15.0
        planned_exit_dt = datetime.fromtimestamp(ts / 1000.0, timezone.utc) + timedelta(minutes=planned_hold_minutes)
        trade_context = {
            'fee_rate': fee_rate,
            'position_value_usd': position_value_usd,
            'account_balance': 1000.0,
            'planned_hold_minutes': planned_hold_minutes,
            'planned_exit_hour': float(planned_exit_dt.hour),
        }
        btc_context_index = _cursor_at_or_before(btc_history, ts) if btc_history else None
        bot_context = build_training_bot_context(
            history,
            signal,
            ts,
            btc_history=btc_history,
            index=btc_context_index,
            support_stats=support_stats,
            h1_history=history_1h,
            h4_history=history_4h,
            d1_history=history_1d,
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
        if features is None:
            continue
        feature_dict = {
            name: float(value)
            for name, value in zip(ml_engine.feature_names, np.asarray(features).reshape(-1))
        }

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

        samples.append(feature_dict)
        labels.append(1 if pnl_percent > 0 else 0)
        metadata.append({'symbol': symbol, 'timestamp': ts, 'pnl_pct': pnl_percent})
        if signal.get('type') == 'support_touch':
            support_pnls.append(float(pnl_percent))
        next_allowed_index = exit_index + 4

    return samples, labels, metadata


def train_challenger_model(output_dir='data', db_file=None, fast_mode=False, use_grid_search=None, use_lightgbm=None):
    """Entraîne le modèle Challenger d'Entrée sur l'historique configuré et le sauvegarde dans aegis_challenger.joblib.
    
    Args:
        use_grid_search: Force Grid Search (None = utilise env ML_USE_GRID_SEARCH)
        use_lightgbm: Force LightGBM (None = utilise env ML_USE_LIGHTGBM, défaut True)
    """
    try:
        challenger_path = os.path.join(output_dir, 'aegis_challenger.joblib')
        champion_path = os.path.join(output_dir, 'aegis_model.joblib')

        if fast_mode and os.path.exists(champion_path):
            shutil.copy2(champion_path, challenger_path)
            return True

        # Options ML
        if use_grid_search is None:
            use_grid_search = os.getenv('ML_USE_GRID_SEARCH', 'false').lower() == 'true'
        if use_lightgbm is None:
            use_lightgbm = os.getenv('ML_USE_LIGHTGBM', 'true').lower() == 'true'

        # Fetch historique via API REST Kraken directe (paires USD réelles), frais 0.4%
        exchange = None  # plus utilisé pour le fetch, on passe par requests
        ml_engine = MLEngine(model_dir=output_dir)
        ml_engine.model_path = challenger_path
        analyzer = PatternAnalyzer(bot=None)
        signal_engine = SignalEngine(analyzer)

        pairs = ['BTC/USD', 'ETH/USD', 'SOL/USD', 'ADA/USD']
        if os.getenv('ML_ARCHIVE_KRAKEN_BEFORE_TRAIN', 'true').lower() == 'true':
            try:
                from scripts.archive_kraken_ohlcv import archive_universe
                archive_summary = archive_universe(
                    pairs=pairs,
                    timeframes=['5m', '15m', '1h', '4h', '1d'],
                )
                print(
                    f"  🗄️ Archive Kraken: {archive_summary['updated']} flux mis à jour, "
                    f"{archive_summary['failed']} échecs"
                )
            except Exception as exc:
                print(f"  ⚠️ Archive Kraken indisponible, training continue: {exc}")
        history_days = int(os.getenv('ML_TRAINING_HISTORY_DAYS', '1095'))
        start_date = (datetime.now(timezone.utc) - timedelta(days=history_days)).strftime("%Y-%m-%d")
        # Durée de détention DYNAMIQUE (basée sur les conditions de marché) au lieu d'un
        # max_hold fixe: la sortie est pilotée par la cassure de tendance (EMA20-15m ET
        # EMA50-1h), max_hold ne sert plus que de filet de sécurité (défaut 960 = 10 jours).
        exit_max_hold = int(os.getenv('ML_EXIT_MAX_HOLD_CANDLES', '960'))
        exit_trend_enabled = os.getenv('ML_EXIT_TREND_EXIT', 'true').lower() == 'true'
        exit_trend_confirm = int(os.getenv('ML_EXIT_TREND_CONFIRM_BARS', '2'))
        btc_history = fetch_symbol_history_2026(exchange, 'BTC/USD', timeframe='15m', start_date=start_date)
        btc_history_1h = fetch_symbol_history_2026(exchange, 'BTC/USD', timeframe='1h', start_date=start_date)

        X_samples, y_labels, sizing_targets, target_labels, pnl_targets, sample_timestamps = [], [], [], [], [], []
        training_histories = {}
        # Compteur de samples générés par TYPE de signal (diagnostic: voir combien
        # chaque déclencheur produit — support_touch, pattern_breakout, ema_pullback_15m,
        # ema_cross_15m). Permet de savoir si les signaux 15m génèrent réellement des samples.
        signal_type_counts = {}
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
            training_histories[symbol] = {
                '15m': klines_15m,
                '5m': klines_5m_full,
                '1h': klines_1h_full,
                '4h': klines_4h_full,
                '1d': klines_1d_full,
            }

            next_allowed_index = 0
            fee_rate = float(os.getenv('TRADING_FEE_PERCENT', '0.4')) / 100.0
            support_pnls = []

            # Curseurs multi-TF (lookup O(1) amorti au lieu de re-scanner toute la liste
            # à chaque itération). candle_ts est monotone croissant -> les curseurs avancent.
            cur_5m = cur_1h = cur_4h = cur_1d = 0
            cur_btc_15m = 0

            # Progression de la génération des samples (barre qui se met à jour sur la même ligne)
            show_gen_progress = os.getenv('ML_FETCH_PROGRESS', 'true').lower() == 'true'
            gen_total = max(1, len(klines_15m) - 1 - 50)
            gen_start = len(X_samples)

            def _render_gen_progress(idx):
                pct = min(1.0, max(0.0, (idx - 50) / gen_total)) * 100.0
                bar_len = 24
                filled = int(bar_len * pct / 100.0)
                bar = '█' * filled + '░' * (bar_len - filled)
                sys.stdout.write(f"\r      🧪 {symbol} génération [{bar}] {pct:5.1f}% — {len(X_samples) - gen_start} samples")
                sys.stdout.flush()

            for index in range(50, len(klines_15m) - 1):
                if show_gen_progress and index % 500 == 0:
                    _render_gen_progress(index)
                if index < next_allowed_index:
                    continue

                # Fenêtre bornée: toutes les fonctions consommatrices (detect_trade_signal,
                # find_support_resistance_levels lookback=100, simple_regime 50) n'utilisent
                # que les ~100 dernières bougies. Copier klines_15m[:index] (jusqu'à 105k
                # éléments) à chaque itération causait un ralentissement quadratique.
                hist_window = int(os.getenv('ML_GEN_HISTORY_WINDOW', '200'))
                win_start = max(0, index - hist_window)
                history = klines_15m[win_start:index]
                current_price = klines_15m[index]['close']
                ts = klines_15m[index]['timestamp']

                # Même univers que le live: une seule opportunité canonique par timestamp.
                best_signal = signal_engine.detect_best(history, current_price)
                if not best_signal:
                    continue
                signals_here = [best_signal]

                # Klines multi-TF (communes à tous les signaux de cet index)
                candle_ts = klines_15m[index]['timestamp']
                cur_btc_15m = _advance_cursor(btc_history, cur_btc_15m, candle_ts) if btc_history else 0
                btc_context_index = cur_btc_15m if btc_history else None
                cur_5m = _advance_cursor(klines_5m_full, cur_5m, candle_ts)
                cur_1h = _advance_cursor(klines_1h_full, cur_1h, candle_ts)
                cur_4h = _advance_cursor(klines_4h_full, cur_4h, candle_ts)
                cur_1d = _advance_cursor(klines_1d_full, cur_1d, candle_ts)
                history_5m = klines_5m_full[max(0, cur_5m - 30):cur_5m]
                history_1h = klines_1h_full[max(0, cur_1h - 30):cur_1h]
                history_4h = klines_4h_full[max(0, cur_4h - 30):cur_4h]
                history_1d = klines_1d_full[max(0, cur_1d - 30):cur_1d]
                planned_hold_minutes = 96 * 15.0
                planned_exit_dt = datetime.fromtimestamp(ts / 1000.0, timezone.utc) + timedelta(minutes=planned_hold_minutes)
                trade_context = {
                    'fee_rate': fee_rate,
                    'position_value_usd': 5.0,
                    'account_balance': 1000.0,
                    'planned_hold_minutes': planned_hold_minutes,
                    'planned_exit_hour': float(planned_exit_dt.hour)
                }

                max_exit_index = index + 1
                for signal in signals_here:
                    _sig_type = signal.get('type', 'unknown')
                    support_stats = support_stats_from_history(support_pnls) if signal.get('type') == 'support_touch' else None
                    bot_context = build_training_bot_context(
                        history,
                        signal,
                        ts,
                        btc_history=btc_history,
                        index=btc_context_index,
                        support_stats=support_stats,
                        h1_history=history_1h,
                        h4_history=history_4h,
                        d1_history=history_1d,
                    )

                    features = ml_engine.extract_features_from_klines(
                        history, current_price,
                        klines_5m=history_5m, klines_1h=history_1h, klines_4h=history_4h, klines_1d=history_1d,
                        trade_context=trade_context, bot_context=bot_context
                    )
                    if features is None:
                        continue

                    # La simulation dépend du stop propre au signal (support_price différent).
                    # Durée dynamique: sortie sur cassure de tendance, max_hold = filet de sécurité.
                    exit_index, exit_price, _ = simulate_trade(
                        klines_15m, index, current_price, signal.get('support_price'), 1.0, exit_max_hold, 2.5,
                        breakeven_stop=True, breakeven_trigger=1.5, breakeven_lock=1.0, fee_rate=fee_rate,
                        trend_exit=exit_trend_enabled, trend_confirm_bars=exit_trend_confirm
                    )
                    max_exit_index = max(max_exit_index, exit_index)

                    pnl_percent = ((exit_price * (1 - fee_rate) - current_price * (1 + fee_rate)) / current_price) * 100
                    label = 1 if pnl_percent > 0 else 0

                    # P_target apprend une cible robuste, pas le meilleur tick futur impossible à timer.
                    # On prend un quantile configurable des gains nets atteints sur le chemin du trade.
                    path_quantile = max(0.50, min(0.95, float(os.getenv('ML_TARGET_PATH_QUANTILE', '0.70'))))
                    path_net_gains = []
                    for j in range(index + 1, min(exit_index + 1, len(klines_15m))):
                        reachable = float(klines_15m[j]['high'])
                        net_gain = ((reachable * (1 - fee_rate) - current_price * (1 + fee_rate)) / current_price) * 100
                        path_net_gains.append(max(0.0, net_gain))
                    target_label = float(np.quantile(path_net_gains, path_quantile)) if path_net_gains else 0.0

                    X_samples.append(features)
                    y_labels.append(label)
                    sizing_targets.append(sizing_factor_target_from_pnl(pnl_percent))
                    target_labels.append(target_label)
                    pnl_targets.append(float(pnl_percent))
                    sample_timestamps.append(float(ts) / 1000.0 if float(ts) > 1e12 else float(ts))
                    signal_type_counts[_sig_type] = signal_type_counts.get(_sig_type, 0) + 1
                    if _sig_type == 'support_touch':
                        support_pnls.append(float(pnl_percent))

                # Anti-chevauchement basé sur la sortie la plus tardive des signaux de cet index
                next_allowed_index = max_exit_index + 4

            # Terminer la barre de génération proprement (100% + saut de ligne)
            if show_gen_progress:
                _render_gen_progress(len(klines_15m) - 1)
                sys.stdout.write("\n")
                sys.stdout.flush()

        # Récap des samples générés PAR TYPE DE SIGNAL (diagnostic clé pour savoir si
        # les signaux 15m produisent réellement des samples ou sont écrasés par support/breakout).
        if signal_type_counts:
            total_gen = sum(signal_type_counts.values())
            print(f"\n  🧭 Samples générés par type de signal (total {total_gen}):")
            for stype, cnt in sorted(signal_type_counts.items(), key=lambda x: x[1], reverse=True):
                pct = cnt / total_gen * 100.0 if total_gen else 0.0
                print(f"       - {stype:20s}: {cnt:6d}  ({pct:4.1f}%)")

        if not X_samples and os.path.exists(champion_path):
            shutil.copy2(champion_path, challenger_path)
            return True

        # Poids par défaut = 1.0 pour tous les samples historiques (OHLCV).
        sample_weights = [1.0] * len(X_samples)

        # === FERMETURE DE LA BOUCLE D'APPRENTISSAGE (Phase 4/5) ===
        # Réinjecter les refus ML rejoués (ml_rejected_replay_results, statut 'replayed')
        # dans le dataset d'entrée. Chaque refus rejoué apporte un vrai exemple live:
        # features réelles vues au moment du refus + label = would_win (le refus aurait-il
        # été gagnant ?). Cela permet au modèle d'apprendre de ses refus au fil du temps.
        replay_db = db_file or os.getenv('ML_LIVE_SQLITE_FILE', 'data/aegis_db.sqlite3')
        replay_max = int(os.getenv('ML_REPLAY_TRAIN_MAX_SAMPLES', '2000'))
        replay_min_pnl = float(os.getenv('ML_REPLAY_TRAIN_MIN_PNL_PCT', '0.0'))
        # Poids modéré: on ne veut pas que les refus rejoués (label grossier, sortie forcée
        # après N bougies) dominent le signal des vraies simulations. Plafonné par env.
        replay_weight_win = float(os.getenv('ML_REPLAY_TRAIN_WEIGHT_WIN', '1.2'))
        replay_weight_loss = float(os.getenv('ML_REPLAY_TRAIN_WEIGHT_LOSS', '1.0'))
        try:
            r_samples, r_labels, r_weights, r_timestamps, r_pnls = load_phase5_replay_samples(
                replay_db, ml_engine.feature_names, max_samples=replay_max, min_pnl_pct=replay_min_pnl
            )
        except Exception as e:
            print(f"  ⚠️ Replay samples ignorés (erreur lecture): {e}")
            r_samples, r_labels, r_weights, r_timestamps, r_pnls = [], [], [], [], []

        n_replay = 0
        if r_samples:
            for feat, lab, w, replay_ts, replay_pnl in zip(r_samples, r_labels, r_weights, r_timestamps, r_pnls):
                if len(feat) != len(ml_engine.feature_names):
                    continue  # sécurité: n'ajouter que des vecteurs alignés au schéma
                X_samples.append(np.array(feat, dtype=np.float64))
                y_labels.append(int(lab))
                # w vaut 1.5 (gagnant) ou 1.0 sinon dans load_phase5; on remappe sur des
                # poids modérés configurables pour ne pas biaiser l'entraînement.
                sample_weights.append(replay_weight_win if w and w > 1.0 else replay_weight_loss)
                sizing_targets.append(0.40)   # sizing neutre-prudent pour un refus rejoué
                target_labels.append(0.0)     # pas de cible de gain fiable pour un refus
                pnl_targets.append(float(replay_pnl))
                sample_timestamps.append(float(replay_ts))
                n_replay += 1
            print(f"  🔁 Refus rejoués réinjectés dans l'entraînement: {n_replay} samples")
        else:
            print("  🔁 Aucun refus rejoué disponible (table vide ou boucle pas encore alimentée).")

        X, y = np.array(X_samples), np.array(y_labels)
        y_sizing = np.array(sizing_targets, dtype=np.float64)
        y_target = np.array(target_labels, dtype=np.float64)
        y_pnl = np.array(pnl_targets, dtype=np.float64)
        w_train = np.array(sample_weights, dtype=np.float64)
        ts_train = np.array(sample_timestamps, dtype=np.float64)

        # Trier globalement tous les symboles + replays par temps AVANT le split temporel.
        # Sans cela, un holdout "dernier 20%" serait encore mélangé par symbole.
        temporal_order = np.argsort(ts_train, kind='stable')
        X = X[temporal_order]
        y = y[temporal_order]
        y_sizing = y_sizing[temporal_order]
        y_target = y_target[temporal_order]
        y_pnl = y_pnl[temporal_order]
        w_train = w_train[temporal_order]
        ts_train = ts_train[temporal_order]
        
        # Stats du dataset d'entraînement
        n_wins = int(np.sum(y == 1))
        n_losses = int(np.sum(y == 0))
        print(f"\n  📊 Dataset Entrée: {len(X)} samples ({n_replay} refus rejoués) | Wins: {n_wins} ({n_wins/len(y)*100:.1f}%) | Losses: {n_losses} ({n_losses/len(y)*100:.1f}%)")
        print(f"  📊 Features: {X.shape[1]} | Fee rate: {fee_rate*100:.2f}%")
        print(f"  📊 Model: {'LightGBM' if use_lightgbm else 'RandomForest'} | Grid Search: {'ON' if use_grid_search else 'OFF'}")
        
        # Entraînement avec Grid Search ou standard
        if use_grid_search:
            success = ml_engine.train_model_with_grid_search(X, y, sample_weight=w_train, use_lightgbm=use_lightgbm)
        else:
            success = ml_engine.train_model(X, y, n_estimators=100, max_depth=6, min_samples_split=5, sample_weight=w_train, use_lightgbm=use_lightgbm)
        if success:
            try:
                if ml_engine.train_edge_model(X, y_pnl, sample_weight=w_train, use_lightgbm=use_lightgbm):
                    print("  ✅ Modèle Expected Net PnL entraîné avec holdout temporel")
            except Exception as ex:
                print(f"  ⚠️ Note entraînement expected PnL: {ex}")

            # Entraînement P_exit multi-symboles. Le label répond à la question économique :
            # "HOLD maintenant vaut-il mieux que EXIT NOW ?" après frais et coût temporel.
            try:
                X_exit_samples, y_exit_labels, exit_timestamps = [], [], []
                exit_min_edge = float(os.getenv('ML_EXIT_MIN_HOLD_EDGE_PCT', '0.05'))
                time_cost_per_day = float(os.getenv('ML_EXIT_HOLD_TIME_COST_PCT_PER_DAY', '0.02'))
                max_exit_samples = int(os.getenv('ML_EXIT_MAX_TRAIN_SAMPLES', '16000'))

                for exit_symbol, tf_bundle in training_histories.items():
                    symbol_15m = list(tf_bundle.get('15m') or [])
                    if len(symbol_15m) < 100:
                        continue

                    def _slice_until(rows, ts_value, count=30):
                        rows = rows or []
                        lo, hi = 0, len(rows)
                        while lo < hi:
                            mid = (lo + hi) // 2
                            if int(rows[mid].get('timestamp', 0)) <= int(ts_value):
                                lo = mid + 1
                            else:
                                hi = mid
                        return rows[max(0, lo - count):lo]

                    for index in range(50, len(symbol_15m) - 10):
                        if len(X_exit_samples) >= max_exit_samples:
                            break

                        entry_price = float(symbol_15m[index]['close'])
                        entry_ts = int(symbol_15m[index]['timestamp'])
                        history = symbol_15m[:index]
                        candidate = signal_engine.detect_best(history[-200:], entry_price)
                        if not candidate:
                            continue

                        entry_5m = _slice_until(tf_bundle.get('5m'), entry_ts, 30)
                        entry_1h = _slice_until(tf_bundle.get('1h'), entry_ts, 30)
                        entry_4h = _slice_until(tf_bundle.get('4h'), entry_ts, 30)
                        entry_1d = _slice_until(tf_bundle.get('1d'), entry_ts, 30)
                        btc_entry_idx = 0
                        if btc_history:
                            lo, hi = 0, len(btc_history)
                            while lo < hi:
                                mid = (lo + hi) // 2
                                if int(btc_history[mid]['timestamp']) <= entry_ts:
                                    lo = mid + 1
                                else:
                                    hi = mid
                            btc_entry_idx = max(0, lo)

                        entry_bot_ctx = build_training_bot_context(
                            history,
                            candidate,
                            entry_ts,
                            btc_history=btc_history,
                            index=btc_entry_idx if btc_history else None,
                            h1_history=_slice_until(tf_bundle.get('1h'), entry_ts, 40),
                            h4_history=_slice_until(tf_bundle.get('4h'), entry_ts, 80),
                            d1_history=_slice_until(tf_bundle.get('1d'), entry_ts, 80),
                        )
                        entry_trade_ctx = {
                            'fee_rate': fee_rate,
                            'position_value_usd': 5.0,
                            'account_balance': 1000.0,
                            'planned_hold_minutes': 96 * 15.0,
                        }
                        entry_p_win_train = ml_engine.predict_win_probability(
                            history,
                            entry_price,
                            klines_5m=entry_5m,
                            klines_1h=entry_1h,
                            klines_4h=entry_4h,
                            klines_1d=entry_1d,
                            trade_context=entry_trade_ctx,
                            bot_context=entry_bot_ctx,
                        )

                        exit_index, final_exit_price, _ = simulate_trade(
                            symbol_15m, index, entry_price, candidate.get('support_price'), 1.0, exit_max_hold, 2.5,
                            breakeven_stop=True, breakeven_trigger=1.5, breakeven_lock=1.0,
                            fee_rate=fee_rate, trend_exit=exit_trend_enabled,
                            trend_confirm_bars=exit_trend_confirm
                        )

                        checkpoints = [
                            index + 4, index + 8, index + 16, index + 32,
                            index + 48, index + 96, index + 192, index + 384, index + 672
                        ]
                        for cp in checkpoints:
                            if cp >= len(symbol_15m) or cp >= exit_index:
                                break
                            cp_price = float(symbol_15m[cp]['close'])
                            cp_history = symbol_15m[:cp]
                            if len(cp_history) < 20:
                                continue

                            duration_minutes = (cp - index) * 15.0
                            remaining_days = max(0.0, (exit_index - cp) * 15.0 / 1440.0)
                            position_data = {
                                'entry_price': entry_price,
                                'buy_price': entry_price,
                                'fee_rate': fee_rate,
                                'duration_minutes': duration_minutes,
                                'stop_price': entry_price * 0.99,
                                'target_price': entry_price * 1.02,
                            }

                            exit_now_net = (
                                (cp_price * (1 - fee_rate) - entry_price * (1 + fee_rate))
                                / max(entry_price, 1e-9)
                            ) * 100.0
                            hold_final_net = (
                                (float(final_exit_price) * (1 - fee_rate) - entry_price * (1 + fee_rate))
                                / max(entry_price, 1e-9)
                            ) * 100.0
                            hold_advantage = hold_final_net - exit_now_net - (remaining_days * time_cost_per_day)
                            exit_label = 1 if hold_advantage >= exit_min_edge else 0

                            cp_ts = int(symbol_15m[cp]['timestamp'])
                            btc_idx = 0
                            if btc_history:
                                # positionner BTC sur la dernière bougie connue au checkpoint, sans futur.
                                lo, hi = 0, len(btc_history)
                                while lo < hi:
                                    mid = (lo + hi) // 2
                                    if int(btc_history[mid]['timestamp']) <= cp_ts:
                                        lo = mid + 1
                                    else:
                                        hi = mid
                                btc_idx = max(0, lo)
                            btc_slice = btc_history[max(0, btc_idx - 30):btc_idx] if btc_history else None
                            bot_ctx = build_training_bot_context(
                                cp_history,
                                None,
                                cp_ts,
                                btc_history=btc_history,
                                index=btc_idx if btc_history else None
                            )
                            exit_features = ml_engine.extract_exit_features(
                                cp_history,
                                cp_price,
                                position_data,
                                continuation_score=50.0,
                                entry_p_win=entry_p_win_train,
                                btc_klines=btc_slice,
                                bot_context=bot_ctx
                            )
                            if exit_features is not None:
                                X_exit_samples.append(exit_features)
                                y_exit_labels.append(exit_label)
                                exit_timestamps.append(cp_ts / 1000.0 if cp_ts > 1e12 else float(cp_ts))

                    if len(X_exit_samples) >= max_exit_samples:
                        break

                if len(X_exit_samples) >= 30:
                    X_exit = np.array(X_exit_samples, dtype=np.float64)
                    y_exit = np.array(y_exit_labels, dtype=np.int64)
                    ts_exit = np.array(exit_timestamps, dtype=np.float64)
                    ml_engine.train_exit_model(
                        X_exit,
                        y_exit,
                        timestamps=ts_exit,
                        n_estimators=150,
                        max_depth=6,
                        min_samples_split=10,
                        use_lightgbm=use_lightgbm
                    )
                    n_continue = int(np.sum(y_exit == 1))
                    n_exit = int(len(y_exit) - n_continue)
                    _tot = max(1, len(y_exit))
                    model_name = 'LightGBM' if use_lightgbm else 'RandomForest'
                    print(
                        f"  ✅ P_exit multi-symboles ({model_name}) : {len(X_exit_samples)} samples "
                        f"(continue:{n_continue} [{n_continue/_tot*100:.1f}%], "
                        f"exit:{n_exit} [{n_exit/_tot*100:.1f}%])"
                    )
                else:
                    print(f"  ⚠️ Pas assez de samples exit ({len(X_exit_samples)}), modèle sortie non entraîné")
            except Exception as ex:
                print(f"  ⚠️ Note entraînement modèle sortie: {ex}")

            try:
                ml_engine.train_sizing_model(X, y_sizing, n_estimators=120, max_depth=6, min_samples_split=10, use_lightgbm=use_lightgbm)
                print(f"  ✅ Modèle de Sizing entraîné et fusionné dans Challenger")
            except Exception as ex:
                print(f"  ⚠️ Note entraînement modèle sizing: {ex}")

            try:
                ml_engine.train_target_model(X, y_target, n_estimators=120, max_depth=8, min_samples_split=10, use_lightgbm=use_lightgbm)
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
    """Train the challenger, then delegate ALL promotion policy to promote_challenger.

    Keeping a single promotion implementation prevents auto-retraining from bypassing
    the same-opportunity shadow guardrails used by manual promotion.
    """
    load_dotenv('.env', override=True)
    db_file = db_file or os.getenv('ML_LIVE_SQLITE_FILE', 'data/aegis_db.sqlite3')

    print("=" * 70)
    print("🚀 PIPELINE ML : TRAINING CHALLENGER + PROMOTION CENTRALISÉE")
    print("=" * 70)

    ok = train_challenger_model(
        output_dir=model_dir,
        db_file=db_file,
        fast_mode=fast_mode,
    )
    if not ok:
        print("❌ Échec de l'entraînement Challenger.")
        return False

    from scripts.promote_challenger import promote
    return bool(
        promote(
            model_dir=model_dir,
            db_file=db_file,
            check_only=check_only,
            force=False,
            trigger_type=trigger_type,
        )
    )

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Pipeline unifiée ML Aegis")
    parser.add_argument('--dir', default='data', help="Répertoire des modèles")
    parser.add_argument('--db', default=os.getenv('ML_LIVE_SQLITE_FILE', 'data/aegis_db.sqlite3'))
    parser.add_argument('--check-only', action='store_true', help="Vérifie les garde-fous sans promouvoir")
    parser.add_argument('--trigger', default='manual', help="auto ou manual")
    parser.add_argument('--fast', action='store_true', help="Mode rapide de test")
    parser.add_argument('--no-grid', action='store_true', help="Désactive Grid Search (activé par défaut)")
    parser.add_argument('--no-lightgbm', action='store_true', help="Utilise RandomForest au lieu de LightGBM")
    args = parser.parse_args()

    # Définir les options ML via variables d'environnement (utilisées par train_challenger_model)
    if args.no_grid:
        os.environ['ML_USE_GRID_SEARCH'] = 'false'
    else:
        os.environ['ML_USE_GRID_SEARCH'] = 'true'
    
    if args.no_lightgbm:
        os.environ['ML_USE_LIGHTGBM'] = 'false'

    run_pipeline(model_dir=args.dir, db_file=args.db, check_only=args.check_only, trigger_type=args.trigger, fast_mode=args.fast)
