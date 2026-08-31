"""Analyse Phase 4B: compare les predictions ML live aux resultats reels."""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from sqlalchemy import or_, select

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.db_orm import (
    DecisionLog,
    MlAnalysisRun,
    MlDriftAlert,
    MlTradeOutcome,
    MlPredictionCalibration,
    MlRejectedReplayResult,
    create_session_factory,
)
from core.ml_live_logger import MLLiveLogger
# simulate_trade reproduit la VRAIE logique de sortie du bot (stop-loss dynamique,
# breakeven zéro-perte, trailing par paliers) — utilisé pour un replay réaliste.
from scripts.trade_signals import simulate_trade


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


def load_entries(session):
    rows = session.execute(
        select(DecisionLog, MlTradeOutcome)
        .outerjoin(
            MlTradeOutcome,
            or_(
                MlTradeOutcome.entry_id == DecisionLog.event_id,
                MlTradeOutcome.entry_id == DecisionLog.entry_id,
            ),
        )
        .where(DecisionLog.action_type == 'ENTRY')
        .order_by(DecisionLog.timestamp.asc())
    ).all()
    entries = []
    linked_outcomes = set()
    for entry, outcome in rows:
        if outcome:
            linked_outcomes.add(outcome.event_id)
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
    orphan_outcomes = session.execute(
        select(MlTradeOutcome)
        .where(MlTradeOutcome.pnl_pct.is_not(None))
        .order_by(MlTradeOutcome.timestamp.asc())
    ).scalars().all()
    for outcome in orphan_outcomes:
        if outcome.event_id in linked_outcomes:
            continue
        entries.append({
            'event_id': outcome.entry_id or outcome.event_id,
            'timestamp': outcome.timestamp,
            'symbol': outcome.symbol,
            'decision': 'accepted',
            'reason': 'closed_outcome_without_entry_decision',
            'price': outcome.buy_price,
            'p_win': None,
            'p_continue': None,
            'label_status': 'closed_orphan',
            'pnl_pct': outcome.pnl_pct,
            'pnl': outcome.pnl,
            'sell_price': outcome.sell_price,
            'buy_price': outcome.buy_price,
            'exit_timestamp': outcome.timestamp,
        })
    return entries


def compute_calibration(session, analysis_id, entries):
    accepted = [row for row in entries if row['decision'] == 'accepted']
    closed = [row for row in accepted if row['pnl_pct'] is not None]
    bucket_rows = []
    brier_values = []
    calibration_errors = []

    for low, high, label in BUCKETS:
        bucket_entries = [
            row for row in accepted
            if row['p_win'] is not None and low <= float(row['p_win'] or 0.0) < high
        ]
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
    # Le bot trade en paires /USD réelles (Kraken live) et l'historique long vient de
    # Coinbase, qui expose aussi des paires /USD. On NE convertit PLUS vers /USDT:
    # c'était incorrect (marché différent, moins liquide) et source d'échecs de replay.
    return str(symbol or '').upper()


def _timeframe_seconds(timeframe):
    """Convertit un timeframe ccxt (ex '15m', '1h', '4h', '1d') en secondes."""
    tf = str(timeframe or '15m').strip().lower()
    units = {'m': 60, 'h': 3600, 'd': 86400, 'w': 604800}
    try:
        return int(tf[:-1]) * units.get(tf[-1], 60)
    except Exception:
        return 15 * 60


def _entry_age_seconds(timestamp_iso, now_dt):
    """Âge (en secondes) d'un refus depuis son timestamp. None si non parseable."""
    try:
        dt = datetime.fromisoformat(str(timestamp_iso))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (now_dt - dt).total_seconds()
    except Exception:
        return None


def _fetch_ohlcv_since(exchange, symbol, since_ms, timeframe, limit):
    """Fetch OHLCV depuis un timestamp donné, en filtrant les bougies antérieures.
    Certains exchanges (Kraken) ignorent 'since' et renvoient les ~720 dernières
    bougies -> on filtre pour ne garder que celles >= since_ms."""
    raw = exchange.fetch_ohlcv(normalize_symbol(symbol), timeframe=timeframe, since=since_ms, limit=limit)
    if not raw:
        return []
    return [c for c in raw if c and c[0] >= since_ms]


def fetch_replay_ohlcv(exchange, symbol, timestamp_iso, timeframe, limit, coinbase_exchange=None):
    """Récupère les bougies POSTÉRIEURES au timestamp d'un refus.

    Kraken (exchange principal live) ne sert que ~720 bougies d'historique public et
    ignore souvent 'since' -> pour un refus un peu ancien, il ne renverra pas les
    bougies autour du refus. On tente d'abord l'exchange principal, et si le résultat
    ne couvre pas la fenêtre demandée (< limit bougies depuis 'since'), on bascule sur
    Coinbase, qui pagine correctement depuis 'since' et couvre plusieurs années.
    """
    dt = datetime.fromisoformat(timestamp_iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    since = int(dt.timestamp() * 1000)

    candles = _fetch_ohlcv_since(exchange, symbol, since, timeframe, limit)
    # Si l'exchange principal ne couvre pas assez la fenêtre future, essayer Coinbase.
    if len(candles) <= limit - 1 and coinbase_exchange is not None:
        try:
            cb_candles = _fetch_ohlcv_since(coinbase_exchange, symbol, since, timeframe, limit)
            if len(cb_candles) > len(candles):
                return cb_candles
        except Exception:
            pass
    return candles


def is_rate_limit_error(exc):
    text = str(exc).lower()
    return (
        'too many requests' in text
        or 'rate limit' in text
        or 'ratelimit' in text
        or 'eapi:rate limit' in text
        or 'egeneral:too many requests' in text
    )


def fetch_replay_ohlcv_with_retry(exchange, symbol, timestamp_iso, timeframe, limit, args, coinbase_exchange=None):
    last_exc = None
    for attempt in range(max(1, args.request_retries + 1)):
        try:
            return fetch_replay_ohlcv(exchange, symbol, timestamp_iso, timeframe, limit, coinbase_exchange=coinbase_exchange)
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
        # MlRejectedReplayResult est déjà importé en tête depuis core.db_orm.
        # (L'ancien code faisait un import erroné depuis core.ml_live_logger, qui levait
        #  une ImportError silencieuse -> already_replayed_ids restait VIDE -> les refus
        #  déjà rejoués n'étaient jamais exclus. Corrigé.)
        from sqlalchemy import select
        res = session.execute(
            select(MlRejectedReplayResult.entry_id).where(MlRejectedReplayResult.replay_status == 'replayed')
        ).scalars().all()
        already_replayed_ids = set(res)
    except Exception as e:
        print(f"⚠️ Impossible de lire les refus déjà rejoués (exclusion désactivée ce run): {e}", flush=True)

    # entries est trié par timestamp ASC (cf. load_entries) -> all_rejected va du plus
    # ancien au plus récent.
    all_rejected = [row for row in entries if row['decision'] == 'rejected']

    # PRIORITÉ AUX REFUS ASSEZ VIEUX POUR ÊTRE REJOUÉS.
    # Un refus n'est rejouable que s'il existe au moins (max_hold_candles + 1) bougies
    # APRÈS son timestamp. Trier "plus récent d'abord" gaspillait le quota sur des refus
    # trop récents (tous repartaient en 'pending_more_candles' -> 0 replay effectif),
    # laissant le backlog de vieux refus jamais atteint. On traite donc du PLUS ANCIEN
    # au plus récent, et on repousse en fin de file les refus trop récents.
    min_age_seconds = (args.max_hold_candles + 1) * _timeframe_seconds(args.timeframe)
    now_ts = datetime.now(timezone.utc)

    def _is_replayable_now(row):
        age = _entry_age_seconds(row.get('timestamp'), now_ts)
        return age is not None and age >= min_age_seconds

    # Non encore rejoués (jamais 'replayed'), séparés en "assez vieux" vs "trop récents".
    # Les refus DÉJÀ 'replayed' sont EXCLUS: leur label vient d'une sortie forcée à N
    # bougies fixes -> le re-rejouer donnerait le même résultat (gaspillage d'appels API).
    # On ne traite donc QUE ce qui n'est pas encore définitivement rejoué.
    unplayed = [r for r in all_rejected if r['event_id'] not in already_replayed_ids]
    unplayed_ready = [r for r in unplayed if _is_replayable_now(r)]        # du plus ancien au plus récent
    unplayed_too_recent = [r for r in unplayed if not _is_replayable_now(r)]

    # Ordre de traitement: vieux rejouables d'abord (rattrape le backlog), puis récents
    # (rejoués lors d'un run futur quand leurs bougies futures existeront). Aucun
    # re-rejeu des refus déjà traités.
    rejected = unplayed_ready + unplayed_too_recent

    coinbase_exchange = None
    try:
        import ccxt
        exchange_id = args.exchange.lower()
        exchange_cls = getattr(ccxt, exchange_id)
        exchange = exchange_cls({'enableRateLimit': True})
        # Exchange de secours Coinbase pour les refus trop anciens: Kraken ne sert que
        # ~720 bougies publiques, Coinbase pagine depuis 'since' sur plusieurs années.
        if exchange_id != 'coinbase':
            try:
                coinbase_exchange = ccxt.coinbase({'enableRateLimit': True})
            except Exception:
                coinbase_exchange = None
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
    to_process = rejected[:args.max_replay]
    total_to_process = len(to_process)
    pending_recent = len(unplayed_too_recent)
    print(f"🔁 REPLAY DES REFUS ML — {total_to_process} refus à traiter ce run "
          f"(rejouables: {len(unplayed_ready)}, trop récents repoussés: {pending_recent}, "
          f"plafond: {args.max_replay})", flush=True)

    def _progress(done, replayed_now, pending_now, unavailable_now):
        pct = (done / total_to_process * 100.0) if total_to_process else 100.0
        bar_len = 20
        filled = int(bar_len * pct / 100.0)
        bar = '█' * filled + '░' * (bar_len - filled)
        print(f"   [{bar}] {pct:5.1f}%  {done}/{total_to_process}  "
              f"✅ rejoués: {replayed_now}  ⏳ pas assez de bougies: {pending_now}  "
              f"⚠️ indispo: {unavailable_now}", flush=True)

    pending_more = 0
    unavailable = 0
    commit_every = 25  # commit périodique -> le status web voit la progression en direct
    for i, row in enumerate(to_process):
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
            candles = fetch_replay_ohlcv_with_retry(exchange, row['symbol'], row['timestamp'], args.timeframe, limit, args, coinbase_exchange=coinbase_exchange)
            if len(candles) <= args.max_hold_candles:
                result['replay_status'] = 'pending_more_candles'
                result['reason'] = f'candles_available:{len(candles)}'
                pending_more += 1
            else:
                entry_price = float(row['price'] or 0.0)
                # SIMULATION DE SORTIE RÉALISTE (au lieu d'une sortie forcée à t+max_hold).
                # On reproduit la vraie gestion du bot: stop-loss dynamique, breakeven
                # zéro-perte et trailing par paliers, via simulate_trade. La bougie du
                # refus est l'entrée (index 0), simulate_trade gère de l'index 1 à max_hold.
                sim_klines = [
                    {'timestamp': c[0], 'open': float(c[1]), 'high': float(c[2]),
                     'low': float(c[3]), 'close': float(c[4]), 'volume': float(c[5])}
                    for c in candles
                ]
                exit_index, exit_price, outcome = simulate_trade(
                    sim_klines, 0, entry_price, None,
                    args.stop_percent, args.max_hold_candles, args.trailing_percent,
                    breakeven_stop=True, breakeven_trigger=args.breakeven_trigger,
                    breakeven_lock=args.breakeven_lock, fee_rate=fee_rate,
                )
                exit_price = float(exit_price)
                pnl_pct = ((exit_price * (1 - fee_rate) - entry_price * (1 + fee_rate)) / entry_price) * 100.0 if entry_price else None
                exit_ts = sim_klines[exit_index]['timestamp'] if 0 <= exit_index < len(sim_klines) else candles[args.max_hold_candles][0]
                result.update({
                    'replay_status': 'replayed',
                    'exit_time': datetime.fromtimestamp(exit_ts / 1000.0, timezone.utc).isoformat(),
                    'exit_price': exit_price,
                    'pnl_pct': pnl_pct,
                    'would_win': 1 if pnl_pct is not None and pnl_pct > 0 else 0,
                    'reason': f'simulated_exit_{outcome}',
                })
                replayed += 1
            time.sleep(args.request_pause)
        except Exception as exc:
            result['replay_status'] = 'retry_later' if is_rate_limit_error(exc) else 'unavailable'
            result['reason'] = str(exc)[:240]
            unavailable += 1
        rows.append(result)

        done = i + 1
        # Commit périodique pour que le status web reflète la progression en direct.
        if done % commit_every == 0:
            try:
                store_replay_rows(session, rows)
                session.commit()
                rows = []
            except Exception:
                pass
        # Affichage progression tous les 10 refus (+ au tout dernier).
        if done % 10 == 0 or done == total_to_process:
            _progress(done, replayed, pending_more, unavailable)

    # Flush du reste non encore commité.
    if rows:
        store_replay_rows(session, rows)
        try:
            session.commit()
        except Exception:
            pass

    print(f"🔁 REPLAY TERMINÉ — {replayed} rejoués, {pending_more} en attente de bougies, "
          f"{unavailable} indisponibles (sur {total_to_process} traités).", flush=True)
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
    load_dotenv('.env.local', override=True)
    load_dotenv('.env.ui', override=True)
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default=os.getenv('ML_LIVE_SQLITE_FILE', 'data/aegis_db.sqlite3'))
    parser.add_argument('--exchange', default=os.getenv('EXCHANGE', 'kraken'))
    parser.add_argument('--timeframe', default=os.getenv('MAIN_TIMEFRAME', '15m'))
    parser.add_argument('--max-hold-candles', type=int, default=int(os.getenv('BACKTEST_MAX_HOLD_CANDLES', '96')))
    parser.add_argument('--fee-rate', type=float, default=float(os.getenv('TRADING_FEE_PERCENT', '0.1')) / 100.0)
    parser.add_argument('--max-replay', type=int, default=int(os.getenv('ML_LIVE_ANALYSIS_MAX_REPLAY', '500')))
    # Paramètres de la simulation de sortie réaliste (alignés sur le bot / le training).
    parser.add_argument('--stop-percent', type=float, default=float(os.getenv('STOP_LOSS_PERCENT', '5')))
    parser.add_argument('--trailing-percent', type=float, default=float(os.getenv('TRAILING_STOP_PERCENT', '2.5')))
    parser.add_argument('--breakeven-trigger', type=float, default=float(os.getenv('BREAKEVEN_TRIGGER_PROFIT_PCT', '1.5')))
    parser.add_argument('--breakeven-lock', type=float, default=float(os.getenv('BREAKEVEN_LOCK_PROFIT_PCT', '1')))
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

    if status in ('WARN', 'CRITICAL'):
        try:
            from core.managers.notification import NotificationManager
            notifier = NotificationManager()
            notifier.notify_ml_drift({
                'status': status,
                'message': message,
                'live_win_rate': metrics.get('live_win_rate'),
                'avg_pnl_pct': metrics.get('avg_pnl_pct')
            })
        except Exception as e:
            print(f"⚠️ Notification drift omise: {e}")


if __name__ == '__main__':
    main()
