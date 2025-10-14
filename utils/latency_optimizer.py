"""
Intégration des optimisations 1, 2, 4, 5, 6
Objectif: Réduire latence de 250-400ms à 100-150ms (60% supplémentaire)
"""
from utils.parallel_fetcher import ParallelFetcher
from utils.websocket_pure import WebSocketPure
from utils.numpy_optimizer import NumpyOptimizer
from utils.adaptive_cache import AdaptiveCache
from utils.event_driven import EventDrivenEngine
import time

class LatencyOptimizer:
    def __init__(self, bot):
        self.bot = bot
        
        # Optimisation 1: Parallélisation
        self.parallel_fetcher = ParallelFetcher(bot, max_workers=10)
        
        # Optimisation 2: WebSocket pur
        self.ws_pure = WebSocketPure()
        
        # Optimisation 4: NumPy
        self.numpy_opt = NumpyOptimizer()
        
        # Optimisation 5: Cache adaptatif
        self.cache = AdaptiveCache()
        
        # Optimisation 6: Event-driven
        self.event_engine = EventDrivenEngine(bot)
        self.event_engine.start()
        
        # Métriques
        self.metrics = {
            'parallel_gain': 0,
            'ws_gain': 0,
            'numpy_gain': 0,
            'cache_hits': 0,
            'events_saved': 0
        }
    
    def fetch_all_parallel(self, trading_pairs):
        """Récupère toutes données en parallèle (Opt 1)"""
        start = time.time()
        results, elapsed = self.parallel_fetcher.fetch_all_data(trading_pairs)
        self.metrics['parallel_gain'] = elapsed
        return results
    
    def get_price_optimized(self, symbol):
        """Prix optimisé: WebSocket > Cache > REST (Opt 2 + 5)"""
        # 1. Essayer WebSocket (5-15ms)
        if self.ws_pure.is_data_fresh(symbol):
            ws_price = self.ws_pure.get_price_ws(symbol)
            if ws_price:
                self.metrics['ws_gain'] += 1
                return ws_price
        
        # 2. Essayer cache (0ms)
        cached = self.cache.get(f'price_{symbol}')
        if cached:
            self.metrics['cache_hits'] += 1
            return cached
        
        # 3. Fallback REST API (50-100ms)
        price = self.bot.get_price(symbol)
        self.cache.set(f'price_{symbol}', price)
        return price
    
    def get_klines_optimized(self, symbol, count=10):
        """Klines optimisés: WebSocket > Cache > REST (Opt 2 + 5)"""
        # 1. WebSocket buffer
        if self.ws_pure.is_data_fresh(symbol):
            ws_klines = self.ws_pure.get_klines_ws(symbol, count)
            if len(ws_klines) >= count:
                self.metrics['ws_gain'] += 1
                return ws_klines
        
        # 2. Cache compressé
        cached = self.cache.get_klines_compressed(symbol)
        if cached and len(cached) >= count:
            self.metrics['cache_hits'] += 1
            return cached[-count:]
        
        # 3. REST API avec cache adaptatif
        klines = self.bot.get_klines(symbol, count)
        
        # Calculer volatilité pour TTL adaptatif
        if len(klines) >= 10:
            volatility = self.numpy_opt.calculate_volatility_fast(klines)
            self.cache.set_klines_compressed(symbol, klines, volatility)
        
        return klines
    
    def score_crypto_optimized(self, symbol, klines):
        """Scoring optimisé avec NumPy (Opt 4)"""
        start = time.time()
        
        # Utiliser NumPy si disponible
        result = self.numpy_opt.score_crypto_fast(klines)
        
        if result:
            elapsed = (time.time() - start) * 1000
            self.metrics['numpy_gain'] += elapsed
            return result
        
        # Fallback standard
        return None
    
    def should_analyze_pair(self, symbol):
        """Détermine si analyse nécessaire (Opt 6)"""
        # Event-driven: analyser seulement si mouvement significatif
        return self.event_engine.should_analyze(symbol)
    
    def on_websocket_price(self, symbol, price):
        """Callback WebSocket prix"""
        self.ws_pure.on_price_update(symbol, price)
        self.event_engine.on_price_change(symbol, price)
    
    def on_websocket_kline(self, symbol, kline):
        """Callback WebSocket kline"""
        self.ws_pure.on_kline_update(symbol, kline)
    
    def get_balance_cached(self):
        """Balance avec cache long (change rarement)"""
        cached = self.cache.get('balance')
        if cached:
            self.metrics['cache_hits'] += 1
            return cached
        
        balance = self.bot.get_balance()
        self.cache.set('balance', balance, ttl=30)
        return balance
    
    def get_min_amount_cached(self, symbol):
        """Min amounts avec cache permanent"""
        key = f'min_amounts_{symbol}'
        cached = self.cache.get(key)
        if cached:
            self.metrics['cache_hits'] += 1
            return cached
        
        min_amount = self.bot.get_min_amount(symbol)
        self.cache.set(key, min_amount, ttl=3600)
        return min_amount
    
    def print_metrics(self):
        """Affiche métriques optimisation"""
        print(f"\n📊 OPTIMISATIONS:")
        print(f"⚡ Parallèle: {self.metrics['parallel_gain']:.0f}ms")
        print(f"🌐 WebSocket: {self.metrics['ws_gain']} hits")
        print(f"💾 Cache: {self.metrics['cache_hits']} hits")
        print(f"🔥 NumPy: {self.metrics['numpy_gain']:.1f}ms saved")
        print(f"🎯 Events: {self.metrics['events_saved']} analyses évitées")
    
    def shutdown(self):
        """Arrêt propre"""
        self.event_engine.stop()
        self.parallel_fetcher.shutdown()
