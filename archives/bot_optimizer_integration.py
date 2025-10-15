"""
Intégration optimisations dans BinanceSpotBot
Ajouter ces méthodes à la classe BinanceSpotBot
"""
import os

def init_optimizer(self):
    """Initialise l'optimiseur de latence"""
    if os.getenv('ENABLE_LATENCY_OPTIMIZER', 'True') == 'True':
        try:
            from utils.latency_optimizer import LatencyOptimizer
            self.optimizer = LatencyOptimizer(self)
            print("⚡ Optimiseur latence activé (objectif: 10-20ms)")
        except Exception as e:
            print(f"⚠️ Optimiseur désactivé: {e}")
            self.optimizer = None
    else:
        self.optimizer = None

def get_price_optimized(self, symbol):
    """Prix optimisé: WebSocket > Cache > REST"""
    if hasattr(self, 'optimizer') and self.optimizer:
        return self.optimizer.get_price_optimized(symbol)
    return self.get_price(symbol)

def get_klines_optimized(self, symbol, count=10):
    """Klines optimisés: WebSocket > Cache > REST"""
    if hasattr(self, 'optimizer') and self.optimizer:
        return self.optimizer.get_klines_optimized(symbol, count)
    return self.get_klines(symbol, count)

def get_balance_optimized(self):
    """Balance avec cache 30s"""
    if hasattr(self, 'optimizer') and self.optimizer:
        return self.optimizer.get_balance_cached()
    return self.get_balance()

def should_analyze_optimized(self, symbol):
    """Event-driven: analyser seulement si mouvement significatif"""
    if hasattr(self, 'optimizer') and self.optimizer:
        return self.optimizer.should_analyze_pair(symbol)
    return True  # Toujours analyser si pas d'optimiseur

def on_websocket_price_optimized(self, symbol, price):
    """Callback WebSocket pour optimiseur"""
    if hasattr(self, 'optimizer') and self.optimizer:
        self.optimizer.on_websocket_price(symbol, price)

def on_websocket_kline_optimized(self, symbol, kline):
    """Callback WebSocket kline pour optimiseur"""
    if hasattr(self, 'optimizer') and self.optimizer:
        self.optimizer.on_websocket_kline(symbol, kline)

def print_optimizer_metrics(self):
    """Affiche métriques optimisation"""
    if hasattr(self, 'optimizer') and self.optimizer:
        self.optimizer.print_metrics()

def shutdown_optimizer(self):
    """Arrêt propre optimiseur"""
    if hasattr(self, 'optimizer') and self.optimizer:
        self.optimizer.shutdown()
