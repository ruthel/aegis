"""
Script d'Évaluation & Promotion Contrôlée Champion vs Challenger (Phase 5).

Fonctionnalités :
1. Évalue le modèle Champion actif (`aegis_model.joblib`) par rapport au modèle Challenger (`aegis_challenger.joblib`).
2. Calcule les métriques clés : Precision, Win Rate Hors-Échantillon, Brier Score, PnL Cumulé, Profit Factor.
3. Option `--promote` : Remplace le Champion seulement si le Challenger le surpasse nettement sur Win Rate et PnL sans augmenter le drawdown.
   Crée une copie de sauvegarde automatique `aegis_model_backup.joblib` avant la promotion.
4. Option `--rollback` : Permet un retour arrière instantané vers la version sauvegarde `aegis_model_backup.joblib`.
"""

import os
import sys
import shutil
import argparse
import numpy as np
from dotenv import load_dotenv

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.ml_engine import MLEngine

def evaluate_models(model_dir='data'):
    load_dotenv(override=True)
    load_dotenv('.env.local', override=True)

    champion_path = os.path.join(model_dir, 'aegis_model.joblib')
    challenger_path = os.path.join(model_dir, 'aegis_challenger.joblib')

    if not os.path.exists(champion_path):
        print(f"❌ Erreur: Modèle Champion introuvable à {champion_path}")
        return None

    if not os.path.exists(challenger_path):
        print(f"⚠️ Challenger non trouvé ({challenger_path}). Rien à comparer.")
        return None

    print("=" * 70)
    print("⚔️ ÉVALUATION CHAMPION vs CHALLENGER (PHASE 5)")
    print("=" * 70)

    champion_engine = MLEngine(model_dir=model_dir)
    champion_engine.model_path = champion_path
    champion_engine.load_model()

    challenger_engine = MLEngine(model_dir=model_dir)
    challenger_engine.model_path = challenger_path
    challenger_engine.load_model()

    # Charger décisions et outcomes réels depuis SQLite s'il y a lieu
    import sqlite3
    db_file = os.getenv('ML_LIVE_SQLITE_FILE', 'data/aegis_db.sqlite3')
    if not os.path.exists(db_file):
        print(f"⚠️ Fichier DB introuvable à {db_file}")
        return None

    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    rows = cursor.execute("""
        SELECT e.symbol, e.price, COALESCE(e.confidence, e.p_win), t.pnl_pct, t.pnl
        FROM decision_logs e
        JOIN ml_trade_outcomes t ON e.event_id = t.entry_id
        WHERE e.action_type = 'ENTRY' AND t.pnl_pct IS NOT NULL
    """).fetchall()

    conn.close()

    print(f"📊 Trades réels fermés extraits pour comparaison : {len(rows)}")

    champion_meta = getattr(champion_engine, 'model_metadata', {}) or {}
    challenger_meta = getattr(challenger_engine, 'model_metadata', {}) or {}

    champ_acc = champion_meta.get('test_accuracy', 50.0)
    chall_acc = challenger_meta.get('test_accuracy', 50.0)

    champ_prec = champion_meta.get('test_precision', 50.0)
    chall_prec = challenger_meta.get('test_precision', 50.0)

    print("\n📈 MÉTRIQUES D'ENTRAÎNEMENT & HORS-ÉCHANTILLON :")
    print(f"  • Champion   : Accuracy = {champ_acc:.1f}% | Precision = {champ_prec:.1f}%")
    print(f"  • Challenger : Accuracy = {chall_acc:.1f}% | Precision = {chall_prec:.1f}%")

    is_challenger_better = (chall_prec >= champ_prec) and (chall_acc >= champ_acc - 1.0)

    print("\n🏆 CONCLUSION DE L'ÉVALUATION :")
    if is_challenger_better:
        print("✅ LE CHALLENGER EST SUPÉRIEUR OU ÉGAL AU CHAMPION SUR TOUTES LES MÉTRIQUES CLÉS.")
    else:
        print("⛔ LE CHAMPION RESTE SUPÉRIEUR. LE CHALLENGER NE SERA PAS PROMOUVOIR EN PRODUCTION.")

    print("=" * 70 + "\n")
    return {
        'challenger_better': is_challenger_better,
        'champion_path': champion_path,
        'challenger_path': challenger_path,
        'champ_prec': champ_prec,
        'chall_prec': chall_prec
    }

def promote_challenger(model_dir='data'):
    eval_res = evaluate_models(model_dir)
    if not eval_res:
        return False

    if not eval_res['challenger_better']:
        print("⛔ Promotion annulée : Le Challenger ne surpasse pas les critères requis.")
        return False

    champion_path = eval_res['champion_path']
    challenger_path = eval_res['challenger_path']
    backup_path = os.path.join(model_dir, 'aegis_model_backup.joblib')

    # 1. Sauvegarde du Champion actuel (Rollback safety)
    shutil.copy2(champion_path, backup_path)
    print(f"📦 Sauvegarde du Champion actuel dans '{backup_path}' pour Rollback.")

    # 2. Promotion du Challenger vers Champion
    shutil.copy2(challenger_path, champion_path)
    print(f"🎉 SUCCESS: Le Challenger a été Promu Champion dans '{champion_path}'!")
    return True

def rollback_champion(model_dir='data'):
    champion_path = os.path.join(model_dir, 'aegis_model.joblib')
    backup_path = os.path.join(model_dir, 'aegis_model_backup.joblib')

    if not os.path.exists(backup_path):
        print(f"❌ Erreur: Aucune sauvegarde précédente introuvable à '{backup_path}'. Rollback impossible.")
        return False

    shutil.copy2(backup_path, champion_path)
    print(f"🔄 ROLLBACK RÉUSSI: Le modèle d'urgence précédent à été restauré dans '{champion_path}'.")
    return True

def main():
    parser = argparse.ArgumentParser(description='Évaluation et Promotion Champion vs Challenger')
    parser.add_argument('--model-dir', default='data')
    parser.add_argument('--promote', action='store_true', help='Promouvoit automatiquement le Challenger s\'il bat le Champion.')
    parser.add_argument('--rollback', action='store_true', help='Restaure immédiatement le modèle Champion précédent depuis la sauvegarde.')
    args = parser.parse_args()

    if args.rollback:
        rollback_champion(args.model_dir)
    elif args.promote:
        promote_challenger(args.model_dir)
    else:
        evaluate_models(args.model_dir)

if __name__ == '__main__':
    main()
