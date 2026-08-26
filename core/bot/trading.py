"""Module de trading - Gestion des ordres d'achat/vente"""
from datetime import datetime, timedelta
import time
import os

class TradingMixin:
    """Mixin pour les opérations de trading"""

    def _refresh_paper_balance_from_accounting(self):
        try:
            if not getattr(self, 'ml_live_logger', None):
                return
            conn = self.ml_live_logger._get_conn()
            account_id = self.ml_live_logger._account_id('paper')
            row = conn.execute(
                "SELECT free FROM balances WHERE account_id=? AND asset='USD'",
                (account_id,),
            ).fetchone()
            if row and row[0] is not None:
                self.paper_balance = round(float(row[0]), 2)
                if hasattr(self, 'state'):
                    self.state['paper_balance'] = self.paper_balance
        except Exception:
            pass

    def _elapsed_since_iso(self, timestamp):
        created_at = datetime.fromisoformat(str(timestamp or '').replace('Z', '+00:00'))
        now_for_delta = datetime.now(created_at.tzinfo) if created_at.tzinfo else datetime.now()
        return now_for_delta - created_at

    def _record_live_order_accounting(self, symbol, side, amount, price, order, order_type='market', filled=True):
        """Trace les ordres live dans orders/fills sans dupliquer le ledger Kraken."""
        if self.paper_trading or not getattr(self, 'ml_live_logger', None) or not order:
            return
        try:
            order_id = str(order.get('id') or f'live_{side}_{symbol.replace("/", "")}_{time.time_ns()}')
            self.ml_live_logger.record_order_transaction(
                symbol,
                side,
                amount,
                price,
                order_type=order_type,
                status='open',
                order_id=order_id,
                mode='live',
                source='live_trade',
                recalculate_balances=False,
            )
            if filled:
                execution = self._extract_execution_details(order, amount, price)
                fee_rate = float(getattr(self, 'trading_fee', 0) or 0)
                if fee_rate <= 0:
                    fee_rate = float(os.getenv('TRADING_FEE_PERCENT', '0.1')) / 100.0
                fee_amount = execution.get('fee_amount')
                if fee_amount is None:
                    fee_amount = float(amount or 0.0) * float(price or 0.0) * fee_rate
                self.ml_live_logger.record_fill_transaction(
                    order_id,
                    symbol,
                    side,
                    amount,
                    price,
                    fee_amount=fee_amount,
                    fee_asset=execution.get('fee_asset') or 'USD',
                    mode='live',
                    source='live_trade',
                    write_ledger=False,
                    recalculate_balances=False,
                )
        except Exception as e:
            print(f"⚠️ Comptabilité live non enregistrée pour {symbol}: {e}")

    def _extract_execution_details(self, order, fallback_amount, fallback_price):
        """Retourne le prix moyen réel, la quantité remplie et les frais depuis CCXT/Kraken."""
        try:
            order = order or {}
            trades = order.get('trades') if isinstance(order.get('trades'), list) else []
            filled = float(order.get('filled') or order.get('amount') or fallback_amount or 0.0)
            cost = float(order.get('cost') or 0.0)
            fee_amount = 0.0
            fee_asset = 'USD'

            if trades:
                trade_amount = 0.0
                trade_cost = 0.0
                for trade in trades:
                    amount = float(trade.get('amount') or 0.0)
                    price = float(trade.get('price') or 0.0)
                    trade_amount += amount
                    trade_cost += float(trade.get('cost') or (amount * price))
                    fee = trade.get('fee') or {}
                    fee_amount += float(fee.get('cost') or 0.0)
                    if fee.get('currency'):
                        fee_asset = str(fee.get('currency')).upper()
                if trade_amount > 0:
                    filled = trade_amount
                    cost = trade_cost

            average = (
                order.get('average')
                or order.get('price')
                or ((cost / filled) if cost > 0 and filled > 0 else None)
                or fallback_price
            )

            fee = order.get('fee') or {}
            if fee and not fee_amount:
                fee_amount = float(fee.get('cost') or 0.0)
                if fee.get('currency'):
                    fee_asset = str(fee.get('currency')).upper()

            return {
                'price': float(average),
                'amount': float(filled or fallback_amount or 0.0),
                'cost': float(cost or (float(filled or fallback_amount or 0.0) * float(average or fallback_price or 0.0))),
                'fee_amount': fee_amount if fee_amount > 0 else None,
                'fee_asset': fee_asset,
            }
        except Exception:
            return {
                'price': float(fallback_price or 0.0),
                'amount': float(fallback_amount or 0.0),
                'cost': float(fallback_amount or 0.0) * float(fallback_price or 0.0),
                'fee_amount': None,
                'fee_asset': 'USD',
            }

    def _resolve_exchange_execution(self, symbol, order, fallback_amount, fallback_price, side=None):
        """Relit Kraken juste apres l'ordre pour eviter de comptabiliser le prix demande."""
        execution = self._extract_execution_details(order, fallback_amount, fallback_price)
        if self.paper_trading or not order or not getattr(self, 'exchange', None):
            return execution

        # Fast path: si l'ordre retourne déjà un prix et montant rempli, pas besoin de re-fetch
        if execution.get('amount') and execution.get('price'):
            status = str(order.get('status') or '').lower()
            filled = float(order.get('filled') or 0.0)
            if status in {'closed', 'filled'} or filled > 0:
                return execution

        order_id = str(order.get('id') or '')
        candidates = []
        if order_id and hasattr(self.exchange, 'fetch_order'):
            # Délais réduits pour market orders (remplis instantanément)
            for delay in (0.15, 0.5, 1.5):
                try:
                    time.sleep(delay)
                    fetched = self.safe_request(self.exchange.fetch_order, order_id, symbol)
                    if fetched:
                        candidates.append(fetched)
                        fetched_exec = self._extract_execution_details(fetched, fallback_amount, fallback_price)
                        if fetched_exec.get('amount') and fetched_exec.get('price'):
                            status = str(fetched.get('status') or '').lower()
                            filled = float(fetched.get('filled') or fetched_exec.get('amount') or 0.0)
                            if status in {'closed', 'filled'} or filled > 0:
                                execution = fetched_exec
                                break
                except Exception:
                    continue

        if (not execution.get('amount') or not execution.get('price') or order_id) and hasattr(self.exchange, 'fetch_my_trades'):
            try:
                since = None
                timestamp = order.get('timestamp') or order.get('lastTradeTimestamp')
                if timestamp:
                    since = int(max(0, float(timestamp) - 120000))
                trades = self.safe_request(self.exchange.fetch_my_trades, symbol, since, 20) or []
                matches = []
                for trade in trades:
                    if order_id and str(trade.get('order') or trade.get('orderId') or '') != order_id:
                        continue
                    if side and str(trade.get('side') or '').lower() != str(side).lower():
                        continue
                    matches.append(trade)
                if matches:
                    execution = self._extract_execution_details({'trades': matches}, fallback_amount, fallback_price)
            except Exception:
                pass

        return execution

    def _sell_limit_arm_distance_pct(self):
        try:
            return max(0.0, float(os.getenv('SELL_LIMIT_ARM_DISTANCE_PCT', '0.30')))
        except Exception:
            return 0.30

    def _is_sell_limit_close_enough(self, current_price, target_price):
        """Autorise un sell limit seulement quand le prix est proche du target."""
        try:
            current = float(current_price or 0.0)
            target = float(target_price or 0.0)
            if current <= 0 or target <= 0:
                return False
            if current >= target:
                return True
            distance_pct = ((target - current) / target) * 100.0
            return distance_pct <= self._sell_limit_arm_distance_pct()
        except Exception:
            return False

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

    def get_open_positions(self):
        """Retourne un dictionnaire {symbol: {'amount': qty, 'cost': entry_cost, 'entry_price': price}} des positions ouvertes."""
        open_pos = {}
        # 1. Source unifiée de vérité : Table SQLite ml_open_entries
        try:
            if hasattr(self, 'ml_live_logger') and self.ml_live_logger:
                conn = self.ml_live_logger._get_conn()
                rows = conn.execute("SELECT symbol, price, amount FROM ml_open_entries").fetchall()
                for r in rows:
                    sym = str(r[0])
                    qty = float(r[2] or 0.0)
                    price = float(r[1] or 0.0)
                    if qty > 0:
                        open_pos[sym] = {
                            'amount': qty,
                            'cost': qty * price,
                            'entry_price': price
                        }
        except Exception:
            pass

        # 2. Source complémentaire : state['positions']
        try:
            positions = getattr(self, 'state', {}).get('positions', []) if hasattr(self, 'state') and self.state else []
            for p in positions:
                if not isinstance(p, dict):
                    continue
                symbol = p.get('symbol')
                if not symbol:
                    continue
                
                side = str(p.get('side', '')).lower()
                status = str(p.get('status', '')).lower()
                closed_at = p.get('closed_at')
                exit_price = p.get('exit_price')
                
                is_open = (side == 'buy' and not exit_price and not closed_at and status != 'closed') or (status == 'opened' and not closed_at)
                
                if is_open:
                    qty = float(p.get('amount', 0.0) or p.get('position_size_crypto', 0.0) or 0.0)
                    price = float(p.get('price', 0.0) or p.get('avg_entry_price', 0.0) or 0.0)
                    cost = float(p.get('cost', qty * price) or (qty * price))
                    if qty > 0 and symbol not in open_pos:
                        open_pos[symbol] = {'amount': qty, 'cost': cost, 'entry_price': price}

            # 3. Source complémentaire : trailing_stop_manager
            if hasattr(self, 'trailing_stop_manager') and hasattr(self.trailing_stop_manager, 'positions'):
                for sym, pdata in self.trailing_stop_manager.positions.items():
                    if sym not in open_pos:
                        qty = float(pdata.get('amount', 0.0) or pdata.get('position_size_crypto', 0.0) or 0.0)
                        price = float(pdata.get('entry_price', 0.0) or pdata.get('buy_price', 0.0) or pdata.get('price', 0.0) or 0.0)
                        if qty > 0:
                            open_pos[sym] = {'amount': qty, 'cost': qty * price, 'entry_price': price}

        except Exception as e:
            print(f"⚠️ Erreur get_open_positions: {e}")
        return open_pos

    def _close_buy_positions(self, symbol, amount, exit_price):
        """Marque les positions d'achat ouvertes correspondantes comme fermées."""
        try:
            target_sym = str(symbol).replace('/', '').upper()
            now_iso = datetime.now().isoformat()
            remaining = float(amount or 0.0)
            for p in reversed(self.state.get('positions', [])):
                if not isinstance(p, dict):
                    continue
                p_sym = str(p.get('symbol', '')).replace('/', '').upper()
                if p_sym == target_sym and p.get('side') == 'buy' and not p.get('closed_at') and not p.get('exit_price'):
                    pos_amount = float(p.get('amount', 0.0) or p.get('position_size_crypto', 0.0) or 0.0)
                    p['exit_price'] = float(exit_price)
                    p['closed_at'] = now_iso
                    p['status'] = 'closed'
                    remaining -= pos_amount
                    if remaining <= 0:
                        break
            self.save_state()
        except Exception as e:
            print(f"⚠️ Erreur _close_buy_positions: {e}")


    def buy_market(self, symbol, amount, allow_averaging=False, sizing_reason=None, ml_buy_prob=None):
        # VÉRIFICATION 1: Limite quotidienne de trades gérée par risk_manager.can_trade()
        if hasattr(self, 'risk_manager') and not self.risk_manager.can_trade():
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
            available = (balance.get('USD') or balance.get('USDT') or balance.get('USDC') or {}).get('free', 0)
            if cost > available:
                return None
        
        try:
            if self.paper_trading:
                if cost > self.paper_balance:
                    print(f"❌ Paper trading: Fonds insuffisants {cost:.2f} > {self.paper_balance:.2f}")
                    return None
                    
                fee_rate = float(getattr(self, 'trading_fee', 0) or 0)
                if fee_rate <= 0:
                    fee_rate = float(os.getenv('TRADING_FEE_PERCENT', '0.1')) / 100.0
                buy_fee = cost * fee_rate
                order_id = f'paper_{time.time_ns()}'
                if getattr(self, 'ml_live_logger', None):
                    self.ml_live_logger.record_order_transaction(
                        symbol, 'buy', amount, price, order_type='market',
                        status='open', order_id=order_id, mode='paper',
                        source='paper_trade'
                    )
                    self.ml_live_logger.record_fill_transaction(
                        order_id, symbol, 'buy', amount, price,
                        fee_amount=buy_fee, fee_asset='USD',
                        mode='paper', source='paper_trade'
                    )
                    self._refresh_paper_balance_from_accounting()
                else:
                    self.paper_balance -= (cost * (1 + fee_rate))
                order = {'id': order_id, 'price': price, 'amount': amount, 'cost': cost}
                action_text = "moyennage" if allow_averaging else "achat"
                print(f"🧪 PAPER - {action_text.title()} simulé: {amount:.6f} {symbol} à {price:.6f} (Balance: {self.paper_balance:.2f} USD)")
            else:
                order = self.safe_request(self.exchange.create_market_buy_order, symbol, amount)
                action_text = "Moyennage" if allow_averaging else "Achat"
                print(f"✅ {action_text} exécuté: {amount:.6f} {symbol}")
            
            if order:
                execution = self._resolve_exchange_execution(symbol, order, amount, price, side='buy')
                exec_price = float(execution['price'])
                exec_amount = float(execution['amount'] or amount)
                fee_rate = float(getattr(self, 'trading_fee', 0) or 0)
                if fee_rate <= 0:
                    fee_rate = float(os.getenv('TRADING_FEE_PERCENT', '0.1')) / 100.0
                buy_fee = float(execution.get('fee_amount') or (exec_amount * exec_price * fee_rate))
                self._record_live_order_accounting(symbol, 'buy', exec_amount, exec_price, order, order_type='market', filled=True)

                position = {
                    'symbol': symbol, 'side': 'buy', 'amount': exec_amount,
                    'price': exec_price, 'timestamp': datetime.now().isoformat(),
                    'order_id': order.get('id'), 'source': 'bot', 'paper': self.paper_trading,
                    'averaging': allow_averaging, 'status': 'executed',
                    'fee_rate': fee_rate, 'fee': buy_fee, 'position_size_crypto': exec_amount, 'position_size_usd': exec_price * exec_amount,
                    'sizing_reason': sizing_reason, 'ml_buy_prob': ml_buy_prob
                }
                if 'positions' not in self.state:
                    self.state['positions'] = []
                self.state['positions'].append(position)
                position['avg_entry_price'] = self.get_real_buy_price(symbol)
                self.save_state()
                
                # Incrémenter le compteur runtime local. Le résultat risque/PnL est
                # enregistré à la vente, quand le trade est réellement clôturé.
                if hasattr(self, 'total_trades'):
                    self.total_trades += 1
                else:
                    self.total_trades = 1
                
                if hasattr(self, 'notifier'):
                    analysis = self.get_cached_analysis(symbol, exec_price)
                    signal_data = {
                        'trend': analysis['global_signal'].get('dominant_trend', 'N/A'),
                        'confidence': analysis['global_signal'].get('confidence', 0),
                        'volatility': analysis.get('volatility', 0)
                    }
                    self.notifier.notify_trade_buy(symbol, exec_amount, exec_price, exec_amount * exec_price, signal_data)
            
            return order
        except Exception as e:
            print(f"❌ Erreur achat: {e}")
            if hasattr(self, 'notifier') and 'insufficient balance' in str(e).lower():
                self.notifier.notify_error("Fonds insuffisants", str(e))
            return None
    
    def sell_market(self, symbol, amount, reason=""):
        price = self.get_price(symbol)
        buy_price = self.get_real_buy_price(symbol)
        
        try:
            if self.paper_trading:
                fee_rate = float(getattr(self, 'trading_fee', 0) or 0)
                if fee_rate <= 0:
                    fee_rate = float(os.getenv('TRADING_FEE_PERCENT', '0.1')) / 100.0
                revenue = amount * price
                sell_fee = revenue * fee_rate
                order_id = f'paper_{time.time_ns()}'
                if getattr(self, 'ml_live_logger', None):
                    self.ml_live_logger.record_order_transaction(
                        symbol, 'sell', amount, price, order_type='market',
                        status='open', order_id=order_id, mode='paper',
                        source='paper_trade'
                    )
                    self.ml_live_logger.record_fill_transaction(
                        order_id, symbol, 'sell', amount, price,
                        fee_amount=sell_fee, fee_asset='USD',
                        mode='paper', source='paper_trade'
                    )
                    self._refresh_paper_balance_from_accounting()
                else:
                    self.paper_balance += (revenue * (1 - fee_rate))
                order = {'id': order_id, 'price': price, 'amount': amount, 'cost': revenue}
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
                execution = self._resolve_exchange_execution(symbol, order, amount, price, side='sell')
                exec_price = float(execution['price'])
                exec_amount = float(execution['amount'] or amount)
                self._record_live_order_accounting(symbol, 'sell', exec_amount, exec_price, order, order_type='market', filled=True)
                # Mettre à jour la position sell existante → 'executed' au lieu d'insérer un doublon
                updated = False
                target_sym = str(symbol).replace('/', '').upper()
                for p in reversed(self.state.get('positions', [])):
                    p_sym = str(p.get('symbol', '')).replace('/', '').upper()
                    if p_sym == target_sym and p.get('side') == 'sell':
                        p['status'] = 'executed'
                        p['price'] = exec_price
                        p['amount'] = exec_amount
                        p['order_id'] = order.get('id', p.get('order_id'))
                        p['avg_entry_price'] = buy_price
                        p['closed_at'] = datetime.now().isoformat()
                        if self.paper_trading:
                            p.update(self._calculate_fee_details(
                                exec_amount, exec_price, buy_price
                            ))
                        updated = True
                        break
                if not updated:
                    position = {
                        'symbol': symbol, 'side': 'sell', 'amount': exec_amount,
                        'price': exec_price, 'timestamp': datetime.now().isoformat(),
                        'order_id': order.get('id'), 'source': 'bot', 'paper': self.paper_trading,
                        'avg_entry_price': buy_price, 'status': 'executed',
                        'closed_at': datetime.now().isoformat()
                    }
                    if self.paper_trading:
                        position.update(self._calculate_fee_details(
                            exec_amount, exec_price, buy_price
                        ))
                    self.state['positions'].append(position)
                self.save_state()
                self.total_trades += 1
                
                pnl = self.calculate_pnl(symbol, 'sell', exec_amount, exec_price, buy_price=buy_price)
                if hasattr(self, 'risk_manager') and pnl is not None:
                    self.risk_manager.record_trade(pnl)
                
                buy_price = self.get_real_buy_price(symbol)
                buy_positions = [p for p in self.state['positions'] if p['symbol'] == symbol and p['side'] == 'buy']
                hold_time = "N/A"
                if buy_positions:
                    buy_time = datetime.fromisoformat(buy_positions[-1]['timestamp'])
                    now_for_delta = datetime.now(buy_time.tzinfo) if buy_time.tzinfo else datetime.now()
                    delta = now_for_delta - buy_time
                    hours = delta.total_seconds() / 3600
                    hold_time = f"{int(hours)}h {int((hours % 1) * 60)}min" if hours >= 1 else f"{int(hours * 60)}min"
                
                if hasattr(self, 'notifier'):
                    self.notifier.notify_trade_sell(symbol, exec_amount, exec_price, exec_amount * exec_price, buy_price or exec_price, pnl or 0, hold_time)

                if hasattr(self, 'record_decision'):
                    self.record_decision(
                        symbol=symbol,
                        action="sell",
                        allowed=True,
                        reason=reason or "market_sell",
                        metrics={
                            'price': exec_price,
                            'requested_price': price,
                            'amount': exec_amount,
                            'buy_price': buy_price,
                            'pnl': pnl,
                            'decision': 'FORCE_EXIT' if 'exit' in str(reason).lower() else 'SELL'
                        },
                        throttle_seconds=0
                    )

                if hasattr(self, 'record_ml_exit_learning_sample'):
                    self.record_ml_exit_learning_sample(
                        symbol,
                        exec_price,
                        exec_amount,
                        buy_price=buy_price,
                        pnl=pnl,
                        hold_time=hold_time,
                        reason='market_sell',
                        order=order
                    )

                if hasattr(self, 'set_symbol_cooldown'):
                    self.set_symbol_cooldown(symbol, reason='sell_executed')
                    
                self._close_buy_positions(symbol, exec_amount, exec_price)
            
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
                order = {'id': f'limit_sell_{time.time_ns()}', 'price': price, 'amount': amount, 'type': 'limit', 'side': 'sell'}
                self.pending_orders[order['id']] = {
                    'order': order, 'timestamp': time.time(), 'symbol': symbol, 'side': 'sell', 'status': 'opened'
                }
                if getattr(self, 'ml_live_logger', None):
                    self.ml_live_logger.record_order_transaction(
                        symbol,
                        'sell',
                        amount,
                        price,
                        order_type='limit',
                        status='open',
                        order_id=order['id'],
                        mode='paper',
                        source='paper_trade'
                    )
                position = {
                    'symbol': symbol, 'side': 'sell', 'amount': amount,
                    'price': price, 'timestamp': __import__('datetime').datetime.now().isoformat(),
                    'order_id': order['id'], 'source': 'bot', 'paper': True,
                    'status': 'opened',
                    'position_size_crypto': amount, 'position_size_usd': amount * price
                }
                self.state.setdefault('positions', []).append(position)
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
                    'source': 'bot',
                    'status': 'opened'
                }
                position = {
                    'symbol': symbol, 'side': 'sell', 'amount': amount,
                    'price': price, 'timestamp': __import__('datetime').datetime.now().isoformat(),
                    'order_id': str(order['id']), 'source': 'bot', 'paper': False,
                    'status': 'opened',
                    'position_size_crypto': amount, 'position_size_usd': amount * price
                }
                self.state.setdefault('positions', []).append(position)
                self._record_live_order_accounting(symbol, 'sell', amount, price, order, order_type='limit', filled=False)
                
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
            if p.get('symbol') == symbol and (
                p.get('side') == 'buy' or
                (p.get('side') == 'sell' and p.get('status') in ('executed', 'filled'))
            )
        ]
        events.sort(key=lambda p: p.get('timestamp', ''))
        return self._calculate_weighted_average_from_events(events)

    def get_real_buy_price(self, symbol):
        # 1. Vérifier si la position ouverte est dans get_open_positions() (Source SQLite ml_open_entries)
        try:
            open_pos = self.get_open_positions()
            if symbol in open_pos:
                price = float(open_pos[symbol].get('entry_price', 0.0) or 0.0)
                if price > 0:
                    return price
            std_sym = symbol.replace('/USD', '/USDT') if symbol.endswith('/USD') else symbol
            if std_sym in open_pos:
                price = float(open_pos[std_sym].get('entry_price', 0.0) or 0.0)
                if price > 0:
                    return price
        except Exception:
            pass

        # 2. Source SQLite ml_trade_outcomes (position venant d'être fermée)
        try:
            if hasattr(self, 'ml_live_logger') and self.ml_live_logger:
                conn = self.ml_live_logger._get_conn()
                row = conn.execute(
                    "SELECT entry_price FROM ml_trade_outcomes WHERE symbol=? ORDER BY exit_time DESC LIMIT 1",
                    (symbol,)
                ).fetchone()
                if not row and symbol.endswith('/USD'):
                    row = conn.execute(
                        "SELECT entry_price FROM ml_trade_outcomes WHERE symbol=? ORDER BY exit_time DESC LIMIT 1",
                        (symbol.replace('/USD', '/USDT'),)
                    ).fetchone()
                if row and row[0]:
                    return float(row[0])
        except Exception:
            pass

        # En paper trading, utiliser le prix moyen pondéré du state
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
        executed_order_ids = set()
        executed_trade_ids = set()
        for position in self.state.get('positions', []):
            if str(position.get('status') or '').lower() in {'executed', 'filled', 'closed'}:
                if position.get('order_id'):
                    executed_order_ids.add(str(position.get('order_id')))
                executed_trade_ids.update(str(trade_id) for trade_id in position.get('trade_ids', []))

        if str(order_id) in executed_order_ids or (trade_ids and trade_ids.intersection(executed_trade_ids)):
            return True

        symbol = execution['symbol']
        side = execution['side']
        amount = execution['amount']
        price = execution['price']
        timestamp = execution.get('timestamp') or int(time.time() * 1000)

        if side == 'sell':
            buy_price = self.get_real_buy_price(symbol)
            if getattr(self, 'ml_live_logger', None) and not self.paper_trading:
                try:
                    self.ml_live_logger.record_fill_transaction(
                        str(order_id),
                        symbol,
                        'sell',
                        amount,
                        price,
                        fee_amount=execution.get('fee', 0),
                        fee_asset='USD',
                        mode='live',
                        source='live_trade',
                        write_ledger=False,
                        recalculate_balances=False,
                    )
                except Exception:
                    pass
            pnl = self.calculate_pnl(symbol, 'sell', amount, price, buy_price=buy_price)
            if hasattr(self, 'risk_manager') and pnl is not None:
                self.risk_manager.record_trade(pnl)

            if hasattr(self, 'notifier'):
                buy_positions = [p for p in self.state['positions'] if p['symbol'] == symbol and p['side'] == 'buy']
                hold_time = "N/A"
                if buy_positions:
                    delta = self._elapsed_since_iso(buy_positions[-1]['timestamp'])
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

            found = False
            for p in reversed(self.state.get('positions', [])):
                if p.get('order_id') == str(order_id) and p.get('status') == 'opened':
                    p['status'] = 'executed'
                    p['price'] = price
                    p['amount'] = amount
                    p['exchange_order_id'] = str(order_id)
                    p['trade_ids'] = execution.get('trade_ids', [])
                    p['fee'] = execution.get('fee', 0)
                    p['position_size_crypto'] = amount
                    p['position_size_usd'] = amount * price
                    p['avg_entry_price'] = buy_price
                    found = True
                    break
            
            if not found:
                position = {
                    'symbol': symbol, 'side': 'sell', 'amount': amount,
                    'price': price, 'timestamp': datetime.fromtimestamp(timestamp / 1000).isoformat(),
                    'order_id': str(order_id),
                    'exchange_order_id': str(order_id), 'trade_ids': execution.get('trade_ids', []),
                    'source': 'bot_confirmed', 'paper': False,
                    'fee': execution.get('fee', 0),
                    'avg_entry_price': buy_price, 'status': 'executed'
                }
                self.state.setdefault('positions', []).append(position)
                
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
