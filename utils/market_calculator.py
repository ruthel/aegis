"""
Calculateur centralisé pour métriques de marché
Évite duplication de code entre crypto_scorer, numpy_optimizer, etc.
"""
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

class MarketCalculator:
    """Calculs de marché centralisés et optimisés"""
    
    @staticmethod
    def calculate_momentum(klines):
        """Calcul momentum sur 10 dernières périodes"""
        if len(klines) < 10:
            return 0
        
        if NUMPY_AVAILABLE:
            prices = np.array([k['close'] for k in klines[-10:]])
            return (prices[-1] - prices[0]) / prices[0] * 100
        
        prices = [k['close'] for k in klines[-10:]]
        return (prices[-1] - prices[0]) / prices[0] * 100
    
    @staticmethod
    def calculate_volume_avg(klines, periods=5):
        """Calcul volume moyen sur N périodes"""
        if len(klines) < periods:
            return 0
        
        if NUMPY_AVAILABLE:
            volumes = np.array([k['volume'] for k in klines[-periods:]])
            return volumes.mean()
        
        return sum(k['volume'] for k in klines[-periods:]) / periods
    
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
        
        momentum = MarketCalculator.calculate_momentum(klines)
        
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
        """Score volume (0-25 points)"""
        if len(klines) < 5:
            return 0
        
        avg_volume = MarketCalculator.calculate_volume_avg(klines)
        
        if avg_volume >= 5000000:
            return 25
        elif avg_volume >= 1000000:
            return 20
        elif avg_volume >= 500000:
            return 15
        elif avg_volume >= 100000:
            return 10
        else:
            return 5
    
    @staticmethod
    def calculate_loss_percent(current_price, buy_price):
        """Calcul pourcentage de perte/gain"""
        return ((current_price - buy_price) / buy_price) * 100
    
    @staticmethod
    def calculate_hours_held(buy_time):
        """Calcul heures de détention"""
        import time
        return (time.time() - buy_time) / 3600
