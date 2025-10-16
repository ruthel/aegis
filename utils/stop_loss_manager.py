"""Gestionnaire Stop Loss et Take Profit intelligent"""
import os
from datetime import datetime

class StopLossManager:
    def __init__(self):
        self.stop_loss_percent = float(os.getenv('STOP_LOSS_PERCENT', '5'))
        self.trailing_stop_percent = float(os.getenv('TRAILING_STOP_PERCENT', '3'))
        self.position_stops = {}  # {symbol: {'stop_price': float, 'highest_price': float}}
    
    def set_stop_loss(self, symbol, buy_price, current_price):
        """Configure le stop loss initial pour une position"""
        stop_price = buy_price * (1 - self.stop_loss_percent / 100)
        
        self.position_stops[symbol] = {
            'buy_price': buy_price,
            'stop_price': stop_price,
            'highest_price': current_price,
            'trailing_active': False,
            'created_at': datetime.now()
        }
        
        return stop_price
    
    def update_trailing_stop(self, symbol, current_price):
        """Met à jour le trailing stop si le prix monte"""
        if symbol not in self.position_stops:
            return None
        
        position = self.position_stops[symbol]
        
        # Activer trailing stop si profit >= 2%
        if not position['trailing_active']:
            profit_pct = ((current_price - position['buy_price']) / position['buy_price']) * 100
            if profit_pct >= 2.0:
                position['trailing_active'] = True
                position['highest_price'] = current_price
        
        # Mettre à jour si trailing actif
        if position['trailing_active'] and current_price > position['highest_price']:
            position['highest_price'] = current_price
            new_stop = current_price * (1 - self.trailing_stop_percent / 100)
            
            # Ne jamais baisser le stop
            if new_stop > position['stop_price']:
                position['stop_price'] = new_stop
                return new_stop
        
        return position['stop_price']
    
    def should_stop_loss(self, symbol, current_price):
        """Vérifie si le stop loss doit être déclenché"""
        if symbol not in self.position_stops:
            return False, None
        
        position = self.position_stops[symbol]
        
        if current_price <= position['stop_price']:
            reason = "Trailing Stop" if position['trailing_active'] else "Stop Loss"
            return True, {
                'reason': reason,
                'stop_price': position['stop_price'],
                'loss_pct': ((current_price - position['buy_price']) / position['buy_price']) * 100
            }
        
        return False, None
    
    def get_take_profit_price(self, buy_price, volatility, min_profit_needed):
        """Calcule le prix de take profit selon volatilité"""
        base_profit = min_profit_needed
        
        # Ajuster selon volatilité
        if volatility >= 4.0:
            profit_target = base_profit + 0.015  # +1.5% pour haute volatilité
        elif volatility >= 2.5:
            profit_target = base_profit + 0.01   # +1% pour volatilité moyenne
        else:
            profit_target = base_profit + 0.005  # +0.5% pour faible volatilité
        
        return buy_price * (1 + profit_target)
    
    def remove_position(self, symbol):
        """Supprime une position du tracking"""
        if symbol in self.position_stops:
            del self.position_stops[symbol]
    
    def get_position_info(self, symbol):
        """Retourne les infos de la position"""
        return self.position_stops.get(symbol, None)
    
    def check_emergency_stop(self, bot):
        """Vérifie les conditions d'arrêt d'urgence"""
        max_daily_loss = float(os.getenv('MAX_DAILY_LOSS', '200'))
        
        if bot.daily_pnl <= -max_daily_loss:
            return True, f"Perte journalière max atteinte: {bot.daily_pnl:.2f} USDT"
        
        return False, None