"""Module d'analyse et prévisions pour le bot de trading"""
from datetime import datetime
from utils.confidence_calculator import ConfidenceCalculator
from utils.volatility_calculator import VolatilityCalculator
from utils.market_calculator import MarketCalculator
import time

class AnalysisMixin:
    """Mixin contenant toutes les méthodes d'analyse et prévisions"""
    
    def get_cached_analysis(self, symbol, current_price, force=False):
        """Récupère analyse depuis cache ou calcule si nécessaire"""
        VolatilityCalculator.clear_cache(symbol)
        analysis = self.multi_tf_analyzer.analyze_all_timeframes(self, symbol, current_price)
        return analysis
    
    def analyze_market_conditions(self, symbol, current_price):
        """Analyse les conditions de marché pour optimiser les ordres"""
        klines = self.get_klines(symbol, 20)
        analysis = self.get_cached_analysis(symbol, current_price)
        volatility = analysis.get('volatility', 2.0)
        spread = 0.01 if volatility > 5 else 0.005
        
        if len(klines) >= 5:
            avg_volume = sum(k['volume'] for k in klines[-5:]) / 5
            liquidity = 'high' if avg_volume > 1000000 else 'medium' if avg_volume > 100000 else 'low'
        else:
            liquidity = 'medium'
            avg_volume = 500000
        
        return {
            'volatility': volatility,
            'spread': spread,
            'liquidity': liquidity,
            'avg_volume': avg_volume
        }
    
    def predict_next_sell_execution(self, symbol):
        """Prédit quand l'ordre de vente sera exécuté"""
        try:
            balance = self.balance_manager.get_balance()
            base_currency = symbol.split('/')[0]
            crypto_locked = balance.get(base_currency, {}).get('used', 0)
            
            if crypto_locked <= 0.00001:
                return None
            
            pending_order = None
            for order_id, order_data in self.pending_orders.items():
                if order_data['symbol'] == symbol and order_data['side'] == 'sell':
                    pending_order = order_data
                    break
            
            if not pending_order:
                return None
            
            current_price = self.get_price(symbol)
            target_price = pending_order['order']['price']
            distance_pct = ((target_price - current_price) / current_price) * 100
            
            klines = self.get_klines(symbol, 30)
            if len(klines) < 10:
                return None
            
            momentum = MarketCalculator.calculate_momentum(klines)
            volatility = VolatilityCalculator.calculate(klines, symbol)
            avg_volume = MarketCalculator.calculate_volume_avg(klines)
            
            closes = [k['close'] for k in klines[-20:]]
            price_changes = [abs(closes[i] - closes[i-1]) / closes[i-1] * 100 for i in range(1, len(closes))]
            avg_speed_per_min = sum(price_changes) / len(price_changes) if price_changes else 0.1
            
            momentum_factor = 1.5 if momentum > 1 else 1.2 if momentum > 0 else 0.8 if momentum < -1 else 1.0
            volatility_factor = 0.7 if volatility >= 4 else 0.85 if volatility >= 3 else 1.0 if volatility >= 2 else 1.3
            volume_factor = 0.9 if avg_volume > 1000000 else 1.1
            
            if distance_pct <= 0:
                time_minutes = 0
                time_estimate = "Imminent"
                probability = 95
            else:
                time_minutes = (distance_pct / avg_speed_per_min) * momentum_factor * volatility_factor * volume_factor
                time_minutes = max(5, min(time_minutes, 720))
                margin = int(time_minutes * 0.4)
                
                if time_minutes < 30:
                    time_estimate = f"{int(time_minutes)}min (±{margin}min)"
                    probability = 85
                elif time_minutes < 120:
                    hours = time_minutes / 60
                    margin_h = margin / 60
                    time_estimate = f"{hours:.1f}h (±{margin_h:.1f}h)"
                    probability = 70
                else:
                    hours = time_minutes / 60
                    time_estimate = f"{hours:.1f}h (±{int(margin/60)}h)"
                    probability = 55
                
                if momentum < -1:
                    probability -= 20
                elif momentum > 1:
                    probability += 10
                
                probability = max(30, min(probability, 95))
            
            reason = "Tendance haussière forte" if momentum > 1 else "Momentum positif" if momentum > 0 else "Tendance baissière (risque)" if momentum < -1 else "Marché neutre"
            
            return {
                'current_price': current_price,
                'target_price': target_price,
                'distance_pct': distance_pct,
                'time_estimate': time_estimate,
                'time_minutes': time_minutes if distance_pct > 0 else 0,
                'probability': probability,
                'momentum': momentum,
                'volatility': volatility,
                'avg_speed': avg_speed_per_min,
                'reason': reason
            }
        except:
            return None
    
    def predict_next_buy_opportunity(self, symbol):
        """Prédit quand le prochain achat sera possible"""
        try:
            import os
            current_price = self.get_price(symbol)
            balance = self.balance_manager.get_balance()
            usdt_available = balance.get('USDT', {}).get('free', 0)
            base_currency = symbol.split('/')[0]
            crypto_free = balance.get(base_currency, {}).get('free', 0)
            crypto_locked = balance.get(base_currency, {}).get('used', 0)
            crypto_total = crypto_free + crypto_locked
            
            if crypto_total > 0:
                position_value = crypto_total * current_price
                min_trade_value = self.get_min_amount(symbol)['min_cost']
                if position_value >= min_trade_value:
                    has_pending_order = any(
                        order['symbol'] == symbol and order['side'] == 'sell'
                        for order in self.pending_orders.values()
                    )
                    if has_pending_order:
                        return {'status': 'BLOCKED', 'time_estimate': 'Ordre limite actif', 'reason': 'Attente exécution vente'}
                    else:
                        return {'status': 'BLOCKED', 'time_estimate': 'Position ouverte', 'reason': 'Attente vente'}
            
            trade_amount = float(os.getenv('TRADE_AMOUNT', '8'))
            if usdt_available < trade_amount:
                return {'status': 'NO_FUNDS', 'time_estimate': 'Fonds insuffisants', 'reason': f'{usdt_available:.2f} USDT disponible'}
            
            VolatilityCalculator.clear_cache(symbol)
            analysis = self.get_cached_analysis(symbol, current_price)
            signal = analysis['global_signal']
            vol_value = analysis.get('volatility', 2.0)
            min_conf = ConfidenceCalculator.get_min_confidence(vol_value)
            
            can_buy_now = (
                signal['action'] in ['BUY', 'STRONG_BUY'] and
                signal['confidence'] >= min_conf and
                self.correlation_manager.can_open_position(symbol, self)
            )
            
            if can_buy_now:
                return {
                    'status': 'READY',
                    'time_estimate': 'Maintenant',
                    'confidence': signal['confidence'],
                    'target_price': current_price,
                    'min_confidence': min_conf,
                    'reason': f"Signal {signal['action']}"
                }
            
            confidence_gap = max(0, min_conf - signal['confidence'])
            klines = self.get_klines(symbol, 20)
            
            if len(klines) >= 10:
                prices = [k['close'] for k in klines[-10:]]
                analysis = self.get_cached_analysis(symbol, current_price)
                volatility = analysis.get('volatility', 2.0)
                
                recent_prices = prices[-5:]
                price_momentum = (recent_prices[-1] - recent_prices[0]) / recent_prices[0] * 100
                
                if abs(price_momentum) > 2 and volatility > 5:
                    speed_factor = 0.5
                elif abs(price_momentum) > 1 or volatility > 3:
                    speed_factor = 0.75
                elif volatility > 1.5:
                    speed_factor = 1.0
                else:
                    speed_factor = 1.5
                
                if confidence_gap < 5:
                    base_time = 5
                elif confidence_gap < 10:
                    base_time = 10
                elif confidence_gap < 15:
                    base_time = 20
                elif confidence_gap < 25:
                    base_time = 40
                else:
                    base_time = 60
                
                estimated_min = int(base_time * speed_factor)
                estimated_max = int(base_time * speed_factor * 1.5)
                
                if signal['action'] in ['BUY', 'STRONG_BUY']:
                    if price_momentum < -1:
                        estimated_min = max(2, int(estimated_min * 0.7))
                        estimated_max = int(estimated_max * 0.8)
                    elif price_momentum > 2:
                        estimated_min = int(estimated_min * 1.3)
                        estimated_max = int(estimated_max * 1.5)
                
                time_estimate = f"{estimated_min}-{estimated_max}min"
            else:
                time_estimate = "Indéterminé"
            
            if signal['action'] == 'HOLD':
                target_price = current_price * 0.98
                reason = f"Baisse → {target_price:.2f}"
            elif signal['action'] in ['SELL', 'STRONG_SELL']:
                target_price = current_price * 0.95
                reason = f"Retournement attendu"
            else:
                target_price = current_price
                reason = f"Signal {signal['confidence']:.0f}%→{min_conf}%"
            
            return {
                'status': 'WAITING',
                'time_estimate': time_estimate,
                'target_price': target_price,
                'current_confidence': signal['confidence'],
                'current_price': current_price,
                'reason': reason
            }
        except Exception as e:
            return {'status': 'ERROR', 'time_estimate': 'Erreur', 'reason': str(e)}
