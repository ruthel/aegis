import os
from binance_spot_bot import BinanceSpotBot
from config import BINANCE_API_KEY, BINANCE_API_SECRET, TESTNET

def check_setup():
    print("=== VERIFICATION CONFIGURATION ===")
    
    # Vérifier clés API
    if not BINANCE_API_KEY or BINANCE_API_KEY == "your_real_api_key":
        print("❌ Clés API non configurées")
        print("1. Allez sur binance.com > Profil > Sécurité API")
        print("2. Créez une nouvelle clé API")
        print("3. Modifiez le fichier .env avec vos vraies clés")
        return False
    
    # Test connexion
    try:
        bot = BinanceSpotBot(BINANCE_API_KEY, BINANCE_API_SECRET, TESTNET)
        balance = bot.get_balance()
        print("✅ Connexion API réussie")
        
        # Vérifier solde USDT
        usdt_balance = balance.get('USDT', {}).get('free', 0)
        if usdt_balance < 20:
            print(f"⚠️ Solde USDT faible: ${usdt_balance}")
            print("Recommandé: minimum 50 USDT pour commencer")
        else:
            print(f"✅ Solde USDT: ${usdt_balance}")
        
        return True
        
    except Exception as e:
        print(f"❌ Erreur connexion: {e}")
        return False

def run_validation():
    print("\n=== VALIDATION COMPLETE ===")
    
    # 1. Installer dépendances
    print("Installation des dépendances...")
    os.system("pip install pandas")
    
    # 2. Lancer tests
    print("\nLancement des tests...")
    from test_suite import run_backtest, run_optimization
    
    try:
        run_backtest()
        print("✅ Backtest terminé")
        
        run_optimization()
        print("✅ Optimisation terminée")
        
    except Exception as e:
        print(f"❌ Erreur tests: {e}")
        return False
    
    return True

def start_paper_trading():
    print("\n=== PAPER TRADING 24H ===")
    print("Démarrage du paper trading...")
    print("Surveillez les performances pendant 24-48h avant trading réel")
    
    from backtester import PaperTrader
    from strategy import ScalpingStrategy
    
    paper_bot = PaperTrader(1000)
    strategy = ScalpingStrategy(paper_bot, 'BTC/USDT', amount_usdt=5)
    
    print("Paper trading démarré avec 1000 USDT virtuels")
    print("Appuyez sur Ctrl+C pour arrêter")
    
    try:
        strategy.run()
    except KeyboardInterrupt:
        print("\nPaper trading arrêté")
        balance = paper_bot.get_balance()
        print(f"Balance finale: ${balance['USDT']['free']:.2f}")

def main():
    print("GUIDE DE MISE EN ROUTE")
    print("1. Vérification configuration")
    print("2. Validation complète")
    print("3. Paper trading 24h")
    
    choice = input("Étape (1-3): ")
    
    if choice == "1":
        if check_setup():
            print("\n✅ Configuration OK - Passez à l'étape 2")
        else:
            print("\n❌ Corrigez la configuration avant de continuer")
    
    elif choice == "2":
        if check_setup() and run_validation():
            print("\n✅ Validation OK - Passez à l'étape 3")
        else:
            print("\n❌ Corrigez les erreurs avant de continuer")
    
    elif choice == "3":
        if check_setup():
            start_paper_trading()
        else:
            print("\n❌ Configuration requise avant paper trading")

if __name__ == "__main__":
    main()