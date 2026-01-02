"""
Multi-Exchange Fallback System
Détecte les pannes Binance et bascule vers exchanges alternatifs
"""

import requests
import time
from typing import Dict, List, Optional, Tuple
import logging

class MultiExchangeFallback:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.binance_down = False
        self.fallback_active = False
        self.last_binance_check = 0
        self.check_interval = 30  # 30s
        
        # Exchanges alternatifs (API publiques)
        self.fallback_exchanges = {
            'coinbase': 'https://api.coinbase.com/v2/exchange-rates',
            'kraken': 'https://api.kraken.com/0/public/Ticker',
            'kucoin': 'https://api.kucoin.com/api/v1/market/orderbook/level1'
        }
        
    def check_binance_status(self) -> bool:
        """Vérifie si Binance API est disponible"""
        if time.time() - self.last_binance_check < self.check_interval:
            return not self.binance_down
            
        try:
            response = requests.get('https://api.binance.com/api/v3/ping', timeout=5)
            self.binance_down = response.status_code != 200
            self.last_binance_check = time.time()
            
            if self.binance_down and not self.fallback_active:
                self.logger.warning("🚨 BINANCE API DOWN - Activation fallback")
                self.fallback_active = True
            elif not self.binance_down and self.fallback_active:
                self.logger.info("✅ BINANCE API RESTORED - Désactivation fallback")
                self.fallback_active = False
                
        except Exception as e:
            self.binance_down = True
            if not self.fallback_active:
                self.logger.error(f"🚨 BINANCE UNREACHABLE: {e}")
                self.fallback_active = True
                
        return not self.binance_down
    
    def get_fallback_price(self, symbol: str) -> Optional[float]:
        """Récupère prix depuis exchange alternatif"""
        if not self.fallback_active:
            return None
            
        # Essayer Coinbase en premier
        try:
            if symbol.endswith('USDT'):
                base = symbol.replace('USDT', '')
                response = requests.get(f'https://api.coinbase.com/v2/exchange-rates?currency={base}', timeout=3)
                data = response.json()
                if 'data' in data and 'rates' in data['data']:
                    usd_price = float(data['data']['rates'].get('USD', 0))
                    return usd_price * 0.999  # USDT ≈ 0.999 USD
        except:
            pass
            
        # Essayer Kraken
        try:
            kraken_symbol = symbol.replace('USDT', 'USD').replace('BTC', 'XBT')
            response = requests.get(f'https://api.kraken.com/0/public/Ticker?pair={kraken_symbol}', timeout=3)
            data = response.json()
            if 'result' in data:
                for pair_data in data['result'].values():
                    return float(pair_data['c'][0])  # Last price
        except:
            pass
            
        return None
    
    def emergency_sell_signal(self) -> bool:
        """Signal de vente d'urgence si panne prolongée"""
        return self.fallback_active and (time.time() - self.last_binance_check > 300)  # 5min
    
    def get_status_message(self) -> str:
        """Message de statut pour l'affichage"""
        if not self.fallback_active:
            return ""
            
        downtime = int(time.time() - self.last_binance_check)
        return f"🚨 BINANCE DOWN ({downtime}s) - Fallback actif"