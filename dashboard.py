from monitor import TradingMonitor
from binance_spot_bot import BinanceSpotBot
from config import BINANCE_API_KEY, BINANCE_API_SECRET, TESTNET
import time

def main():
    bot = BinanceSpotBot(BINANCE_API_KEY, BINANCE_API_SECRET, TESTNET)
    monitor = TradingMonitor()
    
    while True:
        try:
            monitor.print_dashboard(bot)
            
            # Afficher les 5 derniers trades
            if monitor.trades:
                print("\nDerniers trades:")
                for trade in monitor.trades[-5:]:
                    print(f"{trade['timestamp'][:19]} | {trade['action']} | {trade['symbol']} | ${trade['price']:.2f}")
            
            time.sleep(30)  # Refresh toutes les 30 secondes
            
        except KeyboardInterrupt:
            print("\nArret du dashboard")
            break
        except Exception as e:
            print(f"Erreur dashboard: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()