"""Module stratégies - Version unifiée simplifiée"""
from utils.confidence_calculator import ConfidenceCalculator
from utils.ema_analyzer import BinanceEMAAnalyzer
from utils.pullback_detector import PullbackDetector
import time
import os

class StrategiesMixin:
    """Mixin pour les stratégies de trading - Version simplifiée"""
    
    def realtime_intelligent(self, symbol, amount, price):
        """Version temps réel de la stratégie intelligente"""
        if not self.safety_manager.can_trade():
            return
        
        # Gérer le cycle Double Investment périodiquement
        current_time = time.time()
        if not hasattr(self, '_last_dual_check'):
            self._last_dual_check = 0
        
        # Vérifier Double Investment toutes les 5 minutes
        if current_time - self._last_dual_check > 300:  # 5 minutes
            self.manage_double_investment_cycle()
            self._last_dual_check = current_time
        
        # Utiliser la stratégie unifiée
        self.unified_strategy(symbol, amount, price)
    
    def realtime_scalping(self, symbol, amount, price):
        """Version temps réel du scalping - Redirigé vers intelligent"""
        self.realtime_intelligent(symbol, amount, price)
    
    def realtime_adaptive(self, symbol, amount, price):
        """Version temps réel adaptatif - Redirigé vers intelligent"""
        self.realtime_intelligent(symbol, amount, price)