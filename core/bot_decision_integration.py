"""
Intégration affichage décisions dans scalping_strategy
Ajouter ces lignes dans binance_spot_bot.py
"""

# Dans __init__, après self.notifier:
"""
from utils.decision_display import DecisionDisplay
self.decision_display = DecisionDisplay()
if self.notify_trades:
    self.notifier.set_bot(self)
"""

# Dans scalping_strategy, remplacer la section logique d'achat:
"""
def scalping_strategy(self, symbol, amount, current_price):
    if not self.safety_manager.can_trade():
        self.decision_display.show_decision(symbol, 'SKIP', 'Limite trades atteinte', 'Reset quotidien')
        return
    
    # Analyse
    multi_tf_analysis = self.get_cached_analysis(symbol, current_price)
    global_signal = multi_tf_analysis['global_signal']
    
    # Afficher résumé analyse
    self.decision_display.show_analysis_summary(symbol, global_signal['action'], global_signal['confidence'], current_price)
    
    # Position sizing
    smart_amount = self.risk_manager.calculate_position_size(self, symbol, amount)
    
    # LOGIQUE ACHAT avec décisions
    if global_signal['action'] in ['BUY', 'STRONG_BUY']:
        if global_signal['confidence'] < 60:
            self.decision_display.show_decision(
                symbol, 'HOLD', 
                f"Confiance {global_signal['confidence']:.0f}% < 60%",
                f"Confiance ≥60% OU Prix {current_price*1.005:.2f}"
            )
            return
        
        if not self.correlation_manager.can_open_position(symbol, self):
            self.decision_display.show_decision(
                symbol, 'SKIP',
                'Max positions corrélées atteint',
                'Vente position existante'
            )
            return
        
        # Vérifier solde
        balance = self.get_balance()
        usdt = balance.get('USDT', {}).get('free', 0)
        min_cost = self.get_min_amount(symbol)['min_cost']
        
        if usdt < min_cost:
            self.decision_display.show_decision(
                symbol, 'SKIP',
                f'Solde {usdt:.2f} < {min_cost} USDT',
                f'+{min_cost - usdt:.2f} USDT requis'
            )
            return
        
        # ACHAT PRÊT
        self.decision_display.show_decision(symbol, 'BUY_READY', f'Signal {global_signal["confidence"]:.0f}%', 'Exécution immédiate')
        
        trade_amount = smart_amount / current_price
        print(f"🟢 SIGNAL ACHAT - Montant: {trade_amount:.6f} {symbol.split('/')[0]}")
        
        result = self.buy_market(symbol, trade_amount)
        if result:
            self.trailing_stop.add_position(symbol, current_price)
            self.correlation_manager.add_position(symbol)
            self.safety_manager.record_trade(0)
    
    elif global_signal['action'] == 'HOLD':
        self.decision_display.show_decision(
            symbol, 'HOLD',
            f"Signal neutre ({global_signal['confidence']:.0f}%)",
            'Signal BUY/SELL fort'
        )
    
    # LOGIQUE VENTE avec décisions
    self.trailing_stop.update_position(symbol, current_price)
    
    base_currency = symbol.split('/')[0]
    balance = self.get_balance()
    available = balance.get(base_currency, {}).get('free', 0)
    
    if available > 0:
        buy_positions = [p for p in self.state['positions'] if p['symbol'] == symbol and p['side'] == 'buy']
        if buy_positions:
            avg_buy_price = sum(p['price'] for p in buy_positions) / len(buy_positions)
            expected_profit_pct = (current_price - avg_buy_price) / avg_buy_price
            min_profit_needed = self.min_profit_threshold + (2 * self.trading_fee)
            
            should_sell = (
                expected_profit_pct >= min_profit_needed or
                self.trailing_stop.should_stop_loss(symbol, current_price)
            )
            
            if should_sell:
                self.decision_display.show_decision(
                    symbol, 'SELL_READY',
                    f'Profit {expected_profit_pct*100:+.2f}% ≥ {min_profit_needed*100:.2f}%',
                    'Exécution immédiate'
                )
                
                print(f"🔴 SIGNAL VENTE - Montant: {available:.6f} {base_currency}")
                result = self.sell_market(symbol, available)
                if result:
                    profit = self.calculate_pnl(symbol, 'sell', available, current_price)
                    self.safety_manager.record_trade(profit)
                    self.trailing_stop.remove_position(symbol)
                    self.correlation_manager.remove_position(symbol)
            else:
                target_price = avg_buy_price * (1 + min_profit_needed)
                self.decision_display.show_decision(
                    symbol, 'WAITING',
                    f'Profit {expected_profit_pct*100:+.2f}% < {min_profit_needed*100:.2f}%',
                    f'Prix ≥{target_price:.2f} ({((target_price/current_price)-1)*100:+.1f}%)'
                )
"""

# Dans run(), après show_realtime_prices():
"""
# Notification status périodique
if self.notify_trades:
    self.notifier.send_status_update()
"""
