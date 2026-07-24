"""Module de trading - Gestion des ordres d'achat/vente"""
from datetime import datetime, timedelta
import time
import os

class TradingMixin:
    """Mixin pour les opérations de trading"""

    def _calculate_fee_details(self, amount, sell_price, buy_price=None):
        """Retourne les frais paper en USD pour audit des positions sell."""
        fee_rate = float(getattr(self, 'trading_fee', 0) or 0)
        amount = float(amount or 0)
        sell_price = float(sell_price or 0)
        buy_price = float(buy_price or 0) if buy_price else 0

        sell_fee = sell_price * amount * fee_rate
        buy_fee = buy_price * amount * fee_rate if buy_price > 0 else 0
        return {
            'fee_rate': fee_rate,
            'buy_fee': buy_fee,
            'sell_fee': sell_fee,
            'fee': buy_fee + sell_fee,
            'fee_currency': 'USD'
        }
    
    def buy_market(self, symbol, amount, allow_averaging=False):
        if hasattr(self, 'risk_manager') and not self.risk_manager.can_trade():
            return None
        
        # VÉRIFICATION 1: Limite quotidienne de trades
        if hasattr(self, 'total_trades') and hasattr(self, 'max_daily_trades'):
            if self.total_trades >= self.max_daily_trades:
                print(f"❌ Limite quotidienne atteinte: {self.total_trades}/{self.max_daily_trades}")
                return None
        
        # VÉRIFICATION 2: Position existante via can_open_position (VRAIE VÉRIFICATION)
        if not allow_averaging and not self.can_open_position(symbol):
            print(f"❌ Position déjà ouverte sur {symbol} - Limite atteinte")
            return None
        
        if not self.validate_order(symbol, amount):
            print(f"❌ Validation échouée pour {symbol}")
            return None
        
        price = self.get_price(symbol)
        cost = amount * price
        
        if not self.paper_trading:
            balance = self.balance_manager.get_balance()
            available = balance.get('USD', balance.get('USD', {})).get('free', 0)
            if cost > available:
                return None
        
        try:
            if self.paper_trading:
                if cost > self.paper_balance:
                    print(f"❌ Paper trading: Fonds insuffisants {cost:.2f} > {self.paper_balance:.2f}")
                    return None
                    
                self.paper_balance -= cost
                order = {'id': f'paper_{int(time.time())}', 'price': price, 'amount': amount, 'cost': cost}
                action_text = "moyennage" if allow_averaging else "achat"
                print(f"🧪 PAPER - {action_text.title()} simulé: {amount:.6f} {symbol} à {price:.6f} (Balance: {self.paper_balance:.2f} USD)")
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
                position['avg_entry_price'] = self.get_real_buy_price(symbol)
                self.save_state()
                
                # Incrémenter compteur trades
                if hasattr(self, 'total_trades'):
                    self.total_trades += 1
                else:
                    self.total_trades = 1
                if hasattr(self, 'risk_manager'):
                    self.risk_manager.record_trade(0)
                
                if hasattr(self, 'notifier'):
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
            if hasattr(self, 'notifier') and 'insufficient balance' in str(e).lower():
                self.notifier.notify_error("Fonds insuffisants", str(e))
            return None
    
    def sell_market(self, symbol, amount):
        price = self.get_price(symbol)
        buy_price = self.get_real_buy_price(symbol)
        
        try:
            if self.paper_trading:
                revenue = amount * price
                self.paper_balance += revenue
                order = {'id': f'paper_{int(time.time())}', 'price': price, 'amount': amount, 'cost': revenue}
                print(f"🧪 PAPER - Vente simulée: {amount:.6f} {symbol} à {price:.6f} (Balance: {self.paper_balance:.2f} USD)")
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
                    'order_id': order.get('id'), 'source': 'bot', 'paper': self.paper_trading,
                    'avg_entry_price': buy_price
                }
                if self.paper_trading:
                    position.update(self._calculate_fee_details(
                        amount, order.get('price', price), buy_price
                    ))
                self.state['positions'].append(position)
                self.save_state()
                self.total_trades += 1
                
                pnl = self.calculate_pnl(symbol, 'sell', amount, price, buy_price=buy_price)
                if hasattr(self, 'risk_manager') and pnl is not None:
                    self.risk_manager.record_trade(pnl)
                
                buy_price = self.get_real_buy_price(symbol)
                buy_positions = [p for p in self.state['positions'] if p['symbol'] == symbol and p['side'] == 'buy']
                hold_time = "N/A"
                if buy_positions:
                    buy_time = datetime.fromisoformat(buy_positions[-1]['timestamp'])
                    delta = datetime.now() - buy_time
                    hours = delta.total_seconds() / 3600
                    hold_time = f"{int(hours)}h {int((hours % 1) * 60)}min" if hours >= 1 else f"{int(hours * 60)}min"
                
                if hasattr(self, 'notifier'):
                    self.notifier.notify_trade_sell(symbol, amount, price, amount * price, buy_price or price, pnl or 0, hold_time)

                if hasattr(self, 'record_ml_exit_learning_sample'):
                    self.record_ml_exit_learning_sample(
                        symbol,
                        price,
                        amount,
                        buy_price=buy_price,
                        pnl=pnl,
                        hold_time=hold_time,
                        reason='market_sell',
                        order=order
                    )

                if hasattr(self, 'set_symbol_cooldown'):
                    self.set_symbol_cooldown(symbol, reason='sell_executed')
            
            return order
        except Exception as e:
            print(f"Erreur vente: {e}")
            return None
  
    def sell_limit(self, symbol, amount, price=None):
        """Ordre limite de vente avec prix cible intelligent + GARANTIE PROFIT APRÈS FRAIS + Validation 5 USD"""
        try:
            prediction = None
            crypto = symbol.split('/')[0]
            
            # Si pas de prix spécifié, utiliser la prédiction professionnelle
            if price is None:
                current_price = self.get_price(symbol)
                
                # Calculer profit minimum avec frais (0.6% profit + 0.2% frais = 0.8% minimum)
                min_profit_with_fees = 0.8
                
                prediction = self.market_analyzer.predict_price_target_with_probability(
                    self, symbol, current_price, min_profit_pct=min_profit_with_fees
                )
                
                if prediction:
                    price = prediction['target_price']
                    
                    # Vérification finale : prix cible > prix achat + frais
                    buy_price = self.get_real_buy_price(symbol)
                    if buy_price:
                        min_sell_price = buy_price * (1 + min_profit_with_fees / 100)
                        if price < min_sell_price:
                            price = min_sell_price
                            print(f"⚠️ {crypto} → Prix ajusté pour garantir profit: {price:.6f}")
                    
                    print(f"🎯 {symbol.split('/')[0]} → Target: {price:.6f} ({prediction['method_used']}) | "
                          f"Probabilité: {prediction['probability']}% | {prediction['time_horizon']}")
                    
                    if hasattr(self, 'notifier'):
                        profit_pct = prediction['profit_potential']
                        self.notifier.notify_smart_limit_order(
                            symbol, amount, price, profit_pct, prediction
                        )
                else:
                    # Fallback: prix actuel + profit minimum avec frais
                    price = current_price * (1 + min_profit_with_fees / 100)
                    print(f"⚠️ {crypto} → Fallback target: {price:.6f} (+{min_profit_with_fees}% avec frais)")
            
            # Vérifier le minimum de l'exchange pour ce symbole
            notional_value = amount * price
            MIN_NOTIONAL = self.get_min_amount(symbol)['min_cost']
            
            if notional_value < MIN_NOTIONAL:
                print(f"❌ Montant vente {notional_value:.2f} USD < minimum {MIN_NOTIONAL} USD")
                print(f"   Quantité: {amount:.8f} {crypto} × Prix: {price:.2f} = {notional_value:.2f} USD")
                return None
            
            if self.paper_trading:
                order = {'id': f'limit_sell_{int(time.time())}', 'price': price, 'amount': amount, 'type': 'limit', 'side': 'sell'}
                self.pending_orders[order['id']] = {
                    'order': order, 'timestamp': time.time(), 'symbol': symbol, 'side': 'sell'
                }
                print(f"🧪 PAPER - Ordre limite VENTE: {amount:.6f} {symbol} @ {price:.6f} ({notional_value:.2f} USD)")
                return order
            else:
                balance = self.balance_manager.get_balance()
                base_currency = symbol.split('/')[0]
                available = balance.get(base_currency, {}).get('free', 0)
                
                if amount > available:
                    print(f"❌ Pas assez de {base_currency} libre: {amount:.6f} > {available:.6f}")
                    return None
                
                order = self.safe_request(self.exchange.create_limit_sell_order, symbol, amount, price)
                
                if not order:
                    print(f"❌ Échec création ordre limite pour {symbol}")
                    return None
                
                # Ajouter à pending_orders
                self.pending_orders[str(order['id'])] = {
                    'order': order,
                    'timestamp': time.time(),
                    'symbol': symbol,
                    'side': 'sell',
                    'source': 'bot'
                }
                
                # 🔥 NOTIFICATION ORDRE LIMITE (TOUJOURS)
                if hasattr(self, 'notifier'):
                    buy_price = self.get_real_buy_price(symbol)
                    if buy_price:
                        profit_pct = ((price - buy_price) / buy_price) * 100
                        
                        # Si prediction existe, utiliser notify_smart_limit_order
                        if hasattr(self.notifier, 'notify_smart_limit_order') and prediction:
                            self.notifier.notify_smart_limit_order(symbol, amount, price, profit_pct, prediction)
                        # Sinon, notification basique
                        elif hasattr(self.notifier, 'notify'):
                            self.notifier.notify(
                                f"🎯 ORDRE LIMITE PLACÉ\n"
                                f"Crypto: {crypto}\n"
                                f"Quantité: {amount:.6f}\n"
                                f"Prix cible: {price:.2f} USD\n"
                                f"Valeur: {notional_value:.2f} USD\n"
                                f"Profit attendu: +{profit_pct:.2f}%"
                            )
                
                print(f"✅ Ordre limite créé: {amount:.6f} {crypto} @ {price:.6f} ({notional_value:.2f} USD)")
                return order
        except Exception as e:
            print(f"❌ Erreur vente limite: {e}")
            return None
    
    def _calculate_weighted_average_from_events(self, events):
        """Calcule le prix moyen pondéré de la position restante."""
        total_amount = 0.0
        total_cost = 0.0

        for event in events:
            side = event.get('side')
            amount = float(event.get('amount') or 0)
            price = float(event.get('price') or 0)
            if amount <= 0 or price <= 0:
                continue

            if side == 'buy':
                total_amount += amount
                total_cost += amount * price
            elif side == 'sell' and total_amount > 0:
                sold_amount = min(amount, total_amount)
                average_cost = total_cost / total_amount
                total_amount -= sold_amount
                total_cost -= sold_amount * average_cost

                if total_amount <= 0.00000001:
                    total_amount = 0.0
                    total_cost = 0.0

        if total_amount <= 0.00000001:
            return None
        return total_cost / total_amount

    def _get_state_weighted_average_buy_price(self, symbol):
        events = [
            p for p in self.state.get('positions', [])
            if p.get('symbol') == symbol and p.get('side') in ['buy', 'sell']
        ]
        events.sort(key=lambda p: p.get('timestamp', ''))
        return self._calculate_weighted_average_from_events(events)

    def get_real_buy_price(self, symbol):
        # En paper trading, utiliser le prix moyen pondéré du state.
        if self.paper_trading:
            return self._get_state_weighted_average_buy_price(symbol)

        # Mode réel - utiliser l'historique de l'exchange
        try:
            balance = self.balance_manager.get_balance()
            base_currency = symbol.split('/')[0]
            current_amount = balance.get(base_currency, {}).get('free', 0) + balance.get(base_currency, {}).get('used', 0)
            
            if current_amount <= 0.00001:
                return None
            
            trades = self.safe_request(self.exchange.fetch_my_trades, symbol, limit=100)
            events = sorted(trades or [], key=lambda trade: trade.get('timestamp') or 0)
            weighted_price = self._calculate_weighted_average_from_events(events)
            if weighted_price:
                return weighted_price
        except Exception:
            pass
        
        # Fallback sur l'état des positions
        return self._get_state_weighted_average_buy_price(symbol)
    
    def calculate_pnl(self, symbol, side, amount, price, buy_price=None):
        if side == 'sell':
            real_buy_price = buy_price or self.get_real_buy_price(symbol)
            if real_buy_price:
                # Coûts avec frais INCLUS
                buy_cost = real_buy_price * amount * (1 + self.trading_fee)
                sell_revenue = price * amount * (1 - self.trading_fee)
                pnl = sell_revenue - buy_cost
                
                self.daily_pnl += pnl
                if pnl > 0:
                    self.winning_trades += 1
                
                # ✅ FRAIS RÉELS (pas double comptage)
                buy_fee = real_buy_price * amount * self.trading_fee
                sell_fee = price * amount * self.trading_fee
                total_fees = buy_fee + sell_fee
                
                print(f"💰 P&L: {pnl:+.2f} USD (Frais: -{total_fees:.4f} USD)")
                
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
                    buy_price = self.get_real_buy_price(symbol)
                    revenue = amount * current_price
                    self.paper_balance += revenue
                    print(f"✅ PAPER - Ordre limite VENTE exécuté: {amount:.6f} {symbol} @ {current_price:.6f}")
                    
                    # Calculer P&L
                    pnl = self.calculate_pnl(symbol, 'sell', amount, current_price, buy_price=buy_price)
                    if hasattr(self, 'risk_manager') and pnl is not None:
                        self.risk_manager.record_trade(pnl)
                    
                    # Envoyer notification Telegram
                    if hasattr(self, 'notifier'):
                        buy_positions = [p for p in self.state['positions'] if p['symbol'] == symbol and p['side'] == 'buy']
                        hold_time = "N/A"
                        if buy_positions:
                            buy_time = datetime.fromisoformat(buy_positions[-1]['timestamp'])
                            delta = datetime.now() - buy_time
                            hours = delta.total_seconds() / 3600
                            hold_time = f"{int(hours)}h {int((hours % 1) * 60)}min" if hours >= 1 else f"{int(hours * 60)}min"
                        
                        self.notifier.notify_trade_sell(symbol, amount, current_price, amount * current_price, buy_price or current_price, pnl or 0, hold_time)

                    if hasattr(self, 'record_ml_exit_learning_sample'):
                        self.record_ml_exit_learning_sample(
                            symbol,
                            current_price,
                            amount,
                            buy_price=buy_price,
                            pnl=pnl,
                            hold_time=hold_time if 'hold_time' in locals() else None,
                            reason='paper_limit_sell',
                            order=order
                        )
                    
                    # Enregistrer la vente
                    position = {
                        'symbol': symbol, 'side': 'sell', 'amount': amount,
                        'price': current_price, 'timestamp': datetime.now().isoformat(),
                        'order_id': order_id, 'source': 'bot', 'paper': True,
                        'avg_entry_price': buy_price
                    }
                    position.update(self._calculate_fee_details(amount, current_price, buy_price))
                    self.state['positions'].append(position)
                    if hasattr(self, 'set_symbol_cooldown'):
                        self.set_symbol_cooldown(symbol, reason='paper_limit_sell_executed')
                    
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
                    position['avg_entry_price'] = self.get_real_buy_price(symbol)
                    if hasattr(self, 'set_symbol_cooldown'):
                        self.set_symbol_cooldown(symbol, reason='paper_limit_buy_executed')
                
                executed_orders.append(order_id)
        
        # Supprimer les ordres exécutés
        for order_id in executed_orders:
            del self.pending_orders[order_id]
        
        if executed_orders:
            self.save_state()
    
    def optimize_existing_position(self, symbol):
        """Optimise une position existante avec prix cible intelligent et remplacement d'ordres"""
        # Obtenir les soldes
        balance = self.balance_manager.get_balance(force_refresh=True)
        base_currency = symbol.split('/')[0]
        free_holding = balance.get(base_currency, {}).get('free', 0)
        locked_holding = balance.get(base_currency, {}).get('used', 0)
        
        total_amount = free_holding + locked_holding
        
        if total_amount <= 0.00001:
            return False
            
        avg_buy_price = self.get_real_buy_price(symbol)
        if not avg_buy_price:
            return False
            
        current_price = self.get_price(symbol)
        
        # 1. Calculer le nouveau prix cible optimal basé sur les résistances et le profit minimum
        min_profit_pct = self.min_profit_threshold * 100
        prediction = self.market_analyzer.predict_price_target_with_probability(
            self, symbol, current_price, min_profit_pct=min_profit_pct
        )
        
        if prediction:
            sell_price = prediction['target_price']
            method = f"{prediction['method_used']} ({prediction['probability']}%)"
        else:
            # Fallback profit minimum
            sell_price = avg_buy_price * (1 + self.min_profit_threshold)
            method = "fallback"
            
        # S'assurer que la cible de profit est toujours supérieure au prix d'achat réel + frais (Pas de vente à perte)
        min_profitable_price = avg_buy_price * (1 + self.trading_fee * 2 + 0.001)
        if sell_price < min_profitable_price:
            sell_price = max(sell_price, avg_buy_price * (1 + self.min_profit_threshold))
            method = "guaranteed_profit_fallback"
            
        # 2. GESTION DU REPLACEMENT EN MODE PAPER
        if self.paper_trading:
            existing_oid = None
            existing_price = None
            for oid, od in list(self.pending_orders.items()):
                if od.get('symbol') == symbol and od.get('side') == 'sell':
                    existing_oid = oid
                    existing_price = od['order']['price']
                    break
                    
            if existing_oid:
                # Remplacer si l'écart de prix est supérieur à 0.2%
                if abs(existing_price - sell_price) / existing_price > 0.002:
                    print(f"🔄 PAPER {base_currency} : Target de vente optimisée {existing_price:.4f} → {sell_price:.4f} ({method})")
                    if existing_oid in self.pending_orders:
                        del self.pending_orders[existing_oid]
                    
                    order_id = f'paper_sell_{symbol.replace("/", "_")}_{int(time.time())}'
                    order = {'id': order_id, 'price': sell_price, 'amount': total_amount, 'type': 'limit', 'side': 'sell'}
                    self.pending_orders[order_id] = {
                        'order': order, 'timestamp': time.time(), 'symbol': symbol, 'side': 'sell'
                    }
                    return True
                return False
            else:
                # Créer un nouvel ordre de vente paper
                order_id = f'paper_sell_{symbol.replace("/", "_")}_{int(time.time())}'
                order = {'id': order_id, 'price': sell_price, 'amount': total_amount, 'type': 'limit', 'side': 'sell'}
                self.pending_orders[order_id] = {
                    'order': order, 'timestamp': time.time(), 'symbol': symbol, 'side': 'sell'
                }
                print(f"🎯 PAPER {base_currency} → Ordre vente placé @ {sell_price:.4f} ({method}) | Qty: {total_amount:.6f}")
                return True
                
        # 3. GESTION DU REPLACEMENT EN MODE RÉEL (KRAKEN)
        else:
            try:
                open_orders = self.safe_request(self.exchange.fetch_open_orders, symbol)
                sell_orders = [o for o in open_orders if o['side'] == 'sell']
                
                if sell_orders:
                    existing_order = sell_orders[0]
                    existing_price = float(existing_order['price'])
                    existing_id = existing_order['id']
                    
                    # Remplacer si l'écart de prix est supérieur à 0.2%
                    if abs(existing_price - sell_price) / existing_price > 0.002:
                        print(f"🔄 {base_currency} : Remplacement ordre de vente {existing_price:.6f} → {sell_price:.6f} ({method})")
                        self.safe_request(self.exchange.cancel_order, existing_id, symbol)
                        time.sleep(1)
                        
                        # Rafraîchir les fonds libres
                        balance = self.balance_manager.get_balance(force_refresh=True)
                        free_holding = balance.get(base_currency, {}).get('free', 0)
                        if free_holding > 0.00001:
                            self.sell_limit(symbol, free_holding, sell_price)
                            return True
                    return False
                else:
                    # Créer un nouvel ordre de vente réel
                    if free_holding > 0.00001:
                        self.sell_limit(symbol, free_holding, sell_price)
                        return True
                    return False
            except Exception as e:
                print(f"⚠️ Erreur optimisation position réelle {symbol}: {e}")
                return False

    def _get_trade_order_id(self, trade):
        """Extrait l'id d'ordre depuis un trade CCXT, selon l'exchange."""
        info = trade.get('info') or {}
        return str(
            trade.get('order')
            or trade.get('orderId')
            or info.get('orderId')
            or info.get('ordertxid')
            or info.get('order_txid')
            or ''
        )

    def _trade_matches_order(self, trade, order_id, order_data):
        order = order_data.get('order', {})
        trade_order_id = self._get_trade_order_id(trade)
        if trade_order_id and trade_order_id == str(order_id):
            return True

        if trade.get('side') != order_data.get('side'):
            return False

        order_amount = float(order.get('amount') or 0)
        order_price = float(order.get('price') or 0)
        trade_amount = float(trade.get('amount') or 0)
        trade_price = float(trade.get('price') or 0)
        if order_amount <= 0 or order_price <= 0 or trade_amount <= 0 or trade_price <= 0:
            return False

        amount_close = abs(trade_amount - order_amount) <= max(1e-8, order_amount * 0.01)
        price_close = abs(trade_price - order_price) <= max(1e-8, order_price * 0.02)
        return amount_close and price_close

    def _confirm_order_execution(self, order_id, order_data):
        """Confirme qu'un ordre disparu a vraiment généré des trades."""
        try:
            symbol = order_data.get('symbol')
            since = None
            if order_data.get('timestamp'):
                since = int(max(0, order_data['timestamp'] - 60) * 1000)

            trades = self.safe_request(self.exchange.fetch_my_trades, symbol, since, 100)
            matches = [
                trade for trade in trades
                if self._trade_matches_order(trade, order_id, order_data)
            ]
            if not matches:
                return None

            total_amount = sum(float(trade.get('amount') or 0) for trade in matches)
            if total_amount <= 0:
                return None

            total_value = sum(
                float(trade.get('amount') or 0) * float(trade.get('price') or 0)
                for trade in matches
            )
            latest_timestamp = max(trade.get('timestamp') or 0 for trade in matches)

            return {
                'symbol': symbol,
                'side': order_data.get('side'),
                'amount': total_amount,
                'price': total_value / total_amount,
                'timestamp': latest_timestamp,
                'trade_ids': [str(trade.get('id')) for trade in matches if trade.get('id')],
                'fee': sum(float((trade.get('fee') or {}).get('cost') or 0) for trade in matches)
            }
        except Exception as e:
            print(f"⚠️ Confirmation ordre impossible {order_id}: {e}")
            return None

    def _record_confirmed_order_execution(self, order_id, order_data, execution):
        """Enregistre et notifie seulement une exécution confirmée par l'historique."""
        trade_ids = set(execution.get('trade_ids') or [])
        existing_ids = set()
        for position in self.state.get('positions', []):
            if position.get('order_id'):
                existing_ids.add(str(position.get('order_id')))
            existing_ids.update(str(trade_id) for trade_id in position.get('trade_ids', []))

        if str(order_id) in existing_ids or (trade_ids and trade_ids.intersection(existing_ids)):
            return True

        symbol = execution['symbol']
        side = execution['side']
        amount = execution['amount']
        price = execution['price']
        timestamp = execution.get('timestamp') or int(time.time() * 1000)

        if side == 'sell':
            buy_price = self.get_real_buy_price(symbol)
            pnl = self.calculate_pnl(symbol, 'sell', amount, price, buy_price=buy_price)
            if hasattr(self, 'risk_manager') and pnl is not None:
                self.risk_manager.record_trade(pnl)

            if hasattr(self, 'notifier'):
                buy_positions = [p for p in self.state['positions'] if p['symbol'] == symbol and p['side'] == 'buy']
                hold_time = "N/A"
                if buy_positions:
                    buy_time = datetime.fromisoformat(buy_positions[-1]['timestamp'])
                    delta = datetime.now() - buy_time
                    hours = delta.total_seconds() / 3600
                    hold_time = f"{int(hours)}h {int((hours % 1) * 60)}min" if hours >= 1 else f"{int(hours * 60)}min"
                self.notifier.notify_trade_sell(symbol, amount, price, amount * price, buy_price or price, pnl or 0, hold_time)

            if hasattr(self, 'record_ml_exit_learning_sample'):
                self.record_ml_exit_learning_sample(
                    symbol,
                    price,
                    amount,
                    buy_price=buy_price,
                    pnl=pnl,
                    hold_time=hold_time if 'hold_time' in locals() else None,
                    reason='confirmed_exchange_sell',
                    order={'id': str(order_id)}
                )

            position = {
                'symbol': symbol, 'side': 'sell', 'amount': amount,
                'price': price, 'timestamp': datetime.fromtimestamp(timestamp / 1000).isoformat(),
                'order_id': execution['trade_ids'][0] if execution.get('trade_ids') else str(order_id),
                'exchange_order_id': str(order_id), 'trade_ids': execution.get('trade_ids', []),
                'source': 'bot_confirmed', 'paper': False,
                'fee': execution.get('fee', 0),
                'avg_entry_price': buy_price
            }
            self.state['positions'].append(position)
            self.save_state()
            print(f"✅ Ordre limite VENTE confirmé: {amount:.6f} {symbol.split('/')[0]} @ {price:.2f}")
            return True

        return False

    def _handle_disappeared_order(self, order_id, order_data):
        """Classe un ordre disparu comme exécuté seulement si les trades le confirment."""
        execution = self._confirm_order_execution(order_id, order_data)
        if execution:
            return self._record_confirmed_order_execution(order_id, order_data, execution)

        symbol = order_data.get('symbol', 'UNKNOWN')
        side = order_data.get('side', 'UNKNOWN')
        print(f"ℹ️ Ordre disparu sans trade confirmé: {side} {symbol} ({order_id}) - traité comme annulé/inconnu")
        return False
    
    def detect_order_modifications(self):
        """Synchronise TOUS les ordres ouverts depuis l'exchange (bot + manuels) + détecte exécutions."""
        if self.paper_trading:
            return
        
        try:
            import os
            trading_pairs = os.getenv('TRADING_PAIRS', 'BTCUSD,ETHUSD').split(',')
            all_open_orders = {}
            
            # Sauvegarder les ordres précédents pour détecter les exécutions
            previous_orders = dict(self.pending_orders)
            
            for pair in trading_pairs:
                symbol = pair if '/' in pair else (f"{pair.strip()[:-3]}/{pair.strip()[-3:]}" if pair.strip().endswith('USD') else f"{pair.strip()[:3]}/{pair.strip()[3:]}")
                open_orders = self.safe_request(self.exchange.fetch_open_orders, symbol)
                
                for order in open_orders:
                    order_id = str(order['id'])
                    
                    # Détecter modifications d'ordres existants
                    if order_id in self.pending_orders:
                        old_price = self.pending_orders[order_id]['order'].get('price')
                        if old_price and abs(old_price - order['price']) > 0.01:
                            crypto = symbol.split('/')[0]
                            print(f"🔄 {crypto}: Ordre modifié {old_price:.2f} → {order['price']:.2f}")
                    
                    # Synchroniser TOUS les ordres (bot + manuels)
                    order_timestamp = order.get('timestamp')
                    all_open_orders[order_id] = {
                        'order': order, 
                        'timestamp': order_timestamp / 1000 if order_timestamp else time.time(), 
                        'symbol': symbol, 
                        'side': order['side'],
                        'source': 'manual' if order_id not in self.pending_orders else 'bot'
                    }
            
            # Détecter ordres exécutés (présents avant, absents maintenant)
            for order_id, order_data in previous_orders.items():
                if order_id not in all_open_orders:
                    self._handle_disappeared_order(order_id, order_data)
            
            # Remplacer par tous les ordres synchronisés
            self.pending_orders = all_open_orders
            
        except Exception as e:
            print(f"⚠️ Erreur detect_order_modifications: {e}")
    
    def optimize_by_partial_sell(self, symbol, balance, min_cost_needed, usd_available):
        """Optimise en vendant partiellement la position pour libérer des USD"""
        print(f"   🔄 OPTIMISATION PAR VENTE PARTIELLE:")
        
        base_currency = symbol.split('/')[0]
        current_holding = balance.get(base_currency, {}).get('free', 0)
        current_price = self.get_price(symbol)
        
        # Calculer combien vendre pour obtenir les USD nécessaires
        shortage = min_cost_needed - usd_available + 1  # +1 USD de marge
        amount_to_sell = shortage / current_price
        
        print(f"   Besoin: {shortage:.2f} USD -> Vendre {amount_to_sell:.6f} {base_currency}")
        
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
            
            # 2. Vendre une partie au marché pour libérer des USD
            print(f"   💰 Vente partielle: {amount_to_sell:.6f} {base_currency} à {current_price:.2f}")
            sell_order = self.sell_market(symbol, amount_to_sell)
            
            if not sell_order:
                print(f"   ❌ Échec vente partielle")
                return False
            
            return True
            
        except Exception as e:
            print(f"   ❌ Erreur optimisation partielle: {e}")
            return False
    
    def calculate_winrate_30d(self):
        """Calcule le win rate global sur les 30 derniers jours depuis l'exchange."""
        if self.paper_trading:
            return None
        
        try:
            # Timestamp 30 jours avant
            since = int((datetime.now() - timedelta(days=30)).timestamp() * 1000)
            
            all_cycles = []
            trading_pairs = os.getenv('TRADING_PAIRS', 'BTCUSD,ETHUSD').split(',')
            
            for pair in trading_pairs:
                symbol = pair if '/' in pair else (f"{pair.strip()[:-3]}/{pair.strip()[-3:]}" if pair.strip().endswith('USD') else f"{pair.strip()[:3]}/{pair.strip()[3:]}")
                
                # Récupérer tous les trades des 30 derniers jours
                trades = self.safe_request(self.exchange.fetch_my_trades, symbol, since=since)
                if not trades:
                    continue
                
                # Trier par timestamp
                trades.sort(key=lambda x: x['timestamp'])
                
                # Analyser cycles achat/vente
                buy_stack = []  # Stack des achats en attente
                
                for trade in trades:
                    if trade['side'] == 'buy':
                        buy_stack.append({
                            'price': trade['price'],
                            'amount': trade['amount'],
                            'timestamp': trade['timestamp']
                        })
                    elif trade['side'] == 'sell' and buy_stack:
                        # Vente : matcher avec achats
                        sell_amount = trade['amount']
                        sell_price = trade['price']
                        
                        while sell_amount > 0.00001 and buy_stack:
                            buy = buy_stack[0]
                            matched_amount = min(sell_amount, buy['amount'])
                            
                            # Calculer P&L du cycle avec frais
                            buy_cost = buy['price'] * matched_amount * (1 + self.trading_fee)
                            sell_revenue = sell_price * matched_amount * (1 - self.trading_fee)
                            pnl = sell_revenue - buy_cost
                            
                            all_cycles.append({
                                'symbol': symbol,
                                'pnl': pnl,
                                'buy_price': buy['price'],
                                'sell_price': sell_price,
                                'amount': matched_amount,
                                'profitable': pnl > 0
                            })
                            
                            # Mettre à jour les quantités
                            sell_amount -= matched_amount
                            buy['amount'] -= matched_amount
                            
                            if buy['amount'] <= 0.00001:
                                buy_stack.pop(0)
            
            # Calculer statistiques
            if not all_cycles:
                return {
                    'winrate': 0,
                    'total_cycles': 0,
                    'winning_cycles': 0,
                    'losing_cycles': 0,
                    'total_pnl': 0,
                    'best_trade': 0,
                    'worst_trade': 0,
                    'period_start': datetime.fromtimestamp(since / 1000).isoformat(),
                    'last_calculated': datetime.now().isoformat()
                }
            
            winning_cycles = [c for c in all_cycles if c['profitable']]
            losing_cycles = [c for c in all_cycles if not c['profitable']]
            total_pnl = sum(c['pnl'] for c in all_cycles)
            
            stats = {
                'winrate': (len(winning_cycles) / len(all_cycles) * 100) if all_cycles else 0,
                'total_cycles': len(all_cycles),
                'winning_cycles': len(winning_cycles),
                'losing_cycles': len(losing_cycles),
                'total_pnl': total_pnl,
                'best_trade': max(c['pnl'] for c in all_cycles) if all_cycles else 0,
                'worst_trade': min(c['pnl'] for c in all_cycles) if all_cycles else 0,
                'period_start': datetime.fromtimestamp(since / 1000).isoformat(),
                'last_calculated': datetime.now().isoformat()
            }
            
            # Sauvegarder dans state
            self.state['global_stats_30d'] = stats
            self.save_state()
            
            print(f"📊 Win Rate (30j): {stats['winrate']:.1f}% | {stats['total_cycles']} cycles | {stats['total_pnl']:+.2f} USD")
            
            return stats
            
        except Exception as e:
            print(f"⚠️ Erreur calcul win rate 30j: {e}")
            return None
