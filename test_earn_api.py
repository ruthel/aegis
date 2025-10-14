#!/usr/bin/env python3
import os
from core.binance_earn_api import BinanceEarnAPI

# Test des nouvelles API Simple Earn
def test_earn_api():
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')
    
    if not api_key or not api_secret:
        print("❌ Clés API manquantes")
        return
    
    earn_api = BinanceEarnAPI(api_key, api_secret, testnet=False)
    
    print("🔍 Test des nouvelles API Simple Earn...")
    
    # Test 1: Lister produits Flexible
    print("\n1. Test liste produits Flexible:")
    flexible_products = earn_api.get_flexible_products()
    print(f"Réponse: {flexible_products}")
    
    # Test 2: Lister produits Locked
    print("\n2. Test liste produits Locked:")
    locked_products = earn_api.get_locked_products()
    print(f"Réponse: {locked_products}")
    
    # Test 3: Positions actuelles
    print("\n3. Test positions Flexible:")
    positions = earn_api.get_flexible_positions()
    print(f"Réponse: {positions}")
    
    # Test 4: Trouver produit USDT
    print("\n4. Test recherche produit USDT:")
    usdt_product = earn_api.find_usdt_flexible_product()
    print(f"Produit USDT trouvé: {usdt_product}")

if __name__ == "__main__":
    test_earn_api()