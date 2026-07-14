import time
import json
import os
import numpy as np
from datetime import datetime, timedelta
from utils.market_analyzer import MarketAnalyzer

class PositionManager:
    def __init__(self, bot, max_loss_percent=15, stuck_threshold_hours=24):
        self.bot = bot
        self.max_loss_percent = max_loss_percent
        self.stuck_threshold_hours = stuck_threshold_hours
        self.stuck_positions = {}
        self.recovery_strategies = {}
        
        # Position sizing cache
        self.cache = {}
        self.cache_duration = 300  # 5 minutes
        
    def check_stuck_position(self, symbol, current_price, buy_price, buy_time):
        """Vérifie si une position est bloquée"""
        loss_percent = MarketAnalyzer.calculate_loss_percent(current_price, buy_price)
        hours_held = MarketAnalyzer.calculate_hours_held(buy_time)
        
        is_stuck = (
            loss_percent < -5 and  # Perte > 5%
            hours_held > self.stuck_threshold_hours  # Détenu > 24h
        )
        
        if is_stuck:
            if symbol not in self.stuck_positions:
                self.stuck_positions[symbol] = {
                    'buy_price': buy_price,
                    'buy_time': buy_time,
                    'detected_at': time.time(),
                    'max_loss': loss_percent,
                    'recovery_attempts': 0
                }
                print(f"⚠️ POSITION BLOQUÉE: {symbol}")
                print(f"   💸 Perte: {loss_percent:.2f}%")
                print(f"   ⏰ Détenu: {hours_held:.1f}h")
            else:
                # Mettre à jour la perte max
                if loss_percent < self.stuck_positions[symbol]['max_loss']:
                    self.stuck_positions[symbol]['max_loss'] = loss_percent
        
        return is_stuck, loss_percent
    
    def get_recovery_strategy(self, symbol, loss_percent, current_price, buy_price):
        """Détermine la stratégie de récupération"""
        # Moyenner à la baisse (perte -5% à -10%)
        if -10 < loss_percent <= -5:
            return {
                'strategy': 'average_down_aggressive',
                'action': 'buy_more',
                'amount_multiplier': 1.5,
                'reason': 'Moyenner à la baisse pour réduire prix moyen',
                'target_profit': 2.0
            }
        # Accumulation progressive (perte -10% à -15%)
        elif -15 < loss_percent <= -10:
            return {
                'strategy': 'average_down_moderate',
                'action': 'buy_more',
                'amount_multiplier': 1.0,
                'reason': 'Accumulation progressive',
                'target_profit': 1.0
            }
        # Stop Loss d'urgence (perte > -15%)
        elif loss_percent <= -15:
            return {
                'strategy': 'emergency_exit',
                'action': 'sell_all',
                'reason': f'Perte critique {loss_percent:.1f}% - Limiter dégâts',
                'force': True
            }
        # Attente rebond (perte -3% à -5%)
        else:
            return {
                'strategy': 'wait_bounce',
                'action': 'hold',
                'reason': 'Attendre rebond technique',
                'sell_target': buy_price * 1.005
            }
    
    def execute_recovery(self, bot, symbol, current_price):
        """Exécute la stratégie de récupération"""
        if symbol not in self.stuck_positions:
            return False
        
        stuck_data = self.stuck_positions[symbol]
        buy_price = stuck_data['buy_price']
        loss_percent = MarketAnalyzer.calculate_loss_percent(current_price, buy_price)
        
        strategy = self.get_recovery_strategy(symbol, loss_percent, current_price, buy_price)
        
        print(f"\n🔧 RÉCUPÉRATION: {symbol}")
        print(f"📊 Stratégie: {strategy['strategy'].upper()}")
        print(f"💡 Raison: {strategy['reason']}")
        
        # Si vente d'urgence, blacklister la crypto
        if strategy['action'] == 'sell_all':
            if hasattr(bot, 'crypto_scorer'):
                bot.crypto_scorer.add_to_blacklist(symbol)
        
        # Exécuter l'action
        if strategy['action'] == 'buy_more':
            # Moyenner à la baisse
            import os
            base_amount = float(os.getenv('TRADE_AMOUNT', '8'))
            average_amount = base_amount * strategy['amount_multiplier']
            
            print(f"🔄 Moyenner: Achat {average_amount:.2f} USD")
            trade_amount = average_amount / current_price
            result = bot.buy_market(symbol, trade_amount)
            
            if result:
                stuck_data['recovery_attempts'] += 1
                print(f"✅ Moyennage exécuté - Tentative #{stuck_data['recovery_attempts']}")
                return True
        
        elif strategy['action'] == 'sell_all':
            # Vente d'urgence
            print(f"🚨 VENTE D'URGENCE - Perte: {loss_percent:.2f}%")
            base_currency = symbol.split('/')[0]
            balance = bot.balance_manager.get_balance()
            available = balance.get(base_currency, {}).get('free', 0)
            
            if available > 0:
                result = bot.sell_market(symbol, available)
                if result:
                    del self.stuck_positions[symbol]
                    print(f"✅ Position liquidée - Perte acceptée")
                    bot.notifier.notify(f"🚨 STOP LOSS: {symbol} vendu à {loss_percent:.1f}%")
                    return True
        
        elif strategy['action'] == 'hold':
            # Attendre rebond
            sell_target = strategy['sell_target']
            if current_price >= sell_target:
                print(f"🎯 Rebond atteint! Vente à {current_price:.6f}")
                base_currency = symbol.split('/')[0]
                balance = bot.balance_manager.get_balance()
                available = balance.get(base_currency, {}).get('free', 0)
                
                if available > 0:
                    result = bot.sell_market(symbol, available)
                    if result:
                        del self.stuck_positions[symbol]
                        print(f"✅ Position récupérée avec profit minimal")
                        return True
            else:
                print(f"⏳ Attente rebond: {current_price:.6f} → {sell_target:.6f}")
        
        return False
    
    def get_stuck_summary(self):
        """Résumé des positions bloquées"""
        if not self.stuck_positions:
            return None
        
        total_stuck = len(self.stuck_positions)
        total_loss = sum(pos['max_loss'] for pos in self.stuck_positions.values())
        avg_loss = total_loss / total_stuck if total_stuck > 0 else 0
        
        return {
            'count': total_stuck,
            'total_loss_percent': total_loss,
            'avg_loss_percent': avg_loss,
            'positions': self.stuck_positions
        }
    
    def show_stuck_positions(self):
        """Affiche les positions bloquées"""
        summary = self.get_stuck_summary()
        if summary:
            print(f"\n⚠️ POSITIONS BLOQUÉES: {summary['count']}")
            print(f"💸 Perte totale: {summary['total_loss_percent']:.2f}%")
            print(f"📊 Perte moyenne: {summary['avg_loss_percent']:.2f}%")
            
            for symbol, data in summary['positions'].items():
                hours_stuck = (time.time() - data['detected_at']) / 3600
                print(f"   • {symbol}: {data['max_loss']:.2f}% (bloqué {hours_stuck:.1f}h)")
    
    # === POSITION SIZING METHODS ===
    
    def calculate_position_size(self, symbol, signal_strength, account_balance):
        """Calcule la taille de position optimale avec limites dynamiques"""
        # Obtenir les limites selon le capital
        try:
            limits = MarketAnalyzer.get_position_limits(account_balance)
            max_positions = limits['total_max_positions']
            max_per_crypto = limits['max_positions_per_crypto']
            
            # Ajuster la taille selon les limites
            if max_positions == 0:
                return self._get_zero_position_size()
            
            # Calculer taille de base
            base_size = account_balance / max_positions if max_positions > 0 else account_balance * 0.1
            
        except:
            base_size = account_balance * 0.1  # Fallback 10%
        
        cache_key = f"{symbol}_position"
        now = datetime.now()
        
        # Vérifier cache
        if (cache_key in self.cache and 
            (now - self.cache[cache_key]['timestamp']).seconds < self.cache_duration):
            cached_data = self.cache[cache_key]
            return cached_data['base_size']
        
        # Calculer nouvelle taille
        position_data = self._calculate_optimal_size(symbol, signal_strength, base_size)
        
        # Cache résultat
        self.cache[cache_key] = {
            'base_size': position_data,
            'risk_data': position_data['risk_metrics'],
            'timestamp': now
        }
        
        return position_data
    
    def _calculate_optimal_size(self, symbol, signal_strength, account_balance):
        """Calcule la taille optimale basée sur ATR et risque"""
        try:
            # 1. Calculer ATR (volatilité)
            atr_data = self._calculate_atr(symbol)
            
            # 2. Déterminer stop loss optimal
            stop_loss_data = self._calculate_optimal_stop_loss(symbol, atr_data)
            
            # 3. Calculer risk per trade
            risk_per_trade = self._calculate_risk_per_trade(account_balance, signal_strength)
            
            # 4. Position size basée sur risque
            position_size = self._calculate_risk_based_size(
                risk_per_trade, 
                stop_loss_data['distance'], 
                symbol
            )
            
            # 5. Ajustements finaux
            final_size = self._apply_final_adjustments(
                position_size, 
                account_balance, 
                atr_data, 
                signal_strength,
                symbol
            )
            
            return {
                'position_size_usd': final_size['size_usd'],
                'position_size_crypto': final_size['size_crypto'],
                'stop_loss_price': stop_loss_data['price'],
                'stop_loss_percent': stop_loss_data['percent'],
                'risk_reward_ratio': final_size['risk_reward'],
                'risk_metrics': {
                    'atr': atr_data,
                    'volatility_adj': final_size['volatility_adj'],
                    'signal_adj': final_size['signal_adj'],
                    'account_risk': risk_per_trade
                }
            }
            
        except Exception as e:
            print(f"⚠️ Erreur position sizing {symbol}: {e}")
            return self._get_fallback_size(account_balance)
    
    def _calculate_atr(self, symbol, period=14):
        """Calcule Average True Range"""
        try:
            klines = self.bot.get_klines(symbol, period + 5, '1h')
            if len(klines) < period:
                return {'atr': 0, 'atr_percent': 2.0}
            
            true_ranges = []
            for i in range(1, len(klines)):
                current = klines[i]
                previous = klines[i-1]
                
                tr1 = current['high'] - current['low']
                tr2 = abs(current['high'] - previous['close'])
                tr3 = abs(current['low'] - previous['close'])
                
                true_ranges.append(max(tr1, tr2, tr3))
            
            atr = sum(true_ranges[-period:]) / period
            current_price = klines[-1]['close']
            atr_percent = (atr / current_price) * 100
            
            return {
                'atr': atr,
                'atr_percent': atr_percent,
                'volatility_level': self._classify_volatility(atr_percent)
            }
            
        except Exception as e:
            print(f"⚠️ Erreur ATR {symbol}: {e}")
            return {'atr': 0, 'atr_percent': 2.0, 'volatility_level': 'medium'}
    
    def _calculate_optimal_stop_loss(self, symbol, atr_data):
        """Calcule stop loss optimal basé sur ATR"""
        try:
            current_price = self.bot.get_price(symbol)
            atr_percent = atr_data['atr_percent']
            
            # Stop loss adaptatif selon volatilité
            if atr_percent > 4.0:
                stop_multiplier = 2.5
            elif atr_percent > 2.0:
                stop_multiplier = 2.0
            else:
                stop_multiplier = 1.5
            
            stop_distance_percent = atr_percent * stop_multiplier
            stop_distance_percent = max(1.0, min(stop_distance_percent, 8.0))
            
            stop_loss_price = current_price * (1 - stop_distance_percent / 100)
            
            return {
                'price': stop_loss_price,
                'percent': stop_distance_percent,
                'distance': stop_distance_percent / 100
            }
            
        except Exception as e:
            print(f"⚠️ Erreur stop loss {symbol}: {e}")
            return {'price': 0, 'percent': 3.0, 'distance': 0.03}
    
    def _calculate_risk_per_trade(self, account_balance, signal_strength):
        """Calcule le risque par trade selon la force du signal"""
        base_risk_percent = 1.0
        
        if signal_strength >= 80:
            risk_multiplier = 1.5
        elif signal_strength >= 60:
            risk_multiplier = 1.2
        elif signal_strength >= 40:
            risk_multiplier = 1.0
        else:
            risk_multiplier = 0.5
        
        risk_percent = base_risk_percent * risk_multiplier
        risk_amount = account_balance * (risk_percent / 100)
        
        return {
            'percent': risk_percent,
            'amount': risk_amount,
            'multiplier': risk_multiplier
        }
    
    def _calculate_risk_based_size(self, risk_per_trade, stop_distance, symbol):
        """Calcule taille position basée sur risque AVEC frais inclus"""
        try:
            current_price = self.bot.get_price(symbol)
            
            # Montant USD total à dépenser (incluant frais)
            total_usd_to_spend = risk_per_trade['amount'] / stop_distance
            
            # Déduire frais AVANT calcul quantité crypto
            fee_rate = self._get_fee_rate()
            net_usd = total_usd_to_spend / (1 + fee_rate)
            fees_paid = total_usd_to_spend - net_usd
            
            # Quantité crypto RÉELLEMENT reçue après frais
            position_size_crypto = net_usd / current_price
            
            return {
                'size_usd': total_usd_to_spend,
                'size_usd_net': net_usd,
                'size_crypto': position_size_crypto,
                'fees_paid': fees_paid,
                'current_price': current_price
            }
            
        except Exception as e:
            print(f"⚠️ Erreur risk-based size {symbol}: {e}")
            return {'size_usd': 10, 'size_usd_net': 9.99, 'size_crypto': 0, 'fees_paid': 0.01, 'current_price': 0}
    
    def _apply_final_adjustments(self, position_size, account_balance, atr_data, signal_strength, symbol):
        """Applique ajustements finaux AVEC frais + arrondi stepSize + validation 5 USD"""
        try:
            size_usd = position_size['size_usd']
            current_price = position_size['current_price']
            fee_rate = self._get_fee_rate()
            
            # Ajustements multiplicateurs AVANT limites
            volatility_adj = self._get_volatility_adjustment(atr_data['volatility_level'])
            signal_adj = self._get_signal_adjustment(signal_strength)
            size_usd *= volatility_adj * signal_adj
            
            # Limites STRICTES (APRÈS ajustements)
            max_position = account_balance * 0.10
            max_with_reserve = account_balance - 5.0
            size_usd = min(size_usd, max_position, max_with_reserve)
            size_usd = max(size_usd, 5.0)
            
            # Gestion capital restant
            remaining = account_balance - size_usd
            if 0 < remaining < 5.0:
                if account_balance < 10.0:
                    size_usd = account_balance
                    print(f"💰 Micro-capital: Utilisation 100% ({size_usd:.2f} USD)")
                else:
                    size_usd = account_balance - 5.0
                    print(f"💰 Ajustement réserve: {size_usd:.2f} USD")
            
            # Calculer quantité crypto AVEC frais
            net_usd = size_usd / (1 + fee_rate)
            fees_to_pay = size_usd - net_usd
            size_crypto_raw = net_usd / current_price
            
            # Arrondir au step size de l'exchange
            size_crypto = self.round_quantity(symbol, size_crypto_raw)
            filters = self.get_symbol_filters(symbol)
            step_size = filters['stepSize']
            min_amount = max(
                float(filters.get('minQty') or 0),
                float(self.bot.get_min_amount(symbol).get('min_amount') or 0)
            )
            
            if size_crypto < min_amount:
                import math
                adjusted_crypto = math.ceil(min_amount / step_size) * step_size
                adjusted_total_usd = adjusted_crypto * current_price * (1 + fee_rate)

                if adjusted_total_usd > account_balance:
                    print(f"⚠️ Quantité minimum {adjusted_crypto:.8f} coûte {adjusted_total_usd:.2f} USD > capital {account_balance:.2f} USD")
                    return self._get_zero_position_size()

                size_crypto = adjusted_crypto
                print(f"✅ Quantité ajustée au minimum exchange: {size_crypto:.8f}")
            
            # Recalculer USD basé sur quantité arrondie + frais
            net_usd_adjusted = size_crypto * current_price
            total_usd_adjusted = net_usd_adjusted * (1 + fee_rate)
            fees_adjusted = total_usd_adjusted - net_usd_adjusted
            
            # Vérifier minimum notional APRÈS arrondi
            exchange_name = os.getenv('EXCHANGE', 'binance').lower()
            MIN_NOTIONAL = 0.5 if exchange_name == 'kraken' else 5.0
            if total_usd_adjusted < MIN_NOTIONAL:
                print(f"⚠️ Montant {total_usd_adjusted:.2f} USD < minimum {MIN_NOTIONAL} USD après arrondi")
                
                # Augmenter quantité pour atteindre minimum
                min_net_usd = MIN_NOTIONAL / (1 + fee_rate)
                min_crypto_needed = min_net_usd / current_price
                
                # Arrondir vers le HAUT cette fois
                import math
                size_crypto = math.ceil(min_crypto_needed / step_size) * step_size
                
                # Recalculer montant final
                net_usd_adjusted = size_crypto * current_price
                total_usd_adjusted = net_usd_adjusted * (1 + fee_rate)
                fees_adjusted = total_usd_adjusted - net_usd_adjusted
                
                # Vérifier si dépasse capital disponible
                if total_usd_adjusted > account_balance:
                    print(f"⚠️ Montant ajusté {total_usd_adjusted:.2f} USD > capital {account_balance:.2f} USD")
                    return self._get_zero_position_size()
                
                print(f"✅ Ajusté à {total_usd_adjusted:.2f} USD pour respecter le minimum exchange")
            
            print(f"💰 Trade: {total_usd_adjusted:.2f} USD → {size_crypto:.8f} crypto (frais: {fees_adjusted:.4f} USD)")
            
            return {
                'size_usd': round(total_usd_adjusted, 2),
                'size_usd_net': round(net_usd_adjusted, 2),
                'size_crypto': size_crypto,
                'fees': round(fees_adjusted, 4),
                'volatility_adj': volatility_adj,
                'signal_adj': signal_adj,
                'risk_reward': 2.0
            }
            
        except Exception as e:
            print(f"⚠️ Erreur ajustements finaux: {e}")
            return self._get_zero_position_size()
    
    def _classify_volatility(self, atr_percent):
        """Classifie le niveau de volatilité"""
        if atr_percent > 4.0:
            return 'high'
        elif atr_percent > 2.0:
            return 'medium'
        else:
            return 'low'
    
    def _get_volatility_adjustment(self, volatility_level):
        """Ajustement conservateur selon volatilité"""
        adjustments = {
            'low': 1.1,
            'medium': 1.0,
            'high': 0.8
        }
        return adjustments.get(volatility_level, 1.0)
    
    def _get_signal_adjustment(self, signal_strength):
        """Ajustement conservateur selon force du signal"""
        if signal_strength >= 80:
            return 1.15
        elif signal_strength >= 60:
            return 1.05
        elif signal_strength >= 40:
            return 1.0
        else:
            return 0.85
    
    def _get_fee_rate(self):
        """Retourne un taux de frais spot fallback."""
        return 0.001
    
    def get_symbol_filters(self, symbol):
        """Récupère filtres LOT_SIZE depuis l'exchange"""
        if not hasattr(self, 'symbol_filters'):
            self.symbol_filters = {}
        
        if symbol in self.symbol_filters:
            return self.symbol_filters[symbol]
        
        # Paper trading : utiliser des valeurs permissives
        if self.bot.paper_trading:
            filters = {'minQty': 0.00001, 'stepSize': 0.00001}
            self.symbol_filters[symbol] = filters
            return filters
        
        try:
            self.bot.exchange.load_markets()
            market = self.bot.exchange.markets.get(symbol)
            if market and market.get('limits'):
                amount_limits = market['limits'].get('amount', {})
                precision = market.get('precision', {}).get('amount', 8)
                step_size = 10 ** (-precision) if precision else 0.0001
                filters = {
                    'minQty': float(amount_limits.get('min', 0.0001)),
                    'stepSize': step_size
                }
                self.symbol_filters[symbol] = filters
                return filters
            
            return {'minQty': 0.0001, 'stepSize': 0.0001}
        except Exception as e:
            print(f"⚠️ Erreur récupération filtres {symbol}: {e}")
            return {'minQty': 0.0001, 'stepSize': 0.0001}
    
    def round_quantity(self, symbol, quantity):
        """Arrondit quantité au step size exchange (vers le BAS)"""
        import math
        
        filters = self.get_symbol_filters(symbol)
        step_size = filters['stepSize']
        min_qty = filters['minQty']
        
        # Arrondir vers le BAS pour éviter dust
        rounded = math.floor(quantity / step_size) * step_size
        
        # Vérifier minimum exchange
        if rounded < min_qty:
            return 0
        
        return rounded
    
    
    def _get_zero_position_size(self):
        """Retourne une position de taille zéro quand trading arrêté"""
        return {
            'size_usd': 0,
            'size_crypto': 0,
            'size_usd_net': 0,
            'fees': 0,
            'volatility_adj': 1.0,
            'signal_adj': 1.0,
            'risk_reward': 0,
            'position_size_usd': 0,
            'position_size_crypto': 0,
            'stop_loss_price': 0,
            'stop_loss_percent': 0,
            'risk_reward_ratio': 0,
            'risk_metrics': {'trading_disabled': True}
        }
    
    def _get_fallback_size(self, account_balance):
        """Taille de fallback en cas d'erreur"""
        return {
            'position_size_usd': min(10.0, account_balance * 0.02),
            'position_size_crypto': 0,
            'stop_loss_price': 0,
            'stop_loss_percent': 3.0,
            'risk_reward_ratio': 2.0,
            'risk_metrics': {}
        }
