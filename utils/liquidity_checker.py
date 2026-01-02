"""
Liquidity Checker
Surveille spread et profondeur de marché
"""

import logging
import time
from typing import Dict, Optional, Tuple

class LiquidityChecker:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.max_spread_percent = 1.0  # 1% spread max
        self.min_depth_usdt = 1000  # 1000 USDT depth minimum
        self.liquidity_cache = {}
        self.cache_ttl = 10  # 10 secondes
        
    def check_liquidity(self, bot, symbol: str) -> Dict:
        """Vérifie la liquidité du marché"""
        try:
            # Vérifier cache
            cache_key = symbol
            now = time.time()
            
            if cache_key in self.liquidity_cache:
                cached_data, timestamp = self.liquidity_cache[cache_key]
                if now - timestamp < self.cache_ttl:
                    return cached_data
            
            # Récupérer données fraîches
            ticker = bot.get_ticker(symbol)
            orderbook = bot.safe_request(bot.exchange.fetch_order_book, symbol, limit=10)
            
            if not ticker or not orderbook:
                return {'is_liquid': False, 'reason': 'Données indisponibles'}
            
            # Calculer spread
            best_bid = orderbook['bids'][0][0] if orderbook['bids'] else 0
            best_ask = orderbook['asks'][0][0] if orderbook['asks'] else 0
            
            if best_bid == 0 or best_ask == 0:
                return {'is_liquid': False, 'reason': 'Pas de bid/ask'}
            
            spread_percent = ((best_ask - best_bid) / best_bid) * 100
            
            # Calculer profondeur
            bid_depth = sum(price * quantity for price, quantity in orderbook['bids'][:5])
            ask_depth = sum(price * quantity for price, quantity in orderbook['asks'][:5])
            total_depth = bid_depth + ask_depth
            
            # Évaluer liquidité
            is_liquid = (spread_percent <= self.max_spread_percent and 
                        total_depth >= self.min_depth_usdt)
            
            result = {
                'is_liquid': is_liquid,
                'spread_percent': spread_percent,
                'bid_depth_usdt': bid_depth,
                'ask_depth_usdt': ask_depth,
                'total_depth_usdt': total_depth,
                'best_bid': best_bid,
                'best_ask': best_ask,
                'volume_24h': ticker.get('quoteVolume', 0),
                'liquidity_score': self._calculate_liquidity_score(spread_percent, total_depth, ticker.get('quoteVolume', 0))
            }
            
            if not is_liquid:
                reasons = []
                if spread_percent > self.max_spread_percent:
                    reasons.append(f"Spread élevé: {spread_percent:.2f}%")
                if total_depth < self.min_depth_usdt:
                    reasons.append(f"Profondeur faible: {total_depth:.0f} USDT")
                result['reason'] = ', '.join(reasons)
            
            # Cache résultat
            self.liquidity_cache[cache_key] = (result, now)
            return result
            
        except Exception as e:
            self.logger.error(f"Erreur vérification liquidité {symbol}: {e}")
            return {'is_liquid': False, 'reason': f'Erreur: {e}'}
    
    def _calculate_liquidity_score(self, spread_percent: float, depth_usdt: float, volume_24h: float) -> int:
        """Calcule score de liquidité 0-100"""
        score = 100
        
        # Pénalité spread
        if spread_percent > 0.1:
            score -= min(50, spread_percent * 20)  # -20 points par 1% spread
        
        # Pénalité profondeur
        if depth_usdt < 5000:
            score -= min(30, (5000 - depth_usdt) / 100)  # -1 point par 100 USDT manquant
        
        # Bonus volume
        if volume_24h > 1000000:  # >1M USDT volume
            score += min(10, volume_24h / 1000000)  # +1 point par M USDT
        
        return max(0, min(100, int(score)))
    
    def get_trading_recommendation(self, liquidity_result: Dict) -> Dict:
        """Recommandation de trading basée sur liquidité"""
        if not liquidity_result.get('is_liquid', False):
            return {
                'can_trade': False,
                'recommendation': 'AVOID',
                'reason': liquidity_result.get('reason', 'Liquidité insuffisante'),
                'suggested_action': 'Attendre amélioration liquidité'
            }
        
        score = liquidity_result.get('liquidity_score', 0)
        spread = liquidity_result.get('spread_percent', 0)
        
        if score >= 80:
            return {
                'can_trade': True,
                'recommendation': 'MARKET_ORDER',
                'reason': f'Excellente liquidité (score: {score})',
                'suggested_action': 'Ordre au marché recommandé'
            }
        elif score >= 60:
            return {
                'can_trade': True,
                'recommendation': 'LIMIT_ORDER',
                'reason': f'Liquidité correcte (score: {score})',
                'suggested_action': 'Ordre limite recommandé'
            }
        else:
            return {
                'can_trade': False,
                'recommendation': 'WAIT',
                'reason': f'Liquidité faible (score: {score})',
                'suggested_action': 'Attendre ou réduire taille position'
            }
    
    def monitor_spread_changes(self, bot, symbol: str, duration_seconds: int = 60) -> Dict:
        """Surveille les changements de spread sur une période"""
        spreads = []
        start_time = time.time()
        
        try:
            while time.time() - start_time < duration_seconds:
                liquidity = self.check_liquidity(bot, symbol)
                if liquidity.get('is_liquid'):
                    spreads.append(liquidity['spread_percent'])
                time.sleep(5)  # Check toutes les 5s
            
            if not spreads:
                return {'stable': False, 'reason': 'Aucune donnée collectée'}
            
            avg_spread = sum(spreads) / len(spreads)
            max_spread = max(spreads)
            min_spread = min(spreads)
            volatility = (max_spread - min_spread) / avg_spread if avg_spread > 0 else 0
            
            is_stable = volatility < 0.5  # Volatilité spread <50%
            
            return {
                'stable': is_stable,
                'avg_spread': avg_spread,
                'max_spread': max_spread,
                'min_spread': min_spread,
                'volatility': volatility,
                'samples': len(spreads),
                'recommendation': 'STABLE' if is_stable else 'VOLATILE'
            }
            
        except Exception as e:
            self.logger.error(f"Erreur monitoring spread {symbol}: {e}")
            return {'stable': False, 'reason': f'Erreur: {e}'}
    
    def get_optimal_entry_timing(self, bot, symbol: str) -> Dict:
        """Trouve le meilleur moment pour entrer basé sur liquidité"""
        try:
            # Analyser liquidité actuelle
            current_liquidity = self.check_liquidity(bot, symbol)
            
            if not current_liquidity.get('is_liquid'):
                return {
                    'timing': 'WAIT',
                    'reason': current_liquidity.get('reason', 'Liquidité insuffisante'),
                    'wait_time_estimate': 300  # 5 minutes
                }
            
            score = current_liquidity.get('liquidity_score', 0)
            spread = current_liquidity.get('spread_percent', 0)
            
            if score >= 80 and spread <= 0.2:
                return {
                    'timing': 'IMMEDIATE',
                    'reason': f'Liquidité excellente (score: {score}, spread: {spread:.2f}%)',
                    'confidence': 'HIGH'
                }
            elif score >= 60:
                return {
                    'timing': 'GOOD',
                    'reason': f'Liquidité correcte (score: {score})',
                    'confidence': 'MEDIUM'
                }
            else:
                return {
                    'timing': 'WAIT',
                    'reason': f'Liquidité faible (score: {score})',
                    'wait_time_estimate': 180,  # 3 minutes
                    'confidence': 'LOW'
                }
                
        except Exception as e:
            self.logger.error(f"Erreur timing optimal {symbol}: {e}")
            return {'timing': 'ERROR', 'reason': f'Erreur: {e}'}
    
    def get_status_message(self, symbol: str) -> Optional[str]:
        """Message de statut pour affichage"""
        if symbol not in self.liquidity_cache:
            return None
        
        cached_data, _ = self.liquidity_cache[symbol]
        
        if not cached_data.get('is_liquid', True):
            spread = cached_data.get('spread_percent', 0)
            if spread > self.max_spread_percent:
                return f"Spread élevé: {spread:.1f}%"
        
        return None