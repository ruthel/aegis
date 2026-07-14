"""Module synchronisation - Sync positions, ordres, historique"""
from datetime import datetime
import os
import time

class SyncMixin:
    """Mixin pour la synchronisation avec l'exchange spot."""

    def sync_positions_from_exchange(self):
        if self.paper_trading:
            return
        
        try:
            self.sync_open_orders()
            self.sync_trade_history()
            
            balance = self.balance_manager.get_balance()
            trading_pairs = os.getenv('TRADING_PAIRS', 'BTCUSD,ETHUSD').split(',')
            
            all_positions = [p for p in self.state.get('positions', [])]
            active_buy_positions = []
            changed = False
            
            for pair in trading_pairs:
                symbol = pair if '/' in pair else (f"{pair.strip()[:-3]}/{pair.strip()[-3:]}" if pair.strip().endswith('USD') else f"{pair.strip()[:3]}/{pair.strip()[3:]}")
                base_currency = symbol.split('/')[0]
                available = balance.get(base_currency, {}).get('free', 0)
                
                if available > 0.00001:
                    existing_buys = [p for p in all_positions if p['symbol'] == symbol and p['side'] == 'buy']
                    
                    # Ignorer si valeur trop faible (dust)
                    try:
                        current_price = self.get_price(symbol)
                        min_cost = self.get_min_amount(symbol)['min_cost']
                        if available * current_price < min_cost:
                            continue
                    except:
                        pass

                    if existing_buys:
                        position = existing_buys[-1].copy()
                        old_amount = position.get('amount', 0)
                        position['amount'] = available
                        active_buy_positions.append(position)
                        if abs(old_amount - available) > 0.00001:
                            changed = True
                    else:
                        last_trade = self.get_last_buy_from_history(symbol)
                        if last_trade:
                            active_buy_positions.append(last_trade)
                            changed = True
            
            if changed:
                history = [p for p in all_positions if p['side'] == 'sell' or p.get('source') in ['binance_history', 'exchange_history']]
                self.state['positions'] = history + active_buy_positions
                self.save_state()
        except Exception as e:
            print(f"⚠️ Erreur sync: {e}")
    
    def sync_open_orders(self):
        try:
            trading_pairs = os.getenv('TRADING_PAIRS', 'BTCUSD,ETHUSD').split(',')
            
            # Nettoyer d'abord les ordres locaux obsolètes
            all_open_order_ids = set()
            
            for pair in trading_pairs:
                symbol = pair if '/' in pair else (f"{pair.strip()[:-3]}/{pair.strip()[-3:]}" if pair.strip().endswith('USD') else f"{pair.strip()[:3]}/{pair.strip()[3:]}")
                open_orders = self.safe_request(self.exchange.fetch_open_orders, symbol)
                
                for order in open_orders:
                    order_id = str(order['id'])
                    all_open_order_ids.add(order_id)
                    
                    if order_id not in self.pending_orders:
                        order_timestamp = order.get('timestamp')
                        self.pending_orders[order_id] = {
                            'order': order, 'timestamp': order_timestamp / 1000 if order_timestamp else time.time(),
                            'symbol': symbol, 'side': order['side']
                        }
            
            # Supprimer les ordres qui n'existent plus sur l'exchange
            local_order_ids = list(self.pending_orders.keys())
            for order_id in local_order_ids:
                if order_id not in all_open_order_ids:
                    order_data = self.pending_orders.get(order_id)
                    if order_data and hasattr(self, '_handle_disappeared_order'):
                        self._handle_disappeared_order(order_id, order_data)
                    del self.pending_orders[order_id]
                    
        except Exception as e:
            print(f"⚠️ Erreur sync ordres: {e}")
    
    def sync_trade_history(self):
        try:
            trading_pairs = os.getenv('TRADING_PAIRS', 'BTCUSD,ETHUSD').split(',')
            new_trades = []
            existing_order_ids = set()
            for position in self.state.get('positions', []):
                if position.get('order_id'):
                    existing_order_ids.add(str(position.get('order_id')))
                existing_order_ids.update(str(trade_id) for trade_id in position.get('trade_ids', []))
            
            for pair in trading_pairs:
                symbol = pair if '/' in pair else (f"{pair.strip()[:-3]}/{pair.strip()[-3:]}" if pair.strip().endswith('USD') else f"{pair.strip()[:3]}/{pair.strip()[3:]}")
                trades = self.safe_request(self.exchange.fetch_my_trades, symbol, limit=50)
                
                for trade in trades:
                    trade_id = str(trade['id'])
                    if trade_id in existing_order_ids:
                        continue
                    
                    position = {
                        'symbol': symbol, 'side': trade['side'], 'amount': trade['amount'],
                        'price': trade['price'], 
                        'timestamp': datetime.fromtimestamp(trade['timestamp']/1000).isoformat(),
                        'order_id': trade_id, 'source': 'exchange_history',
                        'fee': trade.get('fee', {}).get('cost', 0), 'paper': False
                    }
                    new_trades.append(position)
                    existing_order_ids.add(trade_id)
            
            if new_trades:
                self.state['positions'].extend(new_trades)
                self.state['positions'].sort(key=lambda x: x['timestamp'])
                self.save_state()
        except Exception as e:
            print(f"⚠️ Erreur sync historique: {e}")
    
    def get_last_buy_from_history(self, symbol):
        buys = [p for p in self.state.get('positions', []) 
               if p['symbol'] == symbol and p['side'] == 'buy' and p.get('source') in ['binance_history', 'exchange_history']]
        return buys[-1] if buys else None
    
    def manage_pending_orders(self):
        now_timestamp = time.time()
        orders_to_cancel = []
        
        for order_id, order_data in self.pending_orders.items():
            if 'symbol' not in order_data:
                continue
            
            # Annuler uniquement si timeout (24h par défaut)
            if now_timestamp - order_data['timestamp'] > self.order_timeout:
                orders_to_cancel.append(order_id)
        
        for order_id in orders_to_cancel:
            print(f"⏰ Annulation ordre timeout: {order_id}")
            self.cancel_order(order_id)
    
    def cancel_order(self, order_id):
        try:
            if order_id in self.pending_orders:
                if self.paper_trading:
                    del self.pending_orders[order_id]
                else:
                    order_data = self.pending_orders[order_id]
                    self.safe_request(self.exchange.cancel_order, int(order_id), order_data['symbol'])
                    del self.pending_orders[order_id]
        except Exception as e:
            if 'Unknown order' in str(e) or 'does not exist' in str(e):
                if order_id in self.pending_orders:
                    del self.pending_orders[order_id]
