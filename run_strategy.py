from binance_spot_bot import BinanceSpotBot
from strategy import ScalpingStrategy, DCAStrategy
from config import BINANCE_API_KEY, BINANCE_API_SECRET, TESTNET

def main():
    bot = BinanceSpotBot(BINANCE_API_KEY, BINANCE_API_SECRET, TESTNET)
    
    print("Strategies disponibles:")
    print("1. Scalping (BTC/USDT)")
    print("2. DCA (ETH/USDT)")
    print("3. DCA (BNB/USDT)")
    print("4. Scalping (SOL/USDT)")
    
    choice = input("Choisir (1, 2, 3 ou 4): ")
    
    if choice == "1":
        strategy = ScalpingStrategy(bot, 'BTC/USDT', amount_usdt=10)
        print("Demarrage scalping BTC/USDT...")
        strategy.run()
    elif choice == "2":
        strategy = DCAStrategy(bot, 'ETH/USDT', amount_usdt=10, interval_minutes=60)
        print("Demarrage DCA ETH/USDT...")
        strategy.run()
    elif choice == "3":
        strategy = DCAStrategy(bot, 'BNB/USDT', amount_usdt=10, interval_minutes=60)
        print("Demarrage DCA BNB/USDT...")
        strategy.run()
    elif choice == "4":
        strategy = ScalpingStrategy(bot, 'SOL/USDT', amount_usdt=10)
        print("Demarrage scalping SOL/USDT...")
        strategy.run()
    else:
        print("Choix invalide")

if __name__ == "__main__":
    main()