"""Module synchronisation - Sync positions, ordres, historique"""
from datetime import datetime
import os
import time

class SyncMixin:
    """Mixin pour la synchronisation avec l'exchange spot."""

    def load_state(self):
        """Charge l'état runtime depuis SQLite."""
        if not hasattr(self, 'state') or self.state is None:
            self.state = {'positions': [], 'paper_balance': getattr(self, 'paper_balance', 1000.0)}
        try:
            logger = getattr(self, 'ml_live_logger', None)
            if logger:
                mode = 'paper' if getattr(self, 'paper_trading', True) else 'live'
                data = logger.load_bot_state(mode)
                if isinstance(data, dict):
                    self.state.update(data)
                    if getattr(self, 'paper_trading', True) and data.get('paper_balance') is not None:
                        self.paper_balance = float(data.get('paper_balance') or self.paper_balance)
        except Exception as e:
            print(f"⚠️ Erreur chargement état SQLite: {e}")

    def save_state(self):
        """Sauvegarde l'état runtime dans SQLite."""
        if not hasattr(self, 'state') or self.state is None:
            self.state = {'positions': [], 'paper_balance': getattr(self, 'paper_balance', 1000.0)}
        try:
            logger = getattr(self, 'ml_live_logger', None)
            if logger:
                mode = 'paper' if getattr(self, 'paper_trading', True) else 'live'
                self.state['paper_balance'] = getattr(self, 'paper_balance', self.state.get('paper_balance'))
                logger.save_bot_state(self.state, mode)
        except Exception as e:
            print(f"⚠️ Erreur sauvegarde état SQLite: {e}")

    def sync_positions_from_exchange(self):
        """Réconcilie les positions LIVE avec les avoirs réellement présents sur Kraken.

        En live, le solde Kraken (free + used) est la quantité de référence. Une vente
        manuelle, un retrait ou un reliquat dust ne doit jamais laisser Aegis croire
        qu'il détient encore l'ancienne quantité complète.
        """
        if self.paper_trading:
            return

        try:
            self.sync_open_orders()
            self.sync_trade_history()

            balance = self.balance_manager.get_balance(force_refresh=True)
            trading_pairs = os.getenv('TRADING_PAIRS', 'BTCUSD,ETHUSD').split(',')

            all_positions = list(self.state.get('positions', []))
            changed = False
            now_iso = datetime.now().isoformat()

            for pair in trading_pairs:
                raw = pair.strip()
                symbol = raw if '/' in raw else (
                    f"{raw[:-3]}/{raw[-3:]}" if raw.endswith('USD')
                    else f"{raw[:3]}/{raw[3:]}"
                )
                base_currency = symbol.split('/')[0]

                asset_balance = balance.get(base_currency, {}) or {}
                free_amount = float(asset_balance.get('free') or 0.0)
                used_amount = float(asset_balance.get('used') or asset_balance.get('locked') or 0.0)
                exchange_total = max(0.0, free_amount + used_amount)

                active_buys = [
                    p for p in all_positions
                    if isinstance(p, dict)
                    and p.get('symbol') == symbol
                    and p.get('side') == 'buy'
                    and not p.get('closed_at')
                    and not p.get('exit_price')
                    and str(p.get('status') or '').lower() != 'closed'
                ]

                local_total = sum(
                    float(p.get('amount') or p.get('position_size_crypto') or 0.0)
                    for p in active_buys
                )

                try:
                    current_price = float(self.get_price(symbol) or 0.0)
                    min_cost = float(self.get_min_amount(symbol)['min_cost'] or 0.0)
                except Exception:
                    current_price = 0.0
                    min_cost = 0.0

                exchange_value = exchange_total * current_price if current_price > 0 else 0.0
                is_dust = exchange_total <= 1e-12 or (
                    min_cost > 0 and current_price > 0 and exchange_value < min_cost
                )

                # Rien à rapprocher si Aegis ne connaît aucune position active.
                if not active_buys:
                    if not is_dust and exchange_total > 0:
                        last_trade = self.get_last_buy_from_history(symbol)
                        if last_trade:
                            restored = dict(last_trade)
                            restored['amount'] = exchange_total
                            restored['position_size_crypto'] = exchange_total
                            if float(restored.get('price') or 0.0) > 0:
                                restored['position_size_usd'] = exchange_total * float(restored['price'])
                            restored['status'] = 'executed'
                            restored['closed_at'] = None
                            restored['exchange_reconciled_at'] = now_iso
                            all_positions.append(restored)
                            changed = True
                    continue

                # Si Kraken ne détient plus qu'une poussière, fermer la position
                # tradable locale. La poussière reste visible via les balances Kraken,
                # mais ne doit plus être gérée comme une position vendable complète.
                if is_dust:
                    for p in active_buys:
                        previous_amount = float(p.get('amount') or p.get('position_size_crypto') or 0.0)
                        p['exchange_previous_amount'] = previous_amount
                        p['exchange_remaining_amount'] = exchange_total
                        p['external_reduction_amount'] = max(0.0, previous_amount - exchange_total)
                        p['closed_at'] = now_iso
                        p['status'] = 'external_reconciled_dust'
                        p['close_reason'] = 'kraken_balance_below_min_trade'
                    if local_total > exchange_total + 1e-12:
                        changed = True
                        if hasattr(self, 'record_decision'):
                            self.record_decision(
                                symbol,
                                action_type='sync',
                                allowed=True,
                                reason='exchange_position_reconciled_to_dust',
                                metrics={
                                    'local_amount': local_total,
                                    'exchange_amount': exchange_total,
                                    'exchange_value': exchange_value,
                                    'min_cost': min_cost,
                                },
                                throttle_seconds=0,
                            )
                    continue

                tolerance = max(1e-12, exchange_total * 1e-8)
                if abs(local_total - exchange_total) <= tolerance:
                    continue

                # Répartir la quantité réelle Kraken sur les positions locales, de la
                # plus récente à la plus ancienne. La somme locale devient exactement
                # égale au solde exchange.
                remaining = exchange_total
                for p in reversed(active_buys):
                    old_amount = float(p.get('amount') or p.get('position_size_crypto') or 0.0)
                    new_amount = min(old_amount, remaining)
                    reduction = max(0.0, old_amount - new_amount)

                    if new_amount > 1e-12:
                        p['amount'] = new_amount
                        p['position_size_crypto'] = new_amount
                        entry_price = float(p.get('avg_entry_price') or p.get('price') or 0.0)
                        if entry_price > 0:
                            p['position_size_usd'] = new_amount * entry_price
                        p['exchange_reconciled_at'] = now_iso
                        p['external_reduction_amount'] = float(p.get('external_reduction_amount') or 0.0) + reduction
                        remaining -= new_amount
                    else:
                        p['exchange_previous_amount'] = old_amount
                        p['exchange_remaining_amount'] = 0.0
                        p['external_reduction_amount'] = float(p.get('external_reduction_amount') or 0.0) + old_amount
                        p['closed_at'] = now_iso
                        p['status'] = 'external_reconciled'
                        p['close_reason'] = 'kraken_balance_reconciled'

                changed = True
                if hasattr(self, 'record_decision'):
                    self.record_decision(
                        symbol,
                        action_type='sync',
                        allowed=True,
                        reason='exchange_position_quantity_reconciled',
                        metrics={
                            'local_amount': local_total,
                            'exchange_amount': exchange_total,
                            'difference': exchange_total - local_total,
                        },
                        throttle_seconds=0,
                    )

            if changed:
                self.state['positions'] = all_positions
                self.save_state()

                # Nettoyer aussi les protections runtime des positions devenues dust.
                trailing_manager = getattr(self, 'trailing_stop_manager', None)
                if trailing_manager:
                    for pair in trading_pairs:
                        raw = pair.strip()
                        symbol = raw if '/' in raw else (
                            f"{raw[:-3]}/{raw[-3:]}" if raw.endswith('USD')
                            else f"{raw[:3]}/{raw[3:]}"
                        )
                        base_currency = symbol.split('/')[0]
                        asset_balance = balance.get(base_currency, {}) or {}
                        total = float(asset_balance.get('free') or 0.0) + float(
                            asset_balance.get('used') or asset_balance.get('locked') or 0.0
                        )
                        try:
                            price = float(self.get_price(symbol) or 0.0)
                            min_cost = float(self.get_min_amount(symbol)['min_cost'] or 0.0)
                            if total <= 1e-12 or (price > 0 and min_cost > 0 and total * price < min_cost):
                                trailing_manager.remove_position(symbol)
                        except Exception:
                            pass
        except Exception as e:
            print(f"⚠️ Erreur sync positions Kraken: {e}")

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
               if p['symbol'] == symbol and p['side'] == 'buy' and p.get('source') == 'exchange_history']
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
