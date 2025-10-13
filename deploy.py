from binance_spot_bot import BinanceSpotBot
import os
import sys
from dotenv import load_dotenv

load_dotenv()

def main():
    """Point d'entrée principal - Mode console uniquement"""
    print("🚀 Démarrage du bot de trading...")
    
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')
    
    if not api_key or not api_secret:
        print("❌ Configuration manquante dans .env")
        sys.exit(1)
    
    try:
        bot = BinanceSpotBot(api_key, api_secret)
        bot.run()
    except KeyboardInterrupt:
        print("\n🛑 Arrêt du bot...")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Erreur: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()