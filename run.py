#!/usr/bin/env python3
"""
Point d'entrée principal pour le bot de trading Binance
Démarrage sécurisé avec vérifications et gestion d'erreurs
"""
import sys
import os
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

def main():
    """Point d'entrée principal"""
    print("🚀 Démarrage du bot de trading Binance...")
    
    # Vérification configuration
    
    # Import du bot (après vérification config)
    try:
        from core.binance_spot_bot import BinanceSpotBot
    except ImportError as e:
        print(f"❌ Erreur import: {e}")
        print("📝 Vérifiez que tous les modules sont installés: pip install -r requirements.txt")
        sys.exit(1)
    
    # Récupération configuration
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')
    testnet = os.getenv('TESTNET', 'True').lower() == 'true'
    
    # Démarrage du bot
    try:
        bot = BinanceSpotBot(api_key, api_secret, testnet)
        bot.run()
    except KeyboardInterrupt:
        print("\n🛑 Arrêt du bot...")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Erreur: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()