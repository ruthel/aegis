"""Analyse Phase 4B: compare les predictions ML live aux resultats reels."""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from sqlalchemy import select

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.db_orm import (
    MlAnalysisRun,
    MlDriftAlert,
    MlDecision,
    MlTradeOutcome,
    MlPredictionCalibration,
    MlRejectedReplayResult,
    create_session_factory,
)
from core.ml_live_logger import MLLiveLogger


BUCKETS = [
    (0.0, 50.0, '00_50'),
    (50.0, 60.0, '50_60'),
    (60.0, 65.0, '60_65'),
    (65.0, 70.0, '65_70'),
    (70.0, 80.0, '70_80'),
    (80.0, 100.0001, '80_100'),
]


def run_id():
    return f"ml_analysis_{datetime.now().strftime('%Y%m%d%H%M%S')}"


def bucket_for(p_win):
    value = float(p_win or 0.0)
    for low, high, label in BUCKETS:
        if low <= value < high:
            return low, high, label
    return 0.0, 100.0001, 'unknown'


def load_entries(session):
    rows = session.execute(
        select(MlDecision, MlTradeOutcome)
        .outerjoin(MlTradeOutcome, MlTradeOutcome.entry_id == MlDecision.event_id)
        .where(MlDecision.action_type == 'ENTRY')
        .order_by(MlDecision.timestamp.asc())
    ).all()
    entries = []
    for entry, outcome in rows:
        entries.append({
            'event_id': entry.event_id,
            'timestamp': entry.timestamp,
            'symbol': entry.symbol,
            'decision': entry.decision,
            'reason': entry.reason,
            'price': entry.price,
            'p_win': entry.confidence if entry.confidence is not None else entry.p_win,
            'p_continue': entry.p_continue,
            'label_status': entry.label_status,
            'pnl_pct': outcome.pnl_pct if outcome else None,
            'pnl': outcome.pnl if outcome else None,
            'sell_price': outcome.sell_price if outcome else None,
            'buy_price': outcome.buy_price if outcome else None,
            'exit_timestamp': outcome.timestamp if outcome else None,
        })
    return entries


def compute_calibration(session, analysis_id, entries):
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

    for row in bucket_rows:
        session.merge(MlPredictionCalibration(**row))

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


def is_rate_limit_error(exc):
    text = str(exc).lower()
    return (
        'too many requests' in text
        or 'rate limit' in text
        or 'ratelimit' in text
        or 'eapi:rate limit' in text
        or 'egeneral:too many requests' in text
    )


def fetch_replay_ohlcv_with_retry(exchange, symbol, timestamp_iso, timeframe, limit, args):
    last_exc = None
    for attempt in range(max(1, args.request_retries + 1)):
        try:
            return fetch_replay_ohlcv(exchange, symbol, timestamp_iso, timeframe, limit)
        except Exception as exc:
            last_exc = exc
            if not is_rate_limit_error(exc) or attempt >= args.request_retries:
                raise
            time.sleep(args.request_pause * (args.retry_backoff ** attempt))
    raise last_exc


def replay_rejected(session, analysis_id, entries, args):
    if not args.replay_rejected:
        return 0

    already_replayed_ids = set()
    try:
        from core.ml_live_logger import MlRejectedReplayResult
        from sqlalchemy import select
        res = session.execute(
            select(MlRejectedReplayResult.entry_id).where(MlRejectedReplayResult.replay_status == 'replayed')
        ).scalars().all()
        already_replayed_ids = set(res)
    except Exception:
        pass

    all_rejected = [row for row in entries if row['decision'] == 'rejected']
    unplayed_rejected = [r for r in reversed(all_rejected) if r['event_id'] not in already_replayed_ids]
    played_rejected = [r for r in reversed(all_rejected) if r['event_id'] in already_replayed_ids]
    rejected = unplayed_rejected + played_rejected

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
        store_replay_rows(session, rows)
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
            candles = fetch_replay_ohlcv_with_retry(exchange, row['symbol'], row['timestamp'], args.timeframe, limit, args)
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
            result['replay_status'] = 'retry_later' if is_rate_limit_error(exc) else 'unavailable'
            result['reason'] = str(exc)[:240]
        rows.append(result)

    store_replay_rows(session, rows)
    return replayed


def store_replay_rows(session, rows):
    if not rows:
        return
    for row in rows:
        session.merge(MlRejectedReplayResult(**row))


def drift_status(metrics, rejected_count):
    if metrics['closed_entries'] < 30:
        return 'insufficient_live_outcomes', 'Moins de 30 trades fermes relies au ML.'
    if metrics['live_win_rate'] is not None and metrics['live_win_rate'] < 55:
        return 'warning', f"Win rate live faible: {metrics['live_win_rate']:.1f}%."
    if metrics['calibration_mae'] is not None and metrics['calibration_mae'] > 20:
        return 'warning', f"Calibration ML decalee: MAE {metrics['calibration_mae']:.1f} pts."
    return 'ok', 'Performance live suffisante pour le seuil actuel.'


def write_run_summary(session, analysis_id, metrics, rejected_count, rejected_replayed):
    status, message = drift_status(metrics, rejected_count)
    now = datetime.now().isoformat()
    session.merge(MlAnalysisRun(
        run_id=analysis_id,
        generated_at=now,
        accepted_entries=metrics['accepted_entries'],
        closed_entries=metrics['closed_entries'],
        rejected_entries=rejected_count,
        rejected_replayed=rejected_replayed,
        brier_score=metrics['brier_score'],
        calibration_mae=metrics['calibration_mae'],
        live_win_rate=metrics['live_win_rate'],
        avg_pnl_pct=metrics['avg_pnl_pct'],
        drift_status=status,
        message=message,
        method='accepted calibration + rejected future_close replay',
        stored_at=now,
    ))
    session.merge(MlDriftAlert(
        alert_id=f"drift_{analysis_id}",
        run_id=analysis_id,
        generated_at=now,
        status=status,
        message=message,
        accepted_entries=metrics['accepted_entries'],
        closed_entries=metrics['closed_entries'],
        rejected_entries=rejected_count,
        rejected_replayed=rejected_replayed,
        live_win_rate=metrics['live_win_rate'],
        calibration_mae=metrics['calibration_mae'],
        avg_pnl_pct=metrics['avg_pnl_pct'],
        stored_at=now,
    ))
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
    parser.add_argument('--request-pause', type=float, default=float(os.getenv('ML_REPLAY_REQUEST_PAUSE_SECONDS', '1.2')))
    parser.add_argument('--request-retries', type=int, default=int(os.getenv('ML_REPLAY_REQUEST_RETRIES', '3')))
    parser.add_argument('--retry-backoff', type=float, default=float(os.getenv('ML_REPLAY_RETRY_BACKOFF', '2.0')))
    parser.add_argument('--no-replay-rejected', action='store_false', dest='replay_rejected')
    parser.set_defaults(replay_rejected=True)
    args = parser.parse_args()

    logger = MLLiveLogger(data_dir=os.path.dirname(args.db) or 'data', sqlite_file=args.db)
    logger.close()

    analysis_id = run_id()
    Session = create_session_factory(args.db)
    session = Session()
    entries = load_entries(session)
    metrics = compute_calibration(session, analysis_id, entries)
    rejected_count = len([row for row in entries if row['decision'] == 'rejected'])
    rejected_replayed = replay_rejected(session, analysis_id, entries, args)
    status, message = write_run_summary(session, analysis_id, metrics, rejected_count, rejected_replayed)
    session.commit()
    session.close()

    print(f"Analysis: {analysis_id}")
    print(f"Accepted: {metrics['accepted_entries']} | Closed: {metrics['closed_entries']}")
    print(f"Rejected: {rejected_count} | Replayed: {rejected_replayed}")
    print(f"Drift: {status} - {message}")


if __name__ == '__main__':
    main()
