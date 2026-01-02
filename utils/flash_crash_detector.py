"""Détecteur de Flash Crashes avec Circuit Breakers"""
import time
from datetime import datetime, timedelta

class FlashCrashDetector:
    def __init__(self):
        self.crash_history = {}
        self.emergency_mode = False
        self.emergency_start_time = None
        self.emergency_duration = 24 * 3600  # 24h en secondes
    
    def detect_flash_crash(self, bot, symbol, current_price):
        """Détecte les flash crashes et active les protections d'urgence"""
        try:
            # Récupérer données 1m pour détection rapide
            klines_1m = bot.get_klines(symbol, 10, '1m')
            if len(klines_1m) < 5:
                return False
            
            # Calculer chute sur 5 minutes
            price_5min_ago = klines_1m[-5]['close']
            drop_pct = ((current_price - price_5min_ago) / price_5min_ago) * 100
            
            # Calculer volume anormal
            recent_volumes = [k['volume'] for k in klines_1m[-3:]]
            avg_volume = sum(k['volume'] for k in klines_1m[:-3]) / (len(klines_1m) - 3)
            current_volume = sum(recent_volumes) / len(recent_volumes)
            volume_spike = current_volume / avg_volume if avg_volume > 0 else 1
            
            # CRITÈRES FLASH CRASH
            is_flash_crash = (
                drop_pct < -10 and  # Chute >10% en 5min
                volume_spike > 5    # Volume >500% normal
            )
            
            if is_flash_crash:
                self._activate_emergency_mode(bot, symbol, drop_pct, volume_spike)
                return True
            
            return False
            
        except Exception as e:
            print(f"❌ Erreur détection flash crash {symbol}: {e}")
            return False
    
    def _activate_emergency_mode(self, bot, symbol, drop_pct, volume_spike):
        """Active le mode d'urgence avec ventes automatiques"""
        crypto = symbol.split('/')[0]
        
        print(f"🚨 FLASH CRASH DÉTECTÉ: {crypto} {drop_pct:.1f}% (Vol: {volume_spike:.1f}x)")
        print(f"🛑 ACTIVATION MODE URGENCE - Ventes automatiques")
        
        # Marquer mode urgence
        self.emergency_mode = True
        self.emergency_start_time = time.time()
        
        # Vendre toutes positions du crypto immédiatement
        self._emergency_sell_all(bot, symbol)
        
        # Bloquer achats pendant 24h
        self.crash_history[symbol] = {
            'timestamp': time.time(),
            'drop_pct': drop_pct,
            'volume_spike': volume_spike
        }
    
    def _emergency_sell_all(self, bot, symbol):
        """Vente d'urgence de toutes les positions"""
        try:
            balance = bot.balance_manager.get_balance()
            base_currency = symbol.split('/')[0]
            available = balance.get(base_currency, {}).get('free', 0)
            locked = balance.get(base_currency, {}).get('used', 0)
            
            # Annuler ordres en cours
            if not bot.paper_trading:
                try:
                    open_orders = bot.safe_request(bot.exchange.fetch_open_orders, symbol)
                    for order in open_orders:
                        bot.safe_request(bot.exchange.cancel_order, order['id'], symbol)
                        print(f"🚫 Ordre annulé: {order['id']}")
                except:
                    pass
            
            # Vendre positions libres
            if available > 0.00001:
                position_value = available * bot.get_price(symbol)
                min_cost = bot.get_min_amount(symbol)['min_cost']
                
                if position_value >= min_cost:
                    result = bot.sell_market(symbol, available)
                    if result:
                        print(f"🚨 VENTE URGENCE: {available:.6f} {base_currency}")
            
        except Exception as e:
            print(f"❌ Erreur vente urgence {symbol}: {e}")
    
    def can_trade(self, symbol):
        """Vérifie si trading autorisé après flash crash"""
        if symbol in self.crash_history:
            crash_time = self.crash_history[symbol]['timestamp']
            if time.time() - crash_time < self.emergency_duration:
                remaining_hours = (self.emergency_duration - (time.time() - crash_time)) / 3600
                print(f"🚫 {symbol.split('/')[0]}: Bloqué {remaining_hours:.1f}h après flash crash")
                return False
            else:
                # Nettoyer historique expiré
                del self.crash_history[symbol]
        
        return True
    
    def is_emergency_mode(self):
        """Vérifie si en mode urgence global"""
        if self.emergency_mode and self.emergency_start_time:
            if time.time() - self.emergency_start_time > 3600:  # 1h
                self.emergency_mode = False
                self.emergency_start_time = None
                print("✅ Sortie du mode urgence global")
        
        return self.emergency_mode