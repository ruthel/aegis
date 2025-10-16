import json
import time
from datetime import datetime, timedelta

class SafetyManager:
    def __init__(self, max_daily_trades=50, max_daily_loss=100, emergency_stop_loss=500):
        self.max_daily_trades = max_daily_trades
        self.max_daily_loss = max_daily_loss
        self.emergency_stop_loss = emergency_stop_loss
        self.daily_stats = self.load_daily_stats()
        
    def load_daily_stats(self):
        """Charge les statistiques du jour"""
        try:
            with open('data/daily_stats.json', 'r') as f:
                stats = json.load(f)
                # Vérifier si c'est un nouveau jour
                if stats.get('date') != datetime.now().strftime('%Y-%m-%d'):
                    return self.reset_daily_stats()
                return stats
        except:
            return self.reset_daily_stats()
    
    def reset_daily_stats(self):
        """Remet à zéro les stats du jour"""
        return {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'trades_count': 0,
            'total_loss': 0,
            'total_profit': 0,
            'emergency_stop': False
        }
    
    def save_daily_stats(self):
        """Sauvegarde les stats"""
        with open('data/daily_stats.json', 'w') as f:
            json.dump(self.daily_stats, f, indent=2)
    
    def can_trade(self):
        """Vérifie si le trading est autorisé"""
        # Vérifier arrêt d'urgence
        if self.daily_stats.get('emergency_stop', False):
            print("🚨 ARRÊT D'URGENCE ACTIVÉ")
            return False
        
        # Vérifier limite de trades
        if self.daily_stats['trades_count'] >= self.max_daily_trades:
            print(f"⛔ Limite de trades atteinte: {self.daily_stats['trades_count']}")
            return False
        
        # Vérifier perte journalière
        if abs(self.daily_stats['total_loss']) >= self.max_daily_loss:
            print(f"⛔ Limite de perte atteinte: ${abs(self.daily_stats['total_loss'])}")
            return False
        
        return True
    
    def record_trade(self, profit_loss):
        """Enregistre un trade"""
        self.daily_stats['trades_count'] += 1
        
        if profit_loss > 0:
            self.daily_stats['total_profit'] += profit_loss
        else:
            self.daily_stats['total_loss'] += profit_loss
        
        # Vérifier arrêt d'urgence
        if abs(self.daily_stats['total_loss']) >= self.emergency_stop_loss:
            self.daily_stats['emergency_stop'] = True
            print(f"🚨 ARRÊT D'URGENCE: Perte de ${abs(self.daily_stats['total_loss'])}")
        
        self.save_daily_stats()
        
        # Afficher stats
        print(f"📊 Trades: {self.daily_stats['trades_count']}, P&L: ${self.daily_stats['total_profit'] + self.daily_stats['total_loss']:.2f}")
    
    def get_stats(self):
        """Retourne les statistiques actuelles"""
        return self.daily_stats