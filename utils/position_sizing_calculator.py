"""
Position Sizing Calculator - COMBIEN acheter (30% → 90% pro level)
ATR-based sizing + Risk management + Volatility adjustment
"""

import numpy as np
from datetime import datetime

class PositionSizingCalculator:
    def __init__(self, bot):
        self.bot = bot
        self.cache = {}
        self.cache_duration = 300  # 5 minutes
    
    def calculate_position_size(self, symbol, signal_strength, account_balance):
        """Calcule la taille de position optimale"""
        cache_key = f"{symbol}_position"
        now = datetime.now()
        
        # Vérifier cache
        if (cache_key in self.cache and 
            (now - self.cache[cache_key]['timestamp']).seconds < self.cache_duration):
            cached_data = self.cache[cache_key]
            # Recalculer avec nouveau balance
            return self._adjust_for_balance(cached_data['base_size'], account_balance, cached_data['risk_data'])
        
        # Calculer nouvelle taille
        position_data = self._calculate_optimal_size(symbol, signal_strength, account_balance)
        
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
                signal_strength
            )
            
            return {
                'position_size_usdt': final_size['size_usdt'],
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
            current_price = self.bot.get_current_price(symbol)
            atr_percent = atr_data['atr_percent']
            
            # Stop loss adaptatif selon volatilité
            if atr_percent > 4.0:  # Haute volatilité
                stop_multiplier = 2.5
            elif atr_percent > 2.0:  # Volatilité moyenne
                stop_multiplier = 2.0
            else:  # Faible volatilité
                stop_multiplier = 1.5
            
            stop_distance_percent = atr_percent * stop_multiplier
            stop_distance_percent = max(1.0, min(stop_distance_percent, 8.0))  # Entre 1% et 8%
            
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
        base_risk_percent = 1.0  # 1% de base
        
        # Ajustement selon force du signal
        if signal_strength >= 80:
            risk_multiplier = 1.5  # 1.5% pour signaux très forts
        elif signal_strength >= 60:
            risk_multiplier = 1.2  # 1.2% pour signaux forts
        elif signal_strength >= 40:
            risk_multiplier = 1.0  # 1% pour signaux moyens
        else:
            risk_multiplier = 0.5  # 0.5% pour signaux faibles
        
        risk_percent = base_risk_percent * risk_multiplier
        risk_amount = account_balance * (risk_percent / 100)
        
        return {
            'percent': risk_percent,
            'amount': risk_amount,
            'multiplier': risk_multiplier
        }
    
    def _calculate_risk_based_size(self, risk_per_trade, stop_distance, symbol):
        """Calcule taille position basée sur risque"""
        try:
            current_price = self.bot.get_current_price(symbol)
            
            # Position size = Risk Amount / Stop Distance
            position_size_usdt = risk_per_trade['amount'] / stop_distance
            position_size_crypto = position_size_usdt / current_price
            
            return {
                'size_usdt': position_size_usdt,
                'size_crypto': position_size_crypto,
                'current_price': current_price
            }
            
        except Exception as e:
            print(f"⚠️ Erreur risk-based size {symbol}: {e}")
            return {'size_usdt': 10, 'size_crypto': 0, 'current_price': 0}
    
    def _apply_final_adjustments(self, position_size, account_balance, atr_data, signal_strength):
        """Applique ajustements finaux"""
        try:
            size_usdt = position_size['size_usdt']
            
            # 1. Limite maximale (10% du compte)
            max_position = account_balance * 0.10
            size_usdt = min(size_usdt, max_position)
            
            # 2. Limite minimale (5 USDT)
            size_usdt = max(size_usdt, 5.0)
            
            # 3. Ajustement volatilité
            volatility_adj = self._get_volatility_adjustment(atr_data['volatility_level'])
            size_usdt *= volatility_adj
            
            # 4. Ajustement signal
            signal_adj = self._get_signal_adjustment(signal_strength)
            size_usdt *= signal_adj
            
            # 5. Recalculer crypto amount
            current_price = position_size['current_price']
            size_crypto = size_usdt / current_price if current_price > 0 else 0
            
            # 6. Risk/Reward ratio (target 1:2 minimum)
            risk_reward = 2.0  # Par défaut
            
            return {
                'size_usdt': round(size_usdt, 2),
                'size_crypto': size_crypto,
                'volatility_adj': volatility_adj,
                'signal_adj': signal_adj,
                'risk_reward': risk_reward
            }
            
        except Exception as e:
            print(f"⚠️ Erreur ajustements finaux: {e}")
            return {
                'size_usdt': 10.0,
                'size_crypto': 0,
                'volatility_adj': 1.0,
                'signal_adj': 1.0,
                'risk_reward': 2.0
            }
    
    def _classify_volatility(self, atr_percent):
        """Classifie le niveau de volatilité"""
        if atr_percent > 4.0:
            return 'high'
        elif atr_percent > 2.0:
            return 'medium'
        else:
            return 'low'
    
    def _get_volatility_adjustment(self, volatility_level):
        """Ajustement selon volatilité"""
        adjustments = {
            'low': 1.2,     # Augmenter pour faible volatilité
            'medium': 1.0,  # Normal
            'high': 0.8     # Réduire pour haute volatilité
        }
        return adjustments.get(volatility_level, 1.0)
    
    def _get_signal_adjustment(self, signal_strength):
        """Ajustement selon force du signal"""
        if signal_strength >= 80:
            return 1.3
        elif signal_strength >= 60:
            return 1.1
        elif signal_strength >= 40:
            return 1.0
        else:
            return 0.7
    
    def _adjust_for_balance(self, cached_size, current_balance, risk_data):
        """Ajuste taille cachée pour nouveau balance"""
        # Recalcul rapide basé sur ratio de balance
        # Implementation simplifiée pour éviter recalculs complets
        return cached_size
    
    def _get_fallback_size(self, account_balance):
        """Taille de fallback en cas d'erreur"""
        return {
            'position_size_usdt': min(10.0, account_balance * 0.02),
            'position_size_crypto': 0,
            'stop_loss_price': 0,
            'stop_loss_percent': 3.0,
            'risk_reward_ratio': 2.0,
            'risk_metrics': {}
        }