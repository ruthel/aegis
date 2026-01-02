"""Module de trading - Gestion des ordres d'achat/vente"""
from datetime import datetime
import time

class TradingMixin:
    """Mixin pour les opérations de trading"""
    
    def buy_market(self, symbol, amount, allow_averaging=False):
        print(f"🔄 DEBUG: buy_market appelé pour {symbol}, montant: {amount:.6f}")
        
        # VÉRIFICATION 1: Limite quotidienne de trades
        if hasattr(self, 'total_trades') and hasattr(self, 'max_daily_trades'):
            if self.total_trades >= self.max_daily_trades:
                print(f"❌ Limite quotidienne atteinte: {self.total_trades}/{self.max_daily_trades}")
                return None
        
        # VÉRIFICATION 2: Position existante (sauf moyennage)
        if not allow_averaging:
            existing_positions = [p for p in self.state.get('positions', []) 
                                if p['symbol'] == symbol and p['side'] == 'buy']
            if existing_positions:
                print(f"❌ Position déjà ouverte sur {symbol} - 1 max/crypto")
                return None
        
        if self.paper_trading:
            # En paper trading, utiliser paper_balance au lieu de balance_manager
            current_holding = 0  # Pas de holdings en paper trading simple
        else:
            balance = self.balance_manager.get_balance()
            base_currency = symbol.split('/')[0]
            current_holding = balance.get(base_currency, {}).get('free', 0)
        
        if current_holding > 0.00001 and not allow_averaging:
            position_value = current_holding * self.get_price(symbol)
            min_trade_value = self.get_min_amount(symbol)['min_cost']
            
            if position_value >= min_trade_value:
                print(f"⚠️ {symbol.split('/')[0]} déjà détenu ({position_value:.2f} USDT) - 1 max/crypto")
                return None
        
        if not self.validate_order(symbol, amount):
            print(f"❌ Validation échouée pour {symbol}")
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
                if cost > self.paper_balance:
                    print(f"❌ Paper trading: Fonds insuffisants {cost:.2f} > {self.paper_balance:.2f}")
                    return None
                    
                self.paper_balance -= cost
                order = {'id': f'paper_{int(time.time())}', 'price': price, 'amount': amount, 'cost': cost}
                action_text = "moyennage" if allow_averaging else "achat"
                print(f"🧪 PAPER - {action_text.title()} simulé: {amount:.6f} {symbol} à {price:.6f} (Balance: {self.paper_balance:.2f} USDT)")
            else:
                order = self.safe_request(self.exchange.create_market_buy_order, symbol, amount)
                action_text = "Moyennage" if allow_averaging else "Achat"
                print(f"✅ {action_text} exécuté: {amount:.6f} {symbol}")
            
            if order:
                position = {
                    'symbol': symbol, 'side': 'buy', 'amount': amount,
                    'price': order.get('price', price), 'timestamp': datetime.now().isoformat(),
                    'order_id': order.get('id'), 'source': 'bot', 'paper': self.paper_trading,
                    'averaging': allow_averaging
                }
                if 'positions' not in self.state:
                    self.state['positions'] = []
                self.state['positions'].append(position)
                self.save_state()
                
                # Incrémenter compteur trades
                if hasattr(self, 'total_trades'):
                    self.total_trades += 1
                else:
                    self.total_trades = 1
                
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
                print(f"🧪 PAPER - Vente simulée: {amount:.6f} {symbol} à {price:.6f} (Balance: {self.paper_balance:.2f} USDT)")
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
                self.pending_orders[order['id']] = {'order': order, 'timestamp': time.time(), 'symbol': symbol}
                print(f"🧪 PAPER - Ordre limite ACHAT: {amount:.6f} {symbol} @ {price:.6f}")
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
                # Ajouter à pending_orders pour simulation
                self.pending_orders[order['id']] = {
                    'order': order, 'timestamp': time.time(), 'symbol': symbol, 'side': 'sell'
                }
                print(f"🧪 PAPER - Ordre limite VENTE: {amount:.6f} {symbol} @ {price:.6f}")
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
        # En paper trading, utiliser uniquement l'état des positions
        if self.paper_trading:
            buy_positions = [p for p in self.state['positions'] if p['symbol'] == symbol and p['side'] == 'buy']
            if buy_positions:
                return buy_positions[-1]['price']
            return None
            
        # Mode réel - utiliser l'API Binance
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
        
        # Fallback sur l'état des positions
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
    
    def check_paper_limit_orders(self):
        """Vérifie et exécute les ordres limite en paper trading"""
        if not self.paper_trading or not hasattr(self, 'pending_orders'):
            return
        
        executed_orders = []
        
        for order_id, order_data in self.pending_orders.items():
            order = order_data['order']
            symbol = order_data['symbol']
            
            if order.get('type') != 'limit':
                continue
                
            current_price = self.get_price(symbol)
            limit_price = order['price']
            side = order['side']
            amount = order['amount']
            
            # Vérifier si l'ordre doit être exécuté
            should_execute = False
            if side == 'sell' and current_price >= limit_price:
                should_execute = True
            elif side == 'buy' and current_price <= limit_price:
                should_execute = True
            
            if should_execute:
                # Exécuter l'ordre
                if side == 'sell':
                    revenue = amount * current_price
                    self.paper_balance += revenue
                    print(f"✅ PAPER - Ordre limite VENTE exécuté: {amount:.6f} {symbol} @ {current_price:.6f}")
                    
                    # Calculer P&L
                    pnl = self.calculate_pnl(symbol, 'sell', amount, current_price)
                    
                    # Enregistrer la vente
                    position = {
                        'symbol': symbol, 'side': 'sell', 'amount': amount,
                        'price': current_price, 'timestamp': datetime.now().isoformat(),
                        'order_id': order_id, 'source': 'bot', 'paper': True
                    }
                    self.state['positions'].append(position)
                    
                elif side == 'buy':
                    cost = amount * current_price
                    self.paper_balance -= cost
                    print(f"✅ PAPER - Ordre limite ACHAT exécuté: {amount:.6f} {symbol} @ {current_price:.6f}")
                    
                    # Enregistrer l'achat
                    position = {
                        'symbol': symbol, 'side': 'buy', 'amount': amount,
                        'price': current_price, 'timestamp': datetime.now().isoformat(),
                        'order_id': order_id, 'source': 'bot', 'paper': True
                    }
                    self.state['positions'].append(position)
                
                executed_orders.append(order_id)
        
        # Supprimer les ordres exécutés
        for order_id in executed_orders:
            del self.pending_orders[order_id]
        
        if executed_orders:
            self.save_state()
    
    def optimize_existing_position(self, symbol):
        """Optimise une position existante en recalculant la moyenne des positions"""
        balance = self.balance_manager.get_balance()
        base_currency = symbol.split('/')[0]
        free_holding = balance.get(base_currency, {}).get('free', 0)
        locked_holding = balance.get(base_currency, {}).get('used', 0)
        
        total_amount = free_holding + locked_holding
        
        if total_amount <= 0.00001:
            return False
        
        # Si tout est libre (pas d'ordre actif), placer un ordre de vente
        if locked_holding <= 0.00001:
            avg_buy_price = self.get_real_buy_price(symbol)
            if avg_buy_price:
                min_profit = self.min_profit_threshold + (2 * self.trading_fee)
                sell_price = avg_buy_price * (1 + min_profit)
                sell_order = self.sell_limit(symbol, free_holding, sell_price)
                if sell_order:
                    print(f"💰 Ordre de vente placé: {free_holding:.6f} {base_currency} @ {sell_price:.2f}")
                    return True
            return False
        
        return False
    
    def detect_order_modifications(self):
        """Détecte les modifications d'ordres faites manuellement sur Binance"""
        if self.paper_trading:
            return
        
        try:
            import os
            trading_pairs = os.getenv('TRADING_PAIRS', 'BTCUSDT,ETHUSDT').split(',')
            for pair in trading_pairs:
                symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
                open_orders = self.safe_request(self.exchange.fetch_open_orders, symbol)
                
                for order in open_orders:
                    order_id = str(order['id'])
                    if order_id in self.pending_orders:
                        old_price = self.pending_orders[order_id]['order'].get('price')
                        if old_price and abs(old_price - order['price']) > 0.01:
                            crypto = symbol.split('/')[0]
                            print(f"🔄 {crypto}: Ordre modifié {old_price:.2f} → {order['price']:.2f}")
                    
                    self.pending_orders[order_id] = {
                        'order': order, 'timestamp': order['timestamp'] / 1000, 
                        'symbol': symbol, 'side': order['side']
                    }
        except Exception as e:
            pass
    
    def optimize_by_partial_sell(self, symbol, balance, min_cost_needed, usdt_available):
        """Optimise en vendant partiellement la position pour libérer des USDT"""
        print(f"   🔄 OPTIMISATION PAR VENTE PARTIELLE:")
        
        base_currency = symbol.split('/')[0]
        current_holding = balance.get(base_currency, {}).get('free', 0)
        current_price = self.get_price(symbol)
        
        # Calculer combien vendre pour obtenir les USDT nécessaires
        shortage = min_cost_needed - usdt_available + 1  # +1 USDT de marge
        amount_to_sell = shortage / current_price
        
        print(f"   Besoin: {shortage:.2f} USDT -> Vendre {amount_to_sell:.6f} {base_currency}")
        
        # Vérifier qu'on a assez à vendre
        if amount_to_sell > current_holding:
            print(f"   ❌ Pas assez de {base_currency} libre pour vendre")
            return False
        
        # Vérifier les limites minimales
        min_limits = self.get_min_amount(symbol)
        if amount_to_sell < min_limits['min_amount']:
            amount_to_sell = min_limits['min_amount']
            print(f"   Ajustement au minimum: {amount_to_sell:.6f} {base_currency}")
        
        try:
            # 1. Annuler l'ordre de vente existant
            if not self.paper_trading:
                open_orders = self.safe_request(self.exchange.fetch_open_orders, symbol)
                for order in open_orders:
                    if order['side'] == 'sell':
                        self.safe_request(self.exchange.cancel_order, order['id'], symbol)
                        print(f"   ❌ Ordre de vente annulé: {order['price']:.2f}")
            
            # 2. Vendre une partie au marché pour libérer des USDT
            print(f"   💰 Vente partielle: {amount_to_sell:.6f} {base_currency} à {current_price:.2f}")
            sell_order = self.sell_market(symbol, amount_to_sell)
            
            if not sell_order:
                print(f"   ❌ Échec vente partielle")
                return False
            
            return True
            
        except Exception as e:
            print(f"   ❌ Erreur optimisation partielle: {e}")
            return False
