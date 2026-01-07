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
                        sr_levels = self.sr_analyzer.find_support_resistance_levels(klines)
                        reversal_pred = self.sr_analyzer.predict_reversal_probability(price, sr_levels)
                        
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
            print(f"💳 SPOT: USDT {self.paper_balance:.2f}")
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
            print(f"💳 SPOT: {' | '.join(balances)}")
        else:
            print(f"💳 SPOT: Vide")
    
    def show_performance(self):
        """Affiche les performances et positions ouvertes"""
        if os.getenv('SHOW_PERFORMANCE', 'True') != 'True':
            return
        
        win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0
        print(f"\n📊 {self.daily_pnl:+.2f} | {self.total_trades} trades ({win_rate:.0f}% win)")
        
        # Afficher résumé Double Investment si activé
        if hasattr(self, 'double_investment_manager') and self.double_investment_manager.enabled:
            dual_summary = self.double_investment_manager.get_positions_summary()
            if dual_summary != "Aucune position":
                print(f"💎 Double Investment: {dual_summary}")
            else:
                print(f"💎 Double Investment: Aucune position")
        
        # CORRECTION: Utiliser les positions du state pour paper trading
        if self.paper_trading:
            active_positions = [p for p in self.state.get('positions', []) 
                              if p['side'] == 'buy']
            
            if not active_positions:
                print(f"⏳ Aucune position")
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
                    print(f"🟢 {crypto} {amount:.6f} @ {buy_price:.2f} → {current_price:.2f} ({pnl_pct:+.2f}%) = {position_value:.2f} USDT")
                else:
                    print(f"🔴 {crypto} {amount:.6f} @ {buy_price:.2f} → {current_price:.2f} ({pnl_pct:+.2f}%) = {position_value:.2f} USDT")
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
            
            # Si locked, afficher ordre limite actif avec prix réel Binance
            if locked > 0.00001:
                # Récupérer le prix réel de l'ordre depuis Binance
                real_order_price = None
                if not self.paper_trading:
                    try:
                        open_orders = self.safe_request(self.exchange.fetch_open_orders, symbol)
                        for order in open_orders:
                            if order['side'] == 'sell':
                                real_order_price = order['price']
                                break
                    except:
                        pass
                
                # Fallback sur prix calculé si pas trouvé
                if real_order_price is None:
                    real_order_price = buy_price * (1 + min_profit_needed)
                
                distance_pct = ((real_order_price - current_price) / current_price) * 100
                
                # Marquer les ordres éloignés comme bloquants
                if distance_pct > 5:
                    self.async_print(f"🔴 {base_currency} bloqué: position ouverte {current_holding:.6f} ({position_value:.2f} USDT)")
                else:
                    self.async_print(f"🟡 {base_currency}: Ordre @ {real_order_price:.2f} USDT")
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
            print(f"⏳ Aucune position")
        
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
        cryptos = ', '.join([p.replace('USDT', '') for p in trading_pairs])
        earn_status = "Earn ON" if os.getenv('TIRELIRE_MODE', 'False') == 'True' else "Earn OFF"
        
        # Ajouter statut Double Investment
        dual_status = "DualInv OFF"
        if hasattr(self, 'double_investment_manager'):
            if self.double_investment_manager.enabled:
                # Compter positions réelles + simulées
                real_positions = self.double_investment_manager.get_dual_investment_positions_from_api()
                total_positions = len(real_positions) + len(self.double_investment_manager.positions)
                dual_status = f"DualInv ON ({total_positions})"
        
        print(f"🤖 TETANIS | {mode} {realtime} | {active_positions} positions")
        print(f"📊 {cryptos} | Min dynamique/paire | Seuil 70% | {earn_status} | {dual_status}")
        print("🛑 Ctrl+C pour arrêter")
    
    def show_tradable_pairs(self, tradable_pairs, usdt_available):
        """Affiche les paires tradables (déjà filtrées par le crypto scorer)"""
        if self.paper_trading or not tradable_pairs:
            return
        
        balance = self.balance_manager.get_balance()
        tradable_display = []
        
        # Utiliser directement la liste filtrée par le crypto scorer
        for symbol in tradable_pairs:
            base = symbol.split('/')[0]
            free = balance.get(base, {}).get('free', 0)
            min_cost = self.get_min_amount(symbol)['min_cost']
            
            # Déterminer type d'action possible
            can_buy = usdt_available >= min_cost
            can_sell = free > 0.00001 and (free * self.get_price(symbol)) >= min_cost
            
            if can_buy and can_sell:
                tradable_display.append(f"{base} (A/V)")
            elif can_buy:
                tradable_display.append(f"{base} (A)")
            elif can_sell:
                tradable_display.append(f"{base} (V)")
            else:
                # Crypto dans la liste mais pas tradable actuellement
                tradable_display.append(f"{base} (-)")
        
        if tradable_display:
            print(f"🔍 Tradable: {tradable_display} | USDT: {usdt_available:.2f}")
    
    def show_top_cryptos(self, best_cryptos):
        """Affiche les meilleures cryptos selon le scoring"""
        if best_cryptos:
            print(f"\n🎯 TOP SCORES: {', '.join([s.split('/')[0] for s in best_cryptos])}")
    
    def show_sell_predictions(self, sell_predictions):
        """Affiche les prévisions de vente"""
        if sell_predictions:
            print("\n🔮 PRÉVISIONS VENTES:")
            for symbol, pred in sell_predictions:
                crypto = symbol.split('/')[0]
                print(f"🟢 {crypto}: Ordre @ {pred['target_price']:.2f} USDT")
                print(f"   📍 Actuel: {pred['current_price']:.2f} (+{pred['distance_pct']:.1f}% à atteindre)")
                print(f"   ⏱️ Estimation: {pred['time_estimate']} | 🎯 Probabilité: {pred['probability']}%")
                print(f"   💡 {pred['reason']} (Vol: {pred['volatility']:.1f}/5, Mom: {pred['momentum']:+.1f}%)")
    
    def show_buy_predictions(self, buy_predictions):
        """Affiche les prévisions d'achat avec Support/Résistance"""
        if buy_predictions:
            print("\n🔮 PRÉVISIONS ACHATS:")
            for crypto, prediction in buy_predictions:
                symbol = f"{crypto}/USDT"
                
                # Ajouter info Support/Résistance
                sr_info = ""
                try:
                    klines = self.get_klines(symbol, 100, os.getenv('MAIN_TIMEFRAME', '15m'))
                    if len(klines) >= 50:
                        current_price = self.get_price(symbol)
                        sr_levels = self.sr_analyzer.find_support_resistance_levels(klines)
                        reversal_pred = self.sr_analyzer.predict_reversal_probability(current_price, sr_levels)
                        
                        if reversal_pred['nearest_support']:
                            support_price = reversal_pred['nearest_support']['price']
                            sr_info = f" | Support: {support_price:.2f}"
                except:
                    pass
                
                if prediction['status'] == 'READY':
                    min_conf = prediction.get('min_confidence', 60)
                    print(f"✅ {crypto}: {prediction['time_estimate']} (conf {prediction['confidence']:.0f}%≥{min_conf}%) - {prediction['reason']}{sr_info}")
                elif prediction['status'] == 'WAITING':
                    print(f"⏳ {crypto}: {prediction['time_estimate']} | {prediction['reason']}{sr_info}")
    
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
