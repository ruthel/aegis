"""
Slippage Calculator
Calcule le coût réel d'exécution avant placement d'ordre
"""

import logging
from typing import Dict, Optional, Tuple

class SlippageCalculator:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.max_slippage_percent = 2.0  # 2% max slippage
        self.orderbook_cache = {}
        self.cache_ttl = 5  # 5 secondes
        
    def calculate_execution_cost(self, bot, symbol: str, side: str, amount: float) -> Dict:
        """Calcule le coût réel d'exécution avec slippage"""
        try:
            # Récupérer orderbook
            orderbook = self._get_orderbook(bot, symbol)
            if not orderbook:
                return {'can_execute': False, 'reason': 'Orderbook indisponible'}
            
            # Calculer slippage selon côté
            if side.upper() == 'BUY':
                result = self._calculate_buy_slippage(orderbook, amount)
            else:
                result = self._calculate_sell_slippage(orderbook, amount)
            
            # Vérifier seuil acceptable
            if result['slippage_percent'] > self.max_slippage_percent:
                return {
                    'can_execute': False,
                    'reason': f"Slippage trop élevé: {result['slippage_percent']:.2f}%",
                    'slippage_percent': result['slippage_percent'],
                    'estimated_cost': result['total_cost']
                }
            
            return {
                'can_execute': True,
                'slippage_percent': result['slippage_percent'],
                'estimated_cost': result['total_cost'],
                'average_price': result['avg_price'],
                'market_price': orderbook['bids'][0][0] if side.upper() == 'SELL' else orderbook['asks'][0][0]
            }
            
        except Exception as e:
            self.logger.error(f"Erreur calcul slippage {symbol}: {e}")
            return {'can_execute': False, 'reason': f'Erreur: {e}'}
    
    def _get_orderbook(self, bot, symbol: str) -> Optional[Dict]:
        """Récupère orderbook avec cache"""
        import time
        
        cache_key = symbol
        now = time.time()
        
        # Vérifier cache
        if cache_key in self.orderbook_cache:
            cached_data, timestamp = self.orderbook_cache[cache_key]
            if now - timestamp < self.cache_ttl:
                return cached_data
        
        try:
            # Récupérer orderbook frais
            orderbook = bot.safe_request(bot.exchange.fetch_order_book, symbol, limit=20)
            self.orderbook_cache[cache_key] = (orderbook, now)
            return orderbook
        except Exception as e:
            self.logger.error(f"Erreur orderbook {symbol}: {e}")
            return None
    
    def _calculate_buy_slippage(self, orderbook: Dict, amount_usdt: float) -> Dict:
        """Calcule slippage pour achat (consomme asks)"""
        asks = orderbook['asks']  # [[price, quantity], ...]
        
        remaining_usdt = amount_usdt
        total_quantity = 0
        weighted_price_sum = 0
        
        for price, quantity in asks:
            if remaining_usdt <= 0:
                break
            
            # Coût pour cette tranche
            cost_for_level = min(remaining_usdt, price * quantity)
            quantity_bought = cost_for_level / price
            
            total_quantity += quantity_bought
            weighted_price_sum += price * quantity_bought
            remaining_usdt -= cost_for_level
        
        if total_quantity == 0:
            return {'slippage_percent': 100, 'total_cost': amount_usdt, 'avg_price': 0}
        
        avg_price = weighted_price_sum / total_quantity
        market_price = asks[0][0]  # Meilleur ask
        slippage_percent = ((avg_price - market_price) / market_price) * 100
        
        return {
            'slippage_percent': slippage_percent,
            'total_cost': amount_usdt,
            'avg_price': avg_price,
            'quantity': total_quantity
        }
    
    def _calculate_sell_slippage(self, orderbook: Dict, quantity: float) -> Dict:
        """Calcule slippage pour vente (consomme bids)"""
        bids = orderbook['bids']  # [[price, quantity], ...]
        
        remaining_quantity = quantity
        total_usdt = 0
        weighted_price_sum = 0
        total_sold = 0
        
        for price, bid_quantity in bids:
            if remaining_quantity <= 0:
                break
            
            # Quantité vendue à ce niveau
            quantity_sold = min(remaining_quantity, bid_quantity)
            usdt_received = price * quantity_sold
            
            total_usdt += usdt_received
            weighted_price_sum += price * quantity_sold
            total_sold += quantity_sold
            remaining_quantity -= quantity_sold
        
        if total_sold == 0:
            return {'slippage_percent': 100, 'total_cost': 0, 'avg_price': 0}
        
        avg_price = weighted_price_sum / total_sold
        market_price = bids[0][0]  # Meilleur bid
        slippage_percent = ((market_price - avg_price) / market_price) * 100
        
        return {
            'slippage_percent': slippage_percent,
            'total_cost': total_usdt,
            'avg_price': avg_price,
            'quantity': total_sold
        }
    
    def get_optimal_order_size(self, bot, symbol: str, max_slippage: float = 1.0) -> Dict:
        """Trouve la taille d'ordre optimale pour un slippage donné"""
        try:
            orderbook = self._get_orderbook(bot, symbol)
            if not orderbook:
                return {'optimal_size': 0, 'reason': 'Orderbook indisponible'}
            
            # Tester différentes tailles
            test_sizes = [5, 10, 25, 50, 100, 250, 500]  # USDT
            optimal_size = 0
            
            for size in test_sizes:
                result = self.calculate_execution_cost(bot, symbol, 'BUY', size)
                if result['can_execute'] and result['slippage_percent'] <= max_slippage:
                    optimal_size = size
                else:
                    break
            
            return {
                'optimal_size': optimal_size,
                'max_size_tested': max(test_sizes),
                'recommended_slippage': max_slippage
            }
            
        except Exception as e:
            self.logger.error(f"Erreur taille optimale {symbol}: {e}")
            return {'optimal_size': 0, 'reason': f'Erreur: {e}'}
    
    def should_use_limit_order(self, slippage_result: Dict) -> bool:
        """Recommande ordre limite si slippage élevé"""
        if not slippage_result.get('can_execute', False):
            return True
        
        return slippage_result.get('slippage_percent', 0) > 0.5  # >0.5% = limite recommandé