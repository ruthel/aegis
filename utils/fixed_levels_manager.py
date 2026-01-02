import os

class FixedLevelsManager:
    """Gestionnaire des niveaux fixes pour achats automatiques"""
    
    def __init__(self):
        self.levels = self.load_levels()
    
    def load_levels(self):
        """Charge les niveaux depuis .env"""
        levels = {}
        cryptos = ['BTC', 'ETH', 'SOL', 'BNB']
        
        for crypto in cryptos:
            levels_key = f"{crypto}_LEVELS"
            levels_str = os.getenv(levels_key, '')
            if levels_str:
                levels[crypto] = [float(level) for level in levels_str.split(',')]
        
        return levels
    
    def get_levels(self, crypto):
        """Récupère les niveaux pour une crypto"""
        return self.levels.get(crypto, [])
    
    def is_near_level(self, crypto, price, tolerance=1.5):
        """Vérifie si le prix est proche d'un niveau (±tolerance%)"""
        levels = self.get_levels(crypto)
        for level in levels:
            distance_pct = abs(price - level) / level * 100
            if distance_pct <= tolerance and price <= level * 1.015:
                return True, level
        return False, None