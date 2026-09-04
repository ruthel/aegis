"""
Analyseur de performances Shadow
================================

Analyse détaillée des performances du modèle DL en mode shadow.
Génère des rapports et visualisations.
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class ShadowAnalyzer:
    """
    Analyse les performances du modèle DL en mode shadow.
    """
    
    def __init__(self):
        self.predictions: List[Dict] = []
        self.outcomes: List[Dict] = []
        self.comparisons: List[Dict] = []
    
    def add_prediction(self, prediction: Dict):
        """Ajoute une prédiction à l'analyse"""
        self.predictions.append({
            **prediction,
            'recorded_at': datetime.now().isoformat()
        })
    
    def add_outcome(
        self,
        prediction_timestamp: str,
        actual_pnl: float,
        trade_duration: Optional[int] = None
    ):
        """Enregistre le résultat réel"""
        self.outcomes.append({
            'prediction_timestamp': prediction_timestamp,
            'actual_pnl': actual_pnl,
            'trade_duration': trade_duration,
            'recorded_at': datetime.now().isoformat()
        })
    
    def add_comparison(self, comparison: Dict):
        """Ajoute une comparaison RF vs DL"""
        self.comparisons.append(comparison)
    
    def compute_metrics(
        self,
        time_window: Optional[int] = None
    ) -> Dict:
        """
        Calcule les métriques complètes.
        
        Args:
            time_window: Fenêtre temporelle en heures (None = tout)
        """
        # Filtrer par fenêtre temporelle si spécifié
        if time_window:
            cutoff = datetime.now() - timedelta(hours=time_window)
            predictions = [
                p for p in self.predictions 
                if datetime.fromisoformat(p['recorded_at']) > cutoff
            ]
        else:
            predictions = self.predictions
        
        if not predictions:
            return {'status': 'no_data'}
        
        # Métriques de base
        win_probs = [p['win_probability'] for p in predictions]
        confidences = [p['confidence'] for p in predictions]
        signals = [p['signal'] for p in predictions]
        
        # Distribution des signaux
        signal_dist = defaultdict(int)
        for s in signals:
            signal_dist[s] += 1
        
        # Métriques de prédiction
        metrics = {
            'n_predictions': len(predictions),
            'avg_win_probability': np.mean(win_probs),
            'std_win_probability': np.std(win_probs),
            'avg_confidence': np.mean(confidences),
            'signal_distribution': dict(signal_dist),
            'bullish_ratio': (signal_dist['buy'] + signal_dist['strong_buy']) / len(predictions),
            'bearish_ratio': (signal_dist['sell'] + signal_dist['strong_sell']) / len(predictions),
            'hold_ratio': signal_dist['hold'] / len(predictions)
        }
        
        # Métriques par symbole
        by_symbol = defaultdict(list)
        for p in predictions:
            by_symbol[p['symbol']].append(p)
        
        metrics['by_symbol'] = {}
        for symbol, preds in by_symbol.items():
            metrics['by_symbol'][symbol] = {
                'n_predictions': len(preds),
                'avg_win_probability': np.mean([p['win_probability'] for p in preds]),
                'avg_confidence': np.mean([p['confidence'] for p in preds])
            }
        
        # Métriques de résultats si disponibles
        if self.outcomes:
            outcome_metrics = self._compute_outcome_metrics()
            metrics['outcome_metrics'] = outcome_metrics
        
        # Métriques de comparaison si disponibles
        if self.comparisons:
            comparison_metrics = self._compute_comparison_metrics()
            metrics['comparison_metrics'] = comparison_metrics
        
        return metrics
    
    def _compute_outcome_metrics(self) -> Dict:
        """Calcule les métriques basées sur les résultats réels"""
        if not self.outcomes:
            return {}
        
        # Mapper les outcomes aux prédictions
        outcome_map = {o['prediction_timestamp']: o for o in self.outcomes}
        
        matched = []
        for pred in self.predictions:
            timestamp = pred.get('timestamp')
            if timestamp in outcome_map:
                matched.append({
                    'prediction': pred,
                    'outcome': outcome_map[timestamp]
                })
        
        if not matched:
            return {'matched_outcomes': 0}
        
        # Calculer les métriques
        pnls = [m['outcome']['actual_pnl'] for m in matched]
        
        # Win rate par seuil de confiance
        winrate_by_threshold = {}
        for threshold in [0.5, 0.6, 0.7, 0.8]:
            high_conf = [m for m in matched if m['prediction']['win_probability'] >= threshold]
            if high_conf:
                wins = sum(1 for m in high_conf if m['outcome']['actual_pnl'] > 0)
                winrate_by_threshold[f't_{threshold}'] = wins / len(high_conf)
        
        # Calibration: est-ce que P(win) prédit correspond à la réalité?
        calibration = self._compute_calibration(matched)
        
        return {
            'matched_outcomes': len(matched),
            'total_pnl': sum(pnls),
            'avg_pnl': np.mean(pnls),
            'std_pnl': np.std(pnls),
            'win_rate': sum(1 for p in pnls if p > 0) / len(pnls),
            'profit_factor': self._compute_profit_factor(pnls),
            'winrate_by_threshold': winrate_by_threshold,
            'calibration': calibration
        }
    
    def _compute_calibration(self, matched: List[Dict]) -> Dict:
        """Vérifie si les probabilités prédites sont calibrées"""
        bins = [(0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)]
        calibration = {}
        
        for low, high in bins:
            in_bin = [m for m in matched 
                      if low <= m['prediction']['win_probability'] < high]
            
            if in_bin:
                avg_predicted = np.mean([m['prediction']['win_probability'] for m in in_bin])
                actual_winrate = sum(1 for m in in_bin if m['outcome']['actual_pnl'] > 0) / len(in_bin)
                
                calibration[f'{low:.1f}-{high:.1f}'] = {
                    'n_samples': len(in_bin),
                    'avg_predicted': avg_predicted,
                    'actual_winrate': actual_winrate,
                    'calibration_error': abs(avg_predicted - actual_winrate)
                }
        
        # Expected Calibration Error
        total_samples = sum(c['n_samples'] for c in calibration.values())
        if total_samples > 0:
            ece = sum(
                c['n_samples'] * c['calibration_error'] / total_samples
                for c in calibration.values()
            )
            calibration['ece'] = ece
        
        return calibration
    
    def _compute_profit_factor(self, pnls: List[float]) -> float:
        """Calcule le profit factor"""
        gains = sum(p for p in pnls if p > 0)
        losses = abs(sum(p for p in pnls if p < 0))
        
        if losses == 0:
            return float('inf') if gains > 0 else 0
        
        return gains / losses
    
    def _compute_comparison_metrics(self) -> Dict:
        """Métriques de comparaison RF vs DL"""
        if not self.comparisons:
            return {}
        
        # Taux d'accord
        agreements = sum(1 for c in self.comparisons if c.get('signals_agree', False))
        conflicts = sum(1 for c in self.comparisons if c.get('signals_conflict', False))
        
        return {
            'n_comparisons': len(self.comparisons),
            'agreement_rate': agreements / len(self.comparisons),
            'conflict_rate': conflicts / len(self.comparisons)
        }
    
    def generate_report(self, output_path: Optional[Path] = None) -> str:
        """
        Génère un rapport textuel des performances.
        """
        metrics = self.compute_metrics()
        
        lines = [
            "=" * 60,
            "AEGIS Deep Learning Shadow Report",
            f"Generated: {datetime.now().isoformat()}",
            "=" * 60,
            "",
            "### PREDICTION SUMMARY ###",
            f"Total predictions: {metrics.get('n_predictions', 0)}",
            f"Avg win probability: {metrics.get('avg_win_probability', 0):.2%}",
            f"Avg confidence: {metrics.get('avg_confidence', 0):.2%}",
            "",
            "Signal distribution:"
        ]
        
        for signal, count in metrics.get('signal_distribution', {}).items():
            lines.append(f"  - {signal}: {count}")
        
        lines.extend([
            "",
            f"Bullish ratio: {metrics.get('bullish_ratio', 0):.2%}",
            f"Bearish ratio: {metrics.get('bearish_ratio', 0):.2%}",
            f"Hold ratio: {metrics.get('hold_ratio', 0):.2%}",
            ""
        ])
        
        # Performance par symbole
        lines.append("### PERFORMANCE BY SYMBOL ###")
        for symbol, stats in metrics.get('by_symbol', {}).items():
            lines.append(f"\n{symbol}:")
            lines.append(f"  Predictions: {stats['n_predictions']}")
            lines.append(f"  Avg win prob: {stats['avg_win_probability']:.2%}")
            lines.append(f"  Avg confidence: {stats['avg_confidence']:.2%}")
        
        # Résultats réels
        if 'outcome_metrics' in metrics:
            om = metrics['outcome_metrics']
            lines.extend([
                "",
                "### ACTUAL OUTCOMES ###",
                f"Matched outcomes: {om.get('matched_outcomes', 0)}",
                f"Win rate: {om.get('win_rate', 0):.2%}",
                f"Profit factor: {om.get('profit_factor', 0):.2f}",
                f"Avg PnL: {om.get('avg_pnl', 0):.4%}",
                f"Total PnL: {om.get('total_pnl', 0):.4%}",
                "",
                "Win rate by confidence threshold:"
            ])
            
            for thresh, wr in om.get('winrate_by_threshold', {}).items():
                lines.append(f"  - {thresh}: {wr:.2%}")
            
            # Calibration
            if 'calibration' in om:
                lines.extend([
                    "",
                    "Calibration (predicted vs actual win rate):"
                ])
                for bin_name, cal in om['calibration'].items():
                    if bin_name != 'ece' and isinstance(cal, dict):
                        lines.append(
                            f"  {bin_name}: predicted={cal['avg_predicted']:.2%}, "
                            f"actual={cal['actual_winrate']:.2%}, "
                            f"error={cal['calibration_error']:.2%}"
                        )
                
                if 'ece' in om['calibration']:
                    lines.append(f"\nExpected Calibration Error: {om['calibration']['ece']:.4f}")
        
        # Comparaison RF
        if 'comparison_metrics' in metrics:
            cm = metrics['comparison_metrics']
            lines.extend([
                "",
                "### RF vs DL COMPARISON ###",
                f"Total comparisons: {cm.get('n_comparisons', 0)}",
                f"Agreement rate: {cm.get('agreement_rate', 0):.2%}",
                f"Conflict rate: {cm.get('conflict_rate', 0):.2%}"
            ])
        
        lines.append("")
        lines.append("=" * 60)
        
        report = "\n".join(lines)
        
        if output_path:
            with open(output_path, 'w') as f:
                f.write(report)
            logger.info(f"Report saved to {output_path}")
        
        return report
    
    def export_data(self, output_dir: Path):
        """Exporte toutes les données pour analyse externe"""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Prédictions
        with open(output_dir / 'predictions.json', 'w') as f:
            json.dump(self.predictions, f, indent=2)
        
        # Outcomes
        with open(output_dir / 'outcomes.json', 'w') as f:
            json.dump(self.outcomes, f, indent=2)
        
        # Comparisons
        with open(output_dir / 'comparisons.json', 'w') as f:
            json.dump(self.comparisons, f, indent=2)
        
        # Métriques
        with open(output_dir / 'metrics.json', 'w') as f:
            json.dump(self.compute_metrics(), f, indent=2, default=str)
        
        logger.info(f"Data exported to {output_dir}")
    
    def load_data(self, input_dir: Path):
        """Charge les données depuis des fichiers"""
        input_dir = Path(input_dir)
        
        if (input_dir / 'predictions.json').exists():
            with open(input_dir / 'predictions.json', 'r') as f:
                self.predictions = json.load(f)
        
        if (input_dir / 'outcomes.json').exists():
            with open(input_dir / 'outcomes.json', 'r') as f:
                self.outcomes = json.load(f)
        
        if (input_dir / 'comparisons.json').exists():
            with open(input_dir / 'comparisons.json', 'r') as f:
                self.comparisons = json.load(f)
        
        logger.info(f"Data loaded from {input_dir}")
