"""
Optimiseur de Timing - QUAND acheter (60% → 90% pro level)
Confluence multi-timeframes + Market Structure + Momentum
"""

import numpy as np
from datetime import datetime, timedelta

class TimingOptimizer:
    def __init__(self, bot):
        self.bot = bot
        self.cache = {}
        self.cache_duration = 60  # 1 minute
    
    def get_optimal_timing(self, symbol, signal_strength):
        """Détermine le timing optimal pour l'entrée"""
        cache_key = f"{symbol}_timing"
        now = datetime.now()
        
        # Vérifier cache
        if (cache_key in self.cache and 
            (now - self.cache[cache_key]['timestamp']).seconds < self.cache_duration):
            return self.cache[cache_key]['timing']
        
        timing_score = self._calculate_timing_confluence(symbol, signal_strength)
        
        # Cache résultat
        self.cache[cache_key] = {
            'timing': timing_score,
            'timestamp': now
        }
        
        return timing_score
    
    def _calculate_timing_confluence(self, symbol, signal_strength):
        """Calcule la confluence de timing multi-timeframes"""
        try:
            # 1. HTF Bias (4H trend)
            htf_bias = self._get_htf_bias(symbol)
            
            # 2. Market Structure (BOS/CHoCH)
            structure_score = self._analyze_market_structure(symbol)
            
            # 3. Momentum Alignment
            momentum_score = self._check_momentum_alignment(symbol)
            
            # 4. Volume Confirmation
            volume_score = self._analyze_volume_confirmation(symbol)
            
            # 5. Time-based filters
            time_score = self._check_optimal_time()
            
            # Confluence finale (pondérée)
            confluence = (
                htf_bias * 0.3 +
                structure_score * 0.25 +
                momentum_score * 0.2 +
                volume_score * 0.15 +
                time_score * 0.1
            )
            
            # Ajuster selon force du signal
            final_score = confluence * (signal_strength / 100)
            
            return {
                'score': final_score,
                'components': {
                    'htf_bias': htf_bias,
                    'structure': structure_score,
                    'momentum': momentum_score,
                    'volume': volume_score,
                    'time': time_score
                },
                'action': self._get_timing_action(final_score)
            }
            
        except Exception as e:
            print(f"⚠️ Erreur timing optimizer {symbol}: {e}")
            return {'score': 0.5, 'action': 'WAIT'}
    
    def _get_htf_bias(self, symbol):
        """Analyse bias Higher TimeFrame (4H)"""
        try:
            klines = self.bot.get_klines(symbol, 24, '4h')  # 4 jours
            if len(klines) < 10:
                return 0.5
            
            # EMA 20 sur 4H
            closes = [k['close'] for k in klines]
            ema20 = self._calculate_ema(closes, 20)
            current_price = closes[-1]
            
            # Trend strength
            if current_price > ema20[-1]:
                trend_strength = min((current_price - ema20[-1]) / ema20[-1] * 100, 1.0)
                return 0.5 + trend_strength * 0.5  # 0.5 à 1.0
            else:
                return 0.3  # Bias baissier
                
        except:
            return 0.5
    
    def _analyze_market_structure(self, symbol):
        """Analyse structure de marché (BOS/CHoCH)"""
        try:
            klines = self.bot.get_klines(symbol, 50, '15m')
            if len(klines) < 20:
                return 0.5
            
            highs = [k['high'] for k in klines]
            lows = [k['low'] for k in klines]
            
            # Détecter Break of Structure (BOS)
            recent_high = max(highs[-10:])
            previous_high = max(highs[-20:-10])
            
            if recent_high > previous_high:
                return 0.8  # BOS bullish
            else:
                return 0.4  # Pas de BOS
                
        except:
            return 0.5
    
    def _check_momentum_alignment(self, symbol):
        """Vérifie alignement momentum multi-TF"""
        try:
            # 15M momentum
            klines_15m = self.bot.get_klines(symbol, 20, '15m')
            momentum_15m = self._calculate_rsi(klines_15m, 14)
            
            # 5M momentum
            klines_5m = self.bot.get_klines(symbol, 20, '5m')
            momentum_5m = self._calculate_rsi(klines_5m, 14)
            
            # Alignement bullish
            if momentum_15m > 50 and momentum_5m > 50:
                return 0.8
            elif momentum_15m > 50 or momentum_5m > 50:
                return 0.6
            else:
                return 0.3
                
        except:
            return 0.5
    
    def _analyze_volume_confirmation(self, symbol):
        """Analyse confirmation volume"""
        try:
            klines = self.bot.get_klines(symbol, 20, '5m')
            if len(klines) < 10:
                return 0.5
            
            volumes = [k['volume'] for k in klines if k['volume'] > 0]
            if len(volumes) < 5:
                return 0.5
            
            avg_volume = sum(volumes[:-3]) / len(volumes[:-3])
            recent_volume = sum(volumes[-3:]) / 3
            
            volume_ratio = recent_volume / avg_volume if avg_volume > 0 else 1
            
            if volume_ratio > 1.5:
                return 0.9  # Volume élevé
            elif volume_ratio > 1.2:
                return 0.7
            else:
                return 0.4
                
        except:
            return 0.5
    
    def _check_optimal_time(self):
        """Vérifie si c'est un moment optimal pour trader"""
        now = datetime.now()
        hour = now.hour
        
        # Sessions optimales (UTC)
        if 8 <= hour <= 16:  # Session européenne + US overlap
            return 0.8
        elif 0 <= hour <= 4:  # Session asiatique
            return 0.6
        else:
            return 0.4  # Faible liquidité
    
    def _calculate_ema(self, prices, period):
        """Calcule EMA"""
        if len(prices) < period:
            return [prices[-1]] * len(prices)
        
        ema = [sum(prices[:period]) / period]
        multiplier = 2 / (period + 1)
        
        for price in prices[period:]:
            ema.append((price * multiplier) + (ema[-1] * (1 - multiplier)))
        
        return ema
    
    def _calculate_rsi(self, klines, period=14):
        """Calcule RSI"""
        if len(klines) < period + 1:
            return 50
        
        closes = [k['close'] for k in klines]
        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def _get_timing_action(self, score):
        """Détermine l'action selon le score"""
        if score >= 0.8:
            return 'BUY_NOW'
        elif score >= 0.6:
            return 'BUY_READY'
        elif score >= 0.4:
            return 'WAIT'
        else:
            return 'AVOID'