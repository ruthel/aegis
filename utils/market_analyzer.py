"""
Calculateur centralisé pour métriques de marché et scoring crypto
Fusion de crypto_scorer, volatility_calculator et volume_predictor
"""
import time
import math
import os

from datetime import datetime, timedelta
from typing import Dict, List, Optional

class MarketAnalyzer:
    """Calculs de marché centralisés - Tout-en-un"""
    
    def __init__(self, min_score=40):
        """Initialise le MarketAnalyzer avec les paramètres de scoring"""
        # Configuration scoring crypto
        self.analyzer = None  # Lazy load
        self.base_min_score = min_score
        self.max_tradeable = 2  # Valeur par défaut, sera mise à jour dynamiquement
        self.blacklist = {}
        self.blacklist_duration = 3600
        self.score_history = {}
        self.performance_weights = self._get_default_weights()
        
        # Configuration volume predictor
        self.volume_cycles = {}
        self.last_predictions = {}
        
        # Macro Event Manager
        self.macro_manager = None  # Lazy load
    
    def _get_default_weights(self):
        """Retourne les poids par défaut pour le scoring"""
        return {
            'volume': 0.3,
            'volatility': 0.25,
            'momentum': 0.25,
            'liquidity': 0.2
        }
    
    def _get_analyzer(self):
        """Lazy load TimeframeAnalyzer"""
        if self.analyzer is None:
            from utils.timeframe_analyzer import TimeframeAnalyzer
            self.analyzer = TimeframeAnalyzer()
        return self.analyzer
    
    def _get_macro_manager(self):
        """Lazy load MacroEventManager"""
        if self.macro_manager is None:
            from utils.event_manager import MacroEventManager
            self.macro_manager = MacroEventManager()
        return self.macro_manager
    
    @classmethod
    def calculate_volatility(cls, klines, symbol='', websocket_manager=None):
        """Calcule la volatilité temps réel - Score 1-5 pour scalping - VERSION AMÉLIORÉE"""
        if websocket_manager and websocket_manager.is_connected():
            ws_klines = websocket_manager.get_klines(symbol, 60)
            if len(ws_klines) >= 10:
                klines = ws_klines
        
        try:
            if len(klines) < 10:
                return 2.0
            
            # AMÉLIORATION 5: Détection régime de volatilité
            regime = cls._detect_volatility_regime(klines)
            
            # Adapter période selon régime
            if regime == 'high_vol':
                recent_klines = klines[-10:]  # Période courte pour réactivité
            elif regime == 'low_vol':
                recent_klines = klines[-30:] if len(klines) >= 30 else klines[-20:]  # Période longue pour stabilité
            else:
                recent_klines = klines[-20:]  # Période normale
            
            closes = [k['close'] for k in recent_klines if 'close' in k]
            
            if len(closes) < 10:
                return 2.0
            
            # AMÉLIORATION 1: Parkinson + ATR combinés
            parkinson_vol = cls._calculate_parkinson_volatility(recent_klines)
            atr_vol = cls._calculate_atr_volatility(recent_klines, closes)
            
            # Moyenne pondérée (Parkinson 60% + ATR 40%)
            if parkinson_vol is not None:
                volatility_hourly = 0.6 * parkinson_vol + 0.4 * atr_vol
            else:
                volatility_hourly = atr_vol
            
            # AMÉLIORATION 3: Seuils adaptatifs selon crypto
            thresholds = cls.get_volatility_thresholds(symbol)
            
            # Mapper vers score 1-5 avec seuils adaptatifs
            if volatility_hourly < thresholds['very_low']:
                return 1.0
            elif volatility_hourly < thresholds['low']:
                return 2.0
            elif volatility_hourly < thresholds['medium']:
                return 3.0
            elif volatility_hourly < thresholds['high']:
                return 4.0
            else:
                return 5.0
                
        except Exception:
            return 2.0
    
    @classmethod
    def _calculate_parkinson_volatility(cls, klines):
        """AMÉLIORATION 1: Parkinson Estimator - Plus précis qu'ATR"""
        try:
            if len(klines) < 10:
                return None
            
            hl_ratios_squared = []
            
            for k in klines:
                if k['high'] > 0 and k['low'] > 0 and k['high'] >= k['low']:
                    hl_ratio = math.log(k['high'] / k['low'])
                    hl_ratios_squared.append(hl_ratio ** 2)
            
            if not hl_ratios_squared:
                return None
            
            # Parkinson variance
            parkinson_var = sum(hl_ratios_squared) / (len(hl_ratios_squared) * 4 * math.log(2))
            return math.sqrt(parkinson_var) * 100  # En %
            
        except:
            return None
    
    @classmethod
    def _calculate_atr_volatility(cls, klines, closes):
        """AMÉLIORATION 2: ATR avec EWMA au lieu de moyenne simple"""
        true_ranges = []
        for i in range(1, len(klines)):
            kline = klines[i]
            high = kline.get('high', closes[i] if i < len(closes) else 0)
            low = kline.get('low', closes[i] if i < len(closes) else 0)
            prev_close = closes[i-1] if i-1 < len(closes) else 0
            
            if high <= 0 or low <= 0 or prev_close <= 0 or high < low:
                continue
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            if tr > 0:
                true_ranges.append(tr)
        
        # AMÉLIORATION 2: EWMA au lieu de moyenne simple
        if true_ranges:
            ewma_atr = cls._calculate_ewma_atr(true_ranges)
            current_price = closes[-1]
            if current_price > 0:
                return (ewma_atr / current_price) * 100
        
        # Fallback: volatilité simple
        price_changes = [abs(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes)) if closes[i-1] > 0]
        if price_changes:
            return sum(price_changes) / len(price_changes) * 100
        
        return 2.0
    
    @classmethod
    def _calculate_ewma_atr(cls, true_ranges, alpha=0.1):
        """AMÉLIORATION 2: Exponentially Weighted Moving Average"""
        if not true_ranges:
            return 0
        
        ewma = true_ranges[0]
        for tr in true_ranges[1:]:
            ewma = alpha * tr + (1 - alpha) * ewma
        return ewma
    
    @classmethod
    def get_volatility_thresholds(cls, symbol):
        """AMÉLIORATION 3: Seuils adaptatifs par crypto"""
        # Seuils basés sur données historiques réelles
        crypto_thresholds = {
            'BTC/USDT': {'very_low': 0.12, 'low': 0.25, 'medium': 0.50, 'high': 1.0},
            'ETH/USDT': {'very_low': 0.15, 'low': 0.30, 'medium': 0.60, 'high': 1.2},
            'SOL/USDT': {'very_low': 0.25, 'low': 0.50, 'medium': 1.0, 'high': 2.0},
            'BNB/USDT': {'very_low': 0.18, 'low': 0.35, 'medium': 0.70, 'high': 1.4},
            'ADA/USDT': {'very_low': 0.20, 'low': 0.40, 'medium': 0.80, 'high': 1.6},
            'DOT/USDT': {'very_low': 0.22, 'low': 0.45, 'medium': 0.90, 'high': 1.8},
            'MATIC/USDT': {'very_low': 0.30, 'low': 0.60, 'medium': 1.2, 'high': 2.4},
            'AVAX/USDT': {'very_low': 0.28, 'low': 0.55, 'medium': 1.1, 'high': 2.2}
        }
        
        return crypto_thresholds.get(symbol, {
            'very_low': 0.15, 'low': 0.30, 'medium': 0.60, 'high': 1.2
        })
    
    @classmethod
    def _detect_volatility_regime(cls, klines):
        """AMÉLIORATION 5: Détecte régime de volatilité (calme/normal/volatil)"""
        if len(klines) < 50:
            return 'normal'
        
        try:
            # Volatilité récente vs historique
            recent_closes = [k['close'] for k in klines[-10:]]
            historical_closes = [k['close'] for k in klines[-50:]]
            
            # Calcul volatilité simple pour comparaison
            recent_changes = [abs(recent_closes[i] - recent_closes[i-1]) / recent_closes[i-1] 
                            for i in range(1, len(recent_closes)) if recent_closes[i-1] > 0]
            historical_changes = [abs(historical_closes[i] - historical_closes[i-1]) / historical_closes[i-1] 
                                for i in range(1, len(historical_closes)) if historical_closes[i-1] > 0]
            
            if not recent_changes or not historical_changes:
                return 'normal'
            
            recent_vol = sum(recent_changes) / len(recent_changes)
            historical_vol = sum(historical_changes) / len(historical_changes)
            
            ratio = recent_vol / historical_vol if historical_vol > 0 else 1
            
            if ratio > 1.5:
                return 'high_vol'  # Régime volatil
            elif ratio < 0.7:
                return 'low_vol'   # Régime calme
            else:
                return 'normal'    # Régime normal
                
        except:
            return 'normal'
    
    def predict_price_target_with_probability(self, bot, symbol, current_price, min_profit_pct=0.6):
        """Prédit le prix cible avec probabilité de réussite - Méthode professionnelle"""
        try:
            # Récupérer données techniques
            klines_4h = bot.get_klines(symbol, 50, '4h')
            klines_1h = bot.get_klines(symbol, 100, '1h')
            
            if not klines_4h or not klines_1h:
                return None
            
            # Calculer facteurs de probabilité
            factors = self._analyze_prediction_factors(bot, symbol, klines_4h, klines_1h, current_price)
            
            # Calculer prix cible basé sur résistances
            target_result = self._calculate_professional_target(klines_4h, klines_1h, current_price, min_profit_pct)
            
            # Calculer probabilité globale
            probability = self._calculate_target_probability(factors, target_result['target_price'], current_price)
            
            # Déterminer niveau de confiance
            if probability >= 75:
                confidence_level = "TRÈS ÉLEVÉE"
                time_horizon = "2-6h"
            elif probability >= 60:
                confidence_level = "ÉLEVÉE" 
                time_horizon = "4-12h"
            elif probability >= 45:
                confidence_level = "MODÉRÉE"
                time_horizon = "6-24h"
            else:
                confidence_level = "FAIBLE"
                time_horizon = ">24h"
            
            return {
                'target_price': target_result['target_price'],
                'probability': probability,
                'confidence_level': confidence_level,
                'time_horizon': time_horizon,
                'profit_potential': ((target_result['target_price'] - current_price) / current_price) * 100,
                'method_used': target_result['method_used'],
                'factors': factors
            }
            
        except Exception as e:
            return None
    
    def _analyze_prediction_factors(self, bot, symbol, klines_4h, klines_1h, current_price):
        """Analyse TOUS les facteurs influençant la probabilité - NIVEAU PROFESSIONNEL (12 facteurs)"""
        factors = {}
        closes_1h = [k['close'] for k in klines_1h]
        closes_4h = [k['close'] for k in klines_4h]
        
        # 1. VOLATILITÉ (impact sur précision)
        volatility = self.calculate_volatility(klines_1h, symbol)
        if volatility <= 2.5:
            factors['volatility_score'] = 85  # Optimal pour prédiction
        elif volatility <= 3.5:
            factors['volatility_score'] = 70
        else:
            factors['volatility_score'] = 40  # Trop volatil
        
        # 2. VOLUME CONFIRMATION + PROFIL
        volumes = [k['volume'] for k in klines_1h[-10:]]
        avg_volume = sum(volumes[:-1]) / len(volumes[:-1])
        current_volume = volumes[-1]
        
        # Volume ratio
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1
        if volume_ratio > 1.5:
            volume_base = 90
        elif volume_ratio > 1.2:
            volume_base = 75
        else:
            volume_base = 50
        
        # VWAP confirmation
        total_pv = sum(k['close'] * k['volume'] for k in klines_1h[-10:])
        total_vol = sum(k['volume'] for k in klines_1h[-10:])
        vwap = total_pv / total_vol if total_vol > 0 else current_price
        vwap_distance = abs(current_price - vwap) / current_price
        
        if vwap_distance < 0.005:  # Très près VWAP
            volume_base += 10
        elif vwap_distance > 0.02:  # Loin VWAP
            volume_base -= 15
        
        factors['volume_score'] = min(95, volume_base)
        
        # 3. SUPPORT/RÉSISTANCE AVANCÉ
        try:
            if hasattr(bot, 'pattern_analyzer'):
                levels = bot.pattern_analyzer.find_support_resistance_levels(klines_4h)
                if levels:
                    # Analyser proximité et force des niveaux
                    nearest_resistance = None
                    min_distance = float('inf')
                    
                    for level in levels.get('resistance_levels', []):
                        if level > current_price:
                            distance = (level - current_price) / current_price
                            if distance < min_distance:
                                min_distance = distance
                                nearest_resistance = level
                    
                    if nearest_resistance:
                        if min_distance < 0.01:  # Très proche résistance
                            factors['sr_score'] = 95
                        elif min_distance < 0.03:  # Proche résistance
                            factors['sr_score'] = 85
                        else:
                            factors['sr_score'] = 70
                    else:
                        factors['sr_score'] = 60
                else:
                    factors['sr_score'] = 40
            else:
                factors['sr_score'] = 60
        except:
            factors['sr_score'] = 60
        
        # 4. RSI MULTI-TIMEFRAME
        rsi_1h = self._calculate_rsi(closes_1h)
        rsi_4h = self._calculate_rsi(closes_4h) if len(closes_4h) >= 14 else None
        
        rsi_score = 50  # Base
        if rsi_1h:
            if 30 <= rsi_1h <= 70:  # Zone neutre
                rsi_score = 85
            elif 25 <= rsi_1h < 30 or 70 < rsi_1h <= 75:
                rsi_score = 70
            elif rsi_1h < 25:  # Oversold
                rsi_score = 60
            else:  # Overbought
                rsi_score = 40
        
        # Bonus alignement multi-timeframe
        if rsi_4h and rsi_1h:
            if abs(rsi_1h - rsi_4h) < 10:  # Alignement
                rsi_score += 10
        
        factors['rsi_score'] = min(95, rsi_score)
        
        # 5. MACD CONFLUENCE
        macd_score = 50
        if len(closes_1h) >= 26:
            ema_12 = self._calculate_ema(closes_1h, 12)
            ema_26 = self._calculate_ema(closes_1h, 26)
            macd_line = ema_12 - ema_26
            
            # Signal line (EMA 9 du MACD)
            macd_values = []
            for i in range(26, len(closes_1h)):
                ema12 = self._calculate_ema(closes_1h[:i+1], 12)
                ema26 = self._calculate_ema(closes_1h[:i+1], 26)
                macd_values.append(ema12 - ema26)
            
            if len(macd_values) >= 9:
                signal_line = self._calculate_ema(macd_values, 9)
                
                if macd_line > signal_line and macd_line > 0:
                    macd_score = 90  # Signal haussier fort
                elif macd_line > signal_line:
                    macd_score = 75  # Signal haussier
                elif macd_line > 0:
                    macd_score = 65  # Momentum positif
                else:
                    macd_score = 35  # Momentum négatif
        
        factors['macd_score'] = macd_score
        
        # 6. BOLLINGER BANDS POSITION
        bb_score = 50
        if len(closes_1h) >= 20:
            sma_20 = sum(closes_1h[-20:]) / 20
            variance = sum((c - sma_20) ** 2 for c in closes_1h[-20:]) / 20
            std_dev = variance ** 0.5
            
            upper_band = sma_20 + (2 * std_dev)
            lower_band = sma_20 - (2 * std_dev)
            
            bb_position = (current_price - lower_band) / (upper_band - lower_band)
            
            if 0.3 <= bb_position <= 0.7:  # Zone neutre
                bb_score = 85
            elif 0.2 <= bb_position < 0.3:  # Près bande basse
                bb_score = 75
            elif bb_position > 0.8:  # Près bande haute
                bb_score = 40
            else:
                bb_score = 60
        
        factors['bollinger_score'] = bb_score
        
        # 7. MOMENTUM MULTI-TIMEFRAME
        momentum_1h = self.calculate_momentum(klines_1h)
        momentum_4h = self.calculate_momentum(klines_4h) if len(klines_4h) >= 10 else 0
        
        momentum_score = 50
        if momentum_1h > 1.0 and momentum_4h > 0.5:
            momentum_score = 90  # Momentum aligné fort
        elif momentum_1h > 0.5:
            momentum_score = 75
        elif momentum_1h > 0:
            momentum_score = 65
        elif momentum_1h > -0.5:
            momentum_score = 45
        else:
            momentum_score = 30
        
        factors['momentum_score'] = momentum_score
        
        # 8. FIBONACCI RETRACEMENT
        fib_score = 50
        if len(closes_4h) >= 20:
            high_20 = max(closes_4h[-20:])
            low_20 = min(closes_4h[-20:])
            
            if high_20 != low_20:
                fib_levels = {
                    0.236: high_20 - (high_20 - low_20) * 0.236,
                    0.382: high_20 - (high_20 - low_20) * 0.382,
                    0.618: high_20 - (high_20 - low_20) * 0.618,
                    0.786: high_20 - (high_20 - low_20) * 0.786
                }
                
                for level_name, level_price in fib_levels.items():
                    distance = abs(current_price - level_price) / current_price
                    if distance < 0.01:  # Très proche niveau Fib
                        if level_name in [0.382, 0.618]:  # Niveaux clés
                            fib_score = 90
                        else:
                            fib_score = 75
                        break
        
        factors['fibonacci_score'] = fib_score
        
        # 9. ORDERBOOK IMBALANCE (estimation)
        try:
            # Estimation via spread et volume
            ticker = bot.get_ticker(symbol)
            if ticker:
                bid_ask_spread = 0.01  # Estimation
                if bid_ask_spread < 0.005:
                    orderbook_score = 85
                elif bid_ask_spread < 0.01:
                    orderbook_score = 70
                else:
                    orderbook_score = 50
            else:
                orderbook_score = 60
        except:
            orderbook_score = 60
        
        factors['orderbook_score'] = orderbook_score
        
        # 10. PRICE ACTION PATTERNS
        price_action_score = 50
        if len(klines_1h) >= 3:
            last_candle = klines_1h[-1]
            prev_candle = klines_1h[-2]
            
            # Analyse du pattern de la dernière bougie
            body_size = abs(last_candle['close'] - last_candle['open']) / last_candle['open']
            upper_wick = (last_candle['high'] - max(last_candle['open'], last_candle['close'])) / last_candle['open']
            lower_wick = (min(last_candle['open'], last_candle['close']) - last_candle['low']) / last_candle['open']
            
            # Hammer/Doji patterns
            if body_size < 0.005 and (upper_wick > 0.01 or lower_wick > 0.01):
                price_action_score = 80  # Doji avec wicks
            elif last_candle['close'] > last_candle['open'] and lower_wick > body_size * 2:
                price_action_score = 85  # Hammer bullish
            elif body_size > 0.015 and last_candle['close'] > last_candle['open']:
                price_action_score = 75  # Strong bullish candle
            elif body_size > 0.015 and last_candle['close'] < last_candle['open']:
                price_action_score = 35  # Strong bearish candle
        
        factors['price_action_score'] = price_action_score
        
        # 11. MARKET STRUCTURE (Higher Highs/Lower Lows)
        structure_score = 50
        if len(closes_1h) >= 10:
            recent_highs = [max(closes_1h[i:i+3]) for i in range(len(closes_1h)-6, len(closes_1h)-2)]
            recent_lows = [min(closes_1h[i:i+3]) for i in range(len(closes_1h)-6, len(closes_1h)-2)]
            
            if len(recent_highs) >= 2 and len(recent_lows) >= 2:
                # Higher highs and higher lows = uptrend
                if recent_highs[-1] > recent_highs[0] and recent_lows[-1] > recent_lows[0]:
                    structure_score = 85
                # Lower highs and lower lows = downtrend
                elif recent_highs[-1] < recent_highs[0] and recent_lows[-1] < recent_lows[0]:
                    structure_score = 40
                # Consolidation
                else:
                    structure_score = 65
        
        factors['market_structure_score'] = structure_score
        
        # 12. SESSION DE MARCHÉ & TIMING
        hour = datetime.now().hour
        
        if 14 <= hour <= 21:  # Session US (plus volatile)
            session_score = 85
        elif 8 <= hour <= 16:  # Session EU (stable)
            session_score = 90
        elif 22 <= hour <= 6:  # Session Asie (moins prévisible)
            session_score = 60
        else:  # Transition
            session_score = 70
        
        # Bonus weekend (moins de bruit institutionnel)
        if datetime.now().weekday() >= 5:
            session_score += 5
        
        factors['session_score'] = min(95, session_score)
        
        return factors
    
    def _calculate_professional_target(self, klines_4h, klines_1h, current_price, min_profit_pct):
        """Calcule prix cible selon méthode professionnelle (ordre de priorité) + FRAIS"""
        
        # FRAIS DE TRADING (achat + vente) = 0.1% * 2 = 0.2% minimum
        trading_fees_pct = 0.2  # 0.2% pour couvrir achat + vente
        min_profit_with_fees = min_profit_pct + trading_fees_pct
        
        # 1. RÉSISTANCE TECHNIQUE (Priorité absolue)
        resistance = self._find_nearest_resistance(klines_4h, current_price)
        if resistance:
            target = self._calculate_resistance_based_target(resistance, current_price)
            method = 'resistance_based'
        
        # 2. FIBONACCI EXTENSION (Si pas de résistance claire)
        elif self._has_fibonacci_setup(klines_4h):
            target = self._calculate_fibonacci_target(klines_4h, current_price)
            method = 'fibonacci_based'
        
        # 3. ATR TARGET (Volatilité-based)
        elif self._has_sufficient_volatility(klines_1h):
            atr = self._calculate_atr_simple(klines_1h)
            target = current_price + (atr * 1.5)
            method = 'atr_based'
        
        # 4. PROFIT MINIMUM (Dernier recours)
        else:
            target = current_price * (1 + min_profit_with_fees / 100)
            method = 'fallback'
        
        # FILTRE FINAL : Respecter profit minimum + FRAIS
        min_target_with_fees = current_price * (1 + min_profit_with_fees / 100)
        final_target = max(target, min_target_with_fees)
        
        return {
            'target_price': final_target,
            'method_used': method
        }
    
    def _find_nearest_resistance(self, klines, current_price):
        """Identifie la résistance la plus proche au-dessus du prix actuel"""
        highs = [k['high'] for k in klines[-30:]]
        resistance_levels = []
        
        for i in range(2, len(highs)-2):
            if (highs[i] > highs[i-1] and highs[i] > highs[i+1] and 
                highs[i] > highs[i-2] and highs[i] > highs[i+2]):
                if highs[i] > current_price * 1.002:  # Au moins 0.2% au-dessus
                    resistance_levels.append(highs[i])
        
        if resistance_levels:
            return min(resistance_levels)  # La plus proche
        return None
    
    def _calculate_resistance_based_target(self, resistance, current_price):
        """Calcule target SOUS la résistance (stratégie professionnelle)"""
        distance_to_resistance = (resistance - current_price) / current_price
        
        if distance_to_resistance > 0.05:      # >5% de distance
            safety_margin = 0.03  # 3% sous la résistance
        elif distance_to_resistance > 0.02:    # 2-5% de distance  
            safety_margin = 0.02  # 2% sous la résistance
        else:                                  # <2% de distance
            safety_margin = 0.01  # 1% sous la résistance
        
        return resistance * (1 - safety_margin)
    
    def _has_fibonacci_setup(self, klines):
        """Vérifie si setup Fibonacci valide"""
        if len(klines) < 20:
            return False
        
        prices = [k['close'] for k in klines[-20:]]
        high = max(prices)
        low = min(prices)
        current = prices[-1]
        
        # Setup valide si retracement > 38.2% et < 78.6%
        retracement = (high - current) / (high - low) if high != low else 0
        return 0.382 <= retracement <= 0.786
    
    def _calculate_fibonacci_target(self, klines, current_price):
        """Calcule target Fibonacci (extension 127.2%)"""
        prices = [k['close'] for k in klines[-20:]]
        high = max(prices)
        low = min(prices)
        
        # Extension 127.2%
        fib_extension = high + (high - low) * 0.272
        return min(fib_extension, current_price * 1.05)  # Max 5% de hausse
    
    def _has_sufficient_volatility(self, klines):
        """Vérifie si volatilité suffisante pour ATR target"""
        volatility = self.calculate_volatility(klines)
        return volatility >= 2.0
    
    def _calculate_atr_simple(self, klines):
        """Calcule ATR simple pour target"""
        true_ranges = []
        for i in range(1, min(len(klines), 15)):
            tr = max(
                klines[-i]['high'] - klines[-i]['low'],
                abs(klines[-i]['high'] - klines[-i-1]['close']),
                abs(klines[-i]['low'] - klines[-i-1]['close'])
            )
            true_ranges.append(tr)
        
        return sum(true_ranges) / len(true_ranges) if true_ranges else 0
    
    def _calculate_target_probability(self, factors, target_price, current_price):
        """Calcule probabilité globale basée sur TOUS les facteurs - NIVEAU PROFESSIONNEL (12 facteurs)"""
        
        # PONDÉRATION PROFESSIONNELLE (12 facteurs)
        weights = {
            'volatility_score': 0.12,      # Stabilité prédiction
            'volume_score': 0.11,          # Confirmation volume + VWAP
            'sr_score': 0.15,              # Support/Résistance (critique)
            'rsi_score': 0.10,             # RSI multi-timeframe
            'macd_score': 0.09,            # MACD confluence
            'bollinger_score': 0.08,       # Position Bollinger
            'momentum_score': 0.09,        # Momentum multi-TF
            'fibonacci_score': 0.07,       # Niveaux Fibonacci
            'orderbook_score': 0.06,       # Liquidité/Spread
            'price_action_score': 0.05,    # Patterns bougies
            'market_structure_score': 0.04, # Structure marché
            'session_score': 0.04          # Timing optimal
        }
        
        # Vérification total = 1.0
        total_weight = sum(weights.values())
        if abs(total_weight - 1.0) > 0.01:
            # Normalisation si nécessaire
            for key in weights:
                weights[key] /= total_weight
        
        # SCORE PONDÉRÉ PROFESSIONNEL
        weighted_score = sum(factors.get(factor, 50) * weight for factor, weight in weights.items())
        
        # AJUSTEMENTS DISTANCE TARGET (plus sophistiqués)
        price_move_pct = ((target_price - current_price) / current_price) * 100
        
        # Pénalités graduelles selon ambition du target
        if price_move_pct > 5.0:        # Très ambitieux
            weighted_score *= 0.60
        elif price_move_pct > 3.0:      # Ambitieux
            weighted_score *= 0.75
        elif price_move_pct > 2.0:      # Modéré
            weighted_score *= 0.85
        elif price_move_pct > 1.0:      # Raisonnable
            weighted_score *= 0.95
        elif price_move_pct < 0.3:      # Trop proche
            weighted_score *= 0.88
        # 0.3-1.0% = optimal (pas d'ajustement)
        
        # BONUS CONFLUENCE (facteurs alignés)
        high_confidence_factors = sum(1 for score in factors.values() if score >= 80)
        if high_confidence_factors >= 8:      # 8+ facteurs excellents
            weighted_score *= 1.15
        elif high_confidence_factors >= 6:    # 6+ facteurs excellents
            weighted_score *= 1.10
        elif high_confidence_factors >= 4:    # 4+ facteurs excellents
            weighted_score *= 1.05
        
        # PÉNALITÉ FACTEURS FAIBLES
        low_confidence_factors = sum(1 for score in factors.values() if score <= 40)
        if low_confidence_factors >= 4:       # 4+ facteurs faibles
            weighted_score *= 0.85
        elif low_confidence_factors >= 2:     # 2+ facteurs faibles
            weighted_score *= 0.92
        
        # AJUSTEMENT VOLATILITÉ SPÉCIFIQUE
        volatility_score = factors.get('volatility_score', 50)
        if volatility_score <= 40:  # Très volatil
            weighted_score *= 0.90  # Réduction supplémentaire
        elif volatility_score >= 85:  # Très stable
            weighted_score *= 1.05  # Bonus stabilité
        
        # AJUSTEMENT SESSION DÉJÀ INCLUS dans session_score
        # Pas de double ajustement
        
        return min(95, max(15, int(weighted_score)))
    

    

    

    

    

    

    

    

    

    

    
    @staticmethod
    def get_min_confidence(volatility, symbol=None):
        """
        Calcule le seuil de confiance minimum selon la volatilité - ADAPTATIF
        
        Args:
            volatility: Score volatilité 1-5
            symbol: Symbole pour optimisations futures
        
        Returns:
            int: Seuil de confiance minimum (%)
        """
        # Seuils adaptatifs selon volatilité (sans dépendance à self)
        if volatility >= 4.0:
            return 45  # Très volatil
        elif volatility >= 3.0:
            return 50  # Volatil
        elif volatility >= 2.0:
            return 55  # Moyen
        else:
            return 60  # Calme
      
    
    def calculate_rsi_score(self, klines):
        """Score RSI (0-20 points) - Niveau Professionnel"""
        if len(klines) < 14:
            return 10  # Score neutre
        
        closes = [k['close'] for k in klines]
        rsi = self._calculate_rsi(closes, 14)
        
        if rsi is None:
            return 10
        
        # Scoring professionnel RSI
        if 30 <= rsi <= 70:  # Zone neutre optimale
            return 20
        elif 25 <= rsi < 30 or 70 < rsi <= 75:  # Légèrement oversold/overbought
            return 15
        elif rsi < 25:  # Très oversold (opportunité)
            return 12
        elif rsi > 75:  # Très overbought (risque)
            return 8
        else:
            return 10
    
    def _calculate_rsi(self, closes, period=14):
        """Calcule RSI standard"""
        if len(closes) < period + 1:
            return None
        
        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    def calculate_correlation_score(self, bot, symbol):
        """Score corrélation avec BTC (0-15 points)"""
        if symbol == 'BTC/USDT':
            return 15  # BTC = référence
        
        try:
            # Klines 7 jours pour corrélation fiable
            symbol_klines = bot.get_klines(symbol, 168, '1h')  # 7j en 1h
            btc_klines = bot.get_klines('BTC/USDT', 168, '1h')
            
            if len(symbol_klines) < 50 or len(btc_klines) < 50:
                return 10  # Score neutre si pas assez de données
            
            # Prendre même longueur
            min_len = min(len(symbol_klines), len(btc_klines))
            symbol_closes = [k['close'] for k in symbol_klines[-min_len:]]
            btc_closes = [k['close'] for k in btc_klines[-min_len:]]
            
            correlation = self._calculate_correlation(symbol_closes, btc_closes)
            
            # Scoring: Faible corrélation = meilleur (diversification)
            if correlation < 0.3:  # Très faible corrélation
                return 15
            elif correlation < 0.5:  # Faible corrélation
                return 12
            elif correlation < 0.7:  # Corrélation modérée
                return 10
            elif correlation < 0.9:  # Forte corrélation
                return 7
            else:  # Très forte corrélation (risque)
                return 5
                
        except:
            return 10  # Score neutre en cas d'erreur
    
    def _calculate_correlation(self, x, y):
        """Calcule corrélation de Pearson"""
        if len(x) != len(y) or len(x) < 2:
            return 0.5
        
        n = len(x)
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(x[i] * y[i] for i in range(n))
        sum_x2 = sum(xi * xi for xi in x)
        sum_y2 = sum(yi * yi for yi in y)
        
        numerator = n * sum_xy - sum_x * sum_y
        denominator = ((n * sum_x2 - sum_x * sum_x) * (n * sum_y2 - sum_y * sum_y)) ** 0.5
        
        if denominator == 0:
            return 0
        
        return abs(numerator / denominator)  # Valeur absolue
    
    def calculate_liquidity_score(self, bot, symbol):
        """Score liquidité (0-15 points) - Spread + Order book"""
        try:
            # Estimer spread via ticker
            ticker = bot.get_ticker(symbol)
            if not ticker:
                return 10
            
            # Spread estimé (bid-ask)
            current_price = ticker.get('last', 0)
            if current_price <= 0:
                return 10
            
            # Estimation spread selon crypto (données réelles Binance)
            if symbol in ['BTC/USDT', 'ETH/USDT']:
                estimated_spread = 0.01  # 0.01%
            elif symbol in ['BNB/USDT', 'SOL/USDT']:
                estimated_spread = 0.02  # 0.02%
            else:
                estimated_spread = 0.05  # 0.05%
            
            # Volume 24h comme proxy liquidité
            volume_24h = ticker.get('quoteVolume', 0)
            
            # Score combiné spread + volume
            spread_score = 15 if estimated_spread <= 0.01 else 12 if estimated_spread <= 0.02 else 8 if estimated_spread <= 0.05 else 5
            volume_score = 15 if volume_24h > 100000000 else 12 if volume_24h > 50000000 else 8 if volume_24h > 10000000 else 5
            
            return int((spread_score + volume_score) / 2)
            
        except:
            return 10  # Score neutre
    
    def calculate_technical_score(self, klines):
        """Score technique (0-20 points) - MACD + Bollinger + EMA"""
        if len(klines) < 26:  # MACD nécessite 26 périodes
            return 10
        
        closes = [k['close'] for k in klines]
        score = 0
        signals = 0
        
        # 1. MACD Signal (0-7 points)
        try:
            macd_signal = self._calculate_macd_signal(closes)
            if macd_signal == 'BUY':
                score += 7
            elif macd_signal == 'NEUTRAL':
                score += 4
            # SELL = 0 points
            signals += 1
        except:
            pass
        
        # 2. Bollinger Bands (0-7 points)
        try:
            bb_signal = self._calculate_bollinger_signal(closes)
            if bb_signal == 'BUY':  # Prix près bande basse
                score += 7
            elif bb_signal == 'NEUTRAL':
                score += 4
            signals += 1
        except:
            pass
        
        # 3. EMA Crossover (0-6 points)
        try:
            ema_signal = self._calculate_ema_crossover(closes)
            if ema_signal == 'BUY':
                score += 6
            elif ema_signal == 'NEUTRAL':
                score += 3
            signals += 1
        except:
            pass
        
        # Moyenne pondérée
        if signals > 0:
            return min(20, int((score / signals) * (20 / 7)))  # Normaliser sur 20
        return 10
    
    def _calculate_macd_signal(self, closes):
        """Signal MACD simple"""
        if len(closes) < 26:
            return 'NEUTRAL'
        
        ema_12 = self._calculate_ema(closes, 12)
        ema_26 = self._calculate_ema(closes, 26)
        macd = ema_12 - ema_26
        
        # Signal simple: MACD > 0 = haussier
        if macd > 0:
            return 'BUY'
        elif macd < -0.5:
            return 'SELL'
        return 'NEUTRAL'
    
    def _calculate_bollinger_signal(self, closes):
        """Signal Bollinger Bands"""
        if len(closes) < 20:
            return 'NEUTRAL'
        
        sma_20 = sum(closes[-20:]) / 20
        variance = sum((c - sma_20) ** 2 for c in closes[-20:]) / 20
        std_dev = variance ** 0.5
        
        upper_band = sma_20 + (2 * std_dev)
        lower_band = sma_20 - (2 * std_dev)
        current_price = closes[-1]
        
        # Signal: Prix près bande basse = achat
        distance_to_lower = (current_price - lower_band) / (upper_band - lower_band)
        
        if distance_to_lower < 0.2:  # Près bande basse
            return 'BUY'
        elif distance_to_lower > 0.8:  # Près bande haute
            return 'SELL'
        return 'NEUTRAL'
    
    def _calculate_ema_crossover(self, closes):
        """Signal croisement EMA 9/21"""
        if len(closes) < 21:
            return 'NEUTRAL'
        
        ema_9 = self._calculate_ema(closes, 9)
        ema_21 = self._calculate_ema(closes, 21)
        
        if ema_9 > ema_21:
            return 'BUY'
        elif ema_9 < ema_21 * 0.98:  # 2% en dessous
            return 'SELL'
        return 'NEUTRAL'
    
    def _calculate_ema(self, prices, period):
        """Calcule EMA"""
        if len(prices) < period:
            return sum(prices) / len(prices)
        
        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period
        
        for price in prices[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        
        return ema
    
    def calculate_support_resistance_score(self, bot, symbol, current_price):
        """Score Support/Resistance (0-15 points) - Utilise PatternAnalyzer existant"""
        try:
            if not hasattr(bot, 'pattern_analyzer'):
                return 8  # Score neutre
            
            klines = bot.get_klines(symbol, 100, '4h')
            if len(klines) < 50:
                return 8
            
            levels_data = bot.pattern_analyzer.find_support_resistance_levels(klines)
            reversal_data = bot.pattern_analyzer.predict_reversal_probability(current_price, levels_data)
            
            # Scoring selon proximité et force des niveaux
            if reversal_data['has_reversal_potential']:
                probability = reversal_data['probability']
                if reversal_data['direction'] == 'UP':  # Près support = bon pour achat
                    return min(15, int(probability / 100 * 15))
                else:  # Près résistance = mauvais pour achat
                    return max(3, int((100 - probability) / 100 * 15))
            
            # Pas de niveau proche = score moyen
            return 8
            
        except Exception as e:
            return 8  # Score neutre en cas d'erreur
    
    def calculate_multi_timeframe_score(self, bot, symbol):
        """Score Multi-Timeframe (0-10 points) - Utilise TimeframeAnalyzer existant"""
        try:
            if not hasattr(bot, 'multi_tf_analyzer'):
                return 5  # Score neutre
            
            current_price = bot.get_price(symbol)
            analysis = bot.multi_tf_analyzer.analyze_all_timeframes(bot, symbol, current_price)
            
            global_signal = analysis['global_signal']
            confidence = global_signal['confidence']
            action = global_signal['action']
            
            # Scoring selon alignement des timeframes
            if action in ['STRONG_BUY', 'BUY']:
                return min(10, int(confidence / 10))  # Confidence 80% = 8 points
            elif action in ['STRONG_SELL', 'SELL']:
                return max(2, int((100 - confidence) / 10))  # Inverse pour vente
            else:  # HOLD
                return 5  # Neutre
                
        except Exception as e:
            return 5  # Score neutre en cas d'erreur
    
    def calculate_market_cap_score(self, symbol):
        """Score Market Cap (0-10 points) - Taille relative"""
        # Ranking approximatif des cryptos par market cap
        market_cap_ranking = {
            'BTC/USDT': 1,   # #1
            'ETH/USDT': 2,   # #2
            'BNB/USDT': 4,   # #4
            'SOL/USDT': 5,   # #5
            'ADA/USDT': 10,  # #10
            'DOT/USDT': 15,  # #15
            'MATIC/USDT': 20, # #20
            'AVAX/USDT': 25   # #25
        }
        
        rank = market_cap_ranking.get(symbol, 100)
        
        if rank <= 3:      # Top 3
            return 10
        elif rank <= 10:   # Top 10
            return 8
        elif rank <= 25:   # Top 25
            return 6
        elif rank <= 50:   # Top 50
            return 4
        else:              # Au-delà Top 50
            return 2
    
    def calculate_orderbook_imbalance_score(self, bot, symbol):
        """Score déséquilibre carnet d'ordres (0-15 points)"""
        try:
            orderbook = bot.exchange.fetch_order_book(symbol, limit=10)
            bid_volume = sum(bid[1] for bid in orderbook['bids'][:5])
            ask_volume = sum(ask[1] for ask in orderbook['asks'][:5])
            
            if bid_volume + ask_volume == 0:
                return 10
            
            imbalance = (bid_volume - ask_volume) / (bid_volume + ask_volume)
            
            if imbalance > 0.3:  # Plus d'acheteurs
                return 15
            elif imbalance > 0.1:
                return 12
            elif imbalance < -0.3:  # Plus de vendeurs
                return 5
            else:
                return 10
        except:
            return 10
    
    def calculate_price_action_score(self, klines):
        """Score patterns prix (0-12 points) - Doji, Hammer, etc."""
        if len(klines) < 3:
            return 6
        
        last = klines[-1]
        if last['open'] == 0:
            return 6
            
        body_size = abs(last['close'] - last['open']) / last['open']
        wick_ratio = (last['high'] - last['low']) / last['open'] if last['open'] > 0 else 0
        
        # Doji (indécision)
        if body_size < 0.001:
            return 8
        # Hammer (reversal bullish)
        elif last['close'] > last['open'] and wick_ratio > 0.02:
            return 12
        # Strong candle
        elif body_size > 0.01:
            return 10
        else:
            return 6
    
    def calculate_volume_profile_score(self, klines):
        """Score profil volume (0-18 points)"""
        if len(klines) < 20:
            return 9
        
        volumes = [k['volume'] for k in klines[-20:]]
        prices = [k['close'] for k in klines[-20:]]
        
        total_volume = sum(volumes)
        if total_volume == 0:
            return 9
        
        # Volume-weighted average price
        vwap = sum(p * v for p, v in zip(prices, volumes)) / total_volume
        current_price = prices[-1]
        
        if current_price == 0:
            return 9
            
        distance_from_vwap = abs(current_price - vwap) / current_price
        
        if distance_from_vwap < 0.01:  # Près VWAP
            return 18
        elif distance_from_vwap < 0.02:
            return 15
        else:
            return 9
    
    def calculate_momentum_divergence_score(self, klines):
        """Score divergence momentum/prix (0-16 points)"""
        if len(klines) < 20:
            return 8
        
        prices = [k['close'] for k in klines[-10:]]
        volumes = [k['volume'] for k in klines[-10:]]
        
        if prices[0] == 0 or volumes[0] == 0:
            return 8
        
        price_trend = (prices[-1] - prices[0]) / prices[0]
        volume_trend = (volumes[-1] - volumes[0]) / volumes[0]
        
        # Divergence bullish : prix baisse, volume monte
        if price_trend < -0.01 and volume_trend > 0.1:
            return 16
        # Convergence normale
        elif (price_trend > 0 and volume_trend > 0):
            return 12
        else:
            return 8
    
    def calculate_volatility_clustering_score(self, klines):
        """Score clustering volatilité (0-12 points)"""
        if len(klines) < 20:
            return 6
        
        returns = []
        for i in range(1, len(klines)):
            if klines[i-1]['close'] > 0:
                ret = (klines[i]['close'] - klines[i-1]['close']) / klines[i-1]['close']
                returns.append(abs(ret))
        
        if len(returns) < 10:
            return 6
        
        recent_vol = sum(returns[-5:]) / 5
        avg_vol = sum(returns) / len(returns)
        
        vol_ratio = recent_vol / avg_vol if avg_vol > 0 else 1
        
        if 0.8 <= vol_ratio <= 1.2:  # Volatilité stable
            return 12
        elif vol_ratio > 2.0:  # Volatilité excessive
            return 4
        else:
            return 8
    
    def calculate_fibonacci_score(self, klines):
        """Score niveaux Fibonacci (0-10 points)"""
        if len(klines) < 50:
            return 5
        
        prices = [k['close'] for k in klines]
        high = max(prices[-20:])
        low = min(prices[-20:])
        current = prices[-1]
        
        if high == low or current == 0:
            return 5
        
        # Niveaux Fibonacci
        fib_levels = {
            0.236: high - (high - low) * 0.236,
            0.382: high - (high - low) * 0.382,
            0.618: high - (high - low) * 0.618
        }
        
        for level, price in fib_levels.items():
            if abs(current - price) / current < 0.01:  # Près niveau Fib
                return 10
        
        return 5
    
    def calculate_microstructure_score(self, klines):
        """Score microstructure (0-14 points) - Tick size, gaps"""
        if len(klines) < 10:
            return 7
        
        gaps = []
        tick_sizes = []
        
        for i in range(1, len(klines)):
            if klines[i-1]['close'] > 0 and klines[i]['open'] > 0:
                # Gap entre close précédent et open actuel
                gap = abs(klines[i]['open'] - klines[i-1]['close']) / klines[i-1]['close']
                gaps.append(gap)
                
                # Tick size (plus petit mouvement)
                if klines[i]['open'] > 0:
                    tick = abs(klines[i]['close'] - klines[i]['open']) / klines[i]['open']
                    tick_sizes.append(tick)
        
        if not gaps or not tick_sizes:
            return 7
        
        avg_gap = sum(gaps) / len(gaps)
        avg_tick = sum(tick_sizes) / len(tick_sizes)
        
        # Faibles gaps + ticks réguliers = bon
        if avg_gap < 0.001 and 0.001 < avg_tick < 0.01:
            return 14
        else:
            return 7
    
    def calculate_seasonality_score(self, symbol):
        """Score saisonnalité intraday (0-10 points)"""
        hour = datetime.now().hour
        crypto = symbol.split('/')[0]
        
        # Patterns horaires par crypto (basé sur données historiques)
        hourly_patterns = {
            'BTC': {8: 12, 14: 15, 20: 10, 2: 8},  # Meilleurs à 14h UTC
            'ETH': {9: 12, 15: 14, 21: 9, 3: 7},
            'SOL': {10: 11, 16: 13, 22: 8, 4: 6}
        }
        
        pattern = hourly_patterns.get(crypto, {})
        return pattern.get(hour, 5)  # Score par défaut 5
    
    @staticmethod
    def calculate_momentum(klines):
        """Calcul momentum sur 10 dernières périodes"""
        if len(klines) < 10:
            return 0
        
        prices = np.array([k['close'] for k in klines[-10:]])
        return (prices[-1] - prices[0]) / prices[0] * 100
    
    @staticmethod
    def calculate_volume_avg(klines, periods=5):
        """Calcul volume moyen sur N périodes"""
        if len(klines) < periods:
            return 0
        
        volumes = np.array([k['volume'] for k in klines[-periods:]])
        return volumes.mean()
        
    
    @staticmethod
    def calculate_professional_volume_metrics(bot, symbol):
        """Calcul volume professionnel : 7j + moyennes mobiles + VWAP"""
        try:
            klines_7d = bot.get_klines(symbol, 672, '15m')
            if len(klines_7d) >= 672:
                return MarketAnalyzer._calculate_7d_metrics(klines_7d)
            
            klines_24h = bot.get_klines(symbol, 96, '15m')
            if len(klines_24h) >= 50:
                return MarketAnalyzer._calculate_24h_metrics(klines_24h)
            
            return None
        except:
            return None
    
    @staticmethod
    def _calculate_7d_metrics(klines_7d):
        """Métriques volume 7 jours (optimal)"""
        volumes = [k['volume'] for k in klines_7d]
        
        sma_96 = sum(volumes[-96:]) / 96
        sma_336 = sum(volumes[-336:]) / 336
        sma_672 = sum(volumes) / len(volumes)
        
        current_volume = volumes[-1]
        
        total_pv = sum(k['close'] * k['volume'] for k in klines_7d[-96:])
        total_volume = sum(k['volume'] for k in klines_7d[-96:])
        vwap = total_pv / total_volume if total_volume > 0 else 0
        
        return {
            'volume_7d': sum(volumes),
            'volume_24h': sum(volumes[-96:]),
            'sma_24h': sma_96,
            'sma_3d': sma_336,
            'sma_7d': sma_672,
            'current_volume': current_volume,
            'ratio_vs_24h': current_volume / sma_96 if sma_96 > 0 else 1,
            'ratio_vs_7d': current_volume / sma_672 if sma_672 > 0 else 1,
            'vwap_7d': vwap,
            'data_quality': 'HIGH_7D',
            'volume_trend': MarketAnalyzer._get_volume_trend_7d(sma_96, sma_336, sma_672)
        }
    
    @staticmethod
    def _calculate_24h_metrics(klines_24h):
        """Métriques volume 24h (fallback)"""
        volumes = [k['volume'] for k in klines_24h]
        sma_20 = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 0
        sma_50 = sum(volumes[-50:]) / 50 if len(volumes) >= 50 else 0
        current_volume = volumes[-1]
        
        total_pv = sum(k['close'] * k['volume'] for k in klines_24h[-20:])
        total_volume = sum(k['volume'] for k in klines_24h[-20:])
        vwap = total_pv / total_volume if total_volume > 0 else 0
        
        return {
            'volume_24h': sum(volumes),
            'sma_20': sma_20,
            'sma_50': sma_50,
            'current_volume': current_volume,
            'ratio_vs_sma20': current_volume / sma_20 if sma_20 > 0 else 1,
            'ratio_vs_sma50': current_volume / sma_50 if sma_50 > 0 else 1,
            'vwap': vwap,
            'data_quality': 'LIMITED_24H',
            'volume_trend': 'INCREASING' if current_volume / sma_20 > 1.2 else 'DECREASING' if current_volume / sma_20 < 0.8 else 'STABLE'
        }
    
    @staticmethod
    def _get_volume_trend_7d(sma_24h, sma_3d, sma_7d):
        """Tendance volume basée sur moyennes 7j"""
        if sma_24h > sma_3d * 1.2 and sma_3d > sma_7d * 1.1:
            return 'STRONG_INCREASING'
        elif sma_24h > sma_3d * 1.1:
            return 'INCREASING'
        elif sma_24h < sma_3d * 0.8 and sma_3d < sma_7d * 0.9:
            return 'STRONG_DECREASING'
        elif sma_24h < sma_3d * 0.9:
            return 'DECREASING'
        else:
            return 'STABLE'
    
    @staticmethod
    def get_volatility(bot, symbol):
        """Récupère volatilité du symbole - MÉTHODE CENTRALISÉE"""
        try:
            if bot:
                klines = bot.get_klines(symbol, 20, '15m')  # Timeframe fixe pour calcul volatilité
                if len(klines) >= 10:
                    return MarketAnalyzer.calculate_volatility(klines, symbol)
            return 2.5
        except:
            return 2.5
    
    @staticmethod
    def get_crypto_profile(volatility):
        """Profil adaptatif selon volatilité (échelle Binance 1-5)"""
        if volatility >= 4.0:
            return {
                'min_confidence': 45,
                'profit_target': 1.5,
                'confidence_adjustment': +5
            }
        elif volatility >= 3.0:
            return {
                'min_confidence': 50,
                'profit_target': 1.0,
                'confidence_adjustment': +3
            }
        elif volatility >= 2.0:
            return {
                'min_confidence': 55,
                'profit_target': 0.7,
                'confidence_adjustment': 0
            }
        else:
            return {
                'min_confidence': 60,
                'profit_target': 0.5,
                'confidence_adjustment': 0
            }
    
    @staticmethod
    def calculate_momentum_score(klines):
        """Score momentum (0-25 points)"""
        if len(klines) < 10:
            return 0
        
        momentum = MarketAnalyzer.calculate_momentum(klines)
        
        if momentum >= 1:
            return 25
        elif momentum >= 0.5:
            return 20
        elif momentum >= 0.2:
            return 15
        elif momentum >= 0:
            return 10
        elif momentum >= -0.5:
            return 8
        else:
            return 5
    
    @staticmethod
    def calculate_volume_score(klines):
        """Score volume professionnel (0-25 points) - Standards institutionnels"""
        if len(klines) < 5:
            return 0
        
        avg_volume = sum(k['volume'] for k in klines) / len(klines)
        
        if avg_volume >= 10000000:
            return 25
        elif avg_volume >= 5000000:
            return 22
        elif avg_volume >= 2000000:
            return 18
        elif avg_volume >= 1000000:
            return 15
        elif avg_volume >= 500000:
            return 10
        elif avg_volume >= 100000:
            return 5
        else:
            return 0
    
    @staticmethod
    def calculate_loss_percent(current_price, buy_price):
        """Calcul pourcentage de perte/gain"""
        return ((current_price - buy_price) / buy_price) * 100
    
    @staticmethod
    def calculate_hours_held(buy_time):
        """Calcul heures de détention"""
        return (time.time() - buy_time) / 3600
    
    def calculate_volatility_score(self, klines, symbol='', volatility=None, websocket_manager=None):
        """Score basé sur volatilité 1-5 (0-30 points) - ADAPTATIF"""
        if len(klines) < 10:
            return 0
        
        if volatility is None:
            volatility = self.calculate_volatility(klines, symbol, websocket_manager)
        
        base_points = self._get_base_volatility_points(volatility)
        crypto_multiplier = 1.2 if symbol in ['BTC/USDT', 'ETH/USDT'] else 1.0
        
        return int(base_points * crypto_multiplier)
    
    def calculate_spread_score(self, symbol, current_price):
        """Score basé sur spread estimé (0-10 points)"""
        estimated_spread = 0.01
        
        if estimated_spread <= 0.005:
            return 10
        elif estimated_spread <= 0.01:
            return 7
        elif estimated_spread <= 0.02:
            return 4
        else:
            return 2
    
    def calculate_history_score(self, symbol, stuck_positions):
        """Score basé sur historique (0-10 points)"""
        if symbol in stuck_positions:
            return 0
        
        if symbol in self.blacklist:
            blacklist_time = self.blacklist[symbol]
            if time.time() - blacklist_time < self.blacklist_duration:
                return 0
            else:
                del self.blacklist[symbol]
        
        return 10
    
    def score_crypto(self, bot, symbol, stuck_positions, websocket_manager=None, volatility=None):
        """Calcule le score total d'une crypto (0-100) - Version professionnelle 7j"""
        try:
            volatility = MarketAnalyzer.get_volatility(bot, symbol)
            optimal_timeframe = self._get_analyzer().get_main_timeframe(symbol, volatility)
            klines_7d = bot.get_klines(symbol, 672, '15m')
            klines_short = bot.get_klines(symbol, 20, optimal_timeframe)
            current_price = bot.get_price(symbol)
            
            if not klines_short or len(klines_short) < 10:
                return 0
            
            # Calculer TOUS les scores (10 facteurs)
            volatility_score = self.calculate_volatility_score(klines_short, symbol, volatility, websocket_manager)
            volume_score = self.calculate_volume_score(klines_7d) if klines_7d and len(klines_7d) >= 672 else self.calculate_volume_score(klines_short)
            momentum_score = self.calculate_momentum_score(klines_short)
            spread_score = self.calculate_spread_score(symbol, current_price)
            history_score = self.calculate_history_score(symbol, stuck_positions)
            
            # NOUVEAUX FACTEURS PROFESSIONNELS
            rsi_score = self.calculate_rsi_score(klines_short)
            correlation_score = self.calculate_correlation_score(bot, symbol)
            liquidity_score = self.calculate_liquidity_score(bot, symbol)
            technical_score = self.calculate_technical_score(klines_short)
            market_cap_score = self.calculate_market_cap_score(symbol)
            
            # FACTEURS DÉJÀ IMPLÉMENTÉS (utilise analyseurs existants)
            support_resistance_score = self.calculate_support_resistance_score(bot, symbol, current_price)
            multi_timeframe_score = self.calculate_multi_timeframe_score(bot, symbol)
            
            # 8 NOUVEAUX FACTEURS AVANCÉS
            orderbook_score = self.calculate_orderbook_imbalance_score(bot, symbol)
            price_action_score = self.calculate_price_action_score(klines_short)
            volume_profile_score = self.calculate_volume_profile_score(klines_short)
            momentum_div_score = self.calculate_momentum_divergence_score(klines_short)
            volatility_cluster_score = self.calculate_volatility_clustering_score(klines_short)
            fibonacci_score = self.calculate_fibonacci_score(klines_short)
            microstructure_score = self.calculate_microstructure_score(klines_short)
            seasonality_score = self.calculate_seasonality_score(symbol)
            
            # Déterminer qualité des données
            if klines_7d and len(klines_7d) >= 672:
                data_quality = 'HIGH_7D'
            else:
                data_quality = 'LIMITED'
            
            # Conditions de marché (nécessaire pour ponderation)
            market_conditions = {
                'avg_volatility': 2.0,  # Valeur par défaut
                'avg_volume_ratio': 1.0
            }
            
            weights = self._get_dynamic_weights(symbol, market_conditions)
            if data_quality == 'HIGH_7D':
                weights['volume'] *= 1.1  # Bonus réduit car plus de facteurs
            
            total_score = (
                volatility_score * weights['volatility'] +
                volume_score * weights['volume'] +
                momentum_score * weights['momentum'] +
                rsi_score * weights['rsi'] +
                correlation_score * weights['correlation'] +
                liquidity_score * weights['liquidity'] +
                technical_score * weights['technical'] +
                market_cap_score * weights['market_cap'] +
                support_resistance_score * weights['support_resistance'] +
                multi_timeframe_score * weights['multi_timeframe'] +
                orderbook_score * weights['orderbook'] +
                price_action_score * weights['price_action'] +
                volume_profile_score * weights['volume_profile'] +
                momentum_div_score * weights['momentum_div'] +
                volatility_cluster_score * weights['volatility_cluster'] +
                fibonacci_score * weights['fibonacci'] +
                microstructure_score * weights['microstructure'] +
                seasonality_score * weights['seasonality'] +
                spread_score * weights['spread'] +
                history_score * weights['history']
            )
            
            return min(total_score, 100)
            
        except Exception as e:
            print(f"❌ Erreur scoring {symbol}: {e}")
            return 0
    
    def rank_cryptos(self, bot, trading_pairs, stuck_positions):
        """Classe toutes les cryptos et retourne les meilleures"""
        # Calculer limites dynamiques selon capital
        balance = bot.balance_manager.get_balance()
        total_capital = balance.get('USDT', {}).get('free', 0)
        
        limits = self.get_position_limits(total_capital)
        self.max_tradeable = limits['max_tradeable_cryptos']
        
        balance = bot.balance_manager.get_balance()
        usdt_available = balance.get('USDT', {}).get('free', 0)
        
        if usdt_available <= 0:
            print(f"⚠️ Balance USDT: 0 - Aucune crypto tradable")
            return []
        
        scores = []
        volatilities = []
        volume_ratios = []
        
        for pair in trading_pairs:
            symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
            base_currency = symbol.split('/')[0]
            
            min_cost = bot.get_min_amount(symbol)['min_cost']
            
            if usdt_available < min_cost:
                continue
            
            crypto_balance = balance.get(base_currency, {}).get('free', 0)
            if crypto_balance > 0.00001:
                price = bot.get_price(symbol)
                if (crypto_balance * price) < min_cost:
                    continue
            
            optimal_timeframe = self.analyzer.get_main_timeframe(symbol, MarketAnalyzer.get_volatility(bot, symbol))
            
            klines = bot.get_klines(symbol, 20, optimal_timeframe)
            
            if not klines or len(klines) < 10:
                continue
            
            volatility = self.calculate_volatility(klines, symbol)
            volatilities.append(volatility)
            
            if len(klines) >= 5:
                current_vol = klines[-1]['volume']
                avg_vol = sum(k['volume'] for k in klines[:-1]) / (len(klines) - 1)
                vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0
                volume_ratios.append(vol_ratio)
            
            websocket_manager = getattr(bot, 'websocket', None)
            score = self.score_crypto(bot, symbol, stuck_positions, websocket_manager)
            if score > 0:
                details = self.get_score_details(bot, symbol, stuck_positions, websocket_manager)
                if details:
                    scores.append({
                        'symbol': symbol,
                        'score': score,
                        'volatility': details['volatility'],
                        'volume': details['volume'],
                        'min_cost': min_cost
                    })
        
        scores.sort(key=lambda x: x['score'], reverse=True)
        
        market_conditions = {
            'avg_volatility': sum(volatilities) / len(volatilities) if volatilities else 2.0,
            'avg_volume_ratio': sum(volume_ratios) / len(volume_ratios) if volume_ratios else 1.0,
            'klines_data': None  # Pas de klines spécifiques pour le ranking global
        }
        
        # DÉTECTION MACRO EVENT
        current_macro_event = self._get_macro_manager().detect_macro_event(market_conditions)
        
        dynamic_min_score = self._get_dynamic_min_score(
            available_count=len(scores),
            capital=usdt_available,
            market_conditions=market_conditions,
            bot=bot,
            symbol=None  # Pas de symbol spécifique pour le ranking global
        )
        
        # STOCKER le seuil calculé pour intelligent_strategy()
        self.last_dynamic_threshold = dynamic_min_score
        
        # Prendre TOUTES les cryptos qui passent le seuil, jusqu'à max_tradeable
        tradeable = []
        for c in scores:
            if c['score'] >= dynamic_min_score and len(tradeable) < self.max_tradeable:
                tradeable.append(c['symbol'])
        
        if tradeable:
            top_display = []
            for c in scores[:self.max_tradeable]:
                if c['score'] >= dynamic_min_score:
                    crypto = c['symbol'].replace('/USDT', '')
                    score = int(c['score'])
                    vol_score = c.get('volatility', 0)
                    
                    # Volatilité simplifiée
                    if vol_score >= 30:
                        vol_icon = "🔥"
                    elif vol_score >= 25:
                        vol_icon = "⚡"
                    elif vol_score >= 20:
                        vol_icon = "📊"
                    else:
                        vol_icon = "💤"
                    
                    top_display.append(f"{crypto} {score}{vol_icon}")
            
            if top_display:
                # Raisons ajustement (concis)
                reasons = []
                if usdt_available < 20:
                    reasons.append("💰-15")
                if market_conditions['avg_volatility'] < 1.5:
                    reasons.append("📉-10")
                if len(scores) < 2:
                    reasons.append("🎯-15")
                
                reason_text = f" ({' '.join(reasons)})" if reasons else ""
                print(f"🎯 {' | '.join(top_display)} → Seuil {dynamic_min_score}{reason_text}")
            else:
                print(f"⚠️ Aucune crypto ≥{dynamic_min_score} - Balance {usdt_available:.2f} USDT")
        else:
            if usdt_available > 0:
                print(f"⚠️ Aucune crypto ≥{dynamic_min_score} - Balance {usdt_available:.2f} USDT")
        
        return tradeable
    
    def add_to_blacklist(self, symbol):
        """Ajoute une crypto à la blacklist temporaire"""
        self.blacklist[symbol] = time.time()
        print(f"🚫 {symbol} ajouté à la blacklist pour {self.blacklist_duration/3600:.1f}h")
    
    def _get_default_weights(self):
        """Pondération par défaut - 20 facteurs"""
        return {
            'rsi': 0.15, 'support_resistance': 0.11, 'orderbook': 0.07,
            'correlation': 0.11, 'volume_profile': 0.08, 'multi_timeframe': 0.07,
            'momentum': 0.07, 'technical': 0.07, 'momentum_div': 0.06,
            'volatility': 0.07, 'liquidity': 0.06, 'microstructure': 0.06,
            'volume': 0.05, 'price_action': 0.05, 'volatility_cluster': 0.05,
            'fibonacci': 0.04, 'seasonality': 0.04, 'market_cap': 0.02,
            'spread': 0.01, 'history': 0.01
        }
    
    def _get_base_volatility_points(self, volatility):
        """Points de base selon volatilité"""
        if volatility >= 4.0:
            return 30
        elif volatility >= 3.0:
            return 25
        elif volatility >= 2.0:
            return 20
        elif volatility >= 1.5:
            return 10
        else:
            return 5
    
    def _get_dynamic_weights(self, symbol, market_conditions=None):
        """Pondération adaptative selon crypto ET conditions de marché - 20 Facteurs Pro"""
        # Nouvelle pondération avec 20 facteurs
        if symbol in ['BTC/USDT', 'ETH/USDT']:
            base_weights = {
                'rsi': 0.15, 'support_resistance': 0.12, 'orderbook': 0.08,
                'correlation': 0.10, 'volume_profile': 0.09, 'multi_timeframe': 0.08,
                'liquidity': 0.08, 'technical': 0.06, 'momentum': 0.05,
                'volatility': 0.06, 'momentum_div': 0.06, 'microstructure': 0.07,
                'volume': 0.04, 'price_action': 0.05, 'volatility_cluster': 0.05,
                'fibonacci': 0.04, 'seasonality': 0.04, 'market_cap': 0.03,
                'spread': 0.01, 'history': 0.01
            }
        else:
            base_weights = {
                'rsi': 0.15, 'support_resistance': 0.10, 'orderbook': 0.06,
                'correlation': 0.12, 'volume_profile': 0.07, 'multi_timeframe': 0.06,
                'momentum': 0.09, 'technical': 0.08, 'momentum_div': 0.07,
                'volatility': 0.08, 'liquidity': 0.05, 'microstructure': 0.05,
                'volume': 0.04, 'price_action': 0.04, 'volatility_cluster': 0.04,
                'fibonacci': 0.03, 'seasonality': 0.03, 'market_cap': 0.02,
                'spread': 0.01, 'history': 0.01
            }
        
        # Ajustements dynamiques selon marché
        if market_conditions:
            avg_volatility = market_conditions.get('avg_volatility', 2.0)
            avg_volume_ratio = market_conditions.get('avg_volume_ratio', 1.0)
            
            # Marché très volatil = privilégier RSI + support/resistance + orderbook
            if avg_volatility > 3.5:
                base_weights['rsi'] += 0.03
                base_weights['support_resistance'] += 0.02
                base_weights['orderbook'] += 0.02
                base_weights['momentum'] -= 0.03
                base_weights['volatility'] -= 0.02
                base_weights['volume_profile'] -= 0.02
            
            # Marché calme = privilégier multi-timeframe + liquidité + microstructure
            elif avg_volatility < 1.5:
                base_weights['multi_timeframe'] += 0.03
                base_weights['liquidity'] += 0.02
                base_weights['microstructure'] += 0.02
                base_weights['momentum'] -= 0.04
                base_weights['volatility_cluster'] -= 0.03
            
            # Volume anormal = ajuster volume_profile + momentum_div
            if avg_volume_ratio > 2.0:
                base_weights['volume_profile'] += 0.02
                base_weights['momentum_div'] += 0.02
                base_weights['spread'] -= 0.01
                base_weights['history'] -= 0.01
                base_weights['seasonality'] -= 0.02
            elif avg_volume_ratio < 0.5:
                base_weights['volume_profile'] -= 0.02
                base_weights['volatility'] += 0.02
        
        return base_weights
    
    def get_score_details(self, bot, symbol, stuck_positions, websocket_manager=None):
        """Détails du score professionnel pour debug - 20 facteurs"""
        try:
            # Calculer le score professionnel pondéré
            final_score = self.score_crypto(bot, symbol, stuck_positions, websocket_manager)
            volatility = MarketAnalyzer.get_volatility(bot, symbol)
            optimal_timeframe = self.analyzer.get_main_timeframe(symbol, volatility)
            
            klines_short = bot.get_klines(symbol, 20, optimal_timeframe)
            klines_long = bot.get_klines(symbol, 96, '15m')
            current_price = bot.get_price(symbol)
            
            if not klines_short or len(klines_short) < 10:
                return None
            
            # TOUS les composants (20 facteurs)
            volatility_raw = self.calculate_volatility_score(klines_short, symbol, None, websocket_manager)
            volume_raw = self.calculate_volume_score(klines_long if klines_long and len(klines_long) >= 50 else klines_short)
            momentum_raw = self.calculate_momentum_score(klines_short)
            rsi_raw = self.calculate_rsi_score(klines_short)
            correlation_raw = self.calculate_correlation_score(bot, symbol)
            liquidity_raw = self.calculate_liquidity_score(bot, symbol)
            technical_raw = self.calculate_technical_score(klines_short)
            market_cap_raw = self.calculate_market_cap_score(symbol)
            support_resistance_raw = self.calculate_support_resistance_score(bot, symbol, current_price)
            multi_timeframe_raw = self.calculate_multi_timeframe_score(bot, symbol)
            
            # 8 nouveaux facteurs
            orderbook_raw = self.calculate_orderbook_imbalance_score(bot, symbol)
            price_action_raw = self.calculate_price_action_score(klines_short)
            volume_profile_raw = self.calculate_volume_profile_score(klines_short)
            momentum_div_raw = self.calculate_momentum_divergence_score(klines_short)
            volatility_cluster_raw = self.calculate_volatility_clustering_score(klines_short)
            fibonacci_raw = self.calculate_fibonacci_score(klines_short)
            microstructure_raw = self.calculate_microstructure_score(klines_short)
            seasonality_raw = self.calculate_seasonality_score(symbol)
            
            return {
                'final_score': final_score,
                'volatility': volatility_raw,
                'volume': volume_raw,
                'momentum': momentum_raw,
                'rsi': rsi_raw,
                'correlation': correlation_raw,
                'liquidity': liquidity_raw,
                'technical': technical_raw,
                'market_cap': market_cap_raw,
                'support_resistance': support_resistance_raw,
                'multi_timeframe': multi_timeframe_raw,
                'orderbook': orderbook_raw,
                'price_action': price_action_raw,
                'volume_profile': volume_profile_raw,
                'momentum_div': momentum_div_raw,
                'volatility_cluster': volatility_cluster_raw,
                'fibonacci': fibonacci_raw,
                'microstructure': microstructure_raw,
                'seasonality': seasonality_raw
            }
        except Exception as e:
            return None
    
    def _detect_market_regime(self, klines_data):
        """Détection automatique du régime de marché"""
        if not klines_data or len(klines_data) < 20:
            return 'UNKNOWN'
        
        prices = [float(k['close']) for k in klines_data[-20:]]
        volumes = [float(k['volume']) for k in klines_data[-20:]]
        
        # Tendance
        sma_5 = sum(prices[-5:]) / 5
        sma_20 = sum(prices) / len(prices)
        trend_strength = (sma_5 - sma_20) / sma_20 * 100
        
        # Volatilité
        price_changes = [abs(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
        volatility = sum(price_changes) / len(price_changes) * 100
        
        # Volume trend
        vol_recent = sum(volumes[-5:]) / 5
        vol_avg = sum(volumes) / len(volumes)
        volume_ratio = vol_recent / vol_avg if vol_avg > 0 else 1
        
        if trend_strength > 1.5 and volatility < 2.0 and volume_ratio > 1.2:
            return 'BULL_TRENDING'
        elif trend_strength < -1.5 and volatility < 2.0 and volume_ratio > 1.2:
            return 'BEAR_TRENDING'
        elif volatility > 3.0:
            return 'HIGH_VOLATILITY'
        else:
            return 'SIDEWAYS'
    
    def _apply_regime_adjustment(self, base_min, market_conditions):
        """Ajustement basé sur le régime de marché"""
        if not market_conditions or 'klines_data' not in market_conditions:
            return base_min
        
        regime = self._detect_market_regime(market_conditions['klines_data'])
        
        adjustments = {
            'BULL_TRENDING': -8,
            'BEAR_TRENDING': +12,
            'HIGH_VOLATILITY': +10,
            'SIDEWAYS': +3,
            'UNKNOWN': 0
        }
        
        return base_min + adjustments.get(regime, 0)
    
    def _calculate_portfolio_risk_adjustment(self, bot, symbol):
        """Ajustement basé sur le risque portfolio"""
        if not bot or not hasattr(bot, 'positions') or not bot.positions:
            return 0
        
        existing_symbols = [pos.get('symbol', '').replace('USDT', '') for pos in bot.positions]
        
        correlation_groups = {
            'MAJOR': ['BTC', 'ETH'],
            'DEFI': ['UNI', 'AAVE', 'COMP', 'MKR'],
            'LAYER1': ['SOL', 'ADA', 'DOT', 'AVAX'],
            'MEME': ['DOGE', 'SHIB', 'PEPE']
        }
        
        current_symbol = symbol.replace('USDT', '')
        current_group = None
        
        for group, symbols in correlation_groups.items():
            if current_symbol in symbols:
                current_group = group
                break
        
        if current_group:
            same_group_count = sum(1 for sym in existing_symbols 
                                  if sym in correlation_groups.get(current_group, []))
            
            if same_group_count >= 2:
                return +15
            elif same_group_count == 1:
                return +5
        
        return -3
    
    def _get_dynamic_min_score(self, available_count, capital=None, market_conditions=None, bot=None, symbol=None):
        """Seuil minimum adaptatif professionnel - VERSION COMPLÈTE"""
        base_min = self.base_min_score
        
        # 1. Ajustements capital
        if capital and capital < 20:
            base_min -= 30  # Était 25, augmenté pour plus de cryptos
        elif capital and capital < 50:
            base_min -= 20 #15
        
        # 2. Conditions marché + régime
        if market_conditions:
            if market_conditions.get('avg_volatility', 2.0) < 1.5:
                base_min -= 10
            if market_conditions.get('avg_volume_ratio', 1.0) < 0.7:
                base_min -= 5
            
            # Régime de marché
            base_min = self._apply_regime_adjustment(base_min, market_conditions)
        
        # 3. AJUSTEMENTS MACRO EVENT
        macro_mgr = self._get_macro_manager()
        if macro_mgr.current_event:
            adjustments = macro_mgr.get_adjustments()
            base_min -= adjustments.get('threshold_reduction', 0)
            print(f"   🎯 Ajustement macro: -{adjustments.get('threshold_reduction', 0)} (Événement: {macro_mgr.current_event})")
        
        # 4. Disponibilité cryptos
        if available_count < 2:
            base_min -= 20  # Était 15, augmenté pour forcer plus de cryptos
        elif available_count < 4:
            base_min -= 10  # Était 5, augmenté
        elif available_count > 8:
            base_min += 10
        
        # 5. Performance historique
        if bot and symbol and hasattr(bot, 'trade_history'):
            recent_trades = [t for t in bot.trade_history if t.get('symbol') == symbol][-10:]
            if recent_trades:
                win_rate = sum(1 for t in recent_trades if t.get('profit', 0) > 0) / len(recent_trades)
                if win_rate > 0.7:
                    base_min -= 8
                elif win_rate < 0.4:
                    base_min += 12
        
        # 6. Risque portfolio
        if bot and symbol:
            portfolio_adj = self._calculate_portfolio_risk_adjustment(bot, symbol)
            base_min += portfolio_adj
        
        # 7. Sessions optimales
        now = datetime.now()
        if now.weekday() >= 5:
            base_min -= 5
        elif now.hour < 8 or now.hour > 22:
            base_min -= 3
        
        # Session de marché optimale
        if 14 <= now.hour <= 21:  # Session US
            base_min -= 3
        elif 8 <= now.hour <= 16:  # Session EU
            base_min -= 1
        
        return max(10, min(base_min, 80))
    

    

    @staticmethod
    def get_position_limits(total_capital):
        """
        Calcule les limites de positions selon le capital total
        
        Args:
            total_capital (float): Capital total en USDT
            
        Returns:
            dict: {
                'max_positions_per_crypto': int,
                'max_tradeable_cryptos': int,
                'total_max_positions': int
            }
        """
        if total_capital <= 10:
            return {
                'max_positions_per_crypto': 1,
                'max_tradeable_cryptos': 1,
                'total_max_positions': 1
            }
        elif total_capital <= 15:
            return {
                'max_positions_per_crypto': 1,
                'max_tradeable_cryptos': 2,
                'total_max_positions': 2
            }
        elif total_capital <= 20:
            return {
                'max_positions_per_crypto': 1,
                'max_tradeable_cryptos': 4,
                'total_max_positions': 4
            }
        elif total_capital <= 50:
            return {
                'max_positions_per_crypto': 2,
                'max_tradeable_cryptos': 4,
                'total_max_positions': 8
            }
        elif total_capital <= 100:
            return {
                'max_positions_per_crypto': 3,
                'max_tradeable_cryptos': 4,
                'total_max_positions': 12
            }
        else:
            return {
                'max_positions_per_crypto': 4,
                'max_tradeable_cryptos': 4,
                'total_max_positions': 16
            }