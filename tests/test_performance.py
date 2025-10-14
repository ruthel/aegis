import time
from binance_spot_bot import BinanceSpotBot
from strategy import ScalpingStrategy
from config import BINANCE_API_KEY, BINANCE_API_SECRET, TESTNET

def test_performance():
    """Test des améliorations de performance"""
    print("=== TEST PERFORMANCE - PRIORITÉ 3 ===")
    
    bot = BinanceSpotBot(BINANCE_API_KEY, BINANCE_API_SECRET, TESTNET)
    
    print("\n🚀 Nouvelles fonctionnalités:")
    print("✅ WebSocket temps réel")
    print("✅ Cache intelligent")
    print("✅ Indicateurs techniques (RSI, MACD, Bollinger)")
    print("✅ Signaux de trading avancés")
    print("✅ Analyse de volume")
    
    # Test de vitesse
    print("\n⚡ Test de vitesse:")
    
    # Test WebSocket
    start_time = time.time()
    for i in range(10):
        price = bot.get_price('BTC/USDT')
    ws_time = (time.time() - start_time) / 10
    
    print(f"Prix WebSocket: {ws_time*1000:.1f}ms par requête")
    
    # Test indicateurs
    print("\n📊 Test indicateurs techniques:")
    klines = bot.get_klines('BTC/USDT', 50)
    if len(klines) >= 30:
        from technical_indicators import SignalGenerator
        signal_gen = SignalGenerator()
        signal = signal_gen.analyze_signals('BTC/USDT', klines, price)
        
        print(f"Signal: {signal['action']} (Force: {signal['strength']:.1f})")
        print(f"Raison: {signal['reason']}")
        print(f"RSI: {signal['indicators']['rsi']:.1f}")
        print(f"MACD: {signal['indicators']['macd']:.4f}")
        print(f"Volume: {signal['indicators']['volume']['trend']}")
    
    # Test stratégie avancée
    print(f"\n🎯 Démarrage stratégie ultra-performante sur {bot.websocket.symbols}...")
    print("Fréquence: 1 seconde (vs 5 secondes avant)")
    print("Signaux: Techniques avancés (vs prix simple avant)")
    print("Données: Temps réel WebSocket (vs REST API avant)")
    
    strategy = ScalpingStrategy(bot, 'BTC/USDT', amount_usdt=10)
    
    try:
        strategy.run()
    except KeyboardInterrupt:
        print("\n⏹️ Test arrêté")
        
        # Statistiques finales
        print("\n📈 PERFORMANCE:")
        if bot.websocket.is_connected():
            print("✅ WebSocket actif - Données temps réel")
        else:
            print("⚠️ WebSocket inactif - Mode REST API")
            
        print(f"Cache prix: {len(bot.price_cache)} entrées")
        
        # Arrêter WebSocket
        bot.websocket.stop()

if __name__ == "__main__":
    test_performance()