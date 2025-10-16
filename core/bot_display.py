"""Module d'affichage et monitoring pour le bot de trading"""
import os
import threading
from queue import Queue
from datetime import datetime
import time

class DisplayMixin:
    """Mixin contenant toutes les méthodes d'affichage et monitoring"""
    
    def show_realtime_prices(self, trading_pairs):
        """Affiche les prix en temps réel (format compact, asynchrone)"""
        prices = []
        for pair in trading_pairs:
            symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
            try:
                price = self.get_price(symbol)
                crypto = symbol.split('/')[0]
                if price >= 10000:
                    price_str = f"{price/1000:.1f}K"
                elif price >= 1000:
                    price_str = f"{price/1000:.2f}K"
                else:
                    price_str = f"{price:.0f}"
                prices.append(f"{crypto} {price_str}")
            except:
                prices.append(f"{symbol.split('/')[0]} ERR")
        
        self.async_print(f"\n⚡ {datetime.now().strftime('%H:%M:%S')} | {' | '.join(prices)}")
    
    def show_spot_balances(self, trading_pairs):
        """Affiche tous les soldes Spot (free + locked) sur une ligne"""
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
        
        print(f"🤖 Bot {strategy_type.upper()} | {mode} {realtime} | {active_positions} positions")
        print(f"📊 {cryptos} | Min dynamique/paire | Seuil 70% | {earn_status}")
        print("🛑 Ctrl+C pour arrêter")
    
    def show_tradable_pairs(self, tradable_pairs, usdt_available):
        """Affiche les paires tradables (silencieux si vide)"""
        balance = self.balance_manager.get_balance()
        tradable_display = []
        
        for s in tradable_pairs:
            base = s.split('/')[0]
            free = balance.get(base, {}).get('free', 0)
            if free > 0.00001:
                value = free * self.get_price(s)
                if value >= self.get_min_amount(s)['min_cost']:
                    tradable_display.append(base)
            else:
                tradable_display.append(base)
        
        # Log silencieux si aucun tradable disponible
        if not tradable_display or usdt_available < 0.01:
            return
        
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
        """Affiche les prévisions d'achat"""
        if buy_predictions:
            print("\n🔮 PRÉVISIONS ACHATS:")
            for crypto, prediction in buy_predictions:
                if prediction['status'] == 'READY':
                    min_conf = prediction.get('min_confidence', 60)
                    print(f"✅ {crypto}: {prediction['time_estimate']} (conf {prediction['confidence']:.0f}%≥{min_conf}%) - {prediction['reason']}")
                elif prediction['status'] == 'WAITING':
                    print(f"⏳ {crypto}: {prediction['time_estimate']} | {prediction['reason']}")
    
    def show_strategy_execution(self, symbol, price, change_24h, vol_display):
        """Affiche l'exécution d'une stratégie"""
        self.async_print(f"\n⚡ {symbol} {price:.2f} ({change_24h:+.2f}%) | Vol {vol_display:.1f}/5")
    
    def show_debug_commands(self):
        """Affiche les commandes de debug"""
        print("\n🔧 COMMANDES DEBUG:")
        print("  bot.force_balance_sync()  # Forcer sync balances")
        print("  bot.balance_manager.get_balance(True)  # Rafraîchir balances")
