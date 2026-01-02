"""
Manipulation Detector (Pump & Dump)
Détecte les manipulations de marché via analyse volume/prix
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
import logging
from collections import deque
import time

class ManipulationDetector:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.price_history = {}  # symbol -> deque of (timestamp, price, volume)
        self.manipulation_alerts = {}  # symbol -> timestamp
        self.history_size = 100
        
    def add_data_point(self, symbol: str, price: float, volume: float):
        """Ajoute un point de données pour analyse"""
        if symbol not in self.price_history:
            self.price_history[symbol] = deque(maxlen=self.history_size)
            
        timestamp = time.time()
        self.price_history[symbol].append((timestamp, price, volume))
    
    def detect_pump_and_dump(self, symbol: str) -> Tuple[bool, str, float]:
        """
        Détecte pump & dump
        Returns: (is_manipulation, type, risk_score)
        """
        if symbol not in self.price_history or len(self.price_history[symbol]) < 20:
            return False, "", 0.0
            
        data = list(self.price_history[symbol])
        prices = np.array([d[1] for d in data[-20:]])  # 20 derniers points
        volumes = np.array([d[2] for d in data[-20:]])
        timestamps = np.array([d[0] for d in data[-20:]])
        
        # Calculs de base
        price_changes = np.diff(prices) / prices[:-1] * 100
        volume_avg = np.mean(volumes[:-5])  # Moyenne volume normale
        recent_volume = np.mean(volumes[-5:])  # Volume récent
        
        # 1. Détection PUMP (hausse rapide + volume anormal)
        recent_pump = np.sum(price_changes[-5:])  # 5 derniers changements
        volume_spike = recent_volume / volume_avg if volume_avg > 0 else 1
        
        if recent_pump > 15 and volume_spike > 3:  # +15% + volume x3
            risk_score = min(100, recent_pump * 2 + volume_spike * 10)
            return True, "PUMP", risk_score
            
        # 2. Détection DUMP (chute après pump)
        if recent_pump < -10 and volume_spike > 2:  # -10% + volume x2
            # Vérifier s'il y a eu un pump récent
            earlier_pump = np.sum(price_changes[-15:-5])  # 10 points avant
            if earlier_pump > 10:
                risk_score = min(100, abs(recent_pump) * 3)
                return True, "DUMP", risk_score
                
        # 3. Détection pattern suspect (volatilité extrême)
        volatility = np.std(price_changes[-10:])
        if volatility > 8 and volume_spike > 2.5:  # Volatilité >8% + volume
            risk_score = min(100, volatility * 5 + volume_spike * 5)
            return True, "VOLATILE", risk_score
            
        return False, "", 0.0
    
    def should_avoid_trading(self, symbol: str) -> Tuple[bool, str]:
        """Détermine s'il faut éviter de trader ce symbole"""
        is_manipulation, manip_type, risk_score = self.detect_pump_and_dump(symbol)
        
        if not is_manipulation:
            return False, ""
            
        # Éviter trading si manipulation détectée
        if manip_type == "PUMP" and risk_score > 60:
            return True, f"PUMP détecté (risque {risk_score:.0f}%)"
        elif manip_type == "DUMP" and risk_score > 40:
            return True, f"DUMP en cours (risque {risk_score:.0f}%)"
        elif manip_type == "VOLATILE" and risk_score > 70:
            return True, f"Manipulation suspecte (risque {risk_score:.0f}%)"
            
        return False, ""
    
    def get_manipulation_status(self, symbol: str) -> str:
        """Retourne le statut de manipulation pour affichage"""
        is_manipulation, manip_type, risk_score = self.detect_pump_and_dump(symbol)
        
        if not is_manipulation:
            return ""
            
        if manip_type == "PUMP":
            return f"🚨 PUMP {risk_score:.0f}%"
        elif manip_type == "DUMP":
            return f"📉 DUMP {risk_score:.0f}%"
        elif manip_type == "VOLATILE":
            return f"⚠️ SUSPECT {risk_score:.0f}%"
            
        return ""
    
    def clear_old_alerts(self):
        """Nettoie les anciennes alertes (>1h)"""
        current_time = time.time()
        expired = [symbol for symbol, timestamp in self.manipulation_alerts.items() 
                  if current_time - timestamp > 3600]
        for symbol in expired:
            del self.manipulation_alerts[symbol]