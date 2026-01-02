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
    
    print("🔍 Test prix temps réel...")
    print("Comparaison avec API Binance officielle:")
    print()
    
    for symbol in symbols:
        price = get_binance_price(symbol)
        if price:
            crypto = symbol.replace('USDT', '')
            print(f"{crypto}: {price:.2f}")
    
    print()
    print("⏱️ Attendez 10 secondes pour voir si les prix changent...")
    time.sleep(10)
    
    print("\n🔄 Nouveaux prix:")
    for symbol in symbols:
        price = get_binance_price(symbol)
        if price:
            crypto = symbol.replace('USDT', '')
            print(f"{crypto}: {price:.2f}")

if __name__ == "__main__":
    test_realtime()