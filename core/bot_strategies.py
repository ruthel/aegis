"""Module stratégies - Scalping, DCA, Intelligent, Pullback"""
from utils.confidence_calculator import ConfidenceCalculator
from utils.ema_analyzer import BinanceEMAAnalyzer
from utils.pullback_detector import PullbackDetector
import time
import os

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
        
        # SÉLECTION AUTOMATIQUE DE STRATÉGIE
        strategy_mode = self.auto_select_strategy(symbol, current_price)
        
        # INCOHÉRENCE #6: Si hold, ne rien faire
        if strategy_mode == 'hold':
            return
        
        if strategy_mode == 'scalping_pullback':
            self.scalping_pullback_strategy(symbol, amount, current_price)
        elif strategy_mode == 'momentum':
            self.scalping_strategy(symbol, amount, current_price)
        elif strategy_mode == 'dca':
            self.dca_strategy(symbol, amount, current_price)
    
    def auto_select_strategy(self, symbol, current_price):
        """Sélection automatique de la meilleure stratégie"""
        # Initialiser analyseurs si nécessaire
        if not hasattr(self, 'ema_analyzer'):
            self.ema_analyzer = BinanceEMAAnalyzer()
        if not hasattr(self, 'pullback_detector'):
            self.pullback_detector = PullbackDetector()
        if not hasattr(self, 'strategy_cooldown'):
            self.strategy_cooldown = {}  # INCOHÉRENCE #3: Mémoriser tentatives
        
        # INCOHÉRENCE #3: Vérifier cooldown
        cooldown_key = f"{symbol}_failed"
        if cooldown_key in self.strategy_cooldown:
            if time.time() - self.strategy_cooldown[cooldown_key] < 300:  # 5 min
                return 'hold'  # Skip pendant cooldown
        
        # INCOHÉRENCE #2: Vérifier position ouverte
        if not self.correlation_manager.can_open_position(symbol, self):
            return 'hold'
        
        # INCOHÉRENCE #1: Vérifier fonds disponibles
        balance = self.balance_manager.get_balance()
        usdt_available = balance.get('USDT', {}).get('free', 0)
        min_cost = self.get_min_amount(symbol)['min_cost']
        
        if usdt_available < min_cost:
            return 'hold'  # Pas assez de fonds
        
        # Récupérer priorités
        pullback_priority = int(os.getenv('SCALPING_PULLBACK_PRIORITY', '10'))
        momentum_priority = int(os.getenv('MOMENTUM_PRIORITY', '7'))
        dca_priority = int(os.getenv('DCA_PRIORITY', '5'))
        
        # Analyse EMA Binance
        klines = self.get_klines(symbol, 100)
        ema_analysis = self.ema_analyzer.analyze(klines, current_price)
        
        scores = {}
        
        # Score Scalping Pullback
        if ema_analysis and ema_analysis['case'] == 3:
            pullback_data = self.pullback_detector.detect_pullback(self, symbol, current_price, ema_analysis)
            if pullback_data and pullback_data['is_valid']:
                scores['scalping_pullback'] = pullback_priority * 10
                print(f"🎯 CAS 3 détecté: {ema_analysis['case_name']} - Pullback {pullback_data['pullback_pct']:.2f}%")
        
        # Score Momentum Trading
        multi_tf_analysis = self.get_cached_analysis(symbol, current_price)
        global_signal = multi_tf_analysis['global_signal']
        
        if global_signal['action'] in ['BUY', 'STRONG_BUY']:
            confidence_factor = global_signal['confidence'] / 100
            scores['momentum'] = momentum_priority * confidence_factor * 10
        
        # Score DCA
        if ema_analysis and ema_analysis['case'] in [5, 6]:
            klines = self.get_klines(symbol, 20)
            if len(klines) >= 14:
                closes = [k['close'] for k in klines]
                rsi = self.pullback_detector.calculate_rsi(closes)
                if rsi and rsi < 30:
                    scores['dca'] = dca_priority * 10
        
        # Sélectionner meilleur score
        if scores:
            best_strategy = max(scores, key=scores.get)
            best_score = scores[best_strategy]
            print(f"🤖 Sélection auto: {best_strategy.upper()} (score: {best_score:.0f})")
            for strat, score in scores.items():
                status = "✅" if strat == best_strategy else "❌"
                print(f"   {status} {strat}: {score:.0f}")
            return best_strategy
        
        return 'hold'  # INCOHÉRENCE #6: Retourner hold au lieu de momentum
    
    def scalping_pullback_strategy(self, symbol, amount, current_price):
        """Stratégie scalping sur pullback avec ordre limite"""
        if not self.safety_manager.can_trade():
            return
        
        # INCOHÉRENCE #2: Vérifier position déjà ouverte EN PREMIER
        if not self.correlation_manager.can_open_position(symbol, self):
            return
        
        # INCOHÉRENCE #1: Vérifier fonds disponibles AVANT analyse
        balance = self.balance_manager.get_balance()
        usdt_available = balance.get('USDT', {}).get('free', 0)
        min_cost = self.get_min_amount(symbol)['min_cost']
        
        if usdt_available < min_cost:
            return  # Pas assez de fonds, skip silencieusement
        
        # Analyse EMA
        klines = self.get_klines(symbol, 100)
        ema_analysis = self.ema_analyzer.analyze(klines, current_price)
        
        if not ema_analysis or ema_analysis['case'] != 3:
            return
        
        # Détecter pullback
        pullback_data = self.pullback_detector.detect_pullback(self, symbol, current_price, ema_analysis)
        
        if not pullback_data or not pullback_data['is_valid']:
            return
        
        # Calculer montant
        smart_amount = self.risk_manager.calculate_position_size(self, symbol, amount)
        trade_amount = smart_amount / pullback_data['entry_price']
        
        # Vérifier encore une fois les fonds (double sécurité)
        if smart_amount > usdt_available:
            return
        
        # Placer ordre limite ACHAT
        print(f"📊 SCALPING PULLBACK activé pour {symbol}")
        print(f"   🟡 EMA 7: {ema_analysis['ema_7']:.2f}")
        print(f"   💗 EMA 25: {ema_analysis['ema_25']:.2f}")
        print(f"   🟣 EMA 99: {ema_analysis['ema_99']:.2f}")
        print(f"   💰 Prix: {current_price:.2f}")
        print(f"   🎯 Entrée: {pullback_data['entry_price']:.2f}")
        print(f"   🎯 Cible: {pullback_data['target_price']:.2f} (+{float(os.getenv('SCALPING_PROFIT_TARGET', '0.3')):.1f}%)")
        
        order = self.pullback_detector.place_limit_buy_order(
            self, symbol, pullback_data['entry_price'], trade_amount
        )
        
        if order:
            self.correlation_manager.add_position(symbol)
    
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
        
        # Vérifier et annuler ordres expirés
        if hasattr(self, 'pullback_detector'):
            self.pullback_detector.check_and_cancel_expired_orders(self)
        
        # Sélection automatique
        strategy_mode = self.auto_select_strategy(symbol, current_price)
        
        if strategy_mode == 'scalping_pullback':
            self.scalping_pullback_strategy(symbol, amount, current_price)
        elif strategy_mode == 'momentum':
            self.realtime_scalping(symbol, amount, current_price)
        elif strategy_mode == 'dca':
            trade_amount = amount / current_price
            self.buy_market(symbol, trade_amount)
