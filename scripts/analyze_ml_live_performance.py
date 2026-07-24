"""Analyse Phase 4B: compare les predictions ML live aux resultats reels."""

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.ml_live_logger import MLLiveLogger


BUCKETS = [
    (0.0, 50.0, '00_50'),
    (50.0, 60.0, '50_60'),
    (60.0, 65.0, '60_65'),
    (65.0, 70.0, '65_70'),
    (70.0, 80.0, '70_80'),
    (80.0, 100.0001, '80_100'),
]


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def run_id():
    return f"ml_analysis_{datetime.now().strftime('%Y%m%d%H%M%S')}"


def bucket_for(p_win):
    value = float(p_win or 0.0)
    for low, high, label in BUCKETS:
        if low <= value < high:
            return low, high, label
    return 0.0, 100.0001, 'unknown'


def load_entries(conn):
    return conn.execute(
        """
        SELECT
            e.event_id, e.timestamp, e.symbol, e.decision, e.reason,
            e.price, e.p_win, e.p_continue, e.label_status,
            o.pnl_pct, o.pnl, o.sell_price, o.buy_price, o.timestamp AS exit_timestamp
        FROM ml_entry_decisions e
        LEFT JOIN ml_trade_outcomes o ON o.entry_id = e.event_id
        ORDER BY e.timestamp
        """
    ).fetchall()


def compute_calibration(conn, analysis_id, entries):
    accepted = [row for row in entries if row['decision'] == 'accepted']
    closed = [row for row in accepted if row['pnl_pct'] is not None]
    bucket_rows = []
    brier_values = []
    calibration_errors = []

    for low, high, label in BUCKETS:
        bucket_entries = [row for row in accepted if low <= float(row['p_win'] or 0.0) < high]
        bucket_closed = [row for row in bucket_entries if row['pnl_pct'] is not None]
        predicted_avg = (
            sum(float(row['p_win'] or 0.0) for row in bucket_entries) / len(bucket_entries)
            if bucket_entries else None
        )
        wins = [row for row in bucket_closed if float(row['pnl_pct'] or 0.0) > 0]
        realized = (len(wins) / len(bucket_closed) * 100.0) if bucket_closed else None
        avg_pnl = (
            sum(float(row['pnl_pct'] or 0.0) for row in bucket_closed) / len(bucket_closed)
            if bucket_closed else None
        )
        error = abs(predicted_avg - realized) if predicted_avg is not None and realized is not None else None
        if error is not None:
            calibration_errors.append(error)
        for row in bucket_closed:
            pred = float(row['p_win'] or 0.0) / 100.0
            actual = 1.0 if float(row['pnl_pct'] or 0.0) > 0 else 0.0
            brier_values.append((pred - actual) ** 2)

        bucket_rows.append({
            'run_id': analysis_id,
            'bucket_label': label,
            'min_p_win': low,
            'max_p_win': high if high <= 100 else 100.0,
            'entries': len(bucket_entries),
            'closed_entries': len(bucket_closed),
            'predicted_avg': predicted_avg,
            'realized_win_rate': realized,
            'avg_pnl_pct': avg_pnl,
            'calibration_error': error,
        })

    conn.executemany(
        """
        INSERT OR REPLACE INTO ml_prediction_calibration
        (run_id, bucket_label, min_p_win, max_p_win, entries, closed_entries,
         predicted_avg, realized_win_rate, avg_pnl_pct, calibration_error)
        VALUES (:run_id, :bucket_label, :min_p_win, :max_p_win, :entries,
                :closed_entries, :predicted_avg, :realized_win_rate,
                :avg_pnl_pct, :calibration_error)
        """,
        bucket_rows
    )

    return {
        'accepted_entries': len(accepted),
        'closed_entries': len(closed),
        'brier_score': (sum(brier_values) / len(brier_values)) if brier_values else None,
        'calibration_mae': (sum(calibration_errors) / len(calibration_errors)) if calibration_errors else None,
        'live_win_rate': (
            len([row for row in closed if float(row['pnl_pct'] or 0.0) > 0]) / len(closed) * 100.0
            if closed else None
        ),
        'avg_pnl_pct': (
            sum(float(row['pnl_pct'] or 0.0) for row in closed) / len(closed)
            if closed else None
        ),
        'bucket_rows': bucket_rows,
    }


def normalize_symbol(symbol):
    symbol = str(symbol or '').upper()
    return symbol.replace('/USD', '/USDT') if symbol.endswith('/USD') else symbol


def fetch_replay_ohlcv(exchange, symbol, timestamp_iso, timeframe, limit):
    dt = datetime.fromisoformat(timestamp_iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    since = int(dt.timestamp() * 1000)
    return exchange.fetch_ohlcv(normalize_symbol(symbol), timeframe=timeframe, since=since, limit=limit)


def replay_rejected(conn, analysis_id, entries, args):
    rejected = [row for row in entries if row['decision'] == 'rejected']
    if not args.replay_rejected:
        return 0

    try:
        import ccxt
        exchange_id = args.exchange.lower()
        exchange_cls = getattr(ccxt, exchange_id)
        exchange = exchange_cls({'enableRateLimit': True})
    except Exception as exc:
        now = datetime.now().isoformat()
        rows = [{
            'entry_id': row['event_id'],
            'run_id': analysis_id,
            'symbol': row['symbol'],
            'timestamp': row['timestamp'],
            'entry_price': row['price'],
            'p_win': row['p_win'],
            'p_continue': row['p_continue'],
            'replay_status': 'unavailable',
            'replay_method': 'future_close_net_pnl',
            'exit_time': None,
            'exit_price': None,
            'pnl_pct': None,
            'would_win': None,
            'reason': f'exchange_unavailable:{exc}',
            'updated_at': now,
        } for row in rejected]
        store_replay_rows(conn, rows)
        return 0

    replayed = 0
    rows = []
    fee_rate = args.fee_rate
    limit = max(2, args.max_hold_candles + 1)
    for row in rejected[:args.max_replay]:
        now = datetime.now().isoformat()
        result = {
            'entry_id': row['event_id'],
            'run_id': analysis_id,
            'symbol': row['symbol'],
            'timestamp': row['timestamp'],
            'entry_price': row['price'],
            'p_win': row['p_win'],
            'p_continue': row['p_continue'],
            'replay_status': 'pending',
            'replay_method': 'future_close_net_pnl',
            'exit_time': None,
            'exit_price': None,
            'pnl_pct': None,
            'would_win': None,
            'reason': None,
            'updated_at': now,
        }
        try:
            candles = fetch_replay_ohlcv(exchange, row['symbol'], row['timestamp'], args.timeframe, limit)
            if len(candles) <= args.max_hold_candles:
                result['replay_status'] = 'pending_more_candles'
                result['reason'] = f'candles_available:{len(candles)}'
            else:
                exit_candle = candles[args.max_hold_candles]
                exit_price = float(exit_candle[4])
                entry_price = float(row['price'] or 0.0)
                pnl_pct = ((exit_price * (1 - fee_rate) - entry_price * (1 + fee_rate)) / entry_price) * 100.0 if entry_price else None
                result.update({
                    'replay_status': 'replayed',
                    'exit_time': datetime.fromtimestamp(exit_candle[0] / 1000.0, timezone.utc).isoformat(),
                    'exit_price': exit_price,
                    'pnl_pct': pnl_pct,
                    'would_win': 1 if pnl_pct is not None and pnl_pct > 0 else 0,
                    'reason': 'ok',
                })
                replayed += 1
            time.sleep(args.request_pause)
        except Exception as exc:
            result['replay_status'] = 'unavailable'
            result['reason'] = str(exc)[:240]
        rows.append(result)

    store_replay_rows(conn, rows)
    return replayed


def store_replay_rows(conn, rows):
    if not rows:
        return
    conn.executemany(
        """
        INSERT OR REPLACE INTO ml_rejected_replay_results
        (entry_id, run_id, symbol, timestamp, entry_price, p_win, p_continue,
         replay_status, replay_method, exit_time, exit_price, pnl_pct, would_win,
         reason, updated_at)
        VALUES (:entry_id, :run_id, :symbol, :timestamp, :entry_price, :p_win,
                :p_continue, :replay_status, :replay_method, :exit_time,
                :exit_price, :pnl_pct, :would_win, :reason, :updated_at)
        """,
        rows
    )


def drift_status(metrics, rejected_count):
    if metrics['closed_entries'] < 30:
        return 'insufficient_live_outcomes', 'Moins de 30 trades fermes relies au ML.'
    if metrics['live_win_rate'] is not None and metrics['live_win_rate'] < 55:
        return 'warning', f"Win rate live faible: {metrics['live_win_rate']:.1f}%."
    if metrics['calibration_mae'] is not None and metrics['calibration_mae'] > 20:
        return 'warning', f"Calibration ML decalee: MAE {metrics['calibration_mae']:.1f} pts."
    return 'ok', 'Performance live suffisante pour le seuil actuel.'


def write_run_summary(conn, analysis_id, metrics, rejected_count, rejected_replayed):
    status, message = drift_status(metrics, rejected_count)
    now = datetime.now().isoformat()
    notes = {
        'message': message,
        'rejected_entries': rejected_count,
        'method': 'accepted calibration + rejected future_close replay',
    }
    conn.execute(
        """
        INSERT OR REPLACE INTO ml_analysis_runs
        (run_id, generated_at, accepted_entries, closed_entries, rejected_entries,
         rejected_replayed, brier_score, calibration_mae, live_win_rate,
         avg_pnl_pct, drift_status, notes_data, stored_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            analysis_id,
            now,
            metrics['accepted_entries'],
            metrics['closed_entries'],
            rejected_count,
            rejected_replayed,
            metrics['brier_score'],
            metrics['calibration_mae'],
            metrics['live_win_rate'],
            metrics['avg_pnl_pct'],
            status,
            json.dumps(notes, ensure_ascii=False),
            now,
        )
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO ml_drift_alerts
        (alert_id, run_id, generated_at, status, message, metrics_data, stored_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"drift_{analysis_id}",
            analysis_id,
            now,
            status,
            message,
            json.dumps({
                'accepted_entries': metrics['accepted_entries'],
                'closed_entries': metrics['closed_entries'],
                'rejected_entries': rejected_count,
                'rejected_replayed': rejected_replayed,
                'live_win_rate': metrics['live_win_rate'],
                'calibration_mae': metrics['calibration_mae'],
                'avg_pnl_pct': metrics['avg_pnl_pct'],
            }, ensure_ascii=False),
            now,
        )
    )
    return status, message


def main():
    load_dotenv(override=True)
    load_dotenv('.env.local', override=True)
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default=os.getenv('ML_LIVE_SQLITE_FILE', 'data/aegis_db.sqlite3'))
    parser.add_argument('--exchange', default=os.getenv('EXCHANGE', 'kraken'))
    parser.add_argument('--timeframe', default=os.getenv('MAIN_TIMEFRAME', '15m'))
    parser.add_argument('--max-hold-candles', type=int, default=int(os.getenv('BACKTEST_MAX_HOLD_CANDLES', '96')))
    parser.add_argument('--fee-rate', type=float, default=float(os.getenv('TRADING_FEE_PERCENT', '0.1')) / 100.0)
    parser.add_argument('--max-replay', type=int, default=250)
    parser.add_argument('--request-pause', type=float, default=0.05)
    parser.add_argument('--no-replay-rejected', action='store_false', dest='replay_rejected')
    parser.set_defaults(replay_rejected=True)
    args = parser.parse_args()

    logger = MLLiveLogger(data_dir=os.path.dirname(args.db) or 'data', sqlite_file=args.db)
    logger.close()

    analysis_id = run_id()
    conn = connect(args.db)
    entries = load_entries(conn)
    metrics = compute_calibration(conn, analysis_id, entries)
    rejected_count = len([row for row in entries if row['decision'] == 'rejected'])
    rejected_replayed = replay_rejected(conn, analysis_id, entries, args)
    status, message = write_run_summary(conn, analysis_id, metrics, rejected_count, rejected_replayed)
    conn.commit()
    conn.close()

    print(f"Analysis: {analysis_id}")
    print(f"Accepted: {metrics['accepted_entries']} | Closed: {metrics['closed_entries']}")
    print(f"Rejected: {rejected_count} | Replayed: {rejected_replayed}")
    print(f"Drift: {status} - {message}")


if __name__ == '__main__':
    main()
