"""Module d'affichage et monitoring pour le bot de trading"""
import os
import threading
from queue import Queue
from datetime import datetime
import time

class DisplayMixin:
    """Mixin contenant toutes les méthodes d'affichage et monitoring"""
    
    def show_realtime_prices(self, trading_pairs):
        """Affiche les prix en temps réel avec analyse Support/Résistance"""
        prices = []
        for pair in trading_pairs:
            symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
            try:
                price = self.get_price(symbol)
                crypto = symbol.split('/')[0]
                
                # Analyse Support/Résistance
                sr_info = ""
                try:
                    klines = self.get_klines(symbol, 100, os.getenv('MAIN_TIMEFRAME', '15m'))
                    if len(klines) >= 50:
                        sr_levels = self.pattern_analyzer.find_support_resistance_levels(klines)
                        reversal_pred = self.pattern_analyzer.predict_reversal_probability(price, sr_levels)
                        
                        if reversal_pred['has_reversal_potential']:
                            direction = reversal_pred['direction']
                            prob = reversal_pred['probability']
                            sr_info = f" [{direction} {prob:.0f}%]"
                except:
                    pass
                
                # Affichage prix exact sans arrondi
                if price >= 10000:
                    price_str = f"{price:.2f}"
                elif price >= 1000:
                    price_str = f"{price:.2f}"
                else:
                    price_str = f"{price:.2f}"
                prices.append(f"{crypto} {price_str}{sr_info}")
            except:
                prices.append(f"{symbol.split('/')[0]} ERR")
        
        self.async_print(f"\n⚡ {datetime.now().strftime('%H:%M:%S')} | {' | '.join(prices)}")
    
    def show_spot_balances(self, trading_pairs):
        """Affiche tous les soldes Spot (free + locked) sur une ligne"""
        if self.paper_trading:
            # CORRECTION: Afficher paper_balance au lieu de balance_manager
            self.async_print(f"💳 SPOT: USDT {self.paper_balance:.2f}")
            return
        
        balance = self.balance_manager.get_balance()
        balances = []
        
        usdt_free = balance.get('USDT', {}).get('free', 0)
        usdt_locked = balance.get('USDT', {}).get('used', 0)
        if usdt_free > 0.01 or usdt_locked > 0.01:
            if usdt_locked > 0.01:
                balances.append(f"USDT {usdt_free:.2f} ({usdt_locked:.2f} locked)")
            else:
                balances.append(f"USDT {usdt_free:.2f}")
        
        for pair in trading_pairs:
            symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
            crypto = symbol.split('/')[0]
            free = balance.get(crypto, {}).get('free', 0)
            locked = balance.get(crypto, {}).get('used', 0)
            total = free + locked
            
            if total > 0.00001:
                if locked > 0.00001:
                    balances.append(f"{crypto} {free:.6f} ({locked:.6f} locked)")
                else:
                    balances.append(f"{crypto} {free:.6f}")
        
        if balances:
            self.async_print(f"💳 SPOT: {' | '.join(balances)}")
        else:
            self.async_print(f"💳 SPOT: Vide")
    
    def show_performance(self):
        """Affiche les performances et positions ouvertes"""
        if os.getenv('SHOW_PERFORMANCE', 'True') != 'True':
            return
        
        # Utiliser win rate global 30j si disponible, sinon win rate du bot
        if hasattr(self, 'global_stats_30d') and self.global_stats_30d:
            stats = self.global_stats_30d
            win_rate = stats['winrate']
            total_trades = stats['total_cycles']
            pnl_display = f"{stats['total_pnl']:+.2f}"
            period_info = " (30j)"
        else:
            win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0
            total_trades = self.total_trades
            pnl_display = f"{self.daily_pnl:+.2f}"
            period_info = ""
        
        self.async_print(f"\n📊 {pnl_display} | {total_trades} trades ({win_rate:.0f}% win){period_info}")
        
        # Afficher résumé Double Investment si activé
        if hasattr(self, 'double_investment_manager') and self.double_investment_manager.enabled:
            dual_summary = self.double_investment_manager.get_positions_summary()
            if dual_summary != "Aucune position":
                self.async_print(f"💎 Double Investment: {dual_summary}")
            else:
                self.async_print(f"💎 Double Investment: Aucune position")
        
        # CORRECTION: Utiliser les positions du state pour paper trading
        if self.paper_trading:
            active_positions = [p for p in self.state.get('positions', []) 
                              if p['side'] == 'buy']
            
            if not active_positions:
                self.async_print(f"⏳ Aucune position")
                return
            
            # Afficher positions paper trading
            for position in active_positions:
                symbol = position['symbol']
                crypto = symbol.split('/')[0]
                amount = position['amount']
                buy_price = position['price']
                current_price = self.get_price(symbol)
                
                pnl_pct = ((current_price - buy_price) / buy_price) * 100
                position_value = amount * current_price
                
                if pnl_pct >= 0:
                    self.async_print(f"🟢 {crypto} {amount:.6f} @ {buy_price:.2f} → {current_price:.2f} ({pnl_pct:+.2f}%) = {position_value:.2f} USDT")
                else:
                    self.async_print(f"🔴 {crypto} {amount:.6f} @ {buy_price:.2f} → {current_price:.2f} ({pnl_pct:+.2f}%) = {position_value:.2f} USDT")
            return
        
        # MODE RÉEL - Utiliser balance_manager
        balance = self.balance_manager.get_balance()
        trading_pairs = os.getenv('TRADING_PAIRS', 'BTCUSDT,ETHUSDT').split(',')
        min_profit_needed = self.min_profit_threshold + (2 * self.trading_fee)
        target_pct = min_profit_needed * 100
        
        has_positions = False
        for pair in trading_pairs:
            symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
            base_currency = symbol.split('/')[0]
            free = balance.get(base_currency, {}).get('free', 0)
            locked = balance.get(base_currency, {}).get('used', 0)
            current_holding = free + locked
            
            if current_holding <= 0.00001:
                continue
            
            current_price = self.get_price(symbol)  # WebSocket temps réel, pas de cache
            position_value = current_holding * current_price
            
            if position_value < self.get_min_amount(symbol)['min_cost']:
                continue
            
            buy_positions = [p for p in self.state['positions'] 
                           if p['symbol'] == symbol and p['side'] == 'buy' 
                           and p.get('source') != 'binance_history']
            
            if not buy_positions:
                buy_positions = [p for p in self.state['positions'] 
                               if p['symbol'] == symbol and p['side'] == 'buy']
            
            if not buy_positions:
                continue
            
            has_positions = True
            buy_price = self.get_real_buy_price(symbol)
            if not buy_price:
                continue
            
            # Si locked, afficher TOUS les ordres limite actifs (bot + manuels)
            if locked > 0.00001:
                # Afficher tous les ordres limite pour cette crypto
                limit_orders = []
                for order_id, order_data in self.pending_orders.items():
                    if (order_data['symbol'] == symbol and 
                        order_data['side'] == 'sell'):
                        order = order_data['order']
                        source = order_data.get('source', 'unknown')
                        source_emoji = "🤖" if source == 'bot' else "👤"
                        limit_orders.append({
                            'price': order['price'],
                            'amount': order['amount'],
                            'source': source_emoji
                        })
                
                if limit_orders:
                    for i, order in enumerate(limit_orders):
                        distance_pct = ((order['price'] - current_price) / current_price) * 100
                        
                        # Marquer les ordres éloignés comme bloquants
                        if distance_pct > 5:
                            self.async_print(f"🔴 {base_currency} bloqué: ordre {order['source']} @ {order['price']:.2f} USDT")
                        else:
                            self.async_print(f"🟡 {base_currency}: Ordre {order['source']} @ {order['price']:.2f} USDT")
                            self.async_print(f"   📍 Actuel: {current_price:.2f} (+{distance_pct:.1f}% à atteindre)")
                else:
                    # Fallback si aucun ordre trouvé mais crypto locked
                    fallback_price = buy_price * (1 + min_profit_needed)
                    distance_pct = ((fallback_price - current_price) / current_price) * 100
                    self.async_print(f"🟡 {base_currency}: Ordre @ {fallback_price:.2f} USDT")
                    self.async_print(f"   📍 Actuel: {current_price:.2f} (+{distance_pct:.1f}% à atteindre)")
                continue
            
            pnl_pct = ((current_price - buy_price) / buy_price) * 100
            target_price = buy_price * (1 + min_profit_needed)
            
            if pnl_pct >= min_profit_needed * 100:
                self.async_print(f"🎯 {base_currency} {current_holding:.6f} @ {buy_price:.2f} → {current_price:.2f} ({pnl_pct:+.2f}%) ✅")
            elif pnl_pct < 0:
                progress = max(0, int(((current_price - buy_price) / (target_price - buy_price)) * 100))
                self.async_print(f"🔴 {base_currency} {current_holding:.6f} @ {buy_price:.2f} → {target_price:.2f} ({pnl_pct:+.2f}%/+{target_pct:.2f}%) [{progress}%]")
            else:
                progress = int(((current_price - buy_price) / (target_price - buy_price)) * 100)
                self.async_print(f"⏳ {base_currency} {current_holding:.6f} @ {buy_price:.2f} → {target_price:.2f} ({pnl_pct:+.2f}%/+{target_pct:.2f}%) [{progress}%]")
        
        if not has_positions:
            self.async_print(f"⏳ Aucune position")
        
        self.stuck_manager.show_stuck_positions()
    
    def start_async_display(self):
        """Démarre l'affichage asynchrone"""
        def display_worker():
            while True:
                try:
                    message = self.display_queue.get(timeout=1)
                    if message is None:
                        break
                    print(message)
                    self.display_queue.task_done()
                except:
                    continue
        self.display_thread = threading.Thread(target=display_worker, daemon=True)
        self.display_thread.start()
    
    def async_print(self, message):
        """Affichage asynchrone pour éviter les blocages"""
        try:
            self.display_queue.put_nowait(message)
        except:
            pass
    
    def show_header(self, trading_pairs, strategy_type, trade_amount, active_positions):
        """Affiche l'en-tête du bot"""
        mode = "PAPER" if self.paper_trading else "LIVE"
        realtime = "⚡ TEMPS RÉEL" if self.realtime_trading else "🔄 CYCLIQUE"
        cryptos = ', '.join([p.split('/')[0] if '/' in p else p.replace('USDT', '') for p in trading_pairs])
        earn_status = "Earn ON" if os.getenv('TIRELIRE_MODE', 'False') == 'True' else "Earn OFF"
        
        # Ajouter statut Double Investment
        dual_status = "DualInv OFF"
        if hasattr(self, 'double_investment_manager'):
            if self.double_investment_manager.enabled:
                # Compter positions réelles + simulées
                real_positions = self.double_investment_manager.get_dual_investment_positions_from_api()
                total_positions = len(real_positions) + len(self.double_investment_manager.positions)
                dual_status = f"DualInv ON ({total_positions})" if total_positions > 0 else "DualInv ON"
        
        # Afficher win rate global si disponible
        winrate_info = ""
        if hasattr(self, 'global_stats_30d') and self.global_stats_30d and not self.paper_trading:
            winrate_info = f" | WR: {self.global_stats_30d['winrate']:.0f}% (30j)"
        
        print(f"🤖 TETANIS | {mode} {realtime} | {active_positions} positions{winrate_info}")
        print(f"📊 {cryptos} | Min dynamique | Seuil adaptatif | {earn_status} | {dual_status}")
        print("🛑 Ctrl+C pour arrêter")
    

    def show_top_cryptos(self, best_cryptos):
        """Affiche les meilleures cryptos selon le scoring"""
        if best_cryptos:
            self.async_print(f"\n🎯 TOP SCORES: {', '.join([s.split('/')[0] for s in best_cryptos])}")
    
    def show_sell_predictions(self, sell_predictions):
        """Affiche les prévisions de vente"""
        if sell_predictions:
            self.async_print("\n🔮 PRÉVISIONS VENTES:")
            for symbol, pred in sell_predictions:
                crypto = symbol.split('/')[0]
                self.async_print(f"🟢 {crypto}: Ordre @ {pred['target_price']:.2f} USDT")
                self.async_print(f"   📍 Actuel: {pred['current_price']:.2f} (+{pred['distance_pct']:.1f}% à atteindre)")
                self.async_print(f"   ⏱️ Estimation: {pred['time_estimate']} | 🎯 Probabilité: {pred['probability']}%")
                self.async_print(f"   💡 {pred['reason']} (Vol: {pred['volatility']:.1f}/5, Mom: {pred['momentum']:+.1f}%)")
    
    def show_buy_predictions(self, buy_predictions):
        """Affiche les prévisions d'achat avec Support/Résistance"""
        if buy_predictions:
            self.async_print("\n🔮 PRÉVISIONS ACHATS:")
            for crypto, prediction in buy_predictions:
                symbol = f"{crypto}/USDT"
                
                # Ajouter info Support/Résistance
                sr_info = ""
                try:
                    klines = self.get_klines(symbol, 100, os.getenv('MAIN_TIMEFRAME', '15m'))
                    if len(klines) >= 50:
                        current_price = self.get_price(symbol)
                        sr_levels = self.pattern_analyzer.find_support_resistance_levels(klines)
                        reversal_pred = self.pattern_analyzer.predict_reversal_probability(current_price, sr_levels)
                        
                        if reversal_pred['nearest_support']:
                            support_price = reversal_pred['nearest_support']['price']
                            sr_info = f" | Support: {support_price:.2f}"
                except:
                    pass
                
                if prediction['status'] == 'READY':
                    min_conf = prediction.get('min_confidence', 60)
                    self.async_print(f"✅ {crypto}: {prediction['time_estimate']} (conf {prediction['confidence']:.0f}%≥{min_conf}%) - {prediction['reason']}{sr_info}")
                elif prediction['status'] == 'WAITING':
                    self.async_print(f"⏳ {crypto}: {prediction['time_estimate']} | {prediction['reason']}{sr_info}")
    
    def show_strategy_execution(self, symbol, price, change_24h, vol_display):
        """Affiche l'exécution d'une stratégie"""
        self.async_print(f"\n⚡ {symbol} {price:.2f} ({change_24h:+.2f}%) | Vol {vol_display:.1f}/5")
    
    def show_debug_commands(self):
        """Affiche les commandes de debug"""
        print("\n🔧 COMMANDES DEBUG:")
        print("  bot.force_balance_sync()  # Forcer sync balances")
        print("  bot.balance_manager.get_balance(True)  # Rafraîchir balances")
    
    def get_tradable_pairs(self, trading_pairs, usdt_available):
        """Retourne la liste des paires réellement tradables via le crypto scorer"""
        stuck_positions = []
        return self.crypto_scorer.rank_cryptos(self, trading_pairs, stuck_positions)
    
    def display_levels(self, symbol):
        """Affiche les niveaux dynamiques pour debug"""
        try:
            levels = self.pattern_analyzer.get_dynamic_levels(symbol)
            current_price = self.get_price(symbol)
            
            print(f"\n📊 NIVEAUX DYNAMIQUES {symbol} (Prix: {current_price:.2f})")
            
            pivots = levels.get('pivot_points', {})
            if pivots:
                print("🔸 Pivot Points:")
                for name, price in pivots.items():
                    if price:
                        distance = (price - current_price) / current_price * 100
                        print(f"   {name.upper()}: {price:.2f} ({distance:+.1f}%)")
            
            supports = levels.get('support', [])
            if supports:
                print("🟢 Supports:")
                for i, support in enumerate(supports[:3]):
                    distance = (support - current_price) / current_price * 100
                    print(f"   S{i+1}: {support:.2f} ({distance:+.1f}%)")
            
            resistances = levels.get('resistance', [])
            if resistances:
                print("🔴 Résistances:")
                for i, resistance in enumerate(resistances[:3]):
                    distance = (resistance - current_price) / current_price * 100
                    print(f"   R{i+1}: {resistance:.2f} ({distance:+.1f}%)")
            
            order_blocks = levels.get('order_blocks', [])
            if order_blocks:
                print("📦 Order Blocks:")
                for i, ob in enumerate(order_blocks[:2]):
                    avg_price = (ob['high'] + ob['low']) / 2
                    distance = (avg_price - current_price) / current_price * 100
                    print(f"   OB{i+1} ({ob['type']}): {avg_price:.2f} ({distance:+.1f}%)")
            
            poc = levels.get('volume_poc')
            if poc:
                distance = (poc - current_price) / current_price * 100
                print(f"📊 Volume POC: {poc:.2f} ({distance:+.1f}%)")
            
        except Exception as e:
            print(f"⚠️ Erreur affichage niveaux {symbol}: {e}")
