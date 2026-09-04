#!/usr/bin/env python3
"""
Analyse et visualisation des résultats d'entraînement Deep Learning
====================================================================

Usage:
    python scripts/analyze_dl_training.py                    # Dernier training
    python scripts/analyze_dl_training.py --session 24930806  # Session spécifique
    python scripts/analyze_dl_training.py --compare          # Comparer tous
    python scripts/analyze_dl_training.py --plot             # Graphiques
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import logging

# Ajouter le répertoire parent au path
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def get_all_sessions() -> List[Dict]:
    """Récupère toutes les sessions de training."""
    logs_dir = Path("data/deep_learning/logs")
    sessions = []
    
    for metric_file in logs_dir.glob("test_metrics_*.json"):
        session_id = metric_file.stem.replace("test_metrics_", "")
        
        with open(metric_file, 'r') as f:
            metrics = json.load(f)
        
        # Récupérer les infos du checkpoint
        checkpoint_dir = Path(f"data/deep_learning/checkpoints/{session_id}")
        model_file = checkpoint_dir / "best_model.pt" if checkpoint_dir.exists() else None
        
        sessions.append({
            'session_id': session_id,
            'metrics': metrics,
            'timestamp': metric_file.stat().st_mtime,
            'model_exists': model_file.exists() if model_file else False,
            'model_size_mb': model_file.stat().st_size / 1024 / 1024 if model_file and model_file.exists() else 0
        })
    
    # Trier par timestamp (plus récent en premier)
    sessions.sort(key=lambda x: x['timestamp'], reverse=True)
    return sessions


def display_session_metrics(session: Dict, detailed: bool = False):
    """Affiche les métriques d'une session."""
    metrics = session['metrics']
    session_id = session['session_id']
    timestamp = datetime.fromtimestamp(session['timestamp'])
    
    print("\n" + "=" * 70)
    print(f"SESSION: {session_id}")
    print(f"Date: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Modèle: {'✓ Disponible' if session['model_exists'] else '✗ Non trouvé'}")
    if session['model_size_mb'] > 0:
        print(f"Taille: {session['model_size_mb']:.1f} MB")
    print("=" * 70)
    
    # === MÉTRIQUES PRINCIPALES ===
    print("\n📊 MÉTRIQUES DE CLASSIFICATION")
    print("-" * 40)
    print(f"  AUC-ROC:           {metrics.get('auc_roc', 0):.4f}")
    print(f"  Accuracy (t=0.5):  {metrics.get('accuracy_t0.5', 0):.2%}")
    print(f"  Precision:         {metrics.get('precision', 0):.4f}")
    print(f"  Recall:            {metrics.get('recall', 0):.4f}")
    print(f"  F1 Score:          {metrics.get('f1', 0):.4f}")
    print(f"  Brier Score:       {metrics.get('brier_score', 0):.4f}")
    print(f"  Calibration Error: {metrics.get('calibration_error', 0):.4f}")
    
    # === SIMULATION TRADING ===
    print("\n💰 SIMULATION TRADING")
    print("-" * 40)
    
    thresholds = ['0.5', '0.6', '0.7', '0.8']
    print(f"  {'Seuil':<8} {'WinRate':<10} {'PF':<8} {'EV':<10} {'Trades':<8} {'Sharpe':<8}")
    print(f"  {'-'*6:<8} {'-'*8:<10} {'-'*6:<8} {'-'*8:<10} {'-'*6:<8} {'-'*6:<8}")
    
    for t in thresholds:
        wr = metrics.get(f'sim_win_rate_t{t}', metrics.get(f'win_rate_t{t}', 0))
        pf = metrics.get(f'sim_profit_factor_t{t}', 0)
        ev = metrics.get(f'sim_expected_value_t{t}', 0)
        trades = metrics.get(f'sim_n_trades_t{t}', metrics.get(f'n_trades_t{t}', 0))
        sharpe = metrics.get(f'sim_sharpe_t{t}', 0)
        
        if wr > 0 or trades != 0:
            print(f"  t={t:<5} {wr:>8.1%}   {pf:>6.2f}   {ev:>8.4f}   {str(trades):>6}   {sharpe:>6.2f}")
    
    # === HEADS AUXILIAIRES ===
    if detailed:
        print("\n🎯 HEADS AUXILIAIRES")
        print("-" * 40)
        
        if 'continue_mae' in metrics:
            print(f"  Continue Probability:")
            print(f"    MAE: {float(metrics.get('continue_mae', 0)):.4f}")
            print(f"    MSE: {float(metrics.get('continue_mse', 0)):.4f}")
        
        if 'sizing_mae' in metrics:
            print(f"  Optimal Sizing:")
            print(f"    MAE: {float(metrics.get('sizing_mae', 0)):.4f}")
            print(f"    MSE: {float(metrics.get('sizing_mse', 0)):.4f}")
            print(f"    Correlation: {metrics.get('sizing_correlation', 0):.4f}")
    
    # === INTERPRÉTATION ===
    print("\n📋 INTERPRÉTATION")
    print("-" * 40)
    
    auc = metrics.get('auc_roc', 0)
    pf = metrics.get('sim_profit_factor_t0.5', 0)
    wr = metrics.get('sim_win_rate_t0.5', 0)
    
    # Score global
    if auc >= 0.7 and pf >= 1.5 and wr >= 0.55:
        print("  🟢 EXCELLENT - Modèle prêt pour le shadow mode")
    elif auc >= 0.6 and pf >= 1.2 and wr >= 0.50:
        print("  🟡 CORRECT - Modèle utilisable, amélioration possible")
    elif auc >= 0.5:
        print("  🟠 FAIBLE - Modèle à améliorer (plus d'epochs/données)")
    else:
        print("  🔴 MAUVAIS - Modèle non utilisable")
    
    # Conseils
    if auc < 0.55:
        print("  ⚠️  AUC proche de 0.5 = proche du hasard")
    if metrics.get('calibration_error', 0) > 0.2:
        print("  ⚠️  Calibration error élevée = probabilités mal calibrées")
    if metrics.get('brier_score', 0) > 0.3:
        print("  ⚠️  Brier score élevé = prédictions peu fiables")


def compare_sessions(sessions: List[Dict]):
    """Compare plusieurs sessions de training."""
    if len(sessions) < 2:
        print("Pas assez de sessions pour comparer (minimum 2)")
        return
    
    print("\n" + "=" * 90)
    print("COMPARAISON DES SESSIONS")
    print("=" * 90)
    
    # Header
    header = f"{'Session':<12} {'Date':<12} {'AUC':<8} {'Acc':<8} {'WR':<8} {'PF':<8} {'F1':<8} {'Trades':<8}"
    print(header)
    print("-" * 90)
    
    best_auc = 0
    best_session = None
    
    for s in sessions[:10]:  # Top 10
        m = s['metrics']
        ts = datetime.fromtimestamp(s['timestamp'])
        
        auc = m.get('auc_roc', 0)
        acc = m.get('accuracy_t0.5', 0)
        wr = m.get('sim_win_rate_t0.5', m.get('win_rate_t0.5', 0))
        pf = m.get('sim_profit_factor_t0.5', 0)
        f1 = m.get('f1', 0)
        trades = m.get('sim_n_trades_t0.5', m.get('n_trades_t0.5', 0))
        
        if auc > best_auc:
            best_auc = auc
            best_session = s['session_id']
        
        marker = "⭐" if s['session_id'] == best_session else "  "
        print(f"{marker}{s['session_id']:<10} {ts.strftime('%m/%d %H:%M'):<12} "
              f"{auc:<8.4f} {acc:<8.2%} {wr:<8.2%} {pf:<8.2f} {f1:<8.4f} {str(trades):<8}")
    
    print("-" * 90)
    print(f"⭐ Meilleur modèle: {best_session} (AUC: {best_auc:.4f})")


def plot_training_history(session_id: Optional[str] = None):
    """Génère des graphiques de l'historique d'entraînement."""
    try:
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        print("matplotlib non installé. Installez avec: pip install matplotlib")
        return
    
    # Lire le log de training
    log_file = Path("data/deep_learning/training.log")
    if not log_file.exists():
        print("Fichier training.log non trouvé")
        return
    
    # Parser les logs pour extraire les métriques par epoch
    epochs = []
    train_losses = []
    val_losses = []
    val_winrates = []
    
    current_session = None
    target_session = session_id
    
    with open(log_file, 'r') as f:
        for line in f:
            if "Starting training session" in line:
                current_session = line.split(": ")[-1].strip()
                if target_session and current_session != target_session:
                    current_session = None
            
            if current_session and "Epoch" in line and "Train Loss" in line:
                try:
                    # Parse: Epoch 1/50 - Train Loss: 1.0044 - Val Loss: 0.4819 - Val WinRate: 0.9588
                    parts = line.split(" - ")
                    epoch_part = [p for p in parts if "Epoch" in p][0]
                    epoch = int(epoch_part.split("/")[0].split()[-1])
                    
                    train_loss = float([p for p in parts if "Train Loss" in p][0].split(": ")[-1])
                    val_loss = float([p for p in parts if "Val Loss" in p][0].split(": ")[-1])
                    val_wr = float([p for p in parts if "Val WinRate" in p][0].split(": ")[-1])
                    
                    epochs.append(epoch)
                    train_losses.append(train_loss)
                    val_losses.append(val_loss)
                    val_winrates.append(val_wr)
                except:
                    pass
    
    if not epochs:
        print("Pas de données d'entraînement trouvées dans les logs")
        return
    
    # Créer les graphiques
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    fig.suptitle(f'Training History - Session: {session_id or "Latest"}', fontsize=14)
    
    # Loss curves
    ax1 = axes[0, 0]
    ax1.plot(epochs, train_losses, 'b-', label='Train Loss', linewidth=2)
    ax1.plot(epochs, val_losses, 'r-', label='Val Loss', linewidth=2)
    ax1.set_xlabel('Epoch')
    ax1.set_ylabel('Loss')
    ax1.set_title('Training & Validation Loss')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Win Rate
    ax2 = axes[0, 1]
    ax2.plot(epochs, val_winrates, 'g-', linewidth=2)
    ax2.axhline(y=0.5, color='r', linestyle='--', alpha=0.5, label='Random (50%)')
    ax2.axhline(y=0.55, color='orange', linestyle='--', alpha=0.5, label='Target (55%)')
    ax2.set_xlabel('Epoch')
    ax2.set_ylabel('Win Rate')
    ax2.set_title('Validation Win Rate')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    ax2.set_ylim([0.4, 1.0])
    
    # Loss ratio (overfitting indicator)
    ax3 = axes[1, 0]
    loss_ratio = [v/t if t > 0 else 0 for t, v in zip(train_losses, val_losses)]
    ax3.plot(epochs, loss_ratio, 'm-', linewidth=2)
    ax3.axhline(y=1.0, color='g', linestyle='--', alpha=0.5, label='Ideal (1.0)')
    ax3.set_xlabel('Epoch')
    ax3.set_ylabel('Val/Train Loss Ratio')
    ax3.set_title('Overfitting Indicator')
    ax3.legend()
    ax3.grid(True, alpha=0.3)
    
    # Learning progress
    ax4 = axes[1, 1]
    improvement = [0] + [val_losses[i-1] - val_losses[i] for i in range(1, len(val_losses))]
    colors = ['g' if x > 0 else 'r' for x in improvement]
    ax4.bar(epochs, improvement, color=colors, alpha=0.7)
    ax4.axhline(y=0, color='k', linestyle='-', alpha=0.3)
    ax4.set_xlabel('Epoch')
    ax4.set_ylabel('Loss Improvement')
    ax4.set_title('Learning Progress (per epoch)')
    ax4.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    # Sauvegarder
    output_file = Path(f"data/deep_learning/logs/training_plot_{session_id or 'latest'}.png")
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"\n📈 Graphique sauvegardé: {output_file}")
    
    # Afficher si possible
    try:
        plt.show()
    except:
        pass


def load_and_evaluate_model(session_id: str):
    """Charge un modèle et affiche ses détails."""
    import torch
    
    model_path = Path(f"data/deep_learning/checkpoints/{session_id}/best_model.pt")
    if not model_path.exists():
        model_path = Path(f"data/deep_learning/models/model_{session_id}.pt")
    
    if not model_path.exists():
        print(f"Modèle non trouvé pour session {session_id}")
        return
    
    print(f"\n🔍 ANALYSE DU MODÈLE: {session_id}")
    print("=" * 50)
    
    # PyTorch 2.6+ requires weights_only=False for complex checkpoints
    checkpoint = torch.load(model_path, map_location='cpu', weights_only=False)
    
    if isinstance(checkpoint, dict):
        if 'model_state_dict' in checkpoint:
            state_dict = checkpoint['model_state_dict']
            print(f"  Type: Checkpoint complet")
            print(f"  Epoch: {checkpoint.get('epoch', 'N/A')}")
            if 'best_val_loss' in checkpoint:
                print(f"  Best Val Loss: {checkpoint.get('best_val_loss'):.4f}")
        else:
            state_dict = checkpoint
            print(f"  Type: State dict seul")
    else:
        print("  Format de checkpoint non reconnu")
        return
    
    # Analyser l'architecture
    total_params = 0
    layer_info = {}
    
    for name, param in state_dict.items():
        layer_type = name.split('.')[0]
        param_count = param.numel()
        total_params += param_count
        
        if layer_type not in layer_info:
            layer_info[layer_type] = 0
        layer_info[layer_type] += param_count
    
    print(f"\n  📐 ARCHITECTURE")
    print(f"  Total paramètres: {total_params:,}")
    print(f"  Taille mémoire: {total_params * 4 / 1024 / 1024:.2f} MB (float32)")
    
    print(f"\n  📦 COUCHES")
    for layer, count in sorted(layer_info.items(), key=lambda x: -x[1]):
        pct = count / total_params * 100
        print(f"    {layer:<30} {count:>12,} ({pct:>5.1f}%)")


def main():
    parser = argparse.ArgumentParser(description='Analyse des résultats DL')
    parser.add_argument('--session', '-s', type=str, help='ID de session spécifique')
    parser.add_argument('--compare', '-c', action='store_true', help='Comparer toutes les sessions')
    parser.add_argument('--plot', '-p', action='store_true', help='Générer des graphiques')
    parser.add_argument('--detailed', '-d', action='store_true', help='Affichage détaillé')
    parser.add_argument('--model', '-m', action='store_true', help='Analyser le modèle')
    args = parser.parse_args()
    
    sessions = get_all_sessions()
    
    if not sessions:
        print("Aucune session de training trouvée dans data/deep_learning/logs/")
        return
    
    print(f"\n🤖 ANALYSE DEEP LEARNING AEGIS")
    print(f"   {len(sessions)} session(s) trouvée(s)")
    
    if args.compare:
        compare_sessions(sessions)
    
    if args.session:
        # Session spécifique
        session = next((s for s in sessions if s['session_id'] == args.session), None)
        if session:
            display_session_metrics(session, detailed=args.detailed)
            if args.model:
                load_and_evaluate_model(args.session)
        else:
            print(f"Session {args.session} non trouvée")
    else:
        # Dernière session
        display_session_metrics(sessions[0], detailed=args.detailed)
        if args.model:
            load_and_evaluate_model(sessions[0]['session_id'])
    
    if args.plot:
        plot_training_history(args.session or sessions[0]['session_id'])


if __name__ == "__main__":
    main()
