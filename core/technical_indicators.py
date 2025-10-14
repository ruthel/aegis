import numpy as np
from collections import deque

class TechnicalIndicators:
    def __init__(self):
        self.cache = {}
        
    def calculate_rsi(self, prices, period=14):
        """Calcule le RSI (Relative Strength Index)"""
        if len(prices) < period + 1:
            return None
            
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])
        
        if avg_loss == 0:
            return 100
            
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def calculate_macd(self, prices, fast=12, slow=26, signal=9):
        """Calcule le MACD"""
        if len(prices) < slow:
            return None, None, None
            
        prices = np.array(prices)
        
        # EMA rapide et lente
        ema_fast = self.calculate_ema(prices, fast)
        ema_slow = self.calculate_ema(prices, slow)
        
        if ema_fast is None or ema_slow is None:
            return None, None, None
            
        # Ligne MACD
        macd_line = ema_fast - ema_slow
        
        # Signal line (EMA du MACD)
        signal_line = self.calculate_ema([macd_line], signal)
        
        # Histogramme
        histogram = macd_line - (signal_line or 0)
        
        return macd_line, signal_line, histogram
    
    def calculate_ema(self, prices, period):
        """Calcule l'EMA (Exponential Moving Average)"""
        if len(prices) < period:
            return None
            
        prices = np.array(prices)
        multiplier = 2 / (period + 1)
        
        # Première valeur = SMA
        ema = np.mean(prices[:period])
        
        # Calcul EMA pour le reste
        for price in prices[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
            
        return ema
    
    def calculate_bollinger_bands(self, prices, period=20, std_dev=2):
        """Calcule les Bollinger Bands"""
        if len(prices) < period:
            return None, None, None
            
        prices = np.array(prices)
        
        # Moyenne mobile simple
        sma = np.mean(prices[-period:])
        
        # Écart-type
        std = np.std(prices[-period:])
        
        # Bandes
        upper_band = sma + (std * std_dev)
        lower_band = sma - (std * std_dev)
        
        return upper_band, sma, lower_band
    
    def calculate_volume_profile(self, klines):
        """Analyse le profil de volume"""
        if len(klines) < 10:
            return {'trend': 'neutral', 'strength': 0}
            
        volumes = [k['volume'] for k in klines[-10:]]
        avg_volume = np.mean(volumes)
        current_volume = volumes[-1]
        
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1
        
        if volume_ratio > 1.5:
            return {'trend': 'strong', 'strength': min(volume_ratio, 3)}
        elif volume_ratio > 1.2:
            return {'trend': 'moderate', 'strength': volume_ratio}
        else:
            return {'trend': 'weak', 'strength': volume_ratio}

class SignalGenerator:
    def __init__(self):
        self.indicators = TechnicalIndicators()
        self.signal_history = deque(maxlen=10)
        
    def analyze_signals(self, symbol, klines, current_price):
        """Génère des signaux de trading basés sur les indicateurs"""
        if len(klines) < 30:
            return {'action': 'HOLD', 'strength': 0, 'reason': 'Données insuffisantes'}
        
        # Extraire les prix de clôture
        closes = [k['close'] for k in klines]
        
        # Calculer les indicateurs
        rsi = self.indicators.calculate_rsi(closes)
        macd, signal, histogram = self.indicators.calculate_macd(closes)
        upper_bb, middle_bb, lower_bb = self.indicators.calculate_bollinger_bands(closes)
        volume_profile = self.indicators.calculate_volume_profile(klines)
        
        signals = []
        strength = 0
        
        # Signal RSI
        if rsi is not None:
            if rsi < 30:  # Survente
                signals.append("RSI survente")
                strength += 2
            elif rsi > 70:  # Surachat
                signals.append("RSI surachat")
                strength -= 2
        
        # Signal MACD
        if macd is not None and signal is not None:
            if macd > signal and histogram > 0:  # Croisement haussier
                signals.append("MACD haussier")
                strength += 1.5
            elif macd < signal and histogram < 0:  # Croisement baissier
                signals.append("MACD baissier")
                strength -= 1.5
        
        # Signal Bollinger Bands
        if lower_bb is not None and upper_bb is not None:
            if current_price <= lower_bb:  # Prix touche bande basse
                signals.append("BB support")
                strength += 1
            elif current_price >= upper_bb:  # Prix touche bande haute
                signals.append("BB résistance")
                strength -= 1
        
        # Signal Volume
        if volume_profile['trend'] == 'strong':
            if strength > 0:  # Renforce signal haussier
                signals.append("Volume fort")
                strength *= 1.3
            elif strength < 0:  # Renforce signal baissier
                signals.append("Volume fort")
                strength *= 1.3
        
        # Déterminer l'action
        if strength >= 2:
            action = 'BUY'
        elif strength <= -2:
            action = 'SELL'
        else:
            action = 'HOLD'
        
        signal_data = {
            'action': action,
            'strength': abs(strength),
            'reason': ' + '.join(signals) if signals else 'Aucun signal fort',
            'indicators': {
                'rsi': rsi,
                'macd': macd,
                'bb_position': self._get_bb_position(current_price, upper_bb, middle_bb, lower_bb),
                'volume': volume_profile
            }
        }
        
        # Ajouter à l'historique
        self.signal_history.append({
            'timestamp': klines[-1]['timestamp'],
            'symbol': symbol,
            'signal': signal_data
        })
        
        return signal_data
    
    def _get_bb_position(self, price, upper, middle, lower):
        """Détermine la position du prix par rapport aux Bollinger Bands"""
        if upper is None or lower is None:
            return 'unknown'
            
        if price >= upper:
            return 'above_upper'
        elif price <= lower:
            return 'below_lower'
        elif price > middle:
            return 'above_middle'
        else:
            return 'below_middle'
    
    def get_signal_summary(self, symbol):
        """Résumé des derniers signaux"""
        recent_signals = [s for s in self.signal_history if s['symbol'] == symbol]
        if not recent_signals:
            return "Aucun signal récent"
            
        last_signal = recent_signals[-1]['signal']
        return f"{last_signal['action']} ({last_signal['strength']:.1f}) - {last_signal['reason']}"