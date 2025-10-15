"""Module stratégies - Scalping, DCA, Intelligent"""
from utils.confidence_calculator import ConfidenceCalculator
import time

class StrategiesMixin:
    """Mixin pour les stratégies de trading"""
    
    def scalping_strategy(self, symbol, amount, current_price):
        if not self.safety_manager.can_trade():
            return
        
        multi_tf_analysis = self.get_cached_analysis(symbol, current_price)
        global_signal = multi_tf_analysis['global_signal']
        
        if global_signal['action'] in ['BUY', 'STRONG_BUY', 'SELL', 'STRONG_SELL']:
            vol_display = multi_tf_analysis.get('volatility', 2.0)
            self.async_print(f"🎯 {global_signal['action']} (Force: {global_signal['strength']:.1f}, Conf: {global_signal['confidence']:.1f}%, Vol: {vol_display:.1f}/5)")
        
        smart_amount = self.risk_manager.calculate_position_size(self, symbol, amount)
        vol_value = multi_tf_analysis.get('volatility', 2.0)
        min_confidence = ConfidenceCalculator.get_min_confidence(vol_value)
        
        action_ok = global_signal['action'] in ['BUY', 'STRONG_BUY']
        conf_ok = global_signal['confidence'] >= min_confidence
        corr_ok = self.correlation_manager.can_open_position(symbol, self)
        
        balance = self.balance_manager.get_balance()
        usdt_available = balance.get('USDT', {}).get('free', 0)
        min_cost = self.get_min_amount(symbol)['min_cost']
        funds_ok = usdt_available >= min_cost
        
        print(f"🔍 {symbol.split('/')[0]}: vol={vol_value:.1f}/5 action={global_signal['action']}({action_ok}) conf={global_signal['confidence']:.0f}≥{min_confidence}({conf_ok}) corr={corr_ok} funds={funds_ok}")
        
        if action_ok and conf_ok and corr_ok and funds_ok:
            trade_amount = smart_amount / current_price
            print(f"🟢 ACHAT {symbol.split('/')[0]}: conf {global_signal['confidence']:.0f}% ≥ {min_confidence}%, vol {vol_value:.1f}/5")
            
            result = self.buy_market(symbol, trade_amount)
            if result:
                self.trailing_stop.add_position(symbol, current_price)
                self.correlation_manager.add_position(symbol)
                self.safety_manager.record_trade(0)
        
        self.trailing_stop.update_position(symbol, current_price)
        
        base_currency = symbol.split('/')[0]
        available = balance.get(base_currency, {}).get('free', 0)
        locked = balance.get(base_currency, {}).get('used', 0)
        
        # Ne pas placer d'ordre si déjà locked (ordre actif)
        if locked > 0.00001:
            return
        
        if available > 0.00001:
            position_value = available * current_price
            if position_value < self.get_min_amount(symbol)['min_cost']:
                return
            
            real_buy_price = self.get_real_buy_price(symbol)
            if real_buy_price:
                min_profit_needed = self.min_profit_threshold + (2 * self.trading_fee)
                target_profit = self.min_profit_threshold + (2 * self.trading_fee)
                limit_price = real_buy_price * (1 + target_profit)
                profit_at_limit = ((limit_price - real_buy_price) / real_buy_price) * 100
                
                existing_order = None
                for order_id, order_data in self.pending_orders.items():
                    if order_data['symbol'] == symbol and order_data['side'] == 'sell':
                        if abs(order_data['order'].get('price', 0) - limit_price) < 0.01:
                            existing_order = order_id
                            break
                
                if not existing_order:
                    print(f"🎯 Ordre LIMIT placé: {available:.6f} {base_currency} @ {limit_price:.2f} (profit: +{profit_at_limit:.2f}%)")
                    result = self.sell_limit(symbol, available, limit_price)
                    if result and result.get('id'):
                        self.pending_orders[str(result['id'])] = {
                            'order': result, 'timestamp': time.time(),
                            'symbol': symbol, 'side': 'sell'
                        }
    
    def dca_strategy(self, symbol, amount, current_price):
        trade_amount = amount / current_price
        print(f"⚡ DCA: +{trade_amount:.6f} {symbol.split('/')[0]} @ {current_price/1000:.1f}K")
        self.buy_market(symbol, trade_amount)
    
    def intelligent_strategy(self, symbol, amount, current_price):
        if not self.safety_manager.can_trade():
            return
        
        multi_tf_analysis = self.get_cached_analysis(symbol, current_price)
        global_signal = multi_tf_analysis['global_signal']
        market_metrics = self.analyze_market_conditions(symbol, current_price)
        
        strategy_choice = self.choose_optimal_strategy_advanced(global_signal, market_metrics)
        order_type = self.choose_optimal_order_type(global_signal, market_metrics, strategy_choice)
        
        if strategy_choice == 'scalping':
            self.execute_scalping_with_order_type(symbol, amount, current_price, order_type, global_signal)
        elif strategy_choice == 'dca':
            self.execute_dca_with_order_type(symbol, amount, current_price, order_type)
        else:
            self.scalping_strategy(symbol, amount, current_price)
    
    def adaptive_strategy(self, symbol, amount, current_price):
        if not self.safety_manager.can_trade():
            return
        
        multi_tf_analysis = self.get_cached_analysis(symbol, current_price)
        global_signal = multi_tf_analysis['global_signal']
        volatility = multi_tf_analysis.get('volatility', 2.0)
        
        strategy_choice = self.choose_optimal_strategy(global_signal, volatility, symbol)
        
        if strategy_choice == 'scalping':
            self.scalping_strategy(symbol, amount, current_price)
        elif strategy_choice == 'dca':
            self.dca_strategy(symbol, amount, current_price)
    
    def choose_optimal_strategy(self, global_signal, volatility, symbol):
        action = global_signal['action']
        confidence = global_signal['confidence']
        trend = global_signal.get('dominant_trend', 'neutral')
        
        if (volatility >= 3.0 and confidence >= 65 and 
            action in ['BUY', 'STRONG_BUY', 'SELL', 'STRONG_SELL'] and 
            trend in ['bullish', 'neutral']):
            return 'scalping'
        elif (trend == 'bearish' and confidence >= 50 and action in ['BUY', 'STRONG_BUY']):
            return 'dca'
        else:
            return 'hold'
    
    def choose_optimal_strategy_advanced(self, global_signal, market_metrics):
        action = global_signal['action']
        confidence = global_signal['confidence']
        volatility = market_metrics['volatility']
        liquidity = market_metrics['liquidity']
        
        if (volatility >= 2.5 and confidence >= 60 and 
            liquidity in ['high', 'medium'] and 
            action in ['BUY', 'STRONG_BUY', 'SELL', 'STRONG_SELL']):
            return 'scalping'
        elif (global_signal.get('dominant_trend') == 'bearish' and 
              confidence >= 45 and action in ['BUY', 'STRONG_BUY']):
            return 'dca'
        else:
            return 'hold'
    
    def choose_optimal_order_type(self, global_signal, market_metrics, strategy):
        volatility = market_metrics['volatility']
        confidence = global_signal['confidence']
        urgency = global_signal['strength']
        
        if (urgency >= 2.0 or volatility >= 5.0 or confidence >= 80 or 
            (strategy == 'scalping' and confidence >= 70)):
            return 'market'
        else:
            return 'market'
    
    def execute_scalping_with_order_type(self, symbol, amount, current_price, order_type, global_signal):
        smart_amount = self.risk_manager.calculate_position_size(self, symbol, amount)
        
        if (global_signal['action'] in ['BUY', 'STRONG_BUY'] and
            self.correlation_manager.can_open_position(symbol, self)):
            
            trade_amount = smart_amount / current_price
            result = self.buy_market(symbol, trade_amount)
            
            if result:
                self.trailing_stop.add_position(symbol, current_price)
                self.correlation_manager.add_position(symbol)
                self.safety_manager.record_trade(0)
        
        self.trailing_stop.update_position(symbol, current_price)
        self.handle_sell_logic(symbol, current_price, order_type, global_signal)
    
    def execute_dca_with_order_type(self, symbol, amount, current_price, order_type):
        trade_amount = amount / current_price
        self.buy_market(symbol, trade_amount)
    
    def handle_sell_logic(self, symbol, current_price, order_type, global_signal):
        base_currency = symbol.split('/')[0]
        balance = self.balance_manager.get_balance()
        available = balance.get(base_currency, {}).get('free', 0)
        
        if available > 0:
            real_buy_price = self.get_real_buy_price(symbol)
            if real_buy_price:
                expected_profit_pct = (current_price - real_buy_price) / real_buy_price
                min_profit_needed = self.min_profit_threshold + (2 * self.trading_fee)
                
                should_sell = (expected_profit_pct >= min_profit_needed or
                              self.trailing_stop.should_stop_loss(symbol, current_price))
                
                if should_sell:
                    multi_tf_analysis = self.get_cached_analysis(symbol, current_price)
                    profile = multi_tf_analysis['global_signal'].get('profile', {'profit_target': 0.5})
                    adaptive_profit = profile['profit_target'] / 100
                    limit_price = real_buy_price * (1 + adaptive_profit)
                    
                    result = self.sell_limit(symbol, available, limit_price)
                    if result:
                        self.safety_manager.record_trade(0)
                        self.trailing_stop.remove_position(symbol)
                        self.correlation_manager.remove_position(symbol)
    
    def analyze_market_conditions(self, symbol, current_price):
        analysis = self.get_cached_analysis(symbol, current_price)
        volatility = analysis.get('volatility', 2.0)
        spread = 0.01 if volatility > 5 else 0.005
        
        klines = self.get_klines(symbol, 20)
        if len(klines) >= 5:
            avg_volume = sum(k['volume'] for k in klines[-5:]) / 5
            liquidity = 'high' if avg_volume > 1000000 else 'medium' if avg_volume > 100000 else 'low'
        else:
            liquidity = 'medium'
            avg_volume = 500000
        
        return {'volatility': volatility, 'spread': spread, 'liquidity': liquidity, 'avg_volume': avg_volume}
    
    def realtime_scalping(self, symbol, amount, current_price):
        if not self.safety_manager.can_trade():
            return
        
        multi_tf_analysis = self.get_cached_analysis(symbol, current_price, force=True)
        global_signal = multi_tf_analysis['global_signal']
        
        if global_signal['confidence'] < 70:
            return
        
        smart_amount = self.risk_manager.calculate_position_size(self, symbol, amount)
        
        if (global_signal['action'] in ['BUY', 'STRONG_BUY'] and 
            self.correlation_manager.can_open_position(symbol, self)):
            
            trade_amount = smart_amount / current_price
            result = self.buy_market(symbol, trade_amount)
            if result:
                self.trailing_stop.add_position(symbol, current_price)
                self.correlation_manager.add_position(symbol)
        
        self.trailing_stop.update_position(symbol, current_price)
        
        base_currency = symbol.split('/')[0]
        balance = self.get_balance()
        available = balance.get(base_currency, {}).get('free', 0)
        
        if available > 0:
            real_buy_price = self.get_real_buy_price(symbol)
            if real_buy_price:
                min_profit_needed = self.min_profit_threshold + (2 * self.trading_fee)
                target_profit = self.min_profit_threshold + (2 * self.trading_fee)
                limit_price = real_buy_price * (1 + target_profit)
                
                existing_order = None
                for order_id, order_data in self.pending_orders.items():
                    if order_data['symbol'] == symbol and order_data['side'] == 'sell':
                        if abs(order_data['order'].get('price', 0) - limit_price) < 0.01:
                            existing_order = order_id
                            break
                
                if not existing_order:
                    result = self.sell_limit(symbol, available, limit_price)
                    if result and result.get('id'):
                        self.pending_orders[str(result['id'])] = {
                            'order': result, 'timestamp': time.time(),
                            'symbol': symbol, 'side': 'sell'
                        }
    
    def realtime_adaptive(self, symbol, amount, current_price):
        if not self.safety_manager.can_trade():
            return
        
        multi_tf_analysis = self.get_cached_analysis(symbol, current_price, force=True)
        global_signal = multi_tf_analysis['global_signal']
        volatility = multi_tf_analysis.get('volatility', 2.0)
        
        strategy_choice = self.choose_optimal_strategy(global_signal, volatility, symbol)
        
        if strategy_choice == 'scalping':
            self.realtime_scalping(symbol, amount, current_price)
        elif strategy_choice == 'dca' and global_signal['action'] in ['BUY', 'STRONG_BUY']:
            trade_amount = amount / current_price
            self.buy_market(symbol, trade_amount)
    
    def realtime_intelligent(self, symbol, amount, current_price):
        if not self.safety_manager.can_trade():
            return
        
        multi_tf_analysis = self.get_cached_analysis(symbol, current_price, force=True)
        global_signal = multi_tf_analysis['global_signal']
        market_metrics = self.analyze_market_conditions(symbol, current_price)
        
        strategy_choice = self.choose_optimal_strategy_advanced(global_signal, market_metrics)
        order_type = self.choose_optimal_order_type(global_signal, market_metrics, strategy_choice)
        
        self.manage_pending_orders()
        
        if strategy_choice == 'scalping':
            self.execute_scalping_with_order_type(symbol, amount, current_price, order_type, global_signal)
        elif strategy_choice == 'dca' and global_signal['action'] in ['BUY', 'STRONG_BUY']:
            self.execute_dca_with_order_type(symbol, amount, current_price, order_type)
