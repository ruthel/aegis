#!/usr/bin/env python3
"""Test des prix temps réel"""
import time
import requests

def get_binance_price(symbol):
    """Récupère le prix actuel depuis l'API Binance"""
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        response = requests.get(url)
        data = response.json()
        return float(data['price'])
    except:
        return None

def test_realtime():
    """Test si les prix changent en temps réel"""
    symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT']
    
    print("Test prix temps reel...")
    print("Comparaison avec API Binance officielle:")
    print()
    
    prices_1 = {}
    for symbol in symbols:
        price = get_binance_price(symbol)
        if price:
            crypto = symbol.replace('USDT', '')
            prices_1[crypto] = price
            print(f"{crypto}: {price:.2f}")
    
    print()
    print("Attente 10 secondes...")
    time.sleep(10)
    
    print("\nNouveaux prix:")
    prices_2 = {}
    for symbol in symbols:
        price = get_binance_price(symbol)
        if price:
            crypto = symbol.replace('USDT', '')
            prices_2[crypto] = price
            change = price - prices_1.get(crypto, price)
            print(f"{crypto}: {price:.2f} (change: {change:+.2f})")
    
    # Vérifier si les prix ont changé
    changed = any(abs(prices_2.get(c, 0) - prices_1.get(c, 0)) > 0.01 for c in prices_1.keys())
    
    if changed:
        print("\nOK - Les prix changent en temps reel")
    else:
        print("\nATTENTION - Les prix semblent statiques")

if __name__ == "__main__":
    test_realtime()