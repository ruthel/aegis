#!/usr/bin/env python3
import asyncio
import logging
from binance import AsyncClient
from dynamic_grid_strategy import DynamicGridStrategy
import os
from dotenv import load_dotenv

# Configuration logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_dynamic_grid():
    """Test de la stratégie Grid Dynamique"""
    
    # Chargement configuration
    load_dotenv()
    
    # Client Binance
    client = await AsyncClient.create(
        api_key=os.getenv('BINANCE_API_KEY'),
        api_secret=os.getenv('BINANCE_API_SECRET'),
        testnet=True  # TESTNET pour les tests
    )
    
    try:
        print("🧪 Test Grid Dynamique - TESTNET")
        print("=" * 50)
        
        # Création stratégie
        strategy = DynamicGridStrategy(client, "BTCUSDT", 10.0)
        
        # Test calcul volatilité
        print("📊 Test calcul volatilité...")
        volatility = await strategy.calculate_volatility(24)
        print(f"Volatilité 24h: {volatility:.2f}%")
        
        # Test configuration optimale
        config = strategy.get_optimal_config(volatility)
        print(f"Config optimale: ±{config.range_percent}% - {config.num_levels} niveaux")
        
        # Test prix actuel
        price = await strategy.get_current_price()
        print(f"Prix BTC: ${price:.2f}")
        
        # Test création niveaux
        buy_levels, sell_levels = await strategy.create_grid_levels(price, config)
        print(f"Niveaux créés: {len(buy_levels)} achats, {len(sell_levels)} ventes")
        print(f"Range: ${min(buy_levels):.2f} - ${max(sell_levels):.2f}")
        
        # Démarrage stratégie (simulation courte)
        print("\n🚀 Démarrage Grid Dynamique...")
        await strategy.start()
        
        # Monitoring 2 minutes
        for i in range(4):
            await asyncio.sleep(30)
            status = strategy.get_status()
            print(f"Status: {status['active_orders']} ordres actifs")
            
            if await strategy.should_recalibrate():
                print("🔄 Recalibration nécessaire détectée")
        
        # Arrêt
        await strategy.stop()
        print("✅ Test terminé avec succès")
        
    except Exception as e:
        print(f"❌ Erreur test: {e}")
    
    finally:
        await client.close_connection()

if __name__ == "__main__":
    asyncio.run(test_dynamic_grid())