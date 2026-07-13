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

        # Kraken n'a pas de funding wallet séparé
        if hasattr(self, 'exchange') and self.exchange.name == 'kraken':
            return

        try:
            funding_balance = self.safe_request(self.exchange.fetch_balance, {'type': 'funding'})
            if not funding_balance:
                return

            usdt_funding = funding_balance.get('USDT', {}).get('free', 0)
            if usdt_funding > 1:
                print(f"💸 Transfert {usdt_funding:.2f} USDT: Funding → Spot...")
                self.exchange.transfer('USDT', usdt_funding, 'funding', 'spot')
                print(f"✅ Transfert réussi: {usdt_funding:.2f} USDT disponible en SPOT")
                time.sleep(1)
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
            
            # Nettoyer d'abord les ordres locaux obsolètes
            all_open_order_ids = set()
            
            for pair in trading_pairs:
                symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
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
            
            # Supprimer les ordres qui n'existent plus sur Binance
            local_order_ids = list(self.pending_orders.keys())
            for order_id in local_order_ids:
                if order_id not in all_open_order_ids:
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
