"""Analyseur EMA Binance Style - Détection des 6 cas de configuration"""

class BinanceEMAAnalyzer:
    def __init__(self):
        # Périodes EMA adaptatives (seront calculées dynamiquement)
        self.default_periods = {'short': 7, 'medium': 25, 'long': 99}
    
    def calculate_ema(self, prices, period):
        """Calcule l'EMA pour une période donnée"""
        if len(prices) < period:
            return None
        
        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period
        
        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema
        
        return ema
    
    def analyze(self, klines, current_price, symbol=None, timeframe='15m'):
        """Analyse complète EMA 7/25/99 et détection du cas"""
        if len(klines) < 99:
            return None
        
        # Périodes EMA adaptatives selon timeframe et volatilité
        try:
            from utils.timeframe_manager import TimeframeManager
            ema_periods = TimeframeManager.get_ema_periods(symbol or 'BTC/USDT', timeframe)
            ema_short_period = ema_periods['short']
            ema_medium_period = ema_periods['medium'] 
            ema_long_period = ema_periods['long']
        except:
            # Fallback périodes par défaut
            ema_short_period = self.default_periods['short']
            ema_medium_period = self.default_periods['medium']
            ema_long_period = self.default_periods['long']
        
        closes = [k['close'] for k in klines]
        
        ema_7 = self.calculate_ema(closes, ema_short_period)
        ema_25 = self.calculate_ema(closes, ema_medium_period)
        ema_99 = self.calculate_ema(closes, ema_long_period)
        
        if not all([ema_7, ema_25, ema_99]):
            return None
        
        # Détection du cas (1-6)
        case = self.detect_case(current_price, ema_7, ema_25, ema_99)
        
        return {
            'ema_7': ema_7,
            'ema_25': ema_25,
            'ema_99': ema_99,
            'case': case['number'],
            'case_name': case['name'],
            'signal': case['signal'],
            'probability': case['probability'],
            'description': case['description']
        }
    
    def detect_case(self, price, ema_7, ema_25, ema_99):
        """Détecte le cas de configuration (1-6)"""
        
        # Cas 1: Tendance Haussière Forte
        if price > ema_7 > ema_25 > ema_99:
            return {
                'number': 1,
                'name': 'Haussier Fort',
                'signal': 'STRONG_BUY',
                'probability': 85,
                'description': 'Toutes périodes haussières - Momentum fort'
            }
        
        # Cas 2: Tendance Haussière Modérée
        elif (price > ema_7 > ema_99 > ema_25) or (ema_7 > price > ema_25 > ema_99):
            return {
                'number': 2,
                'name': 'Haussier Modéré',
                'signal': 'BUY',
                'probability': 70,
                'description': 'Tendance haussière avec consolidation'
            }
        
        # Cas 3: Pullback Haussier (VOTRE STRATÉGIE!)
        elif ema_7 > ema_25 > price > ema_99:
            return {
                'number': 3,
                'name': 'Pullback Haussier',
                'signal': 'BUY',
                'probability': 75,
                'description': 'Correction dans tendance haussière - Opportunité!'
            }
        
        # Cas 4: Rebond Baissier
        elif ema_99 > price > ema_25 > ema_7:
            return {
                'number': 4,
                'name': 'Rebond Baissier',
                'signal': 'SELL',
                'probability': 70,
                'description': 'Rebond temporaire dans tendance baissière'
            }
        
        # Cas 5: Tendance Baissière Modérée
        elif (ema_99 > ema_25 > price > ema_7) or (ema_25 > ema_99 > price > ema_7):
            return {
                'number': 5,
                'name': 'Baissier Modéré',
                'signal': 'SELL',
                'probability': 70,
                'description': 'Tendance baissière avec rebonds possibles'
            }
        
        # Cas 6: Tendance Baissière Forte
        elif ema_99 > ema_25 > ema_7 > price:
            return {
                'number': 6,
                'name': 'Baissier Fort',
                'signal': 'STRONG_SELL',
                'probability': 85,
                'description': 'Toutes périodes baissières - Momentum négatif'
            }
        
        # Cas indéterminé
        else:
            return {
                'number': 0,
                'name': 'Neutre',
                'signal': 'HOLD',
                'probability': 50,
                'description': 'Configuration mixte - Attente confirmation'
            }
    
    def get_ema_trend(self, ema_7, ema_25, ema_99):
        """Détermine la tendance générale des EMA"""
        if ema_7 > ema_25 > ema_99:
            return 'bullish'
        elif ema_99 > ema_25 > ema_7:
            return 'bearish'
        else:
            return 'neutral'
