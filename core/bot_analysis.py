"""Module d'analyse et prévisions pour le bot de trading"""
from datetime import datetime
from utils.market_analyzer import MarketAnalyzer
from utils.ema_analyzer import BinanceEMAAnalyzer
import time
import os

class AnalysisMixin:
    """Mixin contenant toutes les méthodes d'analyse et prévisions"""
    
    def get_cached_analysis(self, symbol, current_price, force=False):
        """Récupère analyse depuis cache ou calcule si nécessaire"""
        analysis = self.multi_tf_analyzer.analyze_all_timeframes(self, symbol, current_price)
        
        # Enrichir avec analyse EMA Binance
        if not hasattr(self, 'ema_analyzer'):
            self.ema_analyzer = BinanceEMAAnalyzer()
        
        klines = self.get_klines(symbol, 100, os.getenv('MAIN_TIMEFRAME', '15m'))
        ema_analysis = self.ema_analyzer.analyze(klines, current_price)
        
        if ema_analysis:
            analysis['ema_binance'] = ema_analysis
        
        # NOUVEAU: Analyse Support/Résistance avancée
        if len(klines) >= 50:
            sr_levels = self.pattern_analyzer.find_support_resistance_levels(klines)
            reversal_prediction = self.pattern_analyzer.predict_reversal_probability(current_price, sr_levels)
            
            analysis['support_resistance'] = {
                'levels': sr_levels,
                'reversal_prediction': reversal_prediction
            }
        
        return analysis
    
    def analyze_market_conditions(self, symbol, current_price):
        """Analyse les conditions de marché pour optimiser les ordres"""
        klines = self.get_klines(symbol, 20, os.getenv('MAIN_TIMEFRAME', '15m'))
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
            
            # Récupérer le prix réel de l'ordre sur Binance
            target_price = None
            if not self.paper_trading:
                try:
                    open_orders = self.safe_request(self.exchange.fetch_open_orders, symbol)
                    for order in open_orders:
                        if order['side'] == 'sell':
                            target_price = order['price']
                            break
                except:
                    pass
            
            if not target_price:
                return None
            
            current_price = self.get_price(symbol)
            distance_pct = ((target_price - current_price) / current_price) * 100
            
            klines = self.get_klines(symbol, 30, os.getenv('MAIN_TIMEFRAME', '15m'))
            if len(klines) < 10:
                return None
            
            momentum = MarketAnalyzer.calculate_momentum(klines)
            volatility = MarketAnalyzer.calculate_volatility(klines, symbol)
            avg_volume = MarketAnalyzer.calculate_volume_avg(klines)
            
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
    
    def predict_volume_recovery_time(self, symbol):
        """Prédit quand le volume va récupérer avec notification"""
        try:
            # Initialiser le prédicteur si nécessaire
            if not hasattr(self, 'volume_predictor'):
                self.volume_predictor = self.market_analyzer
            
            # Récupérer données temps réel
            klines_1m = self.get_klines(symbol, 60, '1m')
            klines_15m = self.get_klines(symbol, 100, '15m')
            current_price = self.get_price(symbol)
            
            # Calculer prédiction
            prediction = self.volume_predictor.predict_volume_recovery(
                symbol, klines_1m, klines_15m, current_price
            )
            
            if prediction and self.volume_predictor.should_notify(symbol, prediction):
                # Envoyer notification Telegram
                if hasattr(self, 'notification_manager'):
                    self.notification_manager.notify_volume_prediction(symbol, prediction)
                
                # Log console
                crypto = symbol.split('/')[0]
                recovery_time = prediction['recovery_time_str']
                confidence = prediction['confidence']
                print(f"📉 {crypto} Volume baisse détectée - Récupération: {recovery_time} ({confidence}%)")
            
            return prediction
            
        except Exception as e:
            return None
    
    def predict_next_buy_opportunity(self, symbol):
        """Prédit quand le prochain achat sera possible"""
        try:
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
            
            analysis = self.get_cached_analysis(symbol, current_price)
            signal = analysis['global_signal']
            vol_value = analysis.get('volatility', 2.0)
            min_conf = MarketAnalyzer.get_min_confidence(vol_value)
            
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
            
            # AMÉLIORATION: Prédiction précise avec données 1m temps réel
            confidence_gap = max(0, min_conf - signal['confidence'])
            
            # 1. VITESSE TEMPS RÉEL (1m au lieu de 15m)
            klines_1m = self.get_klines(symbol, 10, '1m')
            klines_15m = self.get_klines(symbol, 20, os.getenv('MAIN_TIMEFRAME', '15m'))
            
            if len(klines_1m) >= 5 and len(klines_15m) >= 10:
                # Vitesse réelle sur 1m (plus précise)
                recent_changes = []
                for i in range(1, len(klines_1m)):
                    change_pct = abs(klines_1m[i]['close'] - klines_1m[i-1]['close']) / klines_1m[i-1]['close'] * 100
                    recent_changes.append(change_pct)
                
                real_speed = sum(recent_changes) / len(recent_changes) if recent_changes else 0.1
                
                # 2. FACTEURS TEMPS RÉEL
                # Volume instantané vs moyenne
                current_vol = klines_1m[-1]['volume']
                avg_vol = sum(k['volume'] for k in klines_1m[:-1]) / (len(klines_1m) - 1) if len(klines_1m) > 1 else 1
                vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1
                
                volume_factor = 0.6 if vol_ratio > 2 else 0.8 if vol_ratio > 1.5 else 1.4 if vol_ratio < 0.5 else 1.0
                
                # Momentum 1m
                prices_1m = [k['close'] for k in klines_1m[-5:]]
                momentum_1m = (prices_1m[-1] - prices_1m[0]) / prices_1m[0] * 100
                momentum_factor = 0.7 if abs(momentum_1m) > 1 else 0.85 if abs(momentum_1m) > 0.5 else 1.2
                
                # 3. SUPPORT/RÉSISTANCE pour cible précise
                support_factor = 1.0
                if hasattr(self, 'pattern_analyzer') and len(klines_15m) >= 50:
                    try:
                        sr_levels = self.pattern_analyzer.find_support_resistance_levels(klines_15m)
                        for level in sr_levels:
                            distance = abs(level['price'] - current_price) / current_price * 100
                            if distance < 0.3:  # Très proche d'un niveau
                                support_factor = 0.8 if level['strength'] > 3 else 1.1
                                break
                    except:
                        pass
                
                # 4. CALCUL PRÉCIS
                if confidence_gap < 5:
                    base_time = max(2, confidence_gap)
                elif confidence_gap < 10:
                    base_time = confidence_gap
                elif confidence_gap < 15:
                    base_time = confidence_gap * 1.2
                else:
                    base_time = min(60, confidence_gap * 2)
                
                # Distance au target avec S/R
                if signal['action'] == 'HOLD':
                    target_distance = 2  # 2% de baisse attendue
                else:
                    target_distance = confidence_gap / 10  # Distance proportionnelle
                
                # Temps basé sur vitesse réelle
                if real_speed > 0:
                    time_from_speed = target_distance / real_speed
                else:
                    time_from_speed = base_time
                
                # Combinaison facteurs
                final_time = (time_from_speed + base_time) / 2 * momentum_factor * volume_factor * support_factor
                final_time = max(1, min(final_time, 120))  # 1min à 2h max
                
                # 5. FORMATAGE INTELLIGENT
                if final_time < 2:
                    time_estimate = f"{int(final_time)}min"
                elif final_time < 5:
                    margin = max(1, int(final_time * 0.3))
                    time_estimate = f"{int(final_time-margin)}-{int(final_time+margin)}min"
                elif final_time < 15:
                    margin = max(1, int(final_time * 0.4))
                    time_estimate = f"{int(final_time-margin)}-{int(final_time+margin)}min"
                elif final_time < 60:
                    margin = max(2, int(final_time * 0.5))
                    time_estimate = f"{int(final_time-margin)}-{int(final_time+margin)}min"
                else:
                    hours = final_time / 60
                    time_estimate = f"{hours:.1f}h"
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
