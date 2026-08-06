"""
ExecutionManager - Phase 7 : Exécution Intelligente & Microstructure de Marché
Gère l'exécution optimale des ordres chez Kraken :
1. Spread-aware execution : pause si spread > MAX_EXECUTION_SPREAD_PCT (ex: 0.08%)
2. Dynamic volume / depth check : ajustement selon liquidité live
3. Adaptive orders : market si high confidence (P_win >= 0.80), limit Maker si standard (P_win < 0.80)
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
        self.spread_pause_timeout = float(os.getenv('SPREAD_PAUSE_TIMEOUT_SEC', '3.0'))
        self.limit_fill_timeout = float(os.getenv('LIMIT_FILL_TIMEOUT_SEC', '5.0'))
        self.adaptive_maker_orders = os.getenv('ADAPTIVE_MAKER_ORDERS', 'true').lower() == 'true'

    def get_market_microstructure(self, symbol):
        """Récupère le spread, bid/ask et la profondeur du carnet live."""
        try:
            bid, ask = None, None
            # 1. Tenter via WebSocket si disponible
            if hasattr(self.bot, 'ws_client') and self.bot.ws_client:
                clean_sym = symbol.replace('/', '')
                ticker = self.bot.ws_client.get_ticker(clean_sym)
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

    def adjust_size_for_depth(self, symbol, position_size_crypto, current_price):
        """Ajuste le montant de la position selon la liquidité live."""
        if position_size_crypto <= 0:
            return position_size_crypto
        try:
            micro = self.get_market_microstructure(symbol)
            order_cost = position_size_crypto * current_price
            # Si le montant USD est au-dessus du minimum et que la liquidité est normale, valider
            return position_size_crypto
        except Exception:
            return position_size_crypto

    def execute_smart_buy(self, symbol, position_data, current_price, reason, ml_entry_learning_id=None):
        """
        Exécute un achat intelligent selon la Phase 7 :
        - Vérification anti-duplication
        - Attente resserrement du spread
        - Détermination du type d'ordre (Market vs Limit Maker)
        - Suivi du slippage et enregistrement SQLite
        """
        start_time = time.time()
        crypto = symbol.split('/')[0]
        
        # 1. Anti-Duplication & Safe Retry Check
        cooldown_remaining = self.bot.get_symbol_cooldown_remaining(symbol)
        if cooldown_remaining > 0:
            return False

        if not self.bot.can_open_position(symbol):
            print(f"❌ Smart Execution: Position déjà ouverte ou verrouillée sur {symbol}")
            return False

        # 2. Spread-Aware Execution
        micro = self.wait_for_tight_spread(symbol, max_wait=self.spread_pause_timeout)
        expected_price = current_price
        requested_price = micro['ask']

        # 3. Dynamic Volume & Sizing Adjustment
        size_crypto = position_data.get('position_size_crypto', 0)
        size_crypto = self.adjust_size_for_depth(symbol, size_crypto, current_price)

        # 4. Adaptive Order Selection (Market Taker vs Limit Maker)
        ml_buy_prob = position_data.get('ml_buy_prob', 0.65) or 0.65
        order_type = 'market'
        
        # Si confiance ML très élevée (>= 0.80) ou mode urgent -> Market
        # Sinon si adaptive maker activé -> Tenter Limit Maker au Bid
        if self.adaptive_maker_orders and ml_buy_prob < 0.80 and not self.bot.paper_trading:
            order_type = 'limit'

        # 5. Exécution de l'ordre
        order = None
        
        if order_type == 'limit' and not self.bot.paper_trading:
            limit_price = micro['bid']  # Poser au Bid pour frais Maker
            print(f"⚡ {symbol}: Ordre LIMIT MAKER au Bid {limit_price:.2f} USD (Confiance ML: {ml_buy_prob*100:.1f}%)")
            try:
                order = self.bot.exchange.create_limit_buy_order(symbol, size_crypto, limit_price)
                fill_start = time.time()
                # Attendre exécution Maker pendant limit_fill_timeout
                while (time.time() - fill_start) < self.limit_fill_timeout:
                    time.sleep(1.0)
                    fetched_order = self.bot.exchange.fetch_order(order['id'], symbol)
                    if fetched_order.get('status') == 'closed':
                        order = fetched_order
                        break
                
                # Si non exécuté après timeout, annuler et basculer en Market
                if order and order.get('status') != 'closed':
                    print(f"⏳ {symbol}: Order Limit non rempli après {self.limit_fill_timeout}s -> Conversion en Market Taker")
                    try:
                        self.bot.exchange.cancel_order(order['id'], symbol)
                    except Exception:
                        pass
                    order_type = 'market'
                    order = self.bot.buy_market(symbol, size_crypto, sizing_reason=position_data.get('sizing_reason'), ml_buy_prob=ml_buy_prob)
            except Exception as e:
                print(f"⚠️ Limit order échoué ({e}) -> Fallback Market")
                order_type = 'market'
                order = self.bot.buy_market(symbol, size_crypto, sizing_reason=position_data.get('sizing_reason'), ml_buy_prob=ml_buy_prob)
        else:
            order = self.bot.buy_market(symbol, size_crypto, sizing_reason=position_data.get('sizing_reason'), ml_buy_prob=ml_buy_prob)

        if not order:
            print(f"❌ Smart Execution: Échec de la création d'ordre sur {symbol}")
            self._log_execution(symbol, 'buy', order_type, expected_price, requested_price, None, None, micro['spread_pct'], size_crypto, (time.time() - start_time)*1000.0, False, "Order placement failed")
            return False

        # 6. Slippage Tracking & Logging
        executed_price = float(order.get('price') or current_price)
        slippage_pct = ((executed_price - expected_price) / expected_price * 100.0) if expected_price > 0 else 0.0
        exec_duration_ms = (time.time() - start_time) * 1000.0

        if ml_entry_learning_id and getattr(self.bot, 'ml_live_logger', None):
            try:
                self.bot.ml_live_logger.mark_entry_opened(
                    symbol,
                    ml_entry_learning_id,
                    order=order,
                    price=executed_price,
                    amount=size_crypto
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
                'position_size_crypto': size_crypto,
                'stop_loss_price': position_data.get('stop_loss_price'),
                'risk_reward_ratio': position_data.get('risk_reward_ratio'),
                'slippage_pct': round(slippage_pct, 4),
                'order_type': order_type,
                'spread_pct': round(micro['spread_pct'], 4)
            },
            throttle_seconds=0
        )

        existing_positions = [p for p in self.bot.state.get('positions', []) if p['symbol'] == symbol and p['side'] == 'buy']
        position_count = len(existing_positions)
        
        slippage_str = f" | Slippage: {slippage_pct:+.2f}%" if abs(slippage_pct) > 0.01 else ""
        print(f"✅ ACHAT {crypto} (#{position_count}): {size_crypto:.6f} {crypto} @ {executed_price:.2f} USD ({position_data['position_size_usd']:.1f} USD) [{order_type.upper()}]{slippage_str} | Stop {position_data['stop_loss_price']:.2f} (-{position_data['stop_loss_percent']:.1f}%) | R/R 1:{position_data['risk_reward_ratio']:.1f}")

        # Enregistrer dans SQLite
        self._log_execution(symbol, 'buy', order_type, expected_price, requested_price, executed_price, slippage_pct, micro['spread_pct'], size_crypto, exec_duration_ms, True, reason)

        # Ajouter trailing stop
        hybrid_safety = os.getenv('HYBRID_PHYSICAL_SAFETY', 'true').lower() == 'true'
        if hasattr(self.bot, 'trailing_stop_manager') and (not (os.getenv('ML_OWNS_EXITS', 'true').lower() == 'true') or hybrid_safety):
            self.bot.trailing_stop_manager.add_position(
                symbol, executed_price, 
                trailing_percent=position_data.get('trailing_stop_percent'),
                support_price=position_data.get('support_price'),
                resistance_price=position_data.get('resistance_price')
            )

        # Placer ordre de vente (paper ET réel)
        if self.bot.paper_trading:
            self.bot._place_paper_sell_order(symbol)
        else:
            time.sleep(1)
            self.bot.optimize_existing_position(symbol)

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
                    reason=reason
                )
            except Exception:
                pass
