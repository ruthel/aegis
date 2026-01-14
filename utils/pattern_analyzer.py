"""
Pattern Recognition System
Détecte Head & Shoulders, Double Top/Bottom, Triangles + Support/Résistance + Dynamic Levels
"""

from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import logging
import time
import os
from datetime import datetime

class PatternAnalyzer:
    def __init__(self, bot):
        self.logger = logging.getLogger(__name__)
        self.min_pattern_length = 20
        # Support/Resistance integration
        self.min_touches = 2
        self.proximity_threshold = 0.005
        # Dynamic Levels integration
        self.bot = bot
        self.cache = {}
        self.cache_duration = 300  # 5 minutes
        
    def detect_patterns(self, klines: List[Dict]) -> Dict:
        """Détecte tous les patterns dans les klines"""
        if len(klines) < self.min_pattern_length:
            return {'patterns': [], 'bearish_detected': False, 'bullish_patterns': [], 'strongest_pattern': None}
        
        # Conversion en listes Python standard
        closes = [k['close'] for k in klines]
        highs = [k['high'] for k in klines]
        lows = [k['low'] for k in klines]
        volumes = [k['volume'] for k in klines]
        
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
    
    def _detect_head_shoulders(self, highs: list, closes: list) -> Optional[Dict]:
        """Détecte pattern Head & Shoulders"""
        try:
            # Lazy import
            from scipy.signal import find_peaks
            import numpy as np
            
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
                    'description': f"H&S {head:.0f} (target {target_price:.0f}, -{((closes[-1] - target_price) / closes[-1]) * 100:.1f}%)"
                }
        except Exception as e:
            self.logger.error(f"Erreur détection H&S: {e}")
        
        return None
    
    def _detect_double_top_bottom(self, highs: list, lows: list, closes: list) -> Optional[Dict]:
        """Détecte Double Top/Bottom"""
        try:
            # Lazy import
            from scipy.signal import find_peaks
            import numpy as np
            
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
                        'description': f"Double Top {max(peak1, peak2):.0f} (résistance forte)"
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
                        'description': f"Double Bottom {min(valley1, valley2):.0f} (support fort)"
                    }
        except Exception as e:
            self.logger.error(f"Erreur détection Double Top/Bottom: {e}")
        
        return None
    
    def _detect_triangles(self, highs: list, lows: list, closes: list) -> Optional[Dict]:
        """Détecte triangles (ascending, descending, symmetrical)"""
        try:
            import numpy as np
            
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
    
    def _detect_flags_pennants(self, highs: list, lows: list, closes: list, volumes: list) -> Optional[Dict]:
        """Détecte flags et pennants"""
        try:
            import numpy as np
            
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
    
    def _detect_wedges(self, highs: list, lows: list, closes: list) -> Optional[Dict]:
        """Détecte wedges"""
        try:
            import numpy as np
            
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
    
    def _detect_cup_handle(self, highs: list, lows: list, closes: list) -> Optional[Dict]:
        """Détecte Cup & Handle pattern"""
        try:
            import numpy as np
            
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
    
    def _detect_breakout_patterns(self, highs: list, lows: list, closes: list, volumes: list) -> Optional[Dict]:
        """Détecte patterns de breakout"""
        try:
            import numpy as np
            
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
    
    # === SUPPORT/RESISTANCE METHODS ===
    
    def find_support_resistance_levels(self, klines, lookback_periods=100):
        """Trouve les niveaux de support et résistance significatifs"""
        if len(klines) < lookback_periods:
            lookback_periods = len(klines)
        
        recent_klines = klines[-lookback_periods:]
        highs = [k['high'] for k in recent_klines]
        lows = [k['low'] for k in recent_klines]
        volumes = [k['volume'] for k in recent_klines]
        
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
        
        for i, high in enumerate(highs):
            level_key = round(high / (high * self.proximity_threshold)) * (high * self.proximity_threshold)
            levels[level_key].append({
                'price': high,
                'index': i,
                'volume': volumes[i] if i < len(volumes) else 0
            })
        
        resistance_levels = []
        for level_price, touches in levels.items():
            if len(touches) >= self.min_touches:
                avg_volume = sum(t['volume'] for t in touches) / len(touches)
                strength = len(touches)  # Nombre de rebonds simple
                
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
                strength = len(touches)  # Nombre de rebonds simple
                
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
        
        near_resistance = self._find_nearest_level(current_price, resistance_levels, 'above')
        near_support = self._find_nearest_level(current_price, support_levels, 'below')
        
        reversal_probability = 0
        reversal_direction = None
        target_level = None
        
        if near_resistance and self._is_near_level(current_price, near_resistance['price']):
            reversal_probability = min(near_resistance['strength'] * 10, 85)
            reversal_direction = 'DOWN'
            target_level = near_resistance
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
            above_levels = [l for l in levels if l['price'] > current_price]
            return min(above_levels, key=lambda x: abs(x['price'] - current_price)) if above_levels else None
        else:
            below_levels = [l for l in levels if l['price'] < current_price]
            return min(below_levels, key=lambda x: abs(x['price'] - current_price)) if below_levels else None
    
    def _is_near_level(self, current_price, level_price):
        """Vérifie si le prix est proche d'un niveau"""
        distance_pct = abs(current_price - level_price) / current_price
        return distance_pct <= self.proximity_threshold * 2
    
    def get_fibonacci_levels(self, klines, trend_direction='up'):
        """Calcule les niveaux de retracement de Fibonacci"""
        if len(klines) < 20:
            return []
        
        recent_klines = klines[-50:]
        highs = [k['high'] for k in recent_klines]
        lows = [k['low'] for k in recent_klines]
        
        if trend_direction == 'up':
            swing_low = min(lows)
            swing_high = max(highs)
        else:
            swing_high = max(highs)
            swing_low = min(lows)
        
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
                'strength': 3 if ratio in [0.382, 0.618] else 2
            })
        
        return fib_levels
    
    # === DYNAMIC LEVELS METHODS ===
    
    def get_dynamic_levels(self, symbol):
        """Calcule les niveaux d'entrée dynamiques"""
        if self._is_cached(symbol):
            return self.cache[symbol]['levels']
        
        levels = {
            'support': [],
            'resistance': [],
            'pivot_points': {},
            'order_blocks': [],
            'volume_poc': None
        }
        
        try:
            levels['pivot_points'] = self._calculate_pivot_points(symbol)
            support_resistance = self._calculate_support_resistance(symbol)
            levels['support'] = support_resistance['support']
            levels['resistance'] = support_resistance['resistance']
            levels['order_blocks'] = self._detect_order_blocks(symbol)
            levels['volume_poc'] = self._calculate_volume_poc(symbol)
            
            self.cache[symbol] = {
                'levels': levels,
                'timestamp': datetime.now()
            }
            
            return levels
            
        except Exception as e:
            print(f"⚠️ Erreur calcul niveaux dynamiques {symbol}: {e}")
            return self._get_fallback_levels_dynamic(symbol)
    
    def _calculate_pivot_points(self, symbol):
        """Calcule les pivot points Daily"""
        try:
            klines = self.bot.get_klines(symbol, 5, '1d')
            if len(klines) < 2:
                return {}
            
            yesterday = klines[-2]
            high = yesterday['high']
            low = yesterday['low']
            close = yesterday['close']
            
            pivot = (high + low + close) / 3
            
            r1 = 2 * pivot - low
            r2 = pivot + (high - low)
            r3 = high + 2 * (pivot - low)
            
            s1 = 2 * pivot - high
            s2 = pivot - (high - low)
            s3 = low - 2 * (high - pivot)
            
            return {
                'pivot': pivot,
                'r1': r1, 'r2': r2, 'r3': r3,
                's1': s1, 's2': s2, 's3': s3
            }
            
        except Exception as e:
            print(f"⚠️ Erreur pivot points {symbol}: {e}")
            return {}
    
    def _calculate_support_resistance(self, symbol):
        """Calcule support/résistance dynamiques"""
        try:
            klines = self.bot.get_klines(symbol, 42, '4h')
            if len(klines) < 20:
                return {'support': [], 'resistance': []}
            
            highs = [k['high'] for k in klines]
            lows = [k['low'] for k in klines]
            
            resistance_levels = self._find_significant_levels(highs, 'high')
            support_levels = self._find_significant_levels(lows, 'low')
            
            return {
                'support': support_levels[:3],
                'resistance': resistance_levels[:3]
            }
            
        except Exception as e:
            print(f"⚠️ Erreur support/résistance {symbol}: {e}")
            return {'support': [], 'resistance': []}
    
    def _find_significant_levels(self, prices, level_type):
        """Trouve les niveaux significatifs par clustering"""
        if len(prices) < 10:
            return []
        
        # Calcul std sans numpy
        mean = sum(prices) / len(prices)
        variance = sum((p - mean) ** 2 for p in prices) / len(prices)
        std = variance ** 0.5
        
        levels = []
        tolerance = std * 0.5
        
        sorted_prices = sorted(prices, reverse=(level_type == 'high'))
        
        for price in sorted_prices:
            is_new_level = True
            for existing_level in levels:
                if abs(price - existing_level) < tolerance:
                    is_new_level = False
                    break
            
            if is_new_level:
                levels.append(price)
                
            if len(levels) >= 5:
                break
        
        return levels
    
    def _detect_order_blocks(self, symbol):
        """Détecte les order blocks institutionnels"""
        try:
            klines = self.bot.get_klines(symbol, 72, '1h')
            if len(klines) < 20:
                return []
            
            order_blocks = []
            volumes = [k['volume'] for k in klines if k['volume'] > 0]
            if len(volumes) < 10:
                return []
            
            avg_volume = sum(volumes) / len(volumes)
            volume_threshold = avg_volume * 1.5
            
            for i in range(2, len(klines) - 2):
                current = klines[i]
                next_candle = klines[i+1]
                
                if current['volume'] == 0 or current['high'] == current['low']:
                    continue
                
                if (current['close'] > current['open'] and
                    current['volume'] > volume_threshold and
                    next_candle['low'] > current['high']):
                    
                    order_blocks.append({
                        'type': 'bullish',
                        'high': current['high'],
                        'low': current['low'],
                        'strength': current['volume']
                    })
                
                elif (current['close'] < current['open'] and
                      current['volume'] > volume_threshold and
                      next_candle['high'] < current['low']):
                    
                    order_blocks.append({
                        'type': 'bearish',
                        'high': current['high'],
                        'low': current['low'],
                        'strength': current['volume']
                    })
            
            if order_blocks:
                order_blocks.sort(key=lambda x: x['strength'], reverse=True)
                return order_blocks[:3]
            
            return []
            
        except Exception as e:
            print(f"⚠️ Erreur order blocks {symbol}: {e}")
            return []
    
    def _calculate_volume_poc(self, symbol):
        """Calcule le Point of Control du Volume Profile"""
        try:
            klines = self.bot.get_klines(symbol, 96, '15m')
            if len(klines) < 50:
                return None
            
            all_prices = []
            all_volumes = []
            
            for k in klines:
                avg_price = (k['high'] + k['low'] + k['close']) / 3
                volume = k['volume']
                
                if volume > 0:
                    all_prices.append(avg_price)
                    all_volumes.append(volume)
            
            if len(all_prices) < 10:
                return None
            
            price_volume_pairs = list(zip(all_prices, all_volumes))
            price_bins = {}
            price_range = max(all_prices) - min(all_prices)
            
            if price_range == 0:
                return all_prices[0]
            
            bin_size = price_range / 20
            
            for price, volume in price_volume_pairs:
                bin_key = int((price - min(all_prices)) / bin_size)
                if bin_key not in price_bins:
                    price_bins[bin_key] = {'total_volume': 0, 'avg_price': 0, 'count': 0}
                
                price_bins[bin_key]['total_volume'] += volume
                price_bins[bin_key]['avg_price'] += price
                price_bins[bin_key]['count'] += 1
            
            if not price_bins:
                return None
            
            max_volume_bin = max(price_bins.items(), key=lambda x: x[1]['total_volume'])
            
            if max_volume_bin[1]['count'] == 0:
                return None
                
            poc_price = max_volume_bin[1]['avg_price'] / max_volume_bin[1]['count']
            
            return poc_price
            
        except Exception as e:
            print(f"⚠️ Erreur Volume POC {symbol}: {e}")
            return None
    
    def get_entry_levels(self, symbol, current_price):
        """Obtient les meilleurs niveaux d'entrée"""
        try:
            levels = self.get_dynamic_levels(symbol)
            entry_opportunities = []
            
            pivots = levels.get('pivot_points', {})
            for level_name, price in pivots.items():
                if level_name.startswith('s') and price:
                    distance = abs(current_price - price) / current_price * 100
                    if distance < 2.0:
                        entry_opportunities.append({
                            'price': price,
                            'type': f'Pivot {level_name.upper()}',
                            'distance': distance,
                            'strength': 0.8
                        })
            
            for support in levels.get('support', []):
                distance = abs(current_price - support) / current_price * 100
                if distance < 1.5:
                    entry_opportunities.append({
                        'price': support,
                        'type': 'Support dynamique',
                        'distance': distance,
                        'strength': 0.9
                    })
            
            for ob in levels.get('order_blocks', []):
                if ob['type'] == 'bullish':
                    avg_price = (ob['high'] + ob['low']) / 2
                    distance = abs(current_price - avg_price) / current_price * 100
                    if distance < 1.0:
                        entry_opportunities.append({
                            'price': avg_price,
                            'type': 'Order Block',
                            'distance': distance,
                            'strength': 0.95
                        })
            
            entry_opportunities.sort(key=lambda x: (x['strength'], -x['distance']), reverse=True)
            
            return entry_opportunities[:3]
            
        except Exception as e:
            print(f"⚠️ Erreur entry levels {symbol}: {e}")
            return []
    
    def _is_cached(self, symbol):
        """Vérifie si les données sont en cache et valides"""
        if symbol not in self.cache:
            return False
        
        cache_age = (datetime.now() - self.cache[symbol]['timestamp']).seconds
        return cache_age < self.cache_duration
    
    def _get_fallback_levels_dynamic(self, symbol):
        """Niveaux de fallback en cas d'erreur"""
        try:
            current_price = self.bot.get_price(symbol)
            return {
                'pivot_points': {'pivot': current_price},
                'support': [current_price * 0.98, current_price * 0.96],
                'resistance': [current_price * 1.02, current_price * 1.04],
                'order_blocks': [],
                'volume_poc': current_price
            }
        except:
            return {
                'pivot_points': {},
                'support': [],
                'resistance': [],
                'order_blocks': [],
                'volume_poc': None
            }