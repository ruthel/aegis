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
            return {'patterns': [], 'bearish_detected': False}
        
        closes = np.array([k['close'] for k in klines])
        highs = np.array([k['high'] for k in klines])
        lows = np.array([k['low'] for k in klines])
        
        patterns = []
        
        # Détecter Head & Shoulders
        hs_pattern = self._detect_head_shoulders(highs, closes)
        if hs_pattern:
            patterns.append(hs_pattern)
        
        # Détecter Double Top
        dt_pattern = self._detect_double_top(highs, closes)
        if dt_pattern:
            patterns.append(dt_pattern)
        
        # Vérifier si pattern baissier détecté
        bearish_patterns = ['HEAD_SHOULDERS', 'DOUBLE_TOP']
        bearish_detected = any(p['type'] in bearish_patterns and p['confidence'] > 70 
                              for p in patterns)
        
        return {
            'patterns': patterns,
            'bearish_detected': bearish_detected,
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
    
    def _detect_double_top(self, highs: np.ndarray, closes: np.ndarray) -> Optional[Dict]:
        """Détecte pattern Double Top"""
        try:
            peaks, _ = find_peaks(highs, distance=8, prominence=np.std(highs) * 0.3)
            
            if len(peaks) < 2:
                return None
            
            recent_peaks = peaks[-2:]
            peak1, peak2 = highs[recent_peaks]
            
            peaks_similar = abs(peak1 - peak2) / max(peak1, peak2) < 0.03
            valley_between = np.min(highs[recent_peaks[0]:recent_peaks[1]])
            significant_valley = (min(peak1, peak2) - valley_between) / min(peak1, peak2) > 0.02
            
            if peaks_similar and significant_valley:
                target_price = valley_between - (min(peak1, peak2) - valley_between)
                
                return {
                    'type': 'DOUBLE_TOP',
                    'confidence': 80,
                    'target_price': target_price,
                    'resistance': max(peak1, peak2),
                    'support': valley_between,
                    'expected_drop_pct': ((closes[-1] - target_price) / closes[-1]) * 100,
                    'description': f"Double Top: {max(peak1, peak2):.0f}, Target {target_price:.0f}"
                }
        except Exception as e:
            self.logger.error(f"Erreur détection Double Top: {e}")
        
        return None