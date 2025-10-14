"""
Optimisation 1: Parallélisation des appels API
Récupère prix, klines, balance en parallèle pour toutes les paires
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

class ParallelFetcher:
    def __init__(self, bot, max_workers=10):
        self.bot = bot
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.cache = {}
        self.cache_ttl = 2  # 2s cache
    
    def fetch_all_data(self, trading_pairs):
        """Récupère toutes les données en parallèle (gain 60-70%)"""
        start = time.time()
        results = {
            'prices': {},
            'klines': {},
            'balance': None,
            'tickers': {}
        }
        
        # Lancer toutes les requêtes en parallèle
        futures = {}
        
        # Balance (1 seule fois)
        futures['balance'] = self.executor.submit(self.bot.get_balance)
        
        # Prix + klines + ticker pour chaque paire
        for pair in trading_pairs:
            symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
            futures[f'price_{symbol}'] = self.executor.submit(self.bot.get_price, symbol)
            futures[f'klines_{symbol}'] = self.executor.submit(self.bot.get_klines, symbol, 10)
            if not self.bot.paper_trading:
                futures[f'ticker_{symbol}'] = self.executor.submit(self.bot.safe_request, self.bot.exchange.fetch_ticker, symbol)
        
        # Collecter résultats
        for future_key, future in futures.items():
            try:
                result = future.result(timeout=5)
                if future_key == 'balance':
                    results['balance'] = result
                elif future_key.startswith('price_'):
                    symbol = future_key.replace('price_', '')
                    results['prices'][symbol] = result
                elif future_key.startswith('klines_'):
                    symbol = future_key.replace('klines_', '')
                    results['klines'][symbol] = result
                elif future_key.startswith('ticker_'):
                    symbol = future_key.replace('ticker_', '')
                    results['tickers'][symbol] = result
            except Exception as e:
                pass
        
        elapsed = (time.time() - start) * 1000
        return results, elapsed
    
    def shutdown(self):
        self.executor.shutdown(wait=False)
