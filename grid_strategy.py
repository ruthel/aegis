import time
import json
from datetime import datetime
from safety_manager import SafetyManager
from notification_manager import AlertManager

class GridTradingStrategy:
    def __init__(self, bot, symbol, total_amount=50, grid_levels=10, grid_range=0.02):
        self.bot = bot
        self.symbol = symbol
        self.total_amount = total_amount  # Montant total à répartir
        self.grid_levels = grid_levels    # Nombre de niveaux de grid
        self.grid_range = grid_range      # Range du grid (2% = 0.02)
        
        self.grid_orders = {}  # {price: {'type': 'buy/sell', 'amount': x, 'order_id': y}}
        self.base_price = 0
        self.amount_per_level = total_amount / grid_levels
        self.is_running = False
        
        # Gestionnaires
        self.safety_manager = SafetyManager()
        self.alert_manager = AlertManager()
        
        # Stats
        self.completed_cycles = 0
        self.total_profit = 0
        self.active_orders = 0
        
    def calculate_grid_levels(self, current_price):
        """Calcule les niveaux de prix du grid"""
        self.base_price = current_price
        
        # Calculer les niveaux d'achat (en dessous du prix actuel)
        buy_levels = []
        for i in range(1, self.grid_levels // 2 + 1):
            price = current_price * (1 - (self.grid_range * i / (self.grid_levels // 2)))
            buy_levels.append(round(price, 2))
        
        # Calculer les niveaux de vente (au dessus du prix actuel)
        sell_levels = []
        for i in range(1, self.grid_levels // 2 + 1):
            price = current_price * (1 + (self.grid_range * i / (self.grid_levels // 2)))
            sell_levels.append(round(price, 2))
        
        return buy_levels, sell_levels
    
    def place_grid_orders(self):
        """Place tous les ordres du grid"""
        try:
            current_price = self.bot.get_price(self.symbol)
            buy_levels, sell_levels = self.calculate_grid_levels(current_price)
            
            print(f"🔄 Placement du grid {self.symbol}")
            print(f"Prix actuel: ${current_price:.2f}")
            print(f"Range: ±{self.grid_range*100:.1f}%")
            print(f"Niveaux: {self.grid_levels}")
            
            # Placer les ordres d'achat
            for price in buy_levels:
                amount = self.amount_per_level / price
                
                if self.bot.validate_order(self.symbol, amount, price):
                    order = self.bot.buy_limit(self.symbol, amount, price)
                    if order:
                        self.grid_orders[price] = {
                            'type': 'buy',
                            'amount': amount,
                            'order_id': order.get('id'),
                            'status': 'pending'
                        }
                        self.active_orders += 1
                        print(f"✅ Ordre d'achat: {amount:.6f} @ ${price:.2f}")
            
            # Placer les ordres de vente (nécessite d'avoir des cryptos)
            balance = self.bot.get_balance()
            base_currency = self.symbol.split('/')[0]
            available_crypto = balance.get(base_currency, {}).get('free', 0)
            
            if available_crypto > 0:
                crypto_per_level = available_crypto / len(sell_levels)
                
                for price in sell_levels:
                    if crypto_per_level > 0:
                        order = self.bot.sell_limit(self.symbol, crypto_per_level, price)
                        if order:
                            self.grid_orders[price] = {
                                'type': 'sell',
                                'amount': crypto_per_level,
                                'order_id': order.get('id'),
                                'status': 'pending'
                            }
                            self.active_orders += 1
                            print(f"✅ Ordre de vente: {crypto_per_level:.6f} @ ${price:.2f}")
            
            print(f"📊 Grid activé: {self.active_orders} ordres placés")
            
        except Exception as e:
            print(f"❌ Erreur placement grid: {e}")
    
    def check_filled_orders(self):
        """Vérifie les ordres exécutés et replace les ordres opposés"""
        try:
            current_price = self.bot.get_price(self.symbol)
            filled_orders = []
            
            for price, order_info in self.grid_orders.items():
                if order_info['status'] == 'pending':
                    # Vérifier si l'ordre est exécuté (simulation simple)
                    if order_info['type'] == 'buy' and current_price <= price:
                        # Ordre d'achat exécuté
                        filled_orders.append((price, order_info, 'buy'))
                        
                    elif order_info['type'] == 'sell' and current_price >= price:
                        # Ordre de vente exécuté
                        filled_orders.append((price, order_info, 'sell'))
            
            # Traiter les ordres exécutés
            for price, order_info, order_type in filled_orders:
                self.process_filled_order(price, order_info, order_type, current_price)
                
        except Exception as e:
            print(f"❌ Erreur vérification ordres: {e}")
    
    def process_filled_order(self, price, order_info, order_type, current_price):
        """Traite un ordre exécuté et place l'ordre opposé"""
        try:
            amount = order_info['amount']
            
            if order_type == 'buy':
                # Ordre d'achat exécuté → placer ordre de vente
                sell_price = price * (1 + (self.grid_range / (self.grid_levels // 2)))
                sell_price = round(sell_price, 2)
                
                # Simuler la vente (en réalité, utiliser bot.sell_limit)
                print(f"💰 ACHAT exécuté: {amount:.6f} @ ${price:.2f}")
                print(f"📈 Placement vente: {amount:.6f} @ ${sell_price:.2f}")
                
                # Calculer le profit potentiel
                potential_profit = (sell_price - price) * amount
                self.total_profit += potential_profit
                self.completed_cycles += 1
                
                # Notification
                self.alert_manager.notify_trade('BUY', self.symbol, amount, price)
                
            elif order_type == 'sell':
                # Ordre de vente exécuté → placer ordre d'achat
                buy_price = price * (1 - (self.grid_range / (self.grid_levels // 2)))
                buy_price = round(buy_price, 2)
                
                print(f"💸 VENTE exécutée: {amount:.6f} @ ${price:.2f}")
                print(f"📉 Placement achat: {amount:.6f} @ ${buy_price:.2f}")
                
                # Notification
                profit = (price - self.base_price) * amount
                self.alert_manager.notify_trade('SELL', self.symbol, amount, price, profit)
            
            # Marquer l'ordre comme exécuté
            self.grid_orders[price]['status'] = 'filled'
            self.active_orders -= 1
            
        except Exception as e:
            print(f"❌ Erreur traitement ordre: {e}")
    
    def get_grid_stats(self):
        """Retourne les statistiques du grid"""
        return {
            'symbol': self.symbol,
            'base_price': self.base_price,
            'grid_levels': self.grid_levels,
            'grid_range': f"{self.grid_range*100:.1f}%",
            'active_orders': self.active_orders,
            'completed_cycles': self.completed_cycles,
            'total_profit': self.total_profit,
            'profit_per_cycle': self.total_profit / max(1, self.completed_cycles)
        }
    
    def print_dashboard(self):
        """Affiche le dashboard du grid"""
        stats = self.get_grid_stats()
        current_price = self.bot.get_price(self.symbol)
        
        print("\n" + "="*50)
        print(f"GRID TRADING - {stats['symbol']}")
        print("="*50)
        print(f"Prix actuel: ${current_price:.2f}")
        print(f"Prix de base: ${stats['base_price']:.2f}")
        print(f"Range: {stats['grid_range']}")
        print(f"Ordres actifs: {stats['active_orders']}")
        print(f"Cycles complétés: {stats['completed_cycles']}")
        print(f"Profit total: ${stats['total_profit']:.2f}")
        print(f"Profit/cycle: ${stats['profit_per_cycle']:.2f}")
        print("="*50)
    
    def run(self):
        """Démarre la stratégie de grid trading"""
        print(f"🚀 Démarrage Grid Trading {self.symbol}")
        print(f"💰 Montant total: ${self.total_amount}")
        print(f"📊 Niveaux: {self.grid_levels}")
        print(f"📈 Range: ±{self.grid_range*100:.1f}%")
        
        self.is_running = True
        
        # Placement initial du grid
        self.place_grid_orders()
        
        # Notification de démarrage
        self.alert_manager.notifier.notify(
            f"Grid Trading démarré sur {self.symbol} - {self.grid_levels} niveaux, range ±{self.grid_range*100:.1f}%",
            priority="important"
        )
        
        counter = 0
        
        while self.is_running:
            try:
                # Vérifier les ordres exécutés
                self.check_filled_orders()
                
                # Afficher dashboard toutes les 20 itérations
                counter += 1
                if counter % 20 == 0:
                    self.print_dashboard()
                
                # Vérifier les limites de sécurité
                if not self.safety_manager.can_trade():
                    print("🛑 Limites de sécurité atteintes - Arrêt du grid")
                    break
                
                time.sleep(10)  # Vérifier toutes les 10 secondes
                
            except KeyboardInterrupt:
                print("\n⏹️ Arrêt du grid demandé")
                break
                
            except Exception as e:
                print(f"❌ Erreur grid: {e}")
                self.alert_manager.check_bot_status(False, str(e))
                time.sleep(30)
        
        self.is_running = False
        print("🛑 Grid Trading arrêté")
        
        # Statistiques finales
        final_stats = self.get_grid_stats()
        print(f"\n📊 BILAN FINAL:")
        print(f"Cycles complétés: {final_stats['completed_cycles']}")
        print(f"Profit total: ${final_stats['total_profit']:.2f}")
        
        # Notification de fin
        self.alert_manager.notifier.notify(
            f"Grid Trading {self.symbol} arrêté - {final_stats['completed_cycles']} cycles, profit: ${final_stats['total_profit']:.2f}",
            priority="important"
        )