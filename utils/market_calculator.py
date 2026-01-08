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
    def calculate_professional_volume_metrics(bot, symbol):
        """Calcul volume professionnel : 7j + moyennes mobiles + VWAP"""
        try:
            # 1. Essayer d'abord 7 jours (optimal)
            klines_7d = bot.get_klines(symbol, 672, '15m')  # 7j en 15m
            if len(klines_7d) >= 672:
                return MarketCalculator._calculate_7d_metrics(klines_7d)
            
            # 2. Fallback 24h si 7j indisponible
            klines_24h = bot.get_klines(symbol, 96, '15m')  # 24h en 15m
            if len(klines_24h) >= 50:
                return MarketCalculator._calculate_24h_metrics(klines_24h)
            
            return None
        except:
            return None
    
    @staticmethod
    def _calculate_7d_metrics(klines_7d):
        """Métriques volume 7 jours (optimal)"""
        volumes = [k['volume'] for k in klines_7d]
        
        # Moyennes mobiles 7j
        sma_96 = sum(volumes[-96:]) / 96    # 24h
        sma_336 = sum(volumes[-336:]) / 336  # 3.5j
        sma_672 = sum(volumes) / len(volumes)  # 7j complets
        
        current_volume = volumes[-1]
        
        # VWAP 7j (plus précis)
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
            'volume_trend': MarketCalculator._get_volume_trend_7d(sma_96, sma_336, sma_672)
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
        """Score volume professionnel (0-25 points) - Standards institutionnels"""
        if len(klines) < 5:
            return 0
        
        # Utiliser volume moyen sur période complète (plus stable)
        avg_volume = sum(k['volume'] for k in klines) / len(klines)
        
        # Seuils professionnels basés sur liquidité réelle
        if avg_volume >= 10000000:     # 10M+ = Liquidité institutionnelle
            return 25
        elif avg_volume >= 5000000:    # 5M+ = Très bonne liquidité
            return 22
        elif avg_volume >= 2000000:    # 2M+ = Bonne liquidité
            return 18
        elif avg_volume >= 1000000:    # 1M+ = Liquidité acceptable
            return 15
        elif avg_volume >= 500000:     # 500K+ = Liquidité minimale
            return 10
        elif avg_volume >= 100000:     # 100K+ = Très faible
            return 5
        else:
            return 0  # < 100K = Illiquide
    
    @staticmethod
    def calculate_loss_percent(current_price, buy_price):
        """Calcul pourcentage de perte/gain"""
        return ((current_price - buy_price) / buy_price) * 100
    
    @staticmethod
    def calculate_hours_held(buy_time):
        """Calcul heures de détention"""
        import time
        return (time.time() - buy_time) / 3600
