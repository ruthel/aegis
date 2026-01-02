import os

class MultiPositionManager:
    """Gestionnaire des positions multiples et scaling"""
    
    def __init__(self):
        self.max_positions = int(os.getenv('MAX_POSITIONS_PER_CRYPTO', '4'))
        self.scale_thresholds = [2.0, 4.0, 6.0]  # -2%, -4%, -6%
        self.multipliers = [1.0, 1.5, 2.0, 3.0]  # 1x, 1.5x, 2x, 3x
    
    def can_open_position(self, existing_positions):
        """Vérifie si on peut ouvrir une nouvelle position"""
        return len(existing_positions) < self.max_positions
    
    def should_scale_in(self, existing_positions, current_price):
        """Détermine si on doit ajouter une position (scale in)"""
        if not existing_positions:
            return True, None  # Première position
        
        # Trier par timestamp et prendre le plus récent
        existing_positions.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        last_buy_price = existing_positions[0].get('price')
        
        if not last_buy_price:
            return False, None
        
        # Calculer la baisse depuis le dernier achat
        price_drop_pct = (last_buy_price - current_price) / last_buy_price * 100
        
        position_count = len(existing_positions)
        if position_count < len(self.scale_thresholds):
            required_drop = self.scale_thresholds[position_count]
            return price_drop_pct >= required_drop, last_buy_price
        
        return False, None
    
    def get_position_multiplier(self, position_count):
        """Retourne le multiplier selon le nombre de positions"""
        return self.multipliers[min(position_count, len(self.multipliers)-1)]