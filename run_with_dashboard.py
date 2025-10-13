import threading
import time
from binance_spot_bot import BinanceSpotBot
from strategy import ScalpingStrategy
from config import BINANCE_API_KEY, BINANCE_API_SECRET, TESTNET
from web_dashboard import WebDashboard, BotManager

def main():
    print("=== BOT TRADING AVEC DASHBOARD WEB ===")
    
    # Initialiser le bot
    bot = BinanceSpotBot(BINANCE_API_KEY, BINANCE_API_SECRET, TESTNET)
    
    # Choisir la stratégie
    print("\nStratégies disponibles:")
    print("1. Scalping BTC/USDT")
    print("2. Scalping ETH/USDT") 
    print("3. Scalping SOL/USDT")
    print("4. Scalping BNB/USDT")
    
    choice = input("Choisir (1-4): ").strip()
    
    symbol_map = {
        "1": "BTC/USDT",
        "2": "ETH/USDT", 
        "3": "SOL/USDT",
        "4": "BNB/USDT"
    }
    
    symbol = symbol_map.get(choice, "BTC/USDT")
    strategy = ScalpingStrategy(bot, symbol, amount_usdt=10)
    
    # Configurer le gestionnaire de bot
    bot_manager = BotManager()
    bot_manager.set_bot(bot, strategy)
    
    # Démarrer le dashboard web dans un thread séparé
    dashboard = WebDashboard(bot_manager)
    dashboard_thread = threading.Thread(
        target=dashboard.run, 
        kwargs={'host': '0.0.0.0', 'port': 8080, 'debug': False}
    )
    dashboard_thread.daemon = True
    dashboard_thread.start()
    
    print(f"\n🚀 Dashboard web démarré: http://localhost:8080")
    print(f"📊 Trading {symbol} avec notifications avancées")
    print("🔔 Configurez vos notifications dans notification_config.json")
    print("\nFonctionnalités disponibles:")
    print("✅ Dashboard temps réel")
    print("✅ Contrôles à distance") 
    print("✅ Notifications Telegram/Discord/Email")
    print("✅ Métriques de performance")
    print("✅ Historique des trades")
    print("✅ Positions avec trailing stops")
    
    # Attendre que le dashboard soit prêt
    time.sleep(2)
    
    # Marquer le bot comme démarré
    bot_manager.is_running = True
    bot_manager.start_time = time.time()
    
    try:
        # Démarrer la stratégie de trading
        print(f"\n🎯 Démarrage du trading {symbol}...")
        print("Appuyez sur Ctrl+C pour arrêter")
        
        strategy.run()
        
    except KeyboardInterrupt:
        print("\n⏹️ Arrêt demandé par l'utilisateur")
        
        # Marquer le bot comme arrêté
        bot_manager.is_running = False
        
        # Fermer les positions ouvertes
        if hasattr(strategy, 'trailing_stop') and strategy.trailing_stop.positions:
            print("🔄 Fermeture des positions ouvertes...")
            for symbol_pos in list(strategy.trailing_stop.positions.keys()):
                try:
                    current_price = bot.get_price(symbol_pos)
                    balance = bot.get_balance()
                    base_currency = symbol_pos.split('/')[0]
                    amount = balance[base_currency]['free']
                    
                    if amount > 0:
                        order = bot.sell_market(symbol_pos, amount)
                        if order:
                            print(f"✅ Position {symbol_pos} fermée")
                except Exception as e:
                    print(f"❌ Erreur fermeture {symbol_pos}: {e}")
        
        # Statistiques finales
        print("\n📈 STATISTIQUES FINALES:")
        if hasattr(strategy, 'safety_manager'):
            stats = strategy.safety_manager.get_stats()
            print(f"Trades: {stats['trades_count']}")
            print(f"Profit: ${stats['total_profit']:.2f}")
            print(f"Perte: ${stats['total_loss']:.2f}")
            print(f"Net: ${stats['total_profit'] + stats['total_loss']:.2f}")
        
        # Notification de fin
        if hasattr(strategy, 'alert_manager'):
            strategy.alert_manager.notifier.notify(
                "Bot arrêté par l'utilisateur",
                priority="important"
            )
        
        print("🛑 Bot arrêté")
        
    except Exception as e:
        print(f"\n❌ Erreur critique: {e}")
        
        # Notification d'erreur critique
        if hasattr(strategy, 'alert_manager'):
            strategy.alert_manager.notifier.notify(
                f"Erreur critique: {e}",
                priority="critical"
            )
        
        bot_manager.is_running = False
    
    finally:
        # Arrêter le WebSocket
        if hasattr(bot, 'websocket'):
            bot.websocket.stop()
        
        print("🔌 Connexions fermées")

if __name__ == "__main__":
    main()