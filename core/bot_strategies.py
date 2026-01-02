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
        
        # VÉRIFIER POSITION EXISTANTE EN PREMIER
        if not self.correlation_manager.can_open_position(symbol, self):
            print(f"🚫 {symbol}: Position déjà ouverte - skip")
            return
        
        multi_tf_analysis = self.get_cached_analysis(symbol, current_price)
        global_signal = multi_tf_analysis['global_signal']
        
        if global_signal['action'] in ['BUY', 'STRONG_BUY', 'SELL', 'STRONG_SELL']:
            vol_display = multi_tf_analysis.get('volatility', 2.0)
            self.async_print(f"🎯 {global_signal['action']} (Force: {global_signal['strength']:.1f}, Conf: {global_signal['confidence']:.1f}%, Vol: {vol_display:.1f}/5)")
        
        # VÉRIFIER MONTANT MINIMUM BINANCE
        min_cost = self.get_min_amount(symbol)['min_cost']
        trade_amount_usdt = max(amount, min_cost)  # Utiliser le plus élevé
        vol_value = multi_tf_analysis.get('volatility', 2.0)
        min_confidence = ConfidenceCalculator.get_min_confidence(vol_value)
        
        action_ok = global_signal['action'] in ['BUY', 'STRONG_BUY']
        conf_ok = global_signal['confidence'] >= min_confidence
        
        # Vérifier fonds disponibles
        balance = self.balance_manager.get_balance()
        usdt_available = balance.get('USDT', {}).get('free', 0)
        funds_ok = usdt_available >= trade_amount_usdt
        
        if not funds_ok:
            print(f"💰 {symbol}: Fonds insuffisants {usdt_available:.2f} < {trade_amount_usdt:.2f}")
            return
        
        print(f"🔍 {symbol.split('/')[0]}: vol={vol_value:.1f}/5 action={global_signal['action']}({action_ok}) conf={global_signal['confidence']:.0f}≥{min_confidence}({conf_ok}) funds={funds_ok}")
        
        if action_ok and conf_ok:
            trade_amount = trade_amount_usdt / current_price
            print(f"🟢 ACHAT {symbol.split('/')[0]}: {trade_amount_usdt:.1f} USDT = {trade_amount:.6f} {symbol.split('/')[0]}")
        
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
        # VÉRIFIER POSITION EXISTANTE
        if not self.correlation_manager.can_open_position(symbol, self):
            print(f"🚫 {symbol}: Position déjà ouverte - skip DCA")
            return
        
        # RESPECTER MONTANT MINIMUM BINANCE
        min_cost = self.get_min_amount(symbol)['min_cost']
        trade_amount_usdt = max(amount, min_cost)
        trade_amount = trade_amount_usdt / current_price
        print(f"⚡ DCA: {trade_amount_usdt:.1f} USDT = {trade_amount:.6f} {symbol.split('/')[0]} @ {current_price/1000:.1f}K")
        result = self.buy_market(symbol, trade_amount)
        if result:
            self.correlation_manager.add_position(symbol)
    
    def intelligent_strategy(self, symbol, amount, current_price):
        print(f"🚀 DEBUT intelligent_strategy pour {symbol} - NOUVEAU CODE ACTIF!")
        print(f"🔄 DEBUG: intelligent_strategy appelée pour {symbol}")
        
        if not self.safety_manager.can_trade():
            print(f"❌ {symbol}: safety_manager.can_trade() = False")
            return
        
        # SÉLECTION AUTOMATIQUE DE STRATÉGIE
        strategy_mode = self.auto_select_strategy(symbol, current_price)
        print(f"🤖 {symbol}: Stratégie sélectionnée = {strategy_mode}")
        
        # Si hold, ne rien faire
        if strategy_mode == 'hold':
            print(f"⏸️ {symbol}: Mode HOLD - Aucune action")
            return
        
        # UTILISER MONTANT FIXE POUR TOUS
        fixed_amount = float(os.getenv('TRADE_AMOUNT', '5'))
        
        if strategy_mode == 'scalping_pullback':
            print(f"🎯 {symbol}: Exécution scalping_pullback (montant: {fixed_amount} USDT)")
            self.scalping_pullback_strategy(symbol, fixed_amount, current_price)
        elif strategy_mode == 'momentum':
            print(f"🚀 {symbol}: Exécution momentum (montant: {fixed_amount} USDT)")
            self.scalping_strategy(symbol, fixed_amount, current_price)
        elif strategy_mode == 'dca':
            print(f"💰 {symbol}: Exécution DCA (montant: {fixed_amount} USDT)")
            self.dca_strategy(symbol, fixed_amount, current_price)
    
    def auto_select_strategy(self, symbol, current_price):
        """Sélection automatique de la meilleure stratégie avec filtres Phase 1 + Anti-Retournement + Protections Critiques"""
        
        # VÉRIFICATIONS CRITIQUES EN PREMIER
        
        # 1. FLASH CRASH DETECTION
        if self.flash_crash_detector.detect_flash_crash(self, symbol, current_price):
            return 'hold'
        
        if not self.flash_crash_detector.can_trade(symbol):
            return 'hold'
        
        # 2. MACRO EVENTS
        if not self.macro_monitor.can_trade():
            return 'hold'
        
        # 3. CONTAGION DETECTION
        trading_pairs = os.getenv('TRADING_PAIRS', 'BTCUSDT,ETHUSDT').split(',')
        formatted_pairs = [p if '/' in p else f"{p[:3]}/{p[3:]}" for p in trading_pairs]
        
        if self.contagion_detector.detect_market_contagion(self, formatted_pairs):
            if self.contagion_detector.should_emergency_sell(self, symbol):
                # Vente d'urgence si contagion détectée
                self._emergency_sell_position(symbol)
            return 'hold'
        
        if not self.contagion_detector.can_trade(symbol):
            return 'hold'
        
        # 4. MULTI-EXCHANGE FALLBACK
        if not self.multi_exchange_fallback.check_binance_status():
            fallback_msg = self.multi_exchange_fallback.get_status_message()
            if fallback_msg:
                print(fallback_msg)
            if self.multi_exchange_fallback.emergency_sell_signal():
                self._emergency_sell_position(symbol)
            return 'hold'
        
        # 5. MANIPULATION DETECTION
        ticker = self.get_ticker(symbol)
        price = ticker['last']
        volume = ticker.get('quoteVolume', 0)
        self.manipulation_detector.add_data_point(symbol, price, volume)
        
        should_avoid, avoid_reason = self.manipulation_detector.should_avoid_trading(symbol)
        if should_avoid:
            crypto = symbol.split('/')[0]
            print(f"🚨 {crypto}: {avoid_reason} - PROTECTION")
            return 'hold'
        
        # 6. NEWS MONITORING
        news_signal, news_confidence, news_reason = self.news_monitor.analyze_news_impact(symbol)
        is_viral, viral_info = self.news_monitor.detect_viral_event(symbol)
        
        # 7. STABLECOIN DEPEG DETECTION
        if hasattr(self, 'stablecoin_monitor') and self.stablecoin_monitor.is_depeg_active():
            crypto = symbol.split('/')[0]
            depeg_msg = self.stablecoin_monitor.get_status_message()
            print(f"💰 {crypto}: {depeg_msg} - PROTECTION")
            return 'hold'
        
        # 8. PATTERN RECOGNITION
        klines = self.get_klines(symbol, 50, os.getenv('MAIN_TIMEFRAME', '15m'))
        if hasattr(self, 'pattern_recognition') and len(klines) >= 20:
            pattern_analysis = self.pattern_recognition.detect_patterns(klines)
            if pattern_analysis['bearish_detected']:
                strongest = pattern_analysis['strongest_pattern']
                crypto = symbol.split('/')[0]
                print(f"📈 {crypto}: {strongest['description']} - PROTECTION")
                return 'hold'
        
        # 9. SLIPPAGE PROTECTION
        if hasattr(self, 'slippage_calculator'):
            trade_amount_usdt = float(os.getenv('TRADE_AMOUNT', '5'))
            slippage_check = self.slippage_calculator.calculate_execution_cost(self, symbol, 'BUY', trade_amount_usdt)
            if not slippage_check.get('can_execute', True):
                crypto = symbol.split('/')[0]
                print(f"💸 {crypto}: {slippage_check.get('reason', 'Slippage élevé')} - PROTECTION")
                return 'hold'
        
        # 10. LIQUIDITY PROTECTION
        if hasattr(self, 'liquidity_checker'):
            liquidity_check = self.liquidity_checker.check_liquidity(self, symbol)
            if not liquidity_check.get('is_liquid', True):
                crypto = symbol.split('/')[0]
                print(f"💧 {crypto}: {liquidity_check.get('reason', 'Liquidité faible')} - PROTECTION")
                return 'hold'
        
        # VÉRIFICATION CRITIQUE: Position existante EN PREMIER
        existing_positions = [p for p in self.state.get('positions', []) 
                            if p['symbol'] == symbol and p['side'] == 'buy']
        if existing_positions:
            print(f"🚫 {symbol}: Position existante détectée - retour HOLD")
            return 'hold'
        
        # NOUVEAUX FILTRES PHASE 1
        multi_tf_analysis = self.get_cached_analysis(symbol, current_price)
        
        # Filtre marché tendanciel
        if os.getenv('AVOID_RANGING_MARKETS', 'False') == 'True':
            timeframes = multi_tf_analysis.get('timeframes', {})
            trending_count = sum(1 for tf_data in timeframes.values() if tf_data.get('is_trending', True))
            if trending_count < len(timeframes) * 0.6:  # Moins de 60% tendanciel
                print(f"🚫 {symbol}: Marché latéral détecté - retour HOLD")
                return 'hold'
        
        # Filtre corrélation BTC
        if not self.multi_tf_analyzer.get_btc_correlation_filter(self, symbol):
            print(f"🚫 {symbol}: BTC en baisse forte - retour HOLD")
            return 'hold'
        
        # NOUVEAU: Vérifier risque de retournement AVANT sélection stratégie
        klines = self.get_klines(symbol, 50, os.getenv('MAIN_TIMEFRAME', '15m'))
        reversal_check = self.multi_tf_analyzer.detect_reversal_signals(klines, current_price)
        
        if reversal_check['has_reversal_risk']:
            risk_factors = ', '.join(reversal_check['risk_factors'])
            # AFFICHAGE AMÉLIORÉ avec détails techniques
            current_price_display = f"{current_price:.2f}"
            crypto = symbol.split('/')[0]
            
            # Analyser les facteurs de risque pour affichage détaillé
            risk_details = []
            for factor in reversal_check['risk_factors']:
                if factor == 'NEAR_KEY_LEVEL':
                    risk_details.append("🎯 Résistance proche")
                elif factor == 'WEAK_MOMENTUM':
                    risk_details.append("📉 Momentum faible")
                elif factor == 'HIGH_RSI':
                    risk_details.append("📊 RSI élevé")
                elif factor == 'VOLUME_DIVERGENCE':
                    risk_details.append("📈 Volume divergent")
                else:
                    risk_details.append(f"⚠️ {factor}")
            
            risk_display = risk_details[-1]
            print(f"🛡️  {crypto} {current_price_display}: {risk_display} - PROTECTION")
            return 'hold'
        
        # NOUVEAU: Analyse Support/Résistance pour prédiction retournement
        if len(klines) >= 50 and hasattr(self, 'sr_analyzer'):
            sr_levels = self.sr_analyzer.find_support_resistance_levels(klines)
            reversal_pred = self.sr_analyzer.predict_reversal_probability(current_price, sr_levels)
            
            if reversal_pred['has_reversal_potential'] and reversal_pred['probability'] > 70:
                direction = reversal_pred['direction']
                level_price = reversal_pred['target_level']['price']
                print(f"🎯 {symbol}: Retournement probable {direction} à {level_price:.2f} ({reversal_pred['probability']:.0f}%)")
                
                # Si retournement DOWN prédit, éviter les achats
                if direction == 'DOWN':
                    crypto = symbol.split('/')[0]
                    print(f"🛡️ {crypto} {current_price:.2f}: RETOURNEMENT {direction} @ {level_price:.2f} ({reversal_pred['probability']:.0f}%) - PROTECTION")
                    return 'hold'
        
        # Initialiser analyseurs si nécessaire
        if not hasattr(self, 'ema_analyzer'):
            self.ema_analyzer = BinanceEMAAnalyzer()
        if not hasattr(self, 'pullback_detector'):
            self.pullback_detector = PullbackDetector()
        if not hasattr(self, 'strategy_cooldown'):
            self.strategy_cooldown = {}
        
        # Vérifier cooldown
        cooldown_key = f"{symbol}_failed"
        if cooldown_key in self.strategy_cooldown:
            if time.time() - self.strategy_cooldown[cooldown_key] < 300:  # 5 min
                print(f"⏰ {symbol}: En cooldown - retour HOLD")
                return 'hold'
        
        # Vérifier fonds disponibles
        balance = self.balance_manager.get_balance()
        usdt_available = balance.get('USDT', {}).get('free', 0)
        min_cost = self.get_min_amount(symbol)['min_cost']
        
        if usdt_available < min_cost:
            print(f"💰 {symbol}: Fonds insuffisants {usdt_available:.2f} < {min_cost:.2f} - retour HOLD")
            return 'hold'
        
        # Récupérer priorités
        pullback_priority = int(os.getenv('SCALPING_PULLBACK_PRIORITY', '10'))
        momentum_priority = int(os.getenv('MOMENTUM_PRIORITY', '7'))
        dca_priority = int(os.getenv('DCA_PRIORITY', '5'))
        
        # Analyse EMA Binance
        ema_analysis = self.ema_analyzer.analyze(klines, current_price)
        
        scores = {}
        
        # Score Scalping Pullback
        if ema_analysis and ema_analysis['case'] == 3:
            pullback_data = self.pullback_detector.detect_pullback(self, symbol, current_price, ema_analysis)
            if pullback_data and pullback_data['is_valid']:
                scores['scalping_pullback'] = pullback_priority * 10
                print(f"🎯 CAS 3 détecté: {ema_analysis['case_name']} - Pullback {pullback_data['pullback_pct']:.2f}%")
        
        # Score Momentum Trading (avec bonus news positives)
        global_signal = multi_tf_analysis['global_signal']
        
        if global_signal['action'] in ['BUY', 'STRONG_BUY']:
            confidence_factor = global_signal['confidence'] / 100
            momentum_score = momentum_priority * confidence_factor * 10
            
            # Bonus si news positives
            if news_signal in ['BUY', 'BUY_WEAK'] and news_confidence > 0.5:
                momentum_score *= 1.2  # +20% bonus
                print(f"📈 Bonus news: {news_reason}")
            
            scores['momentum'] = momentum_score
        
        # Score DCA
        if ema_analysis and ema_analysis['case'] in [5, 6]:
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
        
        return 'hold'  # Retourner hold si aucune stratégie valide
    
    def _emergency_sell_position(self, symbol):
        """Vente d'urgence d'une position"""
        try:
            balance = self.balance_manager.get_balance()
            base_currency = symbol.split('/')[0]
            available = balance.get(base_currency, {}).get('free', 0)
            
            if available > 0.00001:
                position_value = available * self.get_price(symbol)
                min_cost = self.get_min_amount(symbol)['min_cost']
                
                if position_value >= min_cost:
                    result = self.sell_market(symbol, available)
                    if result:
                        print(f"🚨 VENTE URGENCE: {available:.6f} {base_currency}")
                        return True
            return False
        except Exception as e:
            print(f"❌ Erreur vente urgence {symbol}: {e}")
            return False
    
    def scalping_pullback_strategy(self, symbol, amount, current_price):
        """Stratégie scalping sur pullback avec ordre limite"""
        if not self.safety_manager.can_trade():
            return
        
        # VÉRIFIER POSITION EXISTANTE EN PREMIER
        if not self.correlation_manager.can_open_position(symbol, self):
            print(f"🚫 {symbol}: Position déjà ouverte - skip pullback")
            return
        
        # INCOHÉRENCE #1: Vérifier fonds disponibles AVANT analyse
        balance = self.balance_manager.get_balance()
        usdt_available = balance.get('USDT', {}).get('free', 0)
        min_cost = self.get_min_amount(symbol)['min_cost']
        
        if usdt_available < min_cost:
            return  # Pas assez de fonds, skip silencieusement
        
        # Analyse EMA
        klines = self.get_klines(symbol, 100, os.getenv('MAIN_TIMEFRAME', '15m'))
        ema_analysis = self.ema_analyzer.analyze(klines, current_price)
        
        if not ema_analysis or ema_analysis['case'] != 3:
            return
        
        # Détecter pullback
        pullback_data = self.pullback_detector.detect_pullback(self, symbol, current_price, ema_analysis)
        
        if not pullback_data or not pullback_data['is_valid']:
            return
        
        # NOUVEAU: Vérifier niveaux Support/Résistance pour optimiser entrée
        if len(klines) >= 50 and hasattr(self, 'sr_analyzer'):
            sr_levels = self.sr_analyzer.find_support_resistance_levels(klines)
            reversal_pred = self.sr_analyzer.predict_reversal_probability(current_price, sr_levels)
            
            # Si support fort détecté, ajuster prix d'entrée
            if reversal_pred['nearest_support'] and reversal_pred['direction'] == 'UP':
                support_price = reversal_pred['nearest_support']['price']
                if support_price > pullback_data['entry_price']:
                    pullback_data['entry_price'] = support_price
                    print(f"🎯 Support détecté à {support_price:.2f} - Entrée ajustée")
        
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
    
    def handle_sell_logic(self, symbol, current_price, global_signal):
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
        
        klines = self.get_klines(symbol, 20, os.getenv('MAIN_TIMEFRAME', '15m'))
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
        balance = self.balance_manager.get_balance()
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