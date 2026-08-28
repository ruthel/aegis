"""Promotion directe du Challenger déjà entraîné en Champion.

Réutilise le modèle challenger existant (data/aegis_challenger.joblib) SANS
re-télécharger les données ni ré-entraîner. Évalue les mêmes garde-fous de
promotion que la pipeline principale (train_and_evaluate_ml_model.py) en
utilisant les seuils définis dans .env.local, puis effectue le backup du
Champion et la copie challenger -> champion.

Usage:
    python scripts/promote_challenger.py --dir data --db data/aegis_db.sqlite3
    python scripts/promote_challenger.py --check-only     # évalue sans promouvoir
    python scripts/promote_challenger.py --force          # ignore le garde-fou better_perf
"""
import argparse
import os
import shutil
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from core.ml_engine import MLEngine
from core.ml_live_logger import MLLiveLogger
from core.managers.notification import NotificationManager
from scripts.train_and_evaluate_ml_model import compute_guardrail_metrics


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


def promote(model_dir='data', db_file=None, check_only=False, force=False, trigger_type='manual'):
    load_dotenv('.env.local', override=True)
    load_dotenv('.env.ui', override=True)

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
    print("🏆 PROMOTION DIRECTE DU CHALLENGER (sans ré-entraînement)")
    print("=" * 70)

    # Charger les métadonnées des deux modèles
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

    print("\n  🏆 CHAMPION actuel:")
    print(f"    Precision: {champ_prec:.1f}%  Accuracy: {champ_acc:.1f}%")
    print(f"    Samples: {champ_meta.get('train_samples', 'n/a')}  Win rate: {champ_meta.get('train_win_rate', 'n/a')}")
    print(f"    Entraîné le: {champ_meta.get('trained_at', 'n/a')}")

    print("\n  ⚔️ CHALLENGER candidat:")
    print(f"    Precision: {chall_prec:.1f}%  Accuracy: {chall_acc:.1f}%")
    print(f"    Samples: {chall_meta.get('train_samples', 'n/a')}  Win rate: {chall_meta.get('train_win_rate', 'n/a')}")
    print(f"    Entraîné le: {chall_meta.get('trained_at', 'n/a')}")

    prec_delta = chall_prec - champ_prec
    acc_delta = chall_acc - champ_acc
    print(f"\n  📈 Deltas: Precision {prec_delta:+.1f}%  Accuracy {acc_delta:+.1f}%")

    # Garde-fous (mêmes seuils que la pipeline principale)
    guardrail_metrics = compute_guardrail_metrics(db_file)
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
        for item in os.getenv('ML_PROMOTION_ALLOWED_DRIFT_STATUSES', 'ok,insufficient_live_outcomes').split(',')
        if item.strip()
    }

    profit_factor = float(guardrail_metrics['profit_factor'])
    active_days = int(guardrail_metrics['active_days'])
    net_pnl = float(guardrail_metrics['net_pnl'])
    max_dd = float(guardrail_metrics['max_drawdown_pct'])
    calibration_mae = guardrail_metrics.get('latest_calibration_mae')
    drift_status_value = str(guardrail_metrics.get('latest_drift_status') or 'unknown').lower()

    g1 = closed_trades_count >= min_trades
    g2 = active_days >= min_days
    g3 = (chall_prec >= champ_prec + min_precision_delta) and (chall_acc >= champ_acc + min_accuracy_delta)
    g4 = max_dd <= max_drawdown_pct
    g5 = profit_factor >= min_profit_factor
    g6 = net_pnl > 0
    g7 = (calibration_mae is not None and float(calibration_mae) <= max_calibration_mae) if require_calibration \
        else (calibration_mae is None or float(calibration_mae) <= max_calibration_mae)
    g8 = drift_status_value in allowed_drift_statuses

    print("\n🛡️ GARDE-FOUS DE PROMOTION :")
    print(f"  [1] Trades fermés ({closed_trades_count}) >= {min_trades} : {'✅' if g1 else '❌'}")
    print(f"  [2] Jours actifs ({active_days}) >= {min_days} : {'✅' if g2 else '❌'}")
    print(f"  [3] Precision/Accuracy vs Champion (seuils {min_precision_delta:+.1f}%/{min_accuracy_delta:+.1f}%) : {'✅' if g3 else '❌'}")
    print(f"  [4] Max Drawdown ({max_dd:.2f}%) <= {max_drawdown_pct:.2f}% : {'✅' if g4 else '❌'}")
    print(f"  [5] Profit Factor ({profit_factor:.2f}) >= {min_profit_factor:.2f} : {'✅' if g5 else '❌'}")
    print(f"  [6] PnL net ({net_pnl:.2f} USD) > 0 : {'✅' if g6 else '❌'}")
    print(f"  [7] Calibration MAE ({calibration_mae if calibration_mae is not None else 'n/a'}) <= {max_calibration_mae:.1f} : {'✅' if g7 else '❌'}")
    print(f"  [8] Drift status ({drift_status_value}) autorisé : {'✅' if g8 else '❌'}")

    guardrails = {
        'min_trades': g1, 'min_days': g2, 'better_perf': g3, 'drawdown': g4,
        'profit_factor': g5, 'net_pnl': g6, 'calibration': g7, 'drift': g8,
    }
    metrics_data = {
        'closed_trades_count': closed_trades_count,
        'champion_precision': champ_prec, 'challenger_precision': chall_prec,
        'champion_accuracy': champ_acc, 'challenger_accuracy': chall_acc,
        'profit_factor': profit_factor, 'net_pnl': net_pnl, 'max_drawdown_pct': max_dd,
        'guardrails': guardrails,
    }

    all_passed = all(guardrails.values())

    if force and not all_passed:
        failed = [name for name, passed in guardrails.items() if not passed]
        print(f"\n⚠️ --force actif : garde-fous ignorés ({', '.join(failed)})")
        all_passed = True

    if not all_passed:
        failed = [name for name, passed in guardrails.items() if not passed]
        reason = f"Garde-fous non satisfaits: {', '.join(failed)}"
        print(f"\n⛔ PROMOTION REFUSÉE : {reason}")
        print("   Astuce: relance avec --force, ou ajuste ML_PROMOTION_MIN_*_DELTA dans .env.local")
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
    args = parser.parse_args()

    ok = promote(model_dir=args.dir, db_file=args.db, check_only=args.check_only, force=args.force, trigger_type=args.trigger)
    sys.exit(0 if ok else 1)
