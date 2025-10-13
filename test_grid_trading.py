from binance_spot_bot import BinanceSpotBot
from grid_strategy import GridTradingStrategy
from multi_strategy_manager import create_default_strategies
from config import BINANCE_API_KEY, BINANCE_API_SECRET, TESTNET

def test_grid_only():
    """Test du Grid Trading seul"""
    print("=== TEST GRID TRADING ===")
    
    bot = BinanceSpotBot(BINANCE_API_KEY, BINANCE_API_SECRET, TESTNET)
    
    # Configuration du grid
    symbol = input("Symbole (BTC/USDT, SOL/USDT, ETH/USDT): ").strip() or "SOL/USDT"
    total_amount = float(input("Montant total USDT (50): ").strip() or "50")
    grid_levels = int(input("Nombre de niveaux (8): ").strip() or "8")
    grid_range = float(input("Range en % (3): ").strip() or "3") / 100
    
    print(f"\n🎯 Configuration Grid:")
    print(f"Symbole: {symbol}")
    print(f"Montant: ${total_amount}")
    print(f"Niveaux: {grid_levels}")
    print(f"Range: ±{grid_range*100:.1f}%")
    
    # Vérifier le solde
    balance = bot.get_balance()
    usdt_balance = balance.get('USDT', {}).get('free', 0)
    
    if usdt_balance < total_amount:
        print(f"❌ Solde insuffisant: ${usdt_balance:.2f} < ${total_amount}")
        return
    
    print(f"✅ Solde USDT: ${usdt_balance:.2f}")
    
    # Créer et démarrer le grid
    grid_strategy = GridTradingStrategy(
        bot=bot,
        symbol=symbol,
        total_amount=total_amount,
        grid_levels=grid_levels,
        grid_range=grid_range
    )
    
    print(f"\n🚀 Démarrage Grid Trading {symbol}...")
    print("Appuyez sur Ctrl+C pour arrêter")
    
    try:
        grid_strategy.run()
    except KeyboardInterrupt:
        print("\n⏹️ Grid arrêté par l'utilisateur")
        
        # Statistiques finales
        stats = grid_strategy.get_grid_stats()
        print(f"\n📊 RÉSULTATS:")
        print(f"Cycles complétés: {stats['completed_cycles']}")
        print(f"Profit total: ${stats['total_profit']:.2f}")
        print(f"Profit par cycle: ${stats['profit_per_cycle']:.2f}")

def test_multi_strategies():
    """Test de toutes les stratégies simultanément"""
    print("=== TEST MULTI-STRATÉGIES ===")
    
    bot = BinanceSpotBot(BINANCE_API_KEY, BINANCE_API_SECRET, TESTNET)
    
    # Vérifier le solde
    balance = bot.get_balance()
    usdt_balance = balance.get('USDT', {}).get('free', 0)
    
    if usdt_balance < 100:
        print(f"❌ Solde insuffisant pour multi-stratégies: ${usdt_balance:.2f} < $100")
        return
    
    print(f"✅ Solde USDT: ${usdt_balance:.2f}")
    
    # Créer le gestionnaire avec stratégies par défaut
    manager = create_default_strategies(bot)
    
    print("\n🎯 Stratégies configurées:")
    status = manager.get_strategy_status()
    for name, info in status.items():
        print(f"- {name}: {info['type']} sur {info['symbol']}")
    
    print(f"\n🚀 Démarrage de toutes les stratégies...")
    print("Appuyez sur Ctrl+C pour arrêter")
    
    try:
        manager.run_all()
    except KeyboardInterrupt:
        print("\n⏹️ Toutes les stratégies arrêtées")

def main():
    print("🤖 TEST GRID TRADING")
    print("="*40)
    print("1. Grid Trading seul")
    print("2. Multi-stratégies (Scalping + Grid + DCA)")
    print("3. Simulation Grid (sans ordres réels)")
    
    choice = input("\nChoisir (1-3): ").strip()
    
    if choice == "1":
        test_grid_only()
    elif choice == "2":
        test_multi_strategies()
    elif choice == "3":
        print("🧪 Mode simulation - Grid Trading")
        print("(Fonctionnalité à implémenter)")
    else:
        print("❌ Choix invalide")

if __name__ == "__main__":
    main()