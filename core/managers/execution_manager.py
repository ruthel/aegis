"""
ExecutionManager - Phase 7 : Exécution Intelligente & Microstructure de Marché
Gère l'exécution optimale des ordres chez Kraken :
1. Spread-aware execution : pause si spread > MAX_EXECUTION_SPREAD_PCT (ex: 0.08%)
2. Dynamic volume / depth check : ajustement selon liquidité live
3. Adaptive orders : market si high confidence (P_win >= 80%), limit Maker si standard (P_win < 80%)
4. Clean retry & anti-duplicate checks
5. Slippage tracking & persistence des métriques d'exécution dans SQLite (execution_logs)
"""
import time
import os
from datetime import datetime

class ExecutionManager:
    def __init__(self, bot):
        self.bot = bot
        self.max_allowed_spread_pct = float(os.getenv('MAX_EXECUTION_SPREAD_PCT', '0.08'))
        self.spread_pause_timeout = float(os.getenv('SPREAD_PAUSE_TIMEOUT_SEC', '1.0'))
        self.limit_fill_timeout = float(os.getenv('LIMIT_FILL_TIMEOUT_SEC', '2.0'))
        self.limit_fill_poll = max(0.05, float(os.getenv('LIMIT_FILL_POLL_SEC', '0.25')))
        self.adaptive_maker_orders = os.getenv('ADAPTIVE_MAKER_ORDERS', 'true').lower() == 'true'

    def get_market_microstructure(self, symbol):
        """Récupère le spread, bid/ask et la profondeur du carnet live."""
        try:
            bid, ask = None, None
            # 1. Tenter via le WebSocket Kraken du bot si disponible
            websocket = getattr(self.bot, 'websocket', None)
            if websocket and websocket.is_connected():
                ticker = websocket.get_ticker(symbol)
                if ticker:
                    bid = ticker.get('bid')
                    ask = ticker.get('ask')

            # 2. Fallback via ticker API s'il manque
            if not bid or not ask:
                ticker = self.bot.get_ticker(symbol) if hasattr(self.bot, 'get_ticker') else None
                if ticker:
                    bid = ticker.get('bid') or ticker.get('last')
                    ask = ticker.get('ask') or ticker.get('last')

            price = self.bot.get_price(symbol)
            bid = float(bid or price)
            ask = float(ask or price)

            spread_pct = ((ask - bid) / bid * 100.0) if bid > 0 else 0.0
            return {
                'bid': bid,
                'ask': ask,
                'price': price,
                'spread_pct': spread_pct,
                'mid_price': (bid + ask) / 2.0
            }
        except Exception:
            price = self.bot.get_price(symbol)
            return {'bid': price, 'ask': price, 'price': price, 'spread_pct': 0.0, 'mid_price': price}

    def wait_for_tight_spread(self, symbol, max_wait=3.0):
        """Attends que le spread se resserre s'il dépasse le seuil toléré (Spread-aware execution)."""
        start_time = time.time()
        micro = self.get_market_microstructure(symbol)
        
        if micro['spread_pct'] > self.max_allowed_spread_pct:
            print(f"⏳ {symbol}: Spread élevé ({micro['spread_pct']:.3f}% > {self.max_allowed_spread_pct}%) - Attente resserrement carnet...")
            while (time.time() - start_time) < max_wait:
                time.sleep(0.5)
                micro = self.get_market_microstructure(symbol)
                if micro['spread_pct'] <= self.max_allowed_spread_pct:
                    print(f"✅ {symbol}: Spread resserré à {micro['spread_pct']:.3f}% après {time.time()-start_time:.1f}s")
                    break
        return micro

    def execute_smart_buy(self, symbol, position_data, current_price, reason, ml_entry_learning_id=None):
        """
        Exécute un achat intelligent selon la Phase 7 :
        - Vérification anti-duplication
        - Attente resserrement du spread
        - Détermination du type d'ordre (Market vs Limit Maker)
        - Suivi du slippage et enregistrement SQLite
        """
        start_time = time.time()
        execution_start_ns = time.perf_counter_ns()
        latency_trace = dict(position_data.get('latency_trace') or {})
        latency_trace['execution_start_ns'] = execution_start_ns
        crypto = symbol.split('/')[0]
        
        # 1. Anti-Duplication & Safe Retry Check
        cooldown_remaining = self.bot.get_symbol_cooldown_remaining(symbol)
        if cooldown_remaining > 0:
            self.bot.record_decision(
                symbol,
                action_type='buy',
                allowed=False,
                reason='execution_cooldown_active',
                metrics={
                    'price': current_price,
                    'cooldown_remaining_seconds': cooldown_remaining,
                },
                throttle_seconds=30,
            )
            return False

        if not self.bot.can_open_position(symbol):
            print(f"❌ Smart Execution: Position déjà ouverte ou verrouillée sur {symbol}")
            self.bot.record_decision(
                symbol,
                action_type='buy',
                allowed=False,
                reason='execution_position_blocked',
                metrics={'price': current_price},
                throttle_seconds=60,
            )
            return False

        # 2. Spread-Aware Execution
        micro = self.wait_for_tight_spread(symbol, max_wait=self.spread_pause_timeout)
        if float(micro.get('spread_pct') or 0.0) > self.max_allowed_spread_pct:
            print(
                f"⛔ {symbol}: spread toujours trop large "
                f"({micro['spread_pct']:.3f}% > {self.max_allowed_spread_pct:.3f}%)"
            )
            self._log_execution(
                symbol, 'buy', 'none', current_price, micro.get('ask'),
                None, None, micro.get('spread_pct'), position_data.get('position_size_crypto', 0),
                (time.time() - start_time) * 1000.0, False, 'spread_still_too_wide'
            )
            self.bot.record_decision(
                symbol,
                action_type='buy',
                allowed=False,
                reason='execution_spread_too_wide',
                metrics={
                    'price': current_price,
                    'spread_pct': micro.get('spread_pct'),
                    'max_spread_pct': self.max_allowed_spread_pct,
                },
                throttle_seconds=30,
            )
            return False
        expected_price = current_price
        requested_price = micro['ask']

        # 3. Dynamic Volume & Sizing Adjustment
        size_crypto = position_data.get('position_size_crypto', 0)
        final_position_usd = float(size_crypto or 0.0) * float(current_price or 0.0)
        if float(size_crypto or 0.0) <= 0 or final_position_usd <= 0:
            print(f"❌ Smart Execution: taille invalide sur {symbol} ({float(size_crypto or 0.0):.8f}, {final_position_usd:.2f} USD)")
            try:
                self.bot.set_symbol_cooldown(symbol, self.bot.symbol_failure_cooldown_seconds, reason='invalid_order_size')
            except Exception:
                pass
            self.bot.record_decision(
                symbol,
                action_type='buy',
                allowed=False,
                reason='execution_invalid_order_size',
                metrics={
                    'price': current_price,
                    'position_size_crypto': size_crypto,
                    'position_size_usd': final_position_usd,
                },
                throttle_seconds=60,
            )
            return False
        if hasattr(self.bot, 'capital_manager') and not self.bot.capital_manager.can_open_new_position(symbol, final_position_usd):
            print(f"❌ Smart Execution: Garde-fou capital refuse {symbol} ({final_position_usd:.2f} USD)")
            self.bot.record_decision(
                symbol,
                action_type='buy',
                allowed=False,
                reason='execution_capital_blocked',
                metrics={
                    'price': current_price,
                    'position_size_usd': final_position_usd,
                },
                throttle_seconds=60,
            )
            return False

        # 4. Adaptive Order Selection (Market Taker vs Limit Maker)
        ml_buy_prob = float(position_data.get('ml_buy_prob', 50.0) or 50.0)
        order_type = 'market'
        
        # Si confiance ML très élevée (>= 80%) ou mode urgent -> Market
        # Sinon si adaptive maker activé -> Tenter Limit Maker au Bid
        if self.adaptive_maker_orders and ml_buy_prob < 80.0 and not self.bot.paper_trading:
            order_type = 'limit'

        # 5. Exécution de l'ordre
        order = None
        composite_execution = None
        composite_accounted = False
        
        if order_type == 'limit' and not self.bot.paper_trading:
            limit_price = micro['bid']  # Poser au Bid pour frais Maker
            print(f"⚡ {symbol}: Ordre LIMIT MAKER au Bid {limit_price:.2f} USD (Confiance ML: {ml_buy_prob:.1f}%)")
            try:
                latency_trace['order_send_ns'] = time.perf_counter_ns()
                order = self.bot.exchange.create_limit_buy_order(
                    symbol, size_crypto, limit_price, params={'postOnly': True}
                )
                latency_trace['order_ack_ns'] = time.perf_counter_ns()
                fill_start = time.time()
                fetched_order = order
                first_fill_ns = None
                while (time.time() - fill_start) < self.limit_fill_timeout:
                    time.sleep(self.limit_fill_poll)
                    fetched_order = self.bot.exchange.fetch_order(order['id'], symbol) or fetched_order
                    filled_now = float(fetched_order.get('filled') or 0.0)
                    if filled_now > 0 and first_fill_ns is None:
                        first_fill_ns = time.perf_counter_ns()
                        latency_trace['first_fill_ns'] = first_fill_ns
                    if fetched_order.get('status') == 'closed':
                        order = fetched_order
                        latency_trace['final_fill_ns'] = time.perf_counter_ns()
                        break

                if order and order.get('status') != 'closed':
                    print(f"⏳ {symbol}: Limit Maker non rempli après {self.limit_fill_timeout}s -> annulation / reliquat Market")
                    try:
                        self.bot.exchange.cancel_order(order['id'], symbol)
                    except Exception:
                        pass
                    try:
                        fetched_order = self.bot.exchange.fetch_order(order['id'], symbol) or fetched_order
                    except Exception:
                        pass

                    filled_limit = float((fetched_order or {}).get('filled') or 0.0)
                    remaining = max(0.0, float(size_crypto) - filled_limit)

                    if filled_limit > 0:
                        if first_fill_ns is None:
                            latency_trace['first_fill_ns'] = time.perf_counter_ns()
                        limit_exec = self.bot._resolve_exchange_execution(
                            symbol, fetched_order, filled_limit, limit_price, side='buy'
                        )
                        limit_px = float(limit_exec.get('price') or limit_price)
                        self.bot._record_live_order_accounting(
                            symbol, 'buy', filled_limit, limit_px, fetched_order,
                            order_type='limit', filled=True
                        )
                    else:
                        limit_exec = None
                        limit_px = 0.0

                    if remaining > 1e-12:
                        latency_trace['fallback_market_send_ns'] = time.perf_counter_ns()
                        market_order = self.bot.exchange.create_market_buy_order(symbol, remaining)
                        latency_trace['fallback_market_ack_ns'] = time.perf_counter_ns()
                        market_exec = self.bot._resolve_exchange_execution(
                            symbol, market_order, remaining, current_price, side='buy'
                        )
                        if latency_trace.get('first_fill_ns') is None:
                            latency_trace['first_fill_ns'] = time.perf_counter_ns()
                        latency_trace['final_fill_ns'] = time.perf_counter_ns()
                        market_amount = float(market_exec.get('amount') or remaining)
                        market_px = float(market_exec.get('price') or current_price)
                        self.bot._record_live_order_accounting(
                            symbol, 'buy', market_amount, market_px, market_order,
                            order_type='market', filled=True
                        )
                    else:
                        market_order = None
                        market_exec = None
                        market_amount = 0.0
                        market_px = 0.0

                    total_amount = filled_limit + market_amount
                    if total_amount <= 0:
                        order_type = 'market'
                        order = self.bot.buy_market(
                            symbol, size_crypto,
                            sizing_reason=position_data.get('sizing_reason'),
                            ml_buy_prob=ml_buy_prob
                        )
                    else:
                        weighted_price = (
                            (filled_limit * limit_px) + (market_amount * market_px)
                        ) / total_amount
                        total_fee = float((limit_exec or {}).get('fee_amount') or 0.0) + float((market_exec or {}).get('fee_amount') or 0.0)
                        composite_execution = {
                            'price': weighted_price,
                            'amount': total_amount,
                            'fee_amount': total_fee,
                        }
                        composite_accounted = True
                        order_type = 'hybrid' if filled_limit > 0 and market_amount > 0 else ('limit' if filled_limit > 0 else 'market')
                        order = {
                            'id': (market_order or fetched_order or {}).get('id'),
                            'status': 'closed',
                            'price': weighted_price,
                            'amount': total_amount,
                            'filled': total_amount,
                        }
                        latency_trace['final_fill_ns'] = time.perf_counter_ns()
            except Exception as e:
                print(f"⚠️ Limit order échoué ({e}) -> Fallback Market")
                order_type = 'market'
                latency_trace['fallback_market_send_ns'] = time.perf_counter_ns()
                order = self.bot.buy_market(symbol, size_crypto, sizing_reason=position_data.get('sizing_reason'), ml_buy_prob=ml_buy_prob)
                latency_trace['fallback_market_ack_ns'] = time.perf_counter_ns()
        else:
            order = self.bot.buy_market(symbol, size_crypto, sizing_reason=position_data.get('sizing_reason'), ml_buy_prob=ml_buy_prob)

        if not order:
            print(f"❌ Smart Execution: Échec de la création d'ordre sur {symbol}")
            self._log_execution(symbol, 'buy', order_type, expected_price, requested_price, None, None, micro['spread_pct'], size_crypto, (time.time() - start_time)*1000.0, False, "Order placement failed")
            return False

        # 6. Slippage Tracking & Logging. Pour le live, le prix demande peut
        # diverger du prix moyen réellement exécuté, surtout après un fallback.
        execution = composite_execution or self.bot._resolve_exchange_execution(
            symbol,
            order,
            size_crypto,
            current_price,
            side='buy',
        )
        executed_price = float(execution.get('price') or order.get('price') or current_price)
        executed_amount = float(execution.get('amount') or size_crypto)
        slippage_pct = ((executed_price - expected_price) / expected_price * 100.0) if expected_price > 0 else 0.0
        exec_duration_ms = (time.time() - start_time) * 1000.0

        if (order_type in ('limit', 'hybrid') or composite_accounted) and not self.bot.paper_trading:
            if not composite_accounted:
                self.bot._record_live_order_accounting(
                    symbol,
                    'buy',
                    executed_amount,
                    executed_price,
                    order,
                    order_type='limit',
                    filled=True,
                )
            position = {
                'symbol': symbol,
                'side': 'buy',
                'amount': executed_amount,
                'price': executed_price,
                'timestamp': datetime.now().isoformat(),
                'order_id': order.get('id'),
                'source': 'bot',
                'paper': False,
                'status': 'executed',
                'fee': execution.get('fee_amount'),
                'position_size_crypto': executed_amount,
                'position_size_usd': executed_amount * executed_price,
                'sizing_reason': position_data.get('sizing_reason'),
                'ml_buy_prob': ml_buy_prob,
                'ml_target_gain_pct': position_data.get('ml_target_gain_pct'),
                'ml_target_price': position_data.get('ml_target_price'),
            }
            self.bot.state.setdefault('positions', []).append(position)
            self.bot.save_state()

        if ml_entry_learning_id and getattr(self.bot, 'ml_live_logger', None):
            try:
                self.bot.ml_live_logger.mark_entry_opened(
                    symbol,
                    ml_entry_learning_id,
                    order=order,
                    price=executed_price,
                    amount=executed_amount,
                    mode='paper' if self.bot.paper_trading else 'live',
                )
            except Exception:
                pass

        self.bot.set_symbol_cooldown(symbol, reason='buy_executed')
        avg_entry_price = self.bot.get_real_buy_price(symbol)
        
        self.bot.record_decision(
            symbol, 'buy_executed', True, reason,
            {
                'price': executed_price,
                'avg_entry_price': avg_entry_price,
                'position_size_usd': position_data.get('position_size_usd'),
                'position_size_crypto': executed_amount,
                'stop_loss_price': position_data.get('stop_loss_price'),
                'risk_reward_ratio': position_data.get('risk_reward_ratio'),
                'slippage_pct': round(slippage_pct, 4),
                'order_type': order_type,
                'spread_pct': round(micro['spread_pct'], 4)
            },
            throttle_seconds=0
        )

        # Notification Telegram (le chemin limit maker ne passe pas par buy_market qui notifie déjà)
        if (order_type in ('limit', 'hybrid') or composite_accounted) and not self.bot.paper_trading and hasattr(self.bot, 'notifier'):
            try:
                analysis = self.bot.get_cached_analysis(symbol, executed_price)
                signal_data = {
                    'trend': analysis['global_signal'].get('dominant_trend', 'N/A'),
                    'confidence': analysis['global_signal'].get('confidence', 0),
                    'volatility': analysis.get('volatility', 0)
                }
                self.bot.notifier.notify_trade_buy(symbol, executed_amount, executed_price, executed_amount * executed_price, signal_data)
            except Exception:
                pass

        existing_positions = [p for p in self.bot.state.get('positions', []) if p['symbol'] == symbol and p['side'] == 'buy']
        position_count = len(existing_positions)
        
        slippage_str = f" | Slippage: {slippage_pct:+.2f}%" if abs(slippage_pct) > 0.01 else ""
        print(f"✅ ACHAT {crypto} (#{position_count}): {executed_amount:.6f} {crypto} @ {executed_price:.2f} USD ({executed_amount * executed_price:.1f} USD) [{order_type.upper()}]{slippage_str} | Stop {position_data['stop_loss_price']:.2f} (-{position_data['stop_loss_percent']:.1f}%) | R/R 1:{position_data['risk_reward_ratio']:.1f}")

        # Enregistrer dans SQLite
        self._log_execution(symbol, 'buy', order_type, expected_price, requested_price, executed_price, slippage_pct, micro['spread_pct'], executed_amount, exec_duration_ms, True, reason)
        latency_trace['execution_done_ns'] = time.perf_counter_ns()
        if getattr(self.bot, 'ml_live_logger', None) and hasattr(self.bot.ml_live_logger, 'record_execution_latency'):
            try:
                self.bot.ml_live_logger.record_execution_latency(
                    symbol=symbol,
                    side='buy',
                    order_type=order_type,
                    trace=latency_trace,
                    success=True,
                    expected_price=expected_price,
                    executed_price=executed_price,
                    slippage_pct=slippage_pct,
                    mode='paper' if self.bot.paper_trading else 'live',
                )
            except Exception:
                pass

        # Ajouter trailing stop
        hybrid_safety = os.getenv('HYBRID_PHYSICAL_SAFETY', 'true').lower() == 'true'
        trailing_manager = getattr(self.bot, 'trailing_stop_manager', None)
        if trailing_manager and (not (os.getenv('ML_OWNS_EXITS', 'true').lower() == 'true') or hybrid_safety):
            trailing_manager.add_position(
                symbol, executed_price, 
                trailing_percent=position_data.get('trailing_stop_percent'),
                support_price=position_data.get('support_price'),
                resistance_price=position_data.get('resistance_price'),
                target_gain_pct=position_data.get('ml_target_gain_pct')
            )

        # Placer ordre de vente (paper ET réel)
        if self.bot.paper_trading:
            self.bot._place_paper_sell_order(symbol)

        return True

    def _log_execution(self, symbol, side, order_type, expected_price, requested_price, executed_price, slippage_pct, spread_pct, amount, duration_ms, success, reason):
        """Enregistre les détails d'exécution dans SQLite."""
        if hasattr(self.bot, 'ml_live_logger') and self.bot.ml_live_logger:
            try:
                self.bot.ml_live_logger.log_execution_metric(
                    symbol=symbol,
                    side=side,
                    order_type=order_type,
                    expected_price=expected_price,
                    requested_price=requested_price,
                    executed_price=executed_price,
                    slippage_pct=slippage_pct,
                    spread_pct=spread_pct,
                    amount=amount,
                    duration_ms=duration_ms,
                    success=success,
                    reason=reason,
                    mode='paper' if self.bot.paper_trading else 'live',
                )
            except Exception:
                pass
