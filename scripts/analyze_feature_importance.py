"""Analyse l'importance des features pour TOUS les modèles ML du champion.

Affiche, pour chaque modèle (entrée/P_win, sortie/P_exit, sizing, target/P_target):
  - le top des features par importance (avec leurs noms)
  - des agrégats utiles: poids par timeframe (1h vs 5m/15m rapides) et poids de la
    volatilité, pour suivre le rééquilibrage attendu.

Usage:
    python scripts/analyze_feature_importance.py
    python scripts/analyze_feature_importance.py --model data/aegis_challenger.joblib --top 15
"""
import argparse
import ast
import os
import sys

# Forcer UTF-8 sur stdout (la console Windows cp1252 ne gère pas certains caractères).
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    import joblib
except Exception:
    joblib = None

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ML_ENGINE_PATH = os.path.join(ROOT, 'core', 'ml_engine.py')


def _load_feature_name_lists():
    """Lit feature_names et exit_feature_names depuis ml_engine.py sans importer le module
    (évite les dépendances lourdes / effets de bord)."""
    src = open(ML_ENGINE_PATH, encoding='utf-8').read()
    tree = ast.parse(src)
    names = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Attribute) and t.attr in ('feature_names', 'exit_feature_names'):
                    try:
                        names[t.attr] = list(ast.literal_eval(node.value))
                    except Exception:
                        pass
    return names.get('feature_names', []), names.get('exit_feature_names', [])


def _timeframe_of(name):
    n = name.lower()
    if '_1h' in n:
        return '1h'
    if '_4h' in n:
        return '4h'
    if '_1d' in n or 'daily' in n:
        return '1d'
    if '_5m' in n:
        return '5m'
    if '_15m' in n:
        return '15m'
    return 'base/other'


def _print_model(title, importances, feat_names, top):
    if importances is None:
        print(f"\n{'='*66}\n{title}  (modele absent)\n{'='*66}")
        return
    print(f"\n{'='*66}\n{title}  ({len(importances)} features)\n{'='*66}")
    n = min(len(importances), len(feat_names))
    pairs = [(feat_names[i], float(importances[i])) for i in range(n)]
    # Si le modèle a plus de features que de noms (schéma décalé), nommer les extras.
    for i in range(n, len(importances)):
        pairs.append((f"feature_{i}", float(importances[i])))

    ranked = sorted(pairs, key=lambda x: x[1], reverse=True)
    print(f"  ── Top {top} features ──")
    for name, imp in ranked[:top]:
        bar = '#' * int(imp * 100 / max(0.001, ranked[0][1]) * 0.3)
        print(f"    {imp*100:5.1f}%  {name:32s} {bar}")

    # Agrégats par timeframe
    tf_totals = {}
    for name, imp in pairs:
        tf = _timeframe_of(name)
        tf_totals[tf] = tf_totals.get(tf, 0.0) + imp
    print("  ── Poids par timeframe ──")
    for tf, tot in sorted(tf_totals.items(), key=lambda x: x[1], reverse=True):
        print(f"    {tot*100:5.1f}%  {tf}")

    # Poids de la volatilité (atr/std) — pour suivre le P_exit
    vol_names = ('atr_percent', 'volatility_std')
    vol_total = sum(imp for name, imp in pairs if name in vol_names)
    if vol_total > 0:
        print(f"  ── Poids volatilité (atr+std): {vol_total*100:.1f}% ──")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default=os.path.join(ROOT, 'data', 'aegis_model.joblib'))
    parser.add_argument('--top', type=int, default=12)
    args = parser.parse_args()

    if joblib is None:
        print("[ERREUR] joblib indisponible.")
        return
    if not os.path.exists(args.model):
        print(f"[ERREUR] Modele introuvable: {args.model}")
        return

    data = joblib.load(args.model)
    feature_names, exit_feature_names = _load_feature_name_lists()

    meta = data.get('model_metadata') or {}
    print(f"Modèle: {args.model}")
    print(f"Entraîné le: {meta.get('trained_at')} | samples: {meta.get('train_samples')}")

    def imp_of(model):
        return list(model.feature_importances_) if (model is not None and hasattr(model, 'feature_importances_')) else None

    _print_model("ENTRÉE (P_win)", imp_of(data.get('model')), feature_names, args.top)
    _print_model("SORTIE (P_exit / P_continue)", imp_of(data.get('exit_model')), exit_feature_names, args.top)
    _print_model("SIZING", imp_of(data.get('sizing_model')), feature_names, args.top)
    _print_model("TARGET (P_target)", imp_of(data.get('target_model')), feature_names, args.top)


if __name__ == '__main__':
    main()
