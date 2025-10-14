"""
Optimisation 5: Cache adaptatif multi-niveaux
TTL dynamique selon volatilité + réduction données
"""
import time

class AdaptiveCache:
    def __init__(self):
        self.cache = {}
        self.ttl_config = {
            'balance': 30,      # Change rarement
            'min_amounts': 3600,  # Constant
            'price_stable': 2,   # Marché calme
            'price_volatile': 0.5,  # Marché agité
            'klines_stable': 5,
            'klines_volatile': 1,
            'score': 60
        }
    
    def get(self, key, default=None):
        """Récupère depuis cache si valide"""
        if key not in self.cache:
            return default
        
        entry = self.cache[key]
        age = time.time() - entry['timestamp']
        
        if age < entry['ttl']:
            return entry['data']
        
        # Expiré
        del self.cache[key]
        return default
    
    def set(self, key, data, ttl=None, volatility=None):
        """Stocke avec TTL adaptatif"""
        if ttl is None:
            # TTL adaptatif selon volatilité
            if 'price' in key:
                ttl = self.ttl_config['price_volatile'] if volatility and volatility > 3 else self.ttl_config['price_stable']
            elif 'klines' in key:
                ttl = self.ttl_config['klines_volatile'] if volatility and volatility > 3 else self.ttl_config['klines_stable']
            elif 'balance' in key:
                ttl = self.ttl_config['balance']
            elif 'min_amounts' in key:
                ttl = self.ttl_config['min_amounts']
            else:
                ttl = 5
        
        self.cache[key] = {
            'data': data,
            'timestamp': time.time(),
            'ttl': ttl
        }
    
    def invalidate(self, pattern):
        """Invalide cache par pattern"""
        keys_to_delete = [k for k in self.cache.keys() if pattern in k]
        for key in keys_to_delete:
            del self.cache[key]
    
    def get_klines_compressed(self, symbol):
        """Récupère klines compressés (seulement close/volume)"""
        key = f'klines_compressed_{symbol}'
        return self.get(key)
    
    def set_klines_compressed(self, symbol, klines, volatility=None):
        """Stocke klines compressés (économie mémoire 60%)"""
        # Garder seulement close + volume
        compressed = [{'close': k['close'], 'volume': k['volume']} for k in klines]
        key = f'klines_compressed_{symbol}'
        self.set(key, compressed, volatility=volatility)
    
    def get_adaptive_klines_count(self, volatility):
        """Nombre klines adaptatif selon volatilité"""
        if volatility > 5:
            return 20  # Marché volatil = plus de données
        elif volatility > 2:
            return 15
        else:
            return 10  # Marché calme = moins de données
