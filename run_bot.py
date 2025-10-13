from binance_spot_bot import BinanceSpotBot
from config import BINANCE_API_KEY, BINANCE_API_SECRET, TESTNET, TRADING_PAIRS

def main():
    print("Demarrage du bot Binance...")
    
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        print("Erreur: Cles API manquantes dans le fichier .env")
        return
    
    bot = BinanceSpotBot(BINANCE_API_KEY, BINANCE_API_SECRET, TESTNET)
    
    try:
        # Test de connexion
        balance = bot.get_balance()
        print("Connexion reussie a Binance")
        
        # Afficher les soldes principaux
        for currency in ['USDT', 'BTC', 'ETH']:
            if currency in balance:
                free = balance[currency]['free']
                if free > 0:
                    print(f"{currency}: {free}")
        
        # Afficher les prix des paires
        for pair in TRADING_PAIRS:
            try:
                price = bot.get_price(pair)
                print(f"{pair}: ${price}")
            except Exception as e:
                print(f"Erreur prix {pair}: {e}")
        
        print("Bot pret pour le trading!")
        
    except Exception as e:
        print(f"Erreur de connexion: {e}")

if __name__ == "__main__":
    main()