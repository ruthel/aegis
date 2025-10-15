#!/usr/bin/env python3
import asyncio
import logging
from binance_spot_bot import BinanceSpotBot
from multi_strategy_manager import create_dynamic_grid_strategies

# Configuration logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('dynamic_grid.log'),
        logging.StreamHandler()
    ]
)

async def main():
    """Lance les stratégies Grid Dynamique"""
    
    print("🚀 LANCEMENT GRID DYNAMIQUE")
    print("=" * 50)
    print("⚠️  TESTNET ACTIVÉ - Aucun risque financier")
    print("📊 Adaptation automatique à la volatilité")
    print("🔄 Recalibration intelligente")
    print("=" * 50)
    
    try:
        # Initialisation bot
        bot = BinanceSpotBot()
        await bot.initialize()
        
        # Création gestionnaire avec Grid Dynamique
        manager = create_dynamic_grid_strategies(bot)
        
        print("\n📋 Stratégies configurées:")
        for name, strategy in manager.strategies.items():
            print(f"  • {name}: {strategy.symbol} (${strategy.base_amount})")
        
        print("\n🎯 Démarrage dans 3 secondes...")
        await asyncio.sleep(3)
        
        # Lancement
        manager.run_all()
        
    except KeyboardInterrupt:
        print("\n⏹️ Arrêt demandé par l'utilisateur")
    except Exception as e:
        print(f"❌ Erreur: {e}")
        logging.error(f"Erreur main: {e}")

if __name__ == "__main__":
    asyncio.run(main())