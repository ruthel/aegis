"""
Optimisation 2: WebSocket pur (élimination REST API)
Utilise uniquement WebSocket pour prix/klines en temps réel
"""
import json
import threading
import time
from collections import deque

class WebSocketPure:
    def __init__(self):
        self.prices = {}
        self.klines_buffer = {}  # Buffer klines temps réel
        self.last_update = {}
        self.max_klines = 50
        
    def on_kline_update(self, symbol, kline):
        """Callback kline WebSocket"""
        if symbol not in self.klines_buffer:
            self.klines_buffer[symbol] = deque(maxlen=self.max_klines)
        
        # Ajouter nouvelle bougie
        self.klines_buffer[symbol].append({
            'timestamp': kline['t'],
            'open': float(kline['o']),
            'high': float(kline['h']),
            'low': float(kline['l']),
            'close': float(kline['c']),
            'volume': float(kline['v'])
        })
        self.last_update[symbol] = time.time()
    
    def on_price_update(self, symbol, price):
        """Callback prix WebSocket"""
        self.prices[symbol] = float(price)
        self.last_update[symbol] = time.time()
    
    def get_price_ws(self, symbol):
        """Récupère prix depuis WebSocket (5-15ms vs 50-100ms REST)"""
        return self.prices.get(symbol)
    
    def get_klines_ws(self, symbol, count=10):
        """Récupère klines depuis buffer WebSocket"""
        if symbol not in self.klines_buffer:
            return []
        
        klines = list(self.klines_buffer[symbol])
        return klines[-count:] if len(klines) >= count else klines
    
    def is_data_fresh(self, symbol, max_age=5):
        """Vérifie si données WebSocket sont récentes"""
        if symbol not in self.last_update:
            return False
        return (time.time() - self.last_update[symbol]) < max_age
