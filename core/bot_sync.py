"""Module synchronisation - Sync positions, ordres, historique"""
from datetime import datetime
import os
import time

class SyncMixin:
    """Mixin pour la synchronisation avec Binance"""
    
    def transfer_funding_to_spot(self):
        """Transfère automatiquement les fonds du Funding vers Spot"""
        if self.paper_trading:
            return
        
        try:
            funding_balance = self.safe_request(self.exchange.fetch_balance, {'type': 'funding'})
            if not funding_balance:
                return
            
            usdt_funding = funding_balance.get('USDT', {}).get('free', 0)
            if usdt_funding > 1:  # Minimum 1 USDT pour transférer
                print(f"💸 Transfert {usdt_funding:.2f} USDT: Funding → Spot...")
                self.exchange.transfer('USDT', usdt_funding, 'funding', 'spot')
                print(f"✅ Transfert réussi: {usdt_funding:.2f} USDT disponible en SPOT")
                time.sleep(1)  # Attendre confirmation
        except Exception as e:
            print(f"⚠️ Erreur transfert Funding→Spot: {e}")
    
    def sync_positions_from_exchange(self):
        if self.paper_trading:
            return
        
        try:
            self.transfer_funding_to_spot()  # Transfert auto avant sync
            self.sync_open_orders()
            self.sync_trade_history()
            
            balance = self.balance_manager.get_balance()
            trading_pairs = os.getenv('TRADING_PAIRS', 'BTCUSDT,ETHUSDT').split(',')
            
            all_positions = [p for p in self.state.get('positions', [])]
            active_buy_positions = []
            changed = False
            
            for pair in trading_pairs:
                symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
                base_currency = symbol.split('/')[0]
                available = balance.get(base_currency, {}).get('free', 0)
                
                if available > 0.00001:
                    existing_buys = [p for p in all_positions if p['symbol'] == symbol and p['side'] == 'buy']
                    
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
                        else:
                            current_price = self.get_price(symbol)
                            active_buy_positions.append({
                                'symbol': symbol, 'side': 'buy', 'amount': available,
                                'price': current_price, 'timestamp': datetime.now().isoformat(),
                                'order_id': 'synced', 'source': 'binance_manual', 'paper': False
                            })
                        changed = True
            
            if changed:
                history = [p for p in all_positions if p['side'] == 'sell' or p.get('source') == 'binance_history']
                self.state['positions'] = history + active_buy_positions
                self.save_state()
        except Exception as e:
            print(f"⚠️ Erreur sync: {e}")
    
    def sync_open_orders(self):
        try:
            trading_pairs = os.getenv('TRADING_PAIRS', 'BTCUSDT,ETHUSDT').split(',')
            
            for pair in trading_pairs:
                symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
                open_orders = self.safe_request(self.exchange.fetch_open_orders, symbol)
                
                for order in open_orders:
                    order_id = str(order['id'])
                    if order_id not in self.pending_orders:
                        self.pending_orders[order_id] = {
                            'order': order, 'timestamp': order['timestamp'] / 1000,
                            'symbol': symbol, 'side': order['side']
                        }
                
                open_order_ids = {str(o['id']) for o in open_orders}
                executed_orders = [oid for oid in self.pending_orders.keys() 
                                 if self.pending_orders[oid]['symbol'] == symbol 
                                 and oid not in open_order_ids]
                
                for order_id in executed_orders:
                    del self.pending_orders[order_id]
        except Exception as e:
            print(f"⚠️ Erreur sync ordres: {e}")
    
    def sync_trade_history(self):
        try:
            trading_pairs = os.getenv('TRADING_PAIRS', 'BTCUSDT,ETHUSDT').split(',')
            new_trades = []
            existing_order_ids = {p.get('order_id') for p in self.state.get('positions', []) if p.get('order_id')}
            
            for pair in trading_pairs:
                symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
                trades = self.safe_request(self.exchange.fetch_my_trades, symbol, limit=50)
                
                for trade in trades:
                    trade_id = str(trade['id'])
                    if trade_id in existing_order_ids:
                        continue
                    
                    position = {
                        'symbol': symbol, 'side': trade['side'], 'amount': trade['amount'],
                        'price': trade['price'], 
                        'timestamp': datetime.fromtimestamp(trade['timestamp']/1000).isoformat(),
                        'order_id': trade_id, 'source': 'binance_history',
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
               if p['symbol'] == symbol and p['side'] == 'buy' and p.get('source') == 'binance_history']
        return buys[-1] if buys else None
    
    def manage_pending_orders(self):
        now_timestamp = time.time()
        orders_to_cancel = []
        
        for order_id, order_data in self.pending_orders.items():
            if 'symbol' not in order_data:
                continue
            
            symbol = order_data['symbol']
            current_price = self.get_price(symbol)
            order_price = order_data['order']['price']
            price_diff_pct = ((current_price - order_price) / order_price) * 100
            
            if order_data['side'] == 'sell' and price_diff_pct < -3:
                orders_to_cancel.append(order_id)
            elif order_data['side'] == 'buy' and price_diff_pct > 3:
                orders_to_cancel.append(order_id)
            elif now_timestamp - order_data['timestamp'] > self.order_timeout:
                orders_to_cancel.append(order_id)
        
        for order_id in orders_to_cancel:
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
