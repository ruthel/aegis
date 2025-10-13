from binance_spot_bot import BinanceSpotBot
from advanced_scalping_strategy import AdvancedScalpingStrategy
from multi_timeframe_analyzer import MultiTimeframeAnalyzer
from config import BINANCE_API_KEY, BINANCE_API_SECRET, TESTNET

def test_multi_timeframe_analysis():
    """Test de l'analyse multi-timeframes seule"""
    print("=== TEST ANALYSE MULTI-TIMEFRAMES ===")
    
    bot = BinanceSpotBot(BINANCE_API_KEY, BINANCE_API_SECRET, TESTNET)
    analyzer = MultiTimeframeAnalyzer()
    
    symbol = input("Symbole à analyser (BTC/USDT): ").strip() or "BTC/USDT"
    
    try:
        current_price = bot.get_price(symbol)
        print(f"\n📊 Analyse de {symbol} - Prix actuel: ${current_price:.2f}")
        
        # Effectuer l'analyse
        analysis = analyzer.analyze_all_timeframes(bot, symbol, current_price)
        
        # Afficher les résultats détaillés
        print("\n" + "="*70)
        print("ANALYSE DÉTAILLÉE PAR TIMEFRAME")
        print("="*70)
        
        for tf, tf_analysis in analysis['timeframes'].items():
            print(f"\n📈 {tf.upper()} TIMEFRAME:")
            print(f"   Tendance: {tf_analysis['trend'].upper()}")
            print(f"   Force: {tf_analysis['strength']:.2f}")
            print(f"   Signaux: {', '.join(tf_analysis['signals']) if tf_analysis['signals'] else 'Aucun'}")
            
            indicators = tf_analysis['indicators']
            if indicators['rsi']:
                print(f"   RSI: {indicators['rsi']:.1f}")
            if indicators['macd']:
                print(f"   MACD: {indicators['macd']:.4f}")
            print(f"   EMA Trend: {indicators['ema_trend']}")
            print(f"   BB Position: {indicators['bb_position']}")
        
        # Signal global
        global_signal = analysis['global_signal']
        print(f"\n" + "="*70)
        print("SIGNAL GLOBAL")
        print("="*70)
        print(f"🎯 Action recommandée: {global_signal['action']}")
        print(f"💪 Force du signal: {global_signal['strength']:.2f}")
        print(f"🎯 Confiance: {global_signal['confidence']:.1f}%")
        print(f"📊 Tendance dominante: {global_signal['dominant_trend']}")
        print(f"📝 Résumé: {global_signal['summary']}")
        
        print(f"\n🔍 Top signaux:")
        for i, signal in enumerate(global_signal['signals'][:5], 1):
            print(f"   {i}. {signal}")
        
        # Recommandation de trading
        print(f"\n" + "="*70)
        print("RECOMMANDATION DE TRADING")
        print("="*70)
        
        if global_signal['confidence'] >= 70:
            confidence_level = "ÉLEVÉE"
            emoji = "🟢"
        elif global_signal['confidence'] >= 50:
            confidence_level = "MODÉRÉE"
            emoji = "🟡"
        else:
            confidence_level = "FAIBLE"
            emoji = "🔴"
        
        print(f"{emoji} Confiance: {confidence_level} ({global_signal['confidence']:.1f}%)")
        
        if global_signal['action'] in ['STRONG_BUY', 'BUY']:
            print("💰 Recommandation: POSITION D'ACHAT")
            if global_signal['confidence'] >= 80:
                print("   Taille suggérée: 150% de la position normale")
            elif global_signal['confidence'] >= 70:
                print("   Taille suggérée: 120% de la position normale")
            else:
                print("   Taille suggérée: Position normale")
        elif global_signal['action'] in ['STRONG_SELL', 'SELL']:
            print("📉 Recommandation: FERMER LES POSITIONS")
        else:
            print("⏸️ Recommandation: ATTENDRE")
        
    except Exception as e:
        print(f"❌ Erreur lors de l'analyse: {e}")

def test_advanced_scalping():
    """Test de la stratégie de scalping avancée"""
    print("=== TEST SCALPING AVANCÉ MULTI-TIMEFRAMES ===")
    
    bot = BinanceSpotBot(BINANCE_API_KEY, BINANCE_API_SECRET, TESTNET)
    
    symbol = input("Symbole pour scalping (SOL/USDT): ").strip() or "SOL/USDT"
    amount = float(input("Montant USDT (10): ").strip() or "10")
    confidence = int(input("Confiance minimum % (60): ").strip() or "60")
    
    # Vérifier le solde
    balance = bot.get_balance()
    usdt_balance = balance.get('USDT', {}).get('free', 0)
    
    if usdt_balance < amount:
        print(f"❌ Solde insuffisant: ${usdt_balance:.2f} < ${amount}")
        return
    
    print(f"✅ Solde USDT: ${usdt_balance:.2f}")
    
    # Créer la stratégie avancée
    strategy = AdvancedScalpingStrategy(bot, symbol, amount)
    strategy.set_confidence_threshold(confidence)
    
    print(f"\n🧠 Configuration:")
    print(f"   Symbole: {symbol}")
    print(f"   Montant: ${amount}")
    print(f"   Confiance min: {confidence}%")
    print(f"   Timeframes: 1m, 5m, 15m")
    
    print(f"\n🚀 Démarrage du scalping avancé...")
    print("Appuyez sur Ctrl+C pour arrêter")
    
    try:
        strategy.run()
    except KeyboardInterrupt:
        print("\n⏹️ Scalping avancé arrêté")
        
        # Afficher la dernière analyse
        last_analysis = strategy.get_current_analysis()
        if last_analysis:
            print("\n📊 DERNIÈRE ANALYSE:")
            global_signal = last_analysis['global_signal']
            print(f"Signal: {global_signal['action']} (Confiance: {global_signal['confidence']:.1f}%)")
            print(f"Résumé: {global_signal['summary']}")

def compare_strategies():
    """Compare scalping normal vs avancé"""
    print("=== COMPARAISON SCALPING NORMAL VS AVANCÉ ===")
    
    bot = BinanceSpotBot(BINANCE_API_KEY, BINANCE_API_SECRET, TESTNET)
    analyzer = MultiTimeframeAnalyzer()
    
    symbol = "BTC/USDT"
    current_price = bot.get_price(symbol)
    
    print(f"📊 Analyse comparative pour {symbol} à ${current_price:.2f}")
    
    # Analyse multi-timeframes
    analysis = analyzer.analyze_all_timeframes(bot, symbol, current_price)
    
    # Simulation scalping normal (basé sur RSI 1m seulement)
    klines_1m = bot.get_klines(symbol, 50)
    if klines_1m:
        closes_1m = [k['close'] for k in klines_1m]
        rsi_1m = analyzer.indicators.calculate_rsi(closes_1m)
        
        print(f"\n🔸 SCALPING NORMAL (1m seulement):")
        if rsi_1m:
            if rsi_1m < 30:
                normal_signal = "ACHAT (RSI survente)"
            elif rsi_1m > 70:
                normal_signal = "VENTE (RSI surachat)"
            else:
                normal_signal = "ATTENDRE"
            print(f"   Signal: {normal_signal}")
            print(f"   RSI 1m: {rsi_1m:.1f}")
        
        # Scalping avancé
        global_signal = analysis['global_signal']
        print(f"\n🔹 SCALPING AVANCÉ (multi-timeframes):")
        print(f"   Signal: {global_signal['action']}")
        print(f"   Confiance: {global_signal['confidence']:.1f}%")
        print(f"   Résumé: {global_signal['summary']}")
        
        # Recommandation
        print(f"\n💡 RECOMMANDATION:")
        if global_signal['confidence'] >= 70:
            print("   ✅ Utiliser le signal avancé (haute confiance)")
        elif global_signal['confidence'] >= 50:
            print("   🟡 Signal avancé modérément fiable")
        else:
            print("   🔴 Signaux contradictoires - Attendre")

def main():
    print("🧠 TEST ANALYSE MULTI-TIMEFRAMES")
    print("="*50)
    print("1. Test analyse seule")
    print("2. Test scalping avancé")
    print("3. Comparaison normal vs avancé")
    
    choice = input("\nChoisir (1-3): ").strip()
    
    if choice == "1":
        test_multi_timeframe_analysis()
    elif choice == "2":
        test_advanced_scalping()
    elif choice == "3":
        compare_strategies()
    else:
        print("❌ Choix invalide")

if __name__ == "__main__":
    main()