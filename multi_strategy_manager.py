import threading
import time
from datetime import datetime
from strategy import ScalpingStrategy, DCAStrategy
from grid_strategy import GridTradingStrategy
from dynamic_grid_strategy import DynamicGridStrategy

class MultiStrategyManager:
    def __init__(self, bot):
        self.bot = bot
        self.strategies = {}
        self.strategy_threads = {}
        self.is_running = False
        
    def add_strategy(self, name, strategy_instance):
        """Ajoute une stratégie au gestionnaire"""
        self.strategies[name] = strategy_instance
        print(f"✅ Stratégie ajoutée: {name}")
    
    def start_strategy(self, name):
        """Démarre une stratégie spécifique"""
        if name not in self.strategies:
            print(f"❌ Stratégie inconnue: {name}")
            return False
        
        if name in self.strategy_threads and self.strategy_threads[name].is_alive():
            print(f"⚠️ Stratégie {name} déjà en cours")
            return False
        
        strategy = self.strategies[name]
        thread = threading.Thread(target=strategy.run, name=f"Strategy-{name}")
        thread.daemon = True
        thread.start()
        
        self.strategy_threads[name] = thread
        print(f"🚀 Stratégie {name} démarrée")
        return True
    
    def stop_strategy(self, name):
        """Arrête une stratégie spécifique"""
        if name in self.strategies:
            self.strategies[name].is_running = False
            print(f"🛑 Arrêt demandé pour {name}")
    
    def get_strategy_status(self):
        """Retourne le statut de toutes les stratégies"""
        status = {}
        
        for name, strategy in self.strategies.items():
            is_alive = name in self.strategy_threads and self.strategy_threads[name].is_alive()
            
            status[name] = {
                'running': getattr(strategy, 'is_running', False),
                'thread_alive': is_alive,
                'type': strategy.__class__.__name__,
                'symbol': getattr(strategy, 'symbol', 'N/A')
            }
            
            # Stats spécifiques selon le type
            if isinstance(strategy, GridTradingStrategy):
                grid_stats = strategy.get_grid_stats()
                status[name].update({
                    'active_orders': grid_stats['active_orders'],
                    'completed_cycles': grid_stats['completed_cycles'],
                    'total_profit': grid_stats['total_profit']
                })
            elif hasattr(strategy, 'safety_manager'):
                safety_stats = strategy.safety_manager.get_stats()
                status[name].update({
                    'trades_count': safety_stats['trades_count'],
                    'total_profit': safety_stats['total_profit'] + safety_stats['total_loss']
                })
        
        return status
    
    def print_dashboard(self):
        """Affiche le dashboard de toutes les stratégies"""
        status = self.get_strategy_status()
        
        print("\n" + "="*60)
        print("MULTI-STRATEGY DASHBOARD")
        print("="*60)
        
        for name, info in status.items():
            status_icon = "🟢" if info['running'] else "🔴"
            print(f"{status_icon} {name} ({info['type']}) - {info['symbol']}")
            
            if 'active_orders' in info:
                print(f"   Ordres actifs: {info['active_orders']}, Cycles: {info['completed_cycles']}, Profit: ${info['total_profit']:.2f}")
            elif 'trades_count' in info:
                print(f"   Trades: {info['trades_count']}, Profit: ${info['total_profit']:.2f}")
        
        print("="*60)
    
    def run_all(self):
        """Démarre toutes les stratégies configurées"""
        print("🚀 Démarrage de toutes les stratégies...")
        
        for name in self.strategies.keys():
            self.start_strategy(name)
            time.sleep(2)  # Délai entre les démarrages
        
        self.is_running = True
        
        # Boucle de monitoring
        counter = 0
        while self.is_running:
            try:
                counter += 1
                
                # Dashboard toutes les 30 itérations (5 minutes)
                if counter % 30 == 0:
                    self.print_dashboard()
                
                # Vérifier que les threads sont toujours vivants
                for name, thread in self.strategy_threads.items():
                    if not thread.is_alive() and self.strategies[name].is_running:
                        print(f"⚠️ Redémarrage automatique de {name}")
                        self.start_strategy(name)
                
                time.sleep(10)
                
            except KeyboardInterrupt:
                print("\n⏹️ Arrêt de toutes les stratégies...")
                self.stop_all()
                break
            except Exception as e:
                print(f"❌ Erreur gestionnaire: {e}")
                time.sleep(30)
    
    def stop_all(self):
        """Arrête toutes les stratégies"""
        self.is_running = False
        
        for name in self.strategies.keys():
            self.stop_strategy(name)
        
        # Attendre que tous les threads se terminent
        for name, thread in self.strategy_threads.items():
            if thread.is_alive():
                print(f"⏳ Attente arrêt {name}...")
                thread.join(timeout=10)
        
        print("🛑 Toutes les stratégies arrêtées")

def create_default_strategies(bot):
    """Crée un ensemble de stratégies par défaut"""
    manager = MultiStrategyManager(bot)
    
    # Stratégie 1: Scalping BTC avancé (multi-timeframes)
    from advanced_scalping_strategy import AdvancedScalpingStrategy
    advanced_scalping_btc = AdvancedScalpingStrategy(bot, 'BTC/USDT', amount_usdt=10)
    manager.add_strategy('advanced_scalping_btc', advanced_scalping_btc)
    
    # Stratégie 2: Grid SOL (consolidations)
    grid_sol = GridTradingStrategy(bot, 'SOL/USDT', total_amount=50, grid_levels=8, grid_range=0.03)
    manager.add_strategy('grid_sol', grid_sol)
    
    # Stratégie 3: DCA ETH (accumulation long terme)
    dca_eth = DCAStrategy(bot, 'ETH/USDT', amount_usdt=15, interval_minutes=120)
    manager.add_strategy('dca_eth', dca_eth)
    
    return manager

def create_advanced_strategies(bot):
    """Crée un ensemble de stratégies avancées avec multi-timeframes"""
    manager = MultiStrategyManager(bot)
    
    # Stratégies avancées avec multi-timeframes
    from advanced_scalping_strategy import AdvancedScalpingStrategy
    
    # Scalping BTC haute confiance
    btc_scalping = AdvancedScalpingStrategy(bot, 'BTC/USDT', amount_usdt=15)
    btc_scalping.set_confidence_threshold(70)
    manager.add_strategy('btc_advanced', btc_scalping)
    
    # Scalping SOL confiance modérée
    sol_scalping = AdvancedScalpingStrategy(bot, 'SOL/USDT', amount_usdt=10)
    sol_scalping.set_confidence_threshold(60)
    manager.add_strategy('sol_advanced', sol_scalping)
    
    # Grid Dynamique BTC (s'adapte à la volatilité)
    dynamic_grid_btc = DynamicGridStrategy(bot.client, 'BTCUSDT', 12.0)
    manager.add_strategy('dynamic_grid_btc', dynamic_grid_btc)
    
    return manager

def create_dynamic_grid_strategies(bot):
    """Crée des stratégies Grid Dynamique pour différents actifs"""
    manager = MultiStrategyManager(bot)
    
    # Grid Dynamique BTC (volatilité variable)
    btc_dynamic = DynamicGridStrategy(bot.client, 'BTCUSDT', 15.0)
    manager.add_strategy('btc_dynamic', btc_dynamic)
    
    # Grid Dynamique ETH (plus stable)
    eth_dynamic = DynamicGridStrategy(bot.client, 'ETHUSDT', 12.0)
    manager.add_strategy('eth_dynamic', eth_dynamic)
    
    # Grid Dynamique SOL (haute volatilité)
    sol_dynamic = DynamicGridStrategy(bot.client, 'SOLUSDT', 8.0)
    manager.add_strategy('sol_dynamic', sol_dynamic)
    
    return manager