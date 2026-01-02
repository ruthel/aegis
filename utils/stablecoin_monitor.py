"""
Stablecoin Depeg Monitor
Détecte les dépegs USDT/USDC et corrige les calculs
"""

import requests
import time
from typing import Dict, Tuple

class StablecoinMonitor:
    def __init__(self):
        self.last_check = 0
        self.check_interval = 300  # 5min
        self.usdt_usd_rate = 1.0
        self.usdc_usd_rate = 1.0
        self.depeg_threshold = 0.02  # 2%
        self.depeg_active = False
        
    def check_stablecoin_rates(self) -> Dict[str, float]:
        """Vérifie les taux USDT/USD et USDC/USD"""
        current_time = time.time()
        
        if current_time - self.last_check < self.check_interval:
            return {'USDT': self.usdt_usd_rate, 'USDC': self.usdc_usd_rate}
        
        self.last_check = current_time
        
        try:
            # API CoinGecko pour prix USD réels
            response = requests.get(
                'https://api.coingecko.com/api/v3/simple/price',
                params={
                    'ids': 'tether,usd-coin',
                    'vs_currencies': 'usd'
                },
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                new_usdt_rate = data.get('tether', {}).get('usd', 1.0)
                new_usdc_rate = data.get('usd-coin', {}).get('usd', 1.0)
                
                # Détecter depeg significatif
                usdt_depeg = abs(new_usdt_rate - 1.0) > self.depeg_threshold
                usdc_depeg = abs(new_usdc_rate - 1.0) > self.depeg_threshold
                
                if usdt_depeg or usdc_depeg:
                    if not self.depeg_active:
                        print(f"🚨 STABLECOIN DEPEG DÉTECTÉ!")
                        if usdt_depeg:
                            print(f"💰 USDT: {new_usdt_rate:.4f}$ ({(new_usdt_rate-1)*100:+.2f}%)")
                        if usdc_depeg:
                            print(f"💰 USDC: {new_usdc_rate:.4f}$ ({(new_usdc_rate-1)*100:+.2f}%)")
                        self.depeg_active = True
                elif self.depeg_active:
                    print("✅ STABLECOIN DEPEG RÉSOLU")
                    self.depeg_active = False
                
                self.usdt_usd_rate = new_usdt_rate
                self.usdc_usd_rate = new_usdc_rate
                
        except Exception as e:
            print(f"⚠️ Erreur vérification stablecoins: {e}")
        
        return {'USDT': self.usdt_usd_rate, 'USDC': self.usdc_usd_rate}
    
    def get_corrected_price(self, symbol: str, price: float) -> float:
        """Corrige le prix selon le taux de change stablecoin"""
        if not symbol.endswith('/USDT') and not symbol.endswith('/USDC'):
            return price
        
        rates = self.check_stablecoin_rates()
        
        if symbol.endswith('/USDT'):
            return price * rates['USDT']
        elif symbol.endswith('/USDC'):
            return price * rates['USDC']
        
        return price
    
    def get_corrected_balance(self, balance: Dict, currency: str) -> float:
        """Corrige la balance selon le taux de change"""
        if currency not in ['USDT', 'USDC']:
            return balance.get(currency, {}).get('free', 0)
        
        rates = self.check_stablecoin_rates()
        raw_balance = balance.get(currency, {}).get('free', 0)
        
        return raw_balance * rates[currency]
    
    def is_depeg_active(self) -> bool:
        """Vérifie si un depeg est actif"""
        self.check_stablecoin_rates()
        return self.depeg_active
    
    def get_status_message(self) -> str:
        """Message de statut pour affichage"""
        if not self.depeg_active:
            return ""
        
        rates = self.check_stablecoin_rates()
        messages = []
        
        if abs(rates['USDT'] - 1.0) > self.depeg_threshold:
            pct = (rates['USDT'] - 1) * 100
            messages.append(f"USDT {pct:+.1f}%")
        
        if abs(rates['USDC'] - 1.0) > self.depeg_threshold:
            pct = (rates['USDC'] - 1) * 100
            messages.append(f"USDC {pct:+.1f}%")
        
        if messages:
            return f"💰 DEPEG: {' | '.join(messages)}"
        
        return ""