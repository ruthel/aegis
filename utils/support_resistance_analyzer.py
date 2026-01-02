"""Analyseur Support/Résistance Avancé - Prédiction Niveaux de Retournement"""
import numpy as np
from collections import defaultdict

class SupportResistanceAnalyzer:
    def __init__(self):
        self.min_touches = 2  # Minimum de tests pour valider un niveau
        self.proximity_threshold = 0.005  # 0.5% de proximité
        
    def find_support_resistance_levels(self, klines, lookback_periods=100):
        """Trouve les niveaux de support et résistance significatifs"""
        if len(klines) < lookback_periods:
            lookback_periods = len(klines)
        
        recent_klines = klines[-lookback_periods:]
        highs = [k['high'] for k in recent_klines]
        lows = [k['low'] for k in recent_klines]
        volumes = [k['volume'] for k in recent_klines]
        
        # Détecter les pivots (sommets et creux)
        resistance_levels = self._find_pivot_highs(highs, volumes)
        support_levels = self._find_pivot_lows(lows, volumes)
        
        return {
            'resistance_levels': resistance_levels,
            'support_levels': support_levels,
            'strongest_resistance': max(resistance_levels, key=lambda x: x['strength']) if resistance_levels else None,
            'strongest_support': max(support_levels, key=lambda x: x['strength']) if support_levels else None
        }
    
    def _find_pivot_highs(self, highs, volumes):
        """Trouve les résistances (pivots hauts)"""
        levels = defaultdict(list)
        
        # Grouper les prix similaires
        for i, high in enumerate(highs):
            level_key = round(high / (high * self.proximity_threshold)) * (high * self.proximity_threshold)
            levels[level_key].append({
                'price': high,
                'index': i,
                'volume': volumes[i] if i < len(volumes) else 0
            })
        
        # Filtrer et scorer les niveaux
        resistance_levels = []
        for level_price, touches in levels.items():
            if len(touches) >= self.min_touches:
                avg_volume = sum(t['volume'] for t in touches) / len(touches)
                strength = len(touches) * (avg_volume / 1000000)  # Score basé sur tests + volume
                
                resistance_levels.append({
                    'price': level_price,
                    'touches': len(touches),
                    'avg_volume': avg_volume,
                    'strength': strength,
                    'type': 'resistance'
                })
        
        return sorted(resistance_levels, key=lambda x: x['strength'], reverse=True)
    
    def _find_pivot_lows(self, lows, volumes):
        """Trouve les supports (pivots bas)"""
        levels = defaultdict(list)
        
        for i, low in enumerate(lows):
            level_key = round(low / (low * self.proximity_threshold)) * (low * self.proximity_threshold)
            levels[level_key].append({
                'price': low,
                'index': i,
                'volume': volumes[i] if i < len(volumes) else 0
            })
        
        support_levels = []
        for level_price, touches in levels.items():
            if len(touches) >= self.min_touches:
                avg_volume = sum(t['volume'] for t in touches) / len(touches)
                strength = len(touches) * (avg_volume / 1000000)
                
                support_levels.append({
                    'price': level_price,
                    'touches': len(touches),
                    'avg_volume': avg_volume,
                    'strength': strength,
                    'type': 'support'
                })
        
        return sorted(support_levels, key=lambda x: x['strength'], reverse=True)
    
    def predict_reversal_probability(self, current_price, levels_data):
        """Prédit la probabilité de retournement au niveau actuel"""
        # MODE PRO : Ignorer toutes les protections
        import os
        if os.getenv('AGGRESSIVE_MODE', 'False') == 'True':
            return {
                'has_reversal_potential': False,
                'probability': 0,
                'direction': None,
                'target_level': None,
                'nearest_resistance': None,
                'nearest_support': None
            }
        
        resistance_levels = levels_data['resistance_levels']
        support_levels = levels_data['support_levels']
        
        # Vérifier proximité des niveaux
        near_resistance = self._find_nearest_level(current_price, resistance_levels, 'above')
        near_support = self._find_nearest_level(current_price, support_levels, 'below')
        
        reversal_probability = 0
        reversal_direction = None
        target_level = None
        
        # Si proche d'une résistance
        if near_resistance and self._is_near_level(current_price, near_resistance['price']):
            reversal_probability = min(near_resistance['strength'] * 10, 85)  # Max 85%
            reversal_direction = 'DOWN'
            target_level = near_resistance
        
        # Si proche d'un support
        elif near_support and self._is_near_level(current_price, near_support['price']):
            reversal_probability = min(near_support['strength'] * 10, 85)
            reversal_direction = 'UP'
            target_level = near_support
        
        return {
            'has_reversal_potential': reversal_probability > 50,
            'probability': reversal_probability,
            'direction': reversal_direction,
            'target_level': target_level,
            'nearest_resistance': near_resistance,
            'nearest_support': near_support
        }
    
    def _find_nearest_level(self, current_price, levels, direction):
        """Trouve le niveau le plus proche dans une direction"""
        if not levels:
            return None
        
        if direction == 'above':
            # Résistance au-dessus du prix actuel
            above_levels = [l for l in levels if l['price'] > current_price]
            return min(above_levels, key=lambda x: abs(x['price'] - current_price)) if above_levels else None
        else:
            # Support en-dessous du prix actuel
            below_levels = [l for l in levels if l['price'] < current_price]
            return min(below_levels, key=lambda x: abs(x['price'] - current_price)) if below_levels else None
    
    def _is_near_level(self, current_price, level_price):
        """Vérifie si le prix est proche d'un niveau"""
        distance_pct = abs(current_price - level_price) / current_price
        return distance_pct <= self.proximity_threshold * 2  # 1% de proximité
    
    def get_fibonacci_levels(self, klines, trend_direction='up'):
        """Calcule les niveaux de retracement de Fibonacci"""
        if len(klines) < 20:
            return []
        
        recent_klines = klines[-50:]  # 50 dernières bougies
        highs = [k['high'] for k in recent_klines]
        lows = [k['low'] for k in recent_klines]
        
        if trend_direction == 'up':
            swing_low = min(lows)
            swing_high = max(highs)
        else:
            swing_high = max(highs)
            swing_low = min(lows)
        
        # Niveaux de Fibonacci classiques
        fib_ratios = [0.236, 0.382, 0.5, 0.618, 0.786]
        fib_levels = []
        
        price_range = swing_high - swing_low
        
        for ratio in fib_ratios:
            if trend_direction == 'up':
                level = swing_high - (price_range * ratio)
            else:
                level = swing_low + (price_range * ratio)
            
            fib_levels.append({
                'price': level,
                'ratio': ratio,
                'type': 'fibonacci',
                'strength': 3 if ratio in [0.382, 0.618] else 2  # Niveaux dorés plus forts
            })
        
        return fib_levels