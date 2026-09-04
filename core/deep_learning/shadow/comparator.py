"""
Comparateur RF vs Deep Learning
===============================

Compare les performances du modèle DL avec le RandomForest existant
pour déterminer quand promouvoir le DL en production.
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
from datetime import datetime
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ComparisonResult:
    """Résultat d'une comparaison individuelle"""
    timestamp: str
    symbol: str
    rf_signal: str
    dl_signal: str
    rf_confidence: float
    dl_confidence: float
    actual_outcome: Optional[float] = None  # PnL réel si connu
    rf_correct: Optional[bool] = None
    dl_correct: Optional[bool] = None


class RFComparator:
    """
    Compare les prédictions DL vs RF et track les performances.
    
    Utilisé pour:
    - Évaluer si le DL surperforme le RF
    - Décider quand promouvoir le DL en production
    - Identifier les conditions où chaque modèle excelle
    """
    
    def __init__(
        self,
        min_comparisons: int = 500,
        outperformance_threshold: float = 0.05,
        min_winrate: float = 0.55
    ):
        """
        Args:
            min_comparisons: Minimum de comparaisons avant analyse
            outperformance_threshold: Surperformance requise pour promotion
            min_winrate: Win rate minimum du DL pour promotion
        """
        self.min_comparisons = min_comparisons
        self.outperformance_threshold = outperformance_threshold
        self.min_winrate = min_winrate
        
        # Stockage des comparaisons
        self.comparisons: List[ComparisonResult] = []
        
        # Statistiques agrégées
        self.stats = {
            'total_comparisons': 0,
            'agreements': 0,
            'conflicts': 0,
            'rf_only_correct': 0,
            'dl_only_correct': 0,
            'both_correct': 0,
            'both_wrong': 0,
            'pending_outcomes': 0
        }
        
        # Stats par symbole
        self.symbol_stats: Dict[str, Dict] = defaultdict(lambda: {
            'comparisons': 0,
            'rf_correct': 0,
            'dl_correct': 0,
            'agreements': 0
        })
        
        # Stats par condition de marché
        self.condition_stats: Dict[str, Dict] = defaultdict(lambda: {
            'comparisons': 0,
            'rf_winrate': 0.0,
            'dl_winrate': 0.0
        })
    
    def add_comparison(
        self,
        symbol: str,
        rf_prediction: Dict,
        dl_prediction: Dict,
        market_condition: Optional[str] = None
    ) -> ComparisonResult:
        """
        Ajoute une nouvelle comparaison.
        
        Args:
            symbol: Symbole de trading
            rf_prediction: Prédiction RF avec 'decision', 'confidence'
            dl_prediction: Prédiction DL avec 'signal', 'confidence', 'win_probability'
            market_condition: Condition de marché optionnelle
            
        Returns:
            ComparisonResult
        """
        result = ComparisonResult(
            timestamp=datetime.now().isoformat(),
            symbol=symbol,
            rf_signal=rf_prediction.get('decision', 'hold'),
            dl_signal=dl_prediction.get('signal', 'hold'),
            rf_confidence=rf_prediction.get('confidence', 0.5),
            dl_confidence=dl_prediction.get('confidence', 0.5)
        )
        
        self.comparisons.append(result)
        self.stats['total_comparisons'] += 1
        self.stats['pending_outcomes'] += 1
        
        # Vérifier accord/conflit
        rf_bullish = result.rf_signal in ['buy', 'strong_buy']
        dl_bullish = result.dl_signal in ['buy', 'strong_buy']
        rf_bearish = result.rf_signal in ['sell', 'strong_sell']
        dl_bearish = result.dl_signal in ['sell', 'strong_sell']
        
        if (rf_bullish and dl_bullish) or (rf_bearish and dl_bearish) or \
           (result.rf_signal == 'hold' and result.dl_signal == 'hold'):
            self.stats['agreements'] += 1
            self.symbol_stats[symbol]['agreements'] += 1
        elif (rf_bullish and dl_bearish) or (rf_bearish and dl_bullish):
            self.stats['conflicts'] += 1
        
        self.symbol_stats[symbol]['comparisons'] += 1
        
        if market_condition:
            self.condition_stats[market_condition]['comparisons'] += 1
        
        return result
    
    def record_outcome(
        self,
        comparison_index: int,
        actual_pnl: float,
        entry_price: float,
        exit_price: float
    ):
        """
        Enregistre le résultat réel d'un trade.
        
        Args:
            comparison_index: Index de la comparaison (ou -1 pour le dernier)
            actual_pnl: PnL réel en pourcentage
            entry_price: Prix d'entrée
            exit_price: Prix de sortie
        """
        if comparison_index == -1:
            comparison_index = len(self.comparisons) - 1
        
        if comparison_index >= len(self.comparisons):
            return
        
        comparison = self.comparisons[comparison_index]
        comparison.actual_outcome = actual_pnl
        
        # Déterminer si les prédictions étaient correctes
        was_profitable = actual_pnl > 0
        
        # RF correct si: buy signal + profitable, ou sell signal + non-profitable (pour short)
        # Simplifié: on considère que RF est correct si direction = résultat
        rf_predicted_up = comparison.rf_signal in ['buy', 'strong_buy']
        dl_predicted_up = comparison.dl_signal in ['buy', 'strong_buy']
        
        comparison.rf_correct = rf_predicted_up == was_profitable
        comparison.dl_correct = dl_predicted_up == was_profitable
        
        # Mettre à jour les stats
        self.stats['pending_outcomes'] -= 1
        
        if comparison.rf_correct and comparison.dl_correct:
            self.stats['both_correct'] += 1
        elif comparison.rf_correct and not comparison.dl_correct:
            self.stats['rf_only_correct'] += 1
        elif not comparison.rf_correct and comparison.dl_correct:
            self.stats['dl_only_correct'] += 1
        else:
            self.stats['both_wrong'] += 1
        
        # Stats par symbole
        symbol = comparison.symbol
        if comparison.rf_correct:
            self.symbol_stats[symbol]['rf_correct'] += 1
        if comparison.dl_correct:
            self.symbol_stats[symbol]['dl_correct'] += 1
    
    def record_outcome_by_timestamp(
        self,
        timestamp: str,
        actual_pnl: float
    ):
        """Enregistre un outcome en cherchant par timestamp"""
        for i, comp in enumerate(self.comparisons):
            if comp.timestamp == timestamp and comp.actual_outcome is None:
                self.record_outcome(i, actual_pnl, 0, 0)
                return
    
    def get_performance_metrics(self) -> Dict:
        """
        Calcule les métriques de performance comparatives.
        
        Returns:
            Dict avec métriques détaillées
        """
        # Filtrer les comparaisons avec outcomes
        completed = [c for c in self.comparisons if c.actual_outcome is not None]
        
        if not completed:
            return {
                'status': 'insufficient_data',
                'completed_comparisons': 0,
                'pending_comparisons': self.stats['pending_outcomes']
            }
        
        n_completed = len(completed)
        
        # Win rates
        rf_wins = sum(1 for c in completed if c.rf_correct)
        dl_wins = sum(1 for c in completed if c.dl_correct)
        
        rf_winrate = rf_wins / n_completed
        dl_winrate = dl_wins / n_completed
        
        # Cas d'accord et de conflit
        agreements = [c for c in completed if 
                     (c.rf_signal in ['buy', 'strong_buy']) == (c.dl_signal in ['buy', 'strong_buy'])]
        conflicts = [c for c in completed if 
                    (c.rf_signal in ['buy', 'strong_buy']) != (c.dl_signal in ['buy', 'strong_buy']) and
                    c.rf_signal != 'hold' and c.dl_signal != 'hold']
        
        # Performance dans les cas de conflit (très important!)
        conflict_rf_wins = sum(1 for c in conflicts if c.rf_correct) if conflicts else 0
        conflict_dl_wins = sum(1 for c in conflicts if c.dl_correct) if conflicts else 0
        
        metrics = {
            'status': 'active',
            'completed_comparisons': n_completed,
            'pending_comparisons': self.stats['pending_outcomes'],
            
            # Win rates globaux
            'rf_winrate': rf_winrate,
            'dl_winrate': dl_winrate,
            'winrate_difference': dl_winrate - rf_winrate,
            
            # Stats d'accord/conflit
            'agreement_rate': len(agreements) / n_completed if n_completed > 0 else 0,
            'conflict_rate': len(conflicts) / n_completed if n_completed > 0 else 0,
            
            # Performance dans les conflits
            'n_conflicts': len(conflicts),
            'conflict_rf_winrate': conflict_rf_wins / len(conflicts) if conflicts else 0,
            'conflict_dl_winrate': conflict_dl_wins / len(conflicts) if conflicts else 0,
            
            # Cas où un seul a raison
            'rf_only_correct_rate': self.stats['rf_only_correct'] / n_completed,
            'dl_only_correct_rate': self.stats['dl_only_correct'] / n_completed,
            'both_correct_rate': self.stats['both_correct'] / n_completed,
            'both_wrong_rate': self.stats['both_wrong'] / n_completed,
        }
        
        # Stats par symbole
        metrics['by_symbol'] = {}
        for symbol, stats in self.symbol_stats.items():
            if stats['comparisons'] > 0:
                metrics['by_symbol'][symbol] = {
                    'n_comparisons': stats['comparisons'],
                    'rf_winrate': stats['rf_correct'] / stats['comparisons'] if stats['comparisons'] > 0 else 0,
                    'dl_winrate': stats['dl_correct'] / stats['comparisons'] if stats['comparisons'] > 0 else 0,
                    'agreement_rate': stats['agreements'] / stats['comparisons']
                }
        
        return metrics
    
    def should_promote_dl(self) -> Tuple[bool, str]:
        """
        Détermine si le DL devrait être promu en production.
        
        Returns:
            Tuple (should_promote, reason)
        """
        metrics = self.get_performance_metrics()
        
        if metrics['status'] == 'insufficient_data':
            return False, f"Insufficient data: {metrics['completed_comparisons']} comparisons"
        
        n_completed = metrics['completed_comparisons']
        
        # Critère 1: Assez de comparaisons
        if n_completed < self.min_comparisons:
            return False, f"Not enough comparisons: {n_completed}/{self.min_comparisons}"
        
        # Critère 2: Win rate minimum
        dl_winrate = metrics['dl_winrate']
        if dl_winrate < self.min_winrate:
            return False, f"DL winrate too low: {dl_winrate:.2%} < {self.min_winrate:.2%}"
        
        # Critère 3: Surperformance vs RF
        winrate_diff = metrics['winrate_difference']
        if winrate_diff < self.outperformance_threshold:
            return False, f"DL not outperforming RF enough: {winrate_diff:.2%} < {self.outperformance_threshold:.2%}"
        
        # Critère 4: Bon dans les conflits
        if metrics['n_conflicts'] >= 20:
            conflict_advantage = metrics['conflict_dl_winrate'] - metrics['conflict_rf_winrate']
            if conflict_advantage < 0:
                return False, f"DL underperforms in conflicts: {conflict_advantage:.2%}"
        
        # Tous les critères passés
        return True, f"DL ready for promotion: winrate={dl_winrate:.2%}, advantage={winrate_diff:.2%}"
    
    def get_recommendation(self) -> Dict:
        """
        Génère une recommandation détaillée.
        """
        should_promote, reason = self.should_promote_dl()
        metrics = self.get_performance_metrics()
        
        return {
            'should_promote': should_promote,
            'reason': reason,
            'confidence': self._compute_recommendation_confidence(metrics),
            'metrics': metrics,
            'suggestions': self._generate_suggestions(metrics)
        }
    
    def _compute_recommendation_confidence(self, metrics: Dict) -> float:
        """Calcule la confiance dans la recommandation"""
        if metrics['status'] == 'insufficient_data':
            return 0.0
        
        n_completed = metrics['completed_comparisons']
        
        # Plus de données = plus de confiance
        data_confidence = min(n_completed / (self.min_comparisons * 2), 1.0)
        
        # Grande différence de performance = plus de confiance
        winrate_diff = abs(metrics['winrate_difference'])
        perf_confidence = min(winrate_diff / 0.1, 1.0)  # Max à 10% de différence
        
        return (data_confidence + perf_confidence) / 2
    
    def _generate_suggestions(self, metrics: Dict) -> List[str]:
        """Génère des suggestions basées sur les métriques"""
        suggestions = []
        
        if metrics['status'] == 'insufficient_data':
            suggestions.append("Continue collecting shadow data")
            return suggestions
        
        # Analyse du win rate
        if metrics['dl_winrate'] < 0.5:
            suggestions.append("DL model needs retraining - winrate below 50%")
        elif metrics['dl_winrate'] < 0.55:
            suggestions.append("Consider hyperparameter tuning for DL model")
        
        # Analyse des conflits
        if metrics['n_conflicts'] > 0:
            if metrics['conflict_dl_winrate'] < metrics['conflict_rf_winrate']:
                suggestions.append("Investigate why DL underperforms in conflict cases")
            elif metrics['conflict_dl_winrate'] > metrics['conflict_rf_winrate'] + 0.1:
                suggestions.append("DL shows promise in difficult cases - consider hybrid approach")
        
        # Analyse par symbole
        for symbol, stats in metrics.get('by_symbol', {}).items():
            if stats['dl_winrate'] < stats['rf_winrate'] - 0.1:
                suggestions.append(f"DL underperforms on {symbol} - consider symbol-specific training")
        
        return suggestions
    
    def save(self, path: Path):
        """Sauvegarde l'état du comparateur"""
        state = {
            'comparisons': [
                {
                    'timestamp': c.timestamp,
                    'symbol': c.symbol,
                    'rf_signal': c.rf_signal,
                    'dl_signal': c.dl_signal,
                    'rf_confidence': c.rf_confidence,
                    'dl_confidence': c.dl_confidence,
                    'actual_outcome': c.actual_outcome,
                    'rf_correct': c.rf_correct,
                    'dl_correct': c.dl_correct
                }
                for c in self.comparisons
            ],
            'stats': self.stats,
            'symbol_stats': dict(self.symbol_stats)
        }
        
        with open(path, 'w') as f:
            json.dump(state, f, indent=2)
        
        logger.info(f"Comparator state saved to {path}")
    
    def load(self, path: Path):
        """Charge l'état du comparateur"""
        with open(path, 'r') as f:
            state = json.load(f)
        
        self.comparisons = [
            ComparisonResult(**c) for c in state['comparisons']
        ]
        self.stats = state['stats']
        self.symbol_stats = defaultdict(
            lambda: {'comparisons': 0, 'rf_correct': 0, 'dl_correct': 0, 'agreements': 0},
            state['symbol_stats']
        )
        
        logger.info(f"Comparator state loaded from {path}")
