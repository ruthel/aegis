import numpy as np
from collections import deque
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.technical_indicators import TechnicalIndicators

class MultiTimeframeAnalyzer:
    def __init__(self):
        self.indicators = TechnicalIndicators()
        self.timeframes = ['1m', '5m', '15m']
        self.data_cache = {}  # Cache des données par timeframe
        
    def get_klines_for_timeframe(self, bot, symbol, timeframe, limit=50):
        """Récupère les données kline pour un timeframe spécifique"""
        cache_key = f"{symbol}_{timeframe}"
        
        try:
            # En réalité, on utiliserait bot.exchange.fetch_ohlcv avec le timeframe
            # Pour la simulation, on adapte les données 1m
            base_klines = bot.get_klines(symbol, limit * self.get_timeframe_multiplier(timeframe))
            
            if not base_klines:
                return []
            
            # Convertir les données selon le timeframe
            converted_klines = self.convert_to_timeframe(base_klines, timeframe)
            
            self.data_cache[cache_key] = converted_klines
            return converted_klines
            
        except Exception as e:
            print(f"Erreur récupération données {timeframe}: {e}")
            return self.data_cache.get(cache_key, [])
    
    def get_timeframe_multiplier(self, timeframe):
        """Retourne le multiplicateur pour le timeframe"""
        multipliers = {'1m': 1, '5m': 5, '15m': 15}
        return multipliers.get(timeframe, 1)
    
    def convert_to_timeframe(self, klines_1m, target_timeframe):
        """Convertit les données 1m vers le timeframe cible"""
        if target_timeframe == '1m':
            return klines_1m
        
        multiplier = self.get_timeframe_multiplier(target_timeframe)
        converted = []
        
        for i in range(0, len(klines_1m), multiplier):
            chunk = klines_1m[i:i+multiplier]
            if len(chunk) == multiplier:
                # Créer une bougie agrégée
                aggregated = {
                    'timestamp': chunk[0]['timestamp'],
                    'open': chunk[0]['open'],
                    'high': max(k['high'] for k in chunk),
                    'low': min(k['low'] for k in chunk),
                    'close': chunk[-1]['close'],
                    'volume': sum(k['volume'] for k in chunk)
                }
                converted.append(aggregated)
        
        return converted
    
    def analyze_timeframe(self, klines, current_price):
        """Analyse un timeframe spécifique"""
        if len(klines) < 30:
            return {'trend': 'unknown', 'strength': 0, 'signals': []}
        
        closes = [k['close'] for k in klines]
        
        # Calculer les indicateurs
        rsi = self.indicators.calculate_rsi(closes)
        macd, signal, histogram = self.indicators.calculate_macd(closes)
        upper_bb, middle_bb, lower_bb = self.indicators.calculate_bollinger_bands(closes)
        ema_20 = self.indicators.calculate_ema(closes, 20)
        ema_50 = self.indicators.calculate_ema(closes, 50)
        
        # Analyser la tendance
        trend = self.determine_trend(closes, ema_20, ema_50)
        
        # Analyser les signaux
        signals = []
        strength = 0
        
        # Signal RSI
        if rsi is not None:
            if rsi < 30:
                signals.append("RSI survente")
                strength += 1
            elif rsi > 70:
                signals.append("RSI surachat")
                strength -= 1
        
        # Signal MACD
        if macd is not None and signal is not None:
            if macd > signal and histogram > 0:
                signals.append("MACD haussier")
                strength += 1
            elif macd < signal and histogram < 0:
                signals.append("MACD baissier")
                strength -= 1
        
        # Signal Bollinger Bands
        if lower_bb is not None and upper_bb is not None:
            if current_price <= lower_bb:
                signals.append("BB support")
                strength += 1
            elif current_price >= upper_bb:
                signals.append("BB résistance")
                strength -= 1
        
        # Signal EMA
        if ema_20 is not None and ema_50 is not None:
            if ema_20 > ema_50:
                signals.append("EMA haussier")
                strength += 0.5
            else:
                signals.append("EMA baissier")
                strength -= 0.5
        
        return {
            'trend': trend,
            'strength': strength,
            'signals': signals,
            'indicators': {
                'rsi': rsi,
                'macd': macd,
                'bb_position': self.get_bb_position(current_price, upper_bb, middle_bb, lower_bb),
                'ema_trend': 'bullish' if ema_20 and ema_50 and ema_20 > ema_50 else 'bearish'
            }
        }
    
    def determine_trend(self, closes, ema_20, ema_50):
        """Détermine la tendance générale"""
        if not ema_20 or not ema_50:
            return 'unknown'
        
        current_price = closes[-1]
        
        # Tendance basée sur les EMAs et le prix
        if ema_20 > ema_50 and current_price > ema_20:
            return 'bullish'
        elif ema_20 < ema_50 and current_price < ema_20:
            return 'bearish'
        else:
            return 'neutral'
    
    def get_bb_position(self, price, upper, middle, lower):
        """Position du prix par rapport aux Bollinger Bands"""
        if not all([upper, middle, lower]):
            return 'unknown'
        
        if price >= upper:
            return 'above_upper'
        elif price <= lower:
            return 'below_lower'
        elif price > middle:
            return 'above_middle'
        else:
            return 'below_middle'
    
    def analyze_all_timeframes(self, bot, symbol, current_price):
        """Analyse tous les timeframes et génère un signal global"""
        timeframe_analysis = {}
        
        # Analyser chaque timeframe
        for tf in self.timeframes:
            klines = self.get_klines_for_timeframe(bot, symbol, tf)
            analysis = self.analyze_timeframe(klines, current_price)
            timeframe_analysis[tf] = analysis
        
        # Générer le signal global
        global_signal = self.generate_global_signal(timeframe_analysis, current_price)
        
        return {
            'timeframes': timeframe_analysis,
            'global_signal': global_signal,
            'timestamp': bot.exchange.milliseconds() if hasattr(bot, 'exchange') else None
        }
    
    def generate_global_signal(self, timeframe_analysis, current_price):
        """Génère un signal global basé sur tous les timeframes"""
        # Pondération des timeframes (15m plus important que 1m)
        weights = {'15m': 3, '5m': 2, '1m': 1}
        
        total_strength = 0
        max_weight = 0
        trend_votes = {'bullish': 0, 'bearish': 0, 'neutral': 0}
        all_signals = []
        
        for tf, analysis in timeframe_analysis.items():
            weight = weights.get(tf, 1)
            strength = analysis['strength']
            trend = analysis['trend']
            
            # Accumuler la force pondérée
            total_strength += strength * weight
            max_weight += weight
            
            # Voter pour la tendance
            trend_votes[trend] += weight
            
            # Collecter les signaux
            for signal in analysis['signals']:
                all_signals.append(f"{tf}: {signal}")
        
        # Calculer la force moyenne pondérée
        avg_strength = total_strength / max_weight if max_weight > 0 else 0
        
        # Déterminer la tendance dominante
        dominant_trend = max(trend_votes, key=trend_votes.get)
        
        # Générer l'action recommandée
        action = self.determine_action(avg_strength, dominant_trend, timeframe_analysis)
        
        # Calculer le score de confiance
        confidence = self.calculate_confidence(timeframe_analysis, avg_strength)
        
        return {
            'action': action,
            'strength': avg_strength,
            'confidence': confidence,
            'dominant_trend': dominant_trend,
            'signals': all_signals[:5],  # Top 5 signaux
            'summary': self.generate_summary(action, avg_strength, dominant_trend, confidence)
        }
    
    def determine_action(self, avg_strength, dominant_trend, timeframe_analysis):
        """Détermine l'action recommandée"""
        # Seuils pour les actions
        strong_buy_threshold = 2.0
        buy_threshold = 1.0
        sell_threshold = -1.0
        strong_sell_threshold = -2.0
        
        # Vérifier la cohérence entre timeframes
        trends = [analysis['trend'] for analysis in timeframe_analysis.values()]
        trend_consistency = trends.count(dominant_trend) / len(trends)
        
        # Ajuster la force selon la cohérence
        adjusted_strength = avg_strength * trend_consistency
        
        if adjusted_strength >= strong_buy_threshold:
            return 'STRONG_BUY'
        elif adjusted_strength >= buy_threshold:
            return 'BUY'
        elif adjusted_strength <= strong_sell_threshold:
            return 'STRONG_SELL'
        elif adjusted_strength <= sell_threshold:
            return 'SELL'
        else:
            return 'HOLD'
    
    def calculate_confidence(self, timeframe_analysis, avg_strength):
        """Calcule le score de confiance (0-100)"""
        # Facteurs de confiance
        strength_factor = min(abs(avg_strength) / 3.0, 1.0)  # Force du signal
        
        # Cohérence entre timeframes
        trends = [analysis['trend'] for analysis in timeframe_analysis.values()]
        dominant_trend = max(set(trends), key=trends.count)
        consistency_factor = trends.count(dominant_trend) / len(trends)
        
        # Nombre de signaux confirmés
        total_signals = sum(len(analysis['signals']) for analysis in timeframe_analysis.values())
        signal_factor = min(total_signals / 10.0, 1.0)
        
        # Score final (0-100)
        confidence = (strength_factor * 0.4 + consistency_factor * 0.4 + signal_factor * 0.2) * 100
        
        return round(confidence, 1)
    
    def generate_summary(self, action, strength, trend, confidence):
        """Génère un résumé textuel de l'analyse"""
        strength_desc = "forte" if abs(strength) > 2 else "modérée" if abs(strength) > 1 else "faible"
        trend_desc = {"bullish": "haussière", "bearish": "baissière", "neutral": "neutre"}[trend]
        
        return f"{action} - Tendance {trend_desc}, force {strength_desc} (confiance: {confidence}%)"