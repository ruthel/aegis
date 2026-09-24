"""Promotion directe du Challenger déjà entraîné en Champion.

Réutilise le modèle challenger existant (data/aegis_challenger.joblib) SANS
re-télécharger les données ni ré-entraîner. Évalue les mêmes garde-fous de
promotion canonique utilisée aussi par train_and_evaluate_ml_model.py. Tous les
seuils viennent de .env, puis le script effectue le backup du
Champion et la copie challenger -> champion.

Usage:
    python scripts/promote_challenger.py --dir data --db data/aegis_db.sqlite3
    python scripts/promote_challenger.py --check-only     # évalue sans promouvoir
    python scripts/promote_challenger.py --force          # ignore le garde-fou better_perf
"""
import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from core.ml_engine import MLEngine
from core.ml_live_logger import MLLiveLogger
from core.managers.notification import NotificationManager


def _active_mode(mode=None):
    value = str(
        mode
        or os.getenv('ML_GOVERNANCE_MODE')
        or ('paper' if os.getenv('PAPER_TRADING', 'True').lower() == 'true' else 'live')
    ).lower()
    return value if value in ('paper', 'live') else 'paper'


def compute_guardrail_metrics(db_file, mode=None):
    mode = _active_mode(mode)
    """Compute live guardrail metrics used by the single promotion policy."""
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
    if not db_file or not os.path.exists(db_file):
        return metrics

    conn = sqlite3.connect(db_file)
    try:
        cur = conn.cursor()
        trade_rows = cur.execute(
            """
            SELECT
                t.symbol,
                COALESCE(e.price, t.buy_price) AS entry_price,
                COALESCE(e.confidence, e.p_win) AS p_win,
                t.pnl_pct,
                t.pnl,
                t.timestamp
            FROM ml_trade_outcomes t
            LEFT JOIN decision_logs e
              ON e.mode = t.mode
             AND e.action_type IN ('ENTRY', 'BUY')
             AND (e.event_id = t.entry_id OR e.entry_id = t.entry_id)
            WHERE t.mode=?
              AND t.pnl_pct IS NOT NULL
            ORDER BY t.timestamp ASC
            """,
            (mode,),
        ).fetchall()
        metrics['trade_rows'] = trade_rows
        metrics['closed_trades_count'] = len(trade_rows)

        if trade_rows:
            dates, pnls, pnl_pcts = [], [], []
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
            metrics['profit_factor'] = (
                sum(wins) / sum(losses)
                if losses and sum(losses) > 0
                else (2.0 if wins else 1.0)
            )
            metrics['net_pnl'] = sum(pnls)
            metrics['net_pnl_pct_sum'] = sum(pnl_pcts)

            equity = peak = max_dd = 0.0
            for pct in pnl_pcts:
                equity += pct
                peak = max(peak, equity)
                max_dd = max(max_dd, peak - equity)
            metrics['max_drawdown_pct'] = max_dd

        latest_analysis = cur.execute(
            """
            SELECT calibration_mae, live_win_rate, drift_status
            FROM ml_analysis_runs
            WHERE mode=?
            ORDER BY generated_at DESC
            LIMIT 1
            """,
            (mode,),
        ).fetchone()
        if latest_analysis:
            metrics['latest_calibration_mae'] = latest_analysis[0]
            metrics['latest_live_win_rate'] = latest_analysis[1]
            metrics['latest_drift_status'] = latest_analysis[2]
    finally:
        conn.close()
    return metrics


def _prune_model_backups(backups_dir, keep=10):
    """Ne conserve que les `keep` archives de modèle les plus récentes dans backups_dir."""
    try:
        import glob
        archives = glob.glob(os.path.join(backups_dir, 'aegis_model_*.joblib'))
        # Tri par nom (horodatage YYYYMMDD_HHMMSS -> ordre chronologique) décroissant
        archives.sort(reverse=True)
        for old in archives[keep:]:
            try:
                os.remove(old)
                print(f"  🧹 Ancien backup supprimé : {os.path.basename(old)}")
            except Exception:
                pass
    except Exception:
        pass


def _strategy_metrics(pnls):
    pnls = [float(x) for x in pnls]
    gross_profit = sum(x for x in pnls if x > 0)
    gross_loss = abs(sum(x for x in pnls if x < 0))
    pf = gross_profit / gross_loss if gross_loss > 0 else (float('inf') if gross_profit > 0 else 0.0)
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    wins = sum(1 for x in pnls if x > 0)
    return {
        'trades': len(pnls),
        'pnl_pct': sum(pnls),
        'profit_factor': pf,
        'max_drawdown_pct_points': max_dd,
        'win_rate': (wins / len(pnls) * 100.0) if pnls else 0.0,
    }


def compute_shadow_comparison(db_file, mode=None):
    """Compare champion/challenger on the same opportunities of one trading mode."""
    mode = _active_mode(mode)
    empty = {
        'outcomes': 0,
        'champion': _strategy_metrics([]),
        'challenger': _strategy_metrics([]),
    }
    if not db_file or not os.path.exists(db_file):
        return empty
    try:
        con = sqlite3.connect(db_file)
        rows = con.execute(
            """
            SELECT s.timestamp, s.champion_take, s.challenger_take,
                   COALESCE(o.pnl_pct, r.pnl_pct) AS outcome_pnl
            FROM ml_shadow_predictions s
            LEFT JOIN ml_trade_outcomes o
              ON o.entry_id = s.entry_id
             AND o.mode = s.mode
            LEFT JOIN ml_rejected_replay_results r ON r.entry_id = s.entry_id
            WHERE s.mode=?
              AND COALESCE(o.pnl_pct, r.pnl_pct) IS NOT NULL
            ORDER BY s.timestamp ASC
            """,
            (mode,),
        ).fetchall()
        con.close()
    except Exception:
        return empty

    champ = []
    chall = []
    for _, champ_take, chall_take, pnl in rows:
        value = float(pnl or 0.0)
        if int(champ_take or 0) == 1:
            champ.append(value)
        if int(chall_take or 0) == 1:
            chall.append(value)
    return {
        'outcomes': len(rows),
        'champion': _strategy_metrics(champ),
        'challenger': _strategy_metrics(chall),
    }


def promote(model_dir='data', db_file=None, check_only=False, force=False, trigger_type='manual', mode=None):
    load_dotenv('.env', override=True)

    mode = _active_mode(mode)
    db_file = db_file or os.getenv('ML_LIVE_SQLITE_FILE', 'data/aegis_db.sqlite3')

    challenger_path = os.path.join(model_dir, 'aegis_challenger.joblib')
    champion_path = os.path.join(model_dir, 'aegis_model.joblib')
    backup_path = os.path.join(model_dir, 'aegis_model_backup.joblib')

    if not os.path.exists(challenger_path):
        print(f"❌ Aucun Challenger trouvé : {challenger_path}")
        print("   Lance d'abord un entraînement pour produire un challenger.")
        return False

    logger = MLLiveLogger(data_dir=model_dir, sqlite_file=db_file)

    print("=" * 70)
    print(f"🏆 PROMOTION DIRECTE DU CHALLENGER — mode {mode.upper()} (sans ré-entraînement)")
    print("=" * 70)

    # Charger les métadonnées des deux modèles
    champ_engine = MLEngine(model_dir=model_dir)
    champion_exists = os.path.exists(champion_path)
    champion_compatible = False
    if champion_exists:
        champ_engine.model_path = champion_path
        champion_compatible = bool(champ_engine.load_model())

    chall_engine = MLEngine(model_dir=model_dir)
    chall_engine.model_path = challenger_path
    challenger_compatible = bool(chall_engine.load_model())
    if not challenger_compatible:
        reason = "Challenger incompatible avec le schéma/runtime courant"
        print(f"⛔ PROMOTION REFUSÉE : {reason}")
        logger.record_governance_event(
            'promotion_rejected',
            source_model='challenger',
            target_model='champion',
            metrics={'challenger_compatible': False},
            trigger_type=trigger_type,
            reason=reason,
        )
        logger.close()
        return False

    champ_meta = getattr(champ_engine, 'model_metadata', {}) or {}
    chall_meta = getattr(chall_engine, 'model_metadata', {}) or {}

    champ_prec = float(champ_meta.get('test_precision', 50.0)) if champion_compatible else None
    chall_prec = float(chall_meta.get('test_precision', 50.0))
    champ_acc = float(champ_meta.get('test_accuracy', 50.0)) if champion_compatible else None
    chall_acc = float(chall_meta.get('test_accuracy', 50.0))

    print("\n  🏆 CHAMPION actuel:")
    if champion_compatible:
        print(f"    Precision: {champ_prec:.1f}%  Accuracy: {champ_acc:.1f}%")
        print(f"    Samples: {champ_meta.get('train_samples', 'n/a')}  Win rate: {champ_meta.get('train_win_rate', 'n/a')}")
        print(f"    Entraîné le: {champ_meta.get('trained_at', 'n/a')}")
    else:
        print("    Incompatible avec le schéma courant — comparaison directe non applicable.")

    print("\n  ⚔️ CHALLENGER candidat:")
    print(f"    Precision: {chall_prec:.1f}%  Accuracy: {chall_acc:.1f}%")
    print(f"    Samples: {chall_meta.get('train_samples', 'n/a')}  Win rate: {chall_meta.get('train_win_rate', 'n/a')}")
    print(f"    Entraîné le: {chall_meta.get('trained_at', 'n/a')}")

    if champion_compatible:
        prec_delta = chall_prec - champ_prec
        acc_delta = chall_acc - champ_acc
        print(f"\n  📈 Deltas: Precision {prec_delta:+.1f}%  Accuracy {acc_delta:+.1f}%")
    else:
        prec_delta = acc_delta = 0.0
        print("\n  📈 Deltas: n/a — migration de schéma, ancien Champion non comparable.")

    # Garde-fous (mêmes seuils que la pipeline principale)
    guardrail_metrics = compute_guardrail_metrics(db_file, mode=mode)
    closed_trades_count = guardrail_metrics['closed_trades_count']

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
        for item in os.getenv('ML_PROMOTION_ALLOWED_DRIFT_STATUSES', 'ok,warning,insufficient_live_outcomes').split(',')
        if item.strip()
    }

    profit_factor = float(guardrail_metrics['profit_factor'])
    active_days = int(guardrail_metrics['active_days'])
    net_pnl = float(guardrail_metrics['net_pnl'])
    max_dd = float(guardrail_metrics['max_drawdown_pct'])
    calibration_mae = guardrail_metrics.get('latest_calibration_mae')
    drift_status_value = str(guardrail_metrics.get('latest_drift_status') or 'unknown').lower()
    shadow = compute_shadow_comparison(db_file, mode=mode)
    require_shadow = os.getenv('ML_PROMOTION_REQUIRE_SHADOW', 'true').lower() == 'true'
    min_shadow_outcomes = int(os.getenv('ML_PROMOTION_SHADOW_MIN_OUTCOMES', '30'))
    min_shadow_pnl_delta = float(os.getenv('ML_PROMOTION_SHADOW_MIN_PNL_DELTA_PCT', '0.0'))
    max_shadow_dd_delta = float(os.getenv('ML_PROMOTION_SHADOW_MAX_DD_DELTA_PCT', '0.5'))
    champ_shadow = shadow['champion']
    chall_shadow = shadow['challenger']

    g1 = closed_trades_count >= min_trades
    g2 = active_days >= min_days
    g3 = (
        (chall_prec >= champ_prec + min_precision_delta)
        and (chall_acc >= champ_acc + min_accuracy_delta)
    ) if champion_compatible else True
    g4 = max_dd <= max_drawdown_pct
    g5 = profit_factor >= min_profit_factor
    g6 = net_pnl > 0
    g7 = (calibration_mae is not None and float(calibration_mae) <= max_calibration_mae) if require_calibration \
        else (calibration_mae is None or float(calibration_mae) <= max_calibration_mae)
    g8 = drift_status_value in allowed_drift_statuses
    shadow_enough = shadow['outcomes'] >= min_shadow_outcomes
    shadow_better = (
        chall_shadow['pnl_pct'] >= champ_shadow['pnl_pct'] + min_shadow_pnl_delta
        and chall_shadow['max_drawdown_pct_points'] <= champ_shadow['max_drawdown_pct_points'] + max_shadow_dd_delta
    )
    g9 = (shadow_enough and shadow_better) if require_shadow else (not shadow_enough or shadow_better)

    # Chaque tête auxiliaire doit être validée hors-échantillon avant promotion.
    aux_validations = {
        'entry': str(chall_meta.get('validation_type') or '').startswith('temporal_holdout'),
        'edge': chall_meta.get('edge_validation_type') == 'temporal_holdout',
        'exit': chall_meta.get('exit_validation_type') == 'temporal_holdout',
        'sizing': chall_meta.get('sizing_validation_type') == 'temporal_holdout',
    }
    g10 = all(aux_validations.values())

    # Un modèle ne doit pas être promu s'il fait moins bien qu'une prédiction
    # naïve calculée uniquement sur le passé du holdout temporel.
    max_oos_baseline_ratio = max(
        1.0,
        float(os.getenv('ML_PROMOTION_MAX_OOS_BASELINE_RATIO', '1.05')),
    )

    def _not_worse_than_baseline(metric_key, baseline_key):
        try:
            metric = float(chall_meta.get(metric_key))
            baseline = float(chall_meta.get(baseline_key))
        except (TypeError, ValueError):
            return False
        if baseline <= 1e-12:
            return metric <= 1e-12
        return metric <= baseline * max_oos_baseline_ratio

    oos_skill_checks = {
        'entry': _not_worse_than_baseline('test_brier', 'test_baseline_brier'),
        'edge': _not_worse_than_baseline('edge_test_mae_pct', 'edge_baseline_mae_pct'),
        'exit': _not_worse_than_baseline('exit_test_brier', 'exit_test_baseline_brier'),
        'sizing': _not_worse_than_baseline('sizing_test_mae', 'sizing_baseline_mae'),
    }
    g11 = all(oos_skill_checks.values())

    # Migration de schéma : l'ancien champion strictement incompatible ne peut pas
    # produire de shadow comparable. On autorise un bootstrap uniquement si le
    # Challenger v5 est complet et validé temporellement.
    schema_bootstrap = not champion_compatible
    bootstrap_allowed = os.getenv('ML_ALLOW_SCHEMA_BOOTSTRAP_PROMOTION', 'true').lower() == 'true'
    bootstrap_min_samples = int(os.getenv('ML_SCHEMA_BOOTSTRAP_MIN_TRAIN_SAMPLES', '200'))
    bootstrap_heads_ready = all([
        chall_engine.is_trained,
        chall_engine.is_edge_trained,
        chall_engine.is_exit_trained,
        chall_engine.is_sizing_trained,
    ])
    bootstrap_ready = (
        bootstrap_allowed
        and challenger_compatible
        and bootstrap_heads_ready
        and g10
        and g11
        and int(chall_meta.get('train_samples') or 0) >= bootstrap_min_samples
    )

    print("\n🛡️ GARDE-FOUS DE PROMOTION :")
    print(f"  [1] Trades fermés ({closed_trades_count}) >= {min_trades} : {'✅' if g1 else '❌'}")
    print(f"  [2] Jours actifs ({active_days}) >= {min_days} : {'✅' if g2 else '❌'}")
    print(f"  [3] Precision/Accuracy vs Champion (seuils {min_precision_delta:+.1f}%/{min_accuracy_delta:+.1f}%) : {'✅' if g3 else '❌'}")
    print(f"  [4] Max Drawdown ({max_dd:.2f}%) <= {max_drawdown_pct:.2f}% : {'✅' if g4 else '❌'}")
    print(f"  [5] Profit Factor ({profit_factor:.2f}) >= {min_profit_factor:.2f} : {'✅' if g5 else '❌'}")
    print(f"  [6] PnL net ({net_pnl:.2f} USD) > 0 : {'✅' if g6 else '❌'}")
    print(f"  [7] Calibration MAE ({calibration_mae if calibration_mae is not None else 'n/a'}) <= {max_calibration_mae:.1f} : {'✅' if g7 else '❌'}")
    print(f"  [8] Drift status ({drift_status_value}) autorisé : {'✅' if g8 else '❌'}")
    print(
        f"  [9] Shadow mêmes opportunités ({shadow['outcomes']} outcomes): "
        f"Champion PnL {champ_shadow['pnl_pct']:+.2f}% / DD {champ_shadow['max_drawdown_pct_points']:.2f} | "
        f"Challenger PnL {chall_shadow['pnl_pct']:+.2f}% / DD {chall_shadow['max_drawdown_pct_points']:.2f} : "
        f"{'✅' if g9 else '❌'}"
    )
    print(
        f"  [10] Validation temporelle de toutes les têtes "
        f"(entry/edge/exit/sizing): {'✅' if g10 else '❌'}"
    )
    print(
        f"  [11] Performance OOS vs baseline naïve "
        f"(ratio max {max_oos_baseline_ratio:.2f}): {'✅' if g11 else '❌'} "
        f"{oos_skill_checks}"
    )
    if schema_bootstrap:
        print(
            f"  [BOOTSTRAP] Champion absent/incompatible, Challenger complet "
            f"({chall_meta.get('train_samples', 0)} samples >= {bootstrap_min_samples}) : "
            f"{'✅' if bootstrap_ready else '❌'}"
        )
        print(
            "     ↳ Les garde-fous live historiques [1-9] restent affichés à titre "
            "informatif mais ne bloquent pas une migration de schéma. "
            "Le bootstrap exige compatibilité + toutes les têtes OOS + skill vs baseline."
        )

    guardrails = {
        'min_trades': g1, 'min_days': g2, 'better_perf': g3, 'drawdown': g4,
        'profit_factor': g5, 'net_pnl': g6, 'calibration': g7, 'drift': g8,
        'same_opportunity_shadow': g9, 'aux_oos_validation': g10,
        'aux_oos_skill': g11,
    }
    metrics_data = {
        'closed_trades_count': closed_trades_count,
        'champion_precision': champ_prec, 'challenger_precision': chall_prec,
        'champion_accuracy': champ_acc, 'challenger_accuracy': chall_acc,
        'profit_factor': profit_factor, 'net_pnl': net_pnl, 'max_drawdown_pct': max_dd,
        'shadow_comparison': shadow,
        'champion_compatible': champion_compatible,
        'challenger_compatible': challenger_compatible,
        'schema_bootstrap': schema_bootstrap,
        'bootstrap_ready': bootstrap_ready,
        'aux_validations': aux_validations,
        'oos_skill_checks': oos_skill_checks,
        'max_oos_baseline_ratio': max_oos_baseline_ratio,
        'guardrails': guardrails,
    }

    if schema_bootstrap:
        # Les garde-fous live/shadow d'un champion incompatible ne sont pas
        # comparables. Le bootstrap repose donc sur la validation OOS complète.
        all_passed = bootstrap_ready
    else:
        all_passed = all(guardrails.values())

    if force and not all_passed:
        failed = [name for name, passed in guardrails.items() if not passed]
        print(f"\n⚠️ --force actif : garde-fous ignorés ({', '.join(failed)})")
        all_passed = True

    if not all_passed:
        if schema_bootstrap:
            bootstrap_failures = []
            if not bootstrap_allowed:
                bootstrap_failures.append('bootstrap_disabled')
            if not challenger_compatible:
                bootstrap_failures.append('challenger_incompatible')
            if not bootstrap_heads_ready:
                bootstrap_failures.append('missing_ml_head')
            if not g10:
                bootstrap_failures.append('aux_oos_validation')
            if not g11:
                bootstrap_failures.append('aux_oos_skill')
            if int(chall_meta.get('train_samples') or 0) < bootstrap_min_samples:
                bootstrap_failures.append('insufficient_train_samples')
            reason = f"Bootstrap schéma refusé: {', '.join(bootstrap_failures) or 'unknown'}"
        else:
            failed = [name for name, passed in guardrails.items() if not passed]
            reason = f"Garde-fous non satisfaits: {', '.join(failed)}"
        print(f"\n⛔ PROMOTION REFUSÉE : {reason}")
        print("   Astuce: relance avec --force, ou ajuste ML_PROMOTION_MIN_*_DELTA dans .env")
        logger.record_governance_event('promotion_rejected', source_model='challenger', target_model='champion', metrics=metrics_data, trigger_type=trigger_type, reason=reason)
        logger.close()
        return False

    if check_only:
        print("\n🔍 Mode --check-only : validé, promotion NON appliquée.")
        logger.record_governance_event('promotion_checked', source_model='challenger', target_model='champion', metrics=metrics_data, trigger_type=trigger_type, reason="Validation sans promotion")
        logger.close()
        return True

    # Promotion
    print("\n🏆 PROMOTION DU CHALLENGER EN CHAMPION !")
    if os.path.exists(champion_path):
        backups_dir = os.path.join(model_dir, 'backups')
        os.makedirs(backups_dir, exist_ok=True)
        ts_backup_path = os.path.join(backups_dir, f"aegis_model_{datetime.now().strftime('%Y%m%d_%H%M%S')}.joblib")
        shutil.copy2(champion_path, ts_backup_path)
        print(f"  📦 Archive horodatée : {ts_backup_path}")
        _prune_model_backups(backups_dir, keep=10)
        # Pas de backup redondant dans data/: l'archive horodatée fait foi
        if os.path.exists(backup_path):
            try:
                os.remove(backup_path)
            except Exception:
                pass

    shutil.copy2(challenger_path, champion_path)
    print(f"  ✅ NOUVEAU CHAMPION PROMU : {champion_path}")

    reason = f"Promotion directe (Precision {chall_prec:.1f}%, Acc {chall_acc:.1f}%{', forcée' if force else ''})"
    logger.record_governance_event('promotion', source_model='challenger', target_model='champion', metrics=metrics_data, trigger_type=trigger_type, reason=reason)

    try:
        notifier = NotificationManager()
        notifier.notify(f"🏆 **NOUVEAU CHAMPION ML PROMU**\n\nPrecision: {chall_prec:.1f}%\nAccuracy: {chall_acc:.1f}%\nSamples: {chall_meta.get('train_samples', 'n/a')}\nBackup: OK")
    except Exception:
        pass

    logger.close()
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Promotion directe du Challenger déjà entraîné")
    parser.add_argument('--dir', default='data', help="Répertoire des modèles")
    parser.add_argument('--db', default=os.getenv('ML_LIVE_SQLITE_FILE', 'data/aegis_db.sqlite3'))
    parser.add_argument('--check-only', action='store_true', help="Évalue sans promouvoir")
    parser.add_argument('--force', action='store_true', help="Ignore les garde-fous non satisfaits")
    parser.add_argument('--trigger', default='manual', help="auto ou manual")
    parser.add_argument('--mode', choices=('paper', 'live'), default=None)
    args = parser.parse_args()

    ok = promote(
        model_dir=args.dir,
        db_file=args.db,
        check_only=args.check_only,
        force=args.force,
        trigger_type=args.trigger,
        mode=args.mode,
    )
    sys.exit(0 if ok else 1)
