import time

class VolatilityCalculator:
    """Calculateur centralisé de volatilité avec cache"""
    
    _instance = None
    _cache = {}
    _cache_timeout = 300  # 5 minutes
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    def calculate(cls, klines, symbol=''):
        """
        Calcule la volatilité temps réel - Score 1-5 pour scalping
        
        Args:
            klines: Liste de klines avec 'close' prices (1m)
            symbol: Symbole pour le cache (optionnel)
        
        Returns:
            float: Score volatilité 1-5 (1=calme, 5=très volatil)
        """
        # Vérifier cache si symbol fourni
        if symbol and symbol in cls._cache:
            cache_data = cls._cache[symbol]
            if time.time() - cache_data['timestamp'] < cls._cache_timeout:
                return cache_data['volatility']
        
        try:
            if len(klines) < 10:
                return 2.0
            
            # Prendre les données récentes
            recent_klines = klines[-60:] if len(klines) >= 60 else klines[-20:]
            closes = [k['close'] for k in recent_klines if 'close' in k]
            
            if len(closes) < 10:
                return 2.0
            
            # Calcul ATR (Average True Range) temps réel
            true_ranges = []
            for i in range(1, len(recent_klines)):
                high = recent_klines[i].get('high', closes[i])
                low = recent_klines[i].get('low', closes[i])
                prev_close = closes[i-1]
                
                tr = max(
                    high - low,
                    abs(high - prev_close),
                    abs(low - prev_close)
                )
                true_ranges.append(tr)
            
            if not true_ranges:
                return 2.0
            
            atr = sum(true_ranges) / len(true_ranges)
            current_price = closes[-1]
            
            # Volatilité horaire en % (ATR sur 60 bougies 1m = 1h)
            volatility_hourly = (atr / current_price) * 100
            
            # Mapper vers score 1-5 pour scalping temps réel
            # 0-0.8% horaire → 1/5 (très calme)
            # 0.8-1.6% horaire → 2/5 (calme)
            # 1.6-3.2% horaire → 3/5 (moyen)
            # 3.2-4.8% horaire → 4/5 (volatil)
            # 4.8%+ horaire → 5/5 (très volatil)
            volatility_score = min(max(volatility_hourly * 1.25, 1.0), 5.0)
            
            # Mettre en cache
            if symbol:
                cls._cache[symbol] = {
                    'volatility': volatility_score,
                    'timestamp': time.time()
                }
            
            return volatility_score
            
        except Exception as e:
            return 2.0
    
    @classmethod
    def clear_cache(cls, symbol=None):
        """Vide le cache (tout ou un symbole spécifique)"""
        if symbol:
            cls._cache.pop(symbol, None)
        else:
            cls._cache.clear()
