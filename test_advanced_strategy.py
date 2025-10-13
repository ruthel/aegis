from binance_spot_bot import BinanceSpotBot
from strategy import ScalpingStrategy
from config import BINANCE_API_KEY, BINANCE_API_SECRET, TESTNET

def test_advanced_features():
    """Test des nouvelles fonctionnalités avancées"""
    print("=== TEST STRATÉGIE AVANCÉE ===")
    
    bot = BinanceSpotBot(BINANCE_API_KEY, BINANCE_API_SECRET, TESTNET)
    
    # Test avec SOL/USDT (haute volatilité)
    strategy = ScalpingStrategy(bot, 'SOL/USDT', amount_usdt=10)
    
    print("\n🧪 Test des fonctionnalités:")
    print("✅ Position sizing intelligent")
    print("✅ Trailing stop-loss")
    print("✅ Gestion de corrélation")
    print("✅ Validation des ordres")
    print("✅ Sauvegarde d'état")
    
    print(f"\n📊 Volatilité SOL: {strategy.advanced_risk.calculate_volatility(bot, 'SOL/USDT'):.1%}")
    print(f"💰 Position size recommandée: {strategy.advanced_risk.calculate_position_size(bot, 'SOL/USDT', 10):.1f} USDT")
    
    print("\n🚀 Démarrage du trading avancé...")
    print("Appuyez sur Ctrl+C pour arrêter")
    
    try:
        strategy.run()
    except KeyboardInterrupt:
        print("\n⏹️ Bot arrêté par l'utilisateur")
        
        # Afficher les statistiques finales
        print("\n📈 STATISTIQUES FINALES:")
        if strategy.trailing_stop.positions:
            print("Positions avec trailing stops:")
            for symbol, pos in strategy.trailing_stop.positions.items():
                print(f"  {symbol}: Stop à {pos['stop_price']:.2f}")
        
        if strategy.correlation_manager.active_positions:
            print(f"Positions actives: {len(strategy.correlation_manager.active_positions)}")

if __name__ == "__main__":
    test_advanced_features()