"""
Pattern Recognition System
Détecte Head & Shoulders, Double Top/Bottom, Triangles
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from scipy.signal import find_peaks
import logging

class PatternRecognition:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.min_pattern_length = 20
        
    def detect_patterns(self, klines: List[Dict]) -> Dict:
        """Détecte tous les patterns dans les klines"""
        if len(klines) < self.min_pattern_length:
            return {'patterns': [], 'bearish_detected': False, 'bullish_patterns': [], 'strongest_pattern': None}
        
        closes = np.array([k['close'] for k in klines])
        highs = np.array([k['high'] for k in klines])
        lows = np.array([k['low'] for k in klines])
        volumes = np.array([k['volume'] for k in klines])
        
        patterns = []
        
        # Patterns de retournement
        hs_pattern = self._detect_head_shoulders(highs, closes)
        if hs_pattern: patterns.append(hs_pattern)
        
        dt_pattern = self._detect_double_top_bottom(highs, lows, closes)
        if dt_pattern: patterns.append(dt_pattern)
        
        # Patterns de continuation
        triangle_pattern = self._detect_triangles(highs, lows, closes)
        if triangle_pattern: patterns.append(triangle_pattern)
        
        flag_pattern = self._detect_flags_pennants(highs, lows, closes, volumes)
        if flag_pattern: patterns.append(flag_pattern)
        
        # Patterns chandeliers
        candlestick_pattern = self._detect_candlestick_patterns(klines)
        if candlestick_pattern: patterns.append(candlestick_pattern)
        
        # Cup & Handle
        cup_pattern = self._detect_cup_handle(highs, lows, closes)
        if cup_pattern: patterns.append(cup_pattern)
        
        # Séparer patterns haussiers/baissiers
        bullish_patterns = [p for p in patterns if p.get('bullish', False) and p['confidence'] > 65]
        bearish_patterns = [p for p in patterns if p.get('bullish') == False and p['confidence'] > 70]
        
        return {
            'patterns': patterns,
            'bullish_patterns': bullish_patterns,
            'bearish_detected': len(bearish_patterns) > 0,
            'strongest_pattern': max(patterns, key=lambda x: x['confidence']) if patterns else None
        }
    
    def _detect_head_shoulders(self, highs: np.ndarray, closes: np.ndarray) -> Optional[Dict]:
        """Détecte pattern Head & Shoulders"""
        try:
            peaks, _ = find_peaks(highs, distance=5, prominence=np.std(highs) * 0.3)
            
            if len(peaks) < 3:
                return None
            
            recent_peaks = peaks[-3:]
            peak_prices = highs[recent_peaks]
            
            left_shoulder = peak_prices[0]
            head = peak_prices[1]
            right_shoulder = peak_prices[2]
            
            head_higher = head > left_shoulder and head > right_shoulder
            shoulders_similar = abs(left_shoulder - right_shoulder) / left_shoulder < 0.05
            head_significant = (head - max(left_shoulder, right_shoulder)) / head > 0.03
            
            if head_higher and shoulders_similar and head_significant:
                valleys_between = np.min(highs[recent_peaks[0]:recent_peaks[2]])
                neckline = valleys_between
                target_drop = head - neckline
                target_price = neckline - target_drop
                
                confidence = 75
                
                return {
                    'type': 'HEAD_SHOULDERS',
                    'confidence': confidence,
                    'target_price': target_price,
                    'neckline': neckline,
                    'head_price': head,
                    'expected_drop_pct': ((closes[-1] - target_price) / closes[-1]) * 100,
                    'description': f"H&S: Head {head:.0f}, Target {target_price:.0f} ({((closes[-1] - target_price) / closes[-1]) * 100:.1f}%)"
                }
        except Exception as e:
            self.logger.error(f"Erreur détection H&S: {e}")
        
        return None
    
    def _detect_double_top_bottom(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> Optional[Dict]:
        """Détecte Double Top/Bottom"""
        try:
            # Double Top
            peaks, _ = find_peaks(highs, distance=8, prominence=np.std(highs) * 0.3)
            if len(peaks) >= 2:
                recent_peaks = peaks[-2:]
                peak1, peak2 = highs[recent_peaks]
                
                if abs(peak1 - peak2) / max(peak1, peak2) < 0.03:
                    return {
                        'type': 'DOUBLE_TOP',
                        'confidence': 80,
                        'bullish': False,
                        'description': f"Double Top: {max(peak1, peak2):.0f}"
                    }
            
            # Double Bottom
            valleys, _ = find_peaks(-lows, distance=8, prominence=np.std(lows) * 0.3)
            if len(valleys) >= 2:
                recent_valleys = valleys[-2:]
                valley1, valley2 = lows[recent_valleys]
                
                if abs(valley1 - valley2) / min(valley1, valley2) < 0.03:
                    return {
                        'type': 'DOUBLE_BOTTOM',
                        'confidence': 85,
                        'bullish': True,
                        'description': f"Double Bottom: {min(valley1, valley2):.0f}"
                    }
        except Exception as e:
            self.logger.error(f"Erreur détection Double Top/Bottom: {e}")
        
        return None
    
    def _detect_triangles(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> Optional[Dict]:
        """Détecte triangles (ascending, descending, symmetrical)"""
        try:
            if len(highs) < 20:
                return None
            
            recent_highs = highs[-20:]
            recent_lows = lows[-20:]
            
            x = np.arange(len(recent_highs))
            high_slope = np.polyfit(x, recent_highs, 1)[0]
            low_slope = np.polyfit(x, recent_lows, 1)[0]
            
            if abs(high_slope) < 0.1 and low_slope > 0.1:
                return {'type': 'ASCENDING_TRIANGLE', 'confidence': 75, 'bullish': True, 'description': 'Triangle Ascendant'}
            elif high_slope < -0.1 and abs(low_slope) < 0.1:
                return {'type': 'DESCENDING_TRIANGLE', 'confidence': 75, 'bullish': False, 'description': 'Triangle Descendant'}
            elif high_slope < -0.05 and low_slope > 0.05:
                return {'type': 'SYMMETRICAL_TRIANGLE', 'confidence': 70, 'bullish': True, 'description': 'Triangle Symétrique'}
        except:
            pass
        return None
    
    def _detect_flags_pennants(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, volumes: np.ndarray) -> Optional[Dict]:
        """Détecte flags et pennants"""
        try:
            if len(closes) < 15:
                return None
            
            initial_move = (closes[-1] - closes[-10]) / closes[-10]
            if abs(initial_move) < 0.03:
                return None
            
            recent_range = np.max(highs[-5:]) - np.min(lows[-5:])
            avg_price = np.mean(closes[-5:])
            consolidation_pct = recent_range / avg_price
            
            if consolidation_pct < 0.02:
                if initial_move > 0:
                    return {'type': 'BULL_FLAG', 'confidence': 80, 'bullish': True, 'description': 'Bull Flag'}
                else:
                    return {'type': 'BEAR_FLAG', 'confidence': 80, 'bullish': False, 'description': 'Bear Flag'}
        except:
            pass
        return None
    
    def _detect_candlestick_patterns(self, klines: List[Dict]) -> Optional[Dict]:
        """Détecte patterns chandeliers"""
        try:
            if len(klines) < 3:
                return None
            
            c3 = klines[-1]
            
            # Doji
            if abs(c3['close'] - c3['open']) / c3['open'] < 0.001:
                return {'type': 'DOJI', 'confidence': 70, 'bullish': True, 'description': 'Doji - Indécision'}
            
            # Hammer/Hanging Man
            body = abs(c3['close'] - c3['open'])
            lower_shadow = min(c3['open'], c3['close']) - c3['low']
            upper_shadow = c3['high'] - max(c3['open'], c3['close'])
            
            if lower_shadow > body * 2 and upper_shadow < body * 0.5:
                if c3['close'] > c3['open']:
                    return {'type': 'HAMMER', 'confidence': 80, 'bullish': True, 'description': 'Hammer Bullish'}
                else:
                    return {'type': 'HANGING_MAN', 'confidence': 75, 'bullish': False, 'description': 'Hanging Man'}
            
            # Engulfing Pattern
            if len(klines) >= 2:
                c2 = klines[-2]
                prev_bearish = c2['close'] < c2['open']
                curr_bullish = c3['close'] > c3['open']
                
                if (prev_bearish and curr_bullish and 
                    c3['open'] < c2['close'] and c3['close'] > c2['open']):
                    return {'type': 'BULLISH_ENGULFING', 'confidence': 85, 'bullish': True, 'description': 'Bullish Engulfing'}
        except:
            pass
        return None
    
    def _detect_wedges(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> Optional[Dict]:
        """Détecte wedges"""
        try:
            if len(highs) < 15:
                return None
            
            recent_highs = highs[-15:]
            recent_lows = lows[-15:]
            
            x = np.arange(len(recent_highs))
            high_slope = np.polyfit(x, recent_highs, 1)[0]
            low_slope = np.polyfit(x, recent_lows, 1)[0]
            
            if high_slope > 0.05 and low_slope > 0.05 and high_slope < low_slope * 1.5:
                return {'type': 'RISING_WEDGE', 'confidence': 75, 'bullish': False, 'description': 'Rising Wedge'}
            elif high_slope < -0.05 and low_slope < -0.05 and abs(high_slope) < abs(low_slope) * 1.5:
                return {'type': 'FALLING_WEDGE', 'confidence': 75, 'bullish': True, 'description': 'Falling Wedge'}
        except:
            pass
        return None
    
    def _detect_cup_handle(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> Optional[Dict]:
        """Détecte Cup & Handle pattern"""
        try:
            if len(closes) < 30:
                return None
            
            # Cup: U-shape dans les 20 dernières bougies
            cup_data = closes[-20:]
            cup_start = cup_data[0]
            cup_end = cup_data[-1]
            cup_bottom = np.min(cup_data[5:15])  # Bottom au milieu
            
            # Vérifier forme de coupe
            cup_depth = (cup_start - cup_bottom) / cup_start
            cup_recovery = (cup_end - cup_bottom) / (cup_start - cup_bottom)
            
            if 0.12 < cup_depth < 0.35 and cup_recovery > 0.8:
                # Handle: consolidation récente
                handle_data = closes[-5:]
                handle_volatility = np.std(handle_data) / np.mean(handle_data)
                
                if handle_volatility < 0.02:  # Faible volatilité = handle
                    return {
                        'type': 'CUP_HANDLE',
                        'confidence': 85,
                        'bullish': True,
                        'description': f'Cup & Handle (depth: {cup_depth:.1%})'
                    }
        except:
            pass
        return None
    
    def _detect_breakout_patterns(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, volumes: np.ndarray) -> Optional[Dict]:
        """Détecte patterns de breakout"""
        try:
            if len(closes) < 15:
                return None
            
            # Consolidation suivie de breakout
            recent_range = np.max(highs[-10:]) - np.min(lows[-10:])
            avg_price = np.mean(closes[-10:])
            consolidation_pct = recent_range / avg_price
            
            # Volume spike récent
            avg_volume = np.mean(volumes[-10:-1])
            current_volume = volumes[-1]
            volume_spike = current_volume > avg_volume * 1.5
            
            # Prix breakout
            resistance = np.max(highs[-10:-1])
            current_price = closes[-1]
            
            if consolidation_pct < 0.03 and volume_spike and current_price > resistance:
                return {
                    'type': 'VOLUME_BREAKOUT',
                    'confidence': 80,
                    'bullish': True,
                    'description': f'Volume Breakout ({volume_spike:.1f}x vol)'
                }
        except:
            pass
        return None