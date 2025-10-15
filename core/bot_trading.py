"""Module de trading - Gestion des ordres d'achat/vente"""
from datetime import datetime
import time

class TradingMixin:
    """Mixin pour les opérations de trading"""
    
    def buy_market(self, symbol, amount):
        balance = self.balance_manager.get_balance()
        base_currency = symbol.split('/')[0]
        current_holding = balance.get(base_currency, {}).get('free', 0)
        
        if current_holding > 0.00001:
            position_value = current_holding * self.get_price(symbol)
            min_trade_value = self.get_min_amount(symbol)['min_cost']
            
            if position_value >= min_trade_value:
                print(f"⚠️ {base_currency} déjà détenu ({position_value:.2f} USDT) - 1 max/crypto")
                return None
        
        if not self.validate_order(symbol, amount):
            return None
        
        price = self.get_price(symbol)
        cost = amount * price
        
        if cost > self.max_daily_loss:
            print(f"❌ Dépassement limite quotidienne: {cost} > {self.max_daily_loss}")
            return None
        
        if not self.paper_trading:
            balance = self.balance_manager.get_balance()
            available = balance.get('USDT', {}).get('free', 0)
            if cost > available:
                shortage = cost - available
                if not self.earn_manager.withdraw_from_flexible(shortage):
                    return None
        
        try:
            if self.paper_trading:
                self.paper_balance -= cost
                order = {'id': f'paper_{int(time.time())}', 'price': price, 'amount': amount, 'cost': cost}
                print(f"🧪 PAPER - Achat simulé: {amount:.6f} {symbol} à {price:.6f}")
            else:
                order = self.safe_request(self.exchange.create_market_buy_order, symbol, amount)
                print(f"✅ Achat exécuté: {amount:.6f} {symbol}")
            
            if order:
                position = {
                    'symbol': symbol, 'side': 'buy', 'amount': amount,
                    'price': order.get('price', price), 'timestamp': datetime.now().isoformat(),
                    'order_id': order.get('id'), 'source': 'bot', 'paper': self.paper_trading
                }
                self.state['positions'].append(position)
                self.save_state()
                self.total_trades += 1
                
                if self.notify_trades:
                    analysis = self.get_cached_analysis(symbol, price)
                    signal_data = {
                        'trend': analysis['global_signal'].get('dominant_trend', 'N/A'),
                        'confidence': analysis['global_signal'].get('confidence', 0),
                        'volatility': analysis.get('volatility', 0)
                    }
                    self.notifier.notify_trade_buy(symbol, amount, price, cost, signal_data)
            
            return order
        except Exception as e:
            print(f"❌ Erreur achat: {e}")
            if self.notify_trades and 'insufficient balance' in str(e).lower():
                self.notifier.notify_error("Fonds insuffisants", str(e))
            return None
    
    def sell_market(self, symbol, amount):
        price = self.get_price(symbol)
        
        try:
            if self.paper_trading:
                revenue = amount * price
                self.paper_balance += revenue
                order = {'id': f'paper_{int(time.time())}', 'price': price, 'amount': amount, 'cost': revenue}
            else:
                balance = self.balance_manager.get_balance()
                base_currency = symbol.split('/')[0]
                available = balance.get(base_currency, {}).get('free', 0)
                
                if amount > available:
                    print(f"❌ Pas assez de {base_currency}: {amount} > {available}")
                    return None
                
                order = self.safe_request(self.exchange.create_market_sell_order, symbol, amount)
            
            if order:
                position = {
                    'symbol': symbol, 'side': 'sell', 'amount': amount,
                    'price': order.get('price', price), 'timestamp': datetime.now().isoformat(),
                    'order_id': order.get('id'), 'source': 'bot', 'paper': self.paper_trading
                }
                self.state['positions'].append(position)
                self.save_state()
                self.total_trades += 1
                
                pnl = self.calculate_pnl(symbol, 'sell', amount, price)
                
                if self.notify_trades and pnl is not None:
                    buy_price = self.get_real_buy_price(symbol)
                    buy_positions = [p for p in self.state['positions'] if p['symbol'] == symbol and p['side'] == 'buy']
                    hold_time = "N/A"
                    if buy_positions:
                        buy_time = datetime.fromisoformat(buy_positions[-1]['timestamp'])
                        delta = datetime.now() - buy_time
                        hours = delta.total_seconds() / 3600
                        hold_time = f"{int(hours)}h {int((hours % 1) * 60)}min" if hours >= 1 else f"{int(hours * 60)}min"
                    
                    self.notifier.notify_trade_sell(symbol, amount, price, amount * price, buy_price or price, pnl, hold_time)
            
            return order
        except Exception as e:
            print(f"Erreur vente: {e}")
            return None
    
    def buy_limit(self, symbol, amount, price):
        if not self.validate_order(symbol, amount, price):
            return None
        
        try:
            if self.paper_trading:
                order = {'id': f'limit_{int(time.time())}', 'price': price, 'amount': amount, 'type': 'limit', 'side': 'buy'}
                self.pending_orders[order['id']] = order
                return order
            else:
                order = self.safe_request(self.exchange.create_limit_buy_order, symbol, amount, price)
                if order:
                    self.pending_orders[order['id']] = {'order': order, 'timestamp': time.time(), 'symbol': symbol}
                return order
        except Exception as e:
            print(f"❌ Erreur ordre limite: {e}")
            return None
    
    def sell_limit(self, symbol, amount, price):
        try:
            if self.paper_trading:
                order = {'id': f'limit_sell_{int(time.time())}', 'price': price, 'amount': amount, 'type': 'limit', 'side': 'sell'}
                return order
            else:
                balance = self.balance_manager.get_balance()
                base_currency = symbol.split('/')[0]
                available = balance.get(base_currency, {}).get('free', 0)
                
                if amount > available:
                    return None
                
                order = self.safe_request(self.exchange.create_limit_sell_order, symbol, amount, price)
                if order and self.notify_trades:
                    estimation = self.predict_next_sell_execution(symbol)
                    profit_pct = ((price - self.get_real_buy_price(symbol)) / self.get_real_buy_price(symbol)) * 100
                    self.notifier.notify_limit_order(symbol, amount, price, profit_pct, estimation)
                
                return order
        except Exception as e:
            print(f"❌ Erreur vente limite: {e}")
            return None
    
    def get_real_buy_price(self, symbol):
        if not self.paper_trading:
            try:
                balance = self.balance_manager.get_balance()
                base_currency = symbol.split('/')[0]
                current_amount = balance.get(base_currency, {}).get('free', 0) + balance.get(base_currency, {}).get('used', 0)
                
                if current_amount <= 0.00001:
                    return None
                
                trades = self.safe_request(self.exchange.fetch_my_trades, symbol, limit=100)
                net_amount = 0
                weighted_price = 0
                
                for trade in reversed(trades):
                    if trade['side'] == 'buy':
                        net_amount += trade['amount']
                        weighted_price += trade['price'] * trade['amount']
                    else:
                        net_amount -= trade['amount']
                    
                    if net_amount >= current_amount:
                        break
                
                if net_amount > 0:
                    return weighted_price / net_amount
            except:
                pass
        
        buy_positions = [p for p in self.state['positions'] if p['symbol'] == symbol and p['side'] == 'buy']
        if buy_positions:
            return buy_positions[-1]['price']
        return None
    
    def calculate_pnl(self, symbol, side, amount, price):
        if side == 'sell':
            real_buy_price = self.get_real_buy_price(symbol)
            if real_buy_price:
                buy_cost = real_buy_price * amount * (1 + self.trading_fee)
                sell_revenue = price * amount * (1 - self.trading_fee)
                pnl = sell_revenue - buy_cost
                
                self.daily_pnl += pnl
                if pnl > 0:
                    self.winning_trades += 1
                
                fee_cost = (real_buy_price + price) * amount * self.trading_fee
                print(f"💰 P&L: {pnl:+.2f} USDT (Frais: -{fee_cost:.2f})")
                
                return pnl
        return None
