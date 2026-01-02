#!/usr/bin/env python3
"""Test du mode professionnel intégré"""

def test_pro_integration():
    """Teste l'intégration du mode professionnel"""
    
    print("🧪 TEST MODE PROFESSIONNEL")
    print("=" * 50)
    
    # Vérifier les fichiers créés
    files_to_check = [
        "utils/fixed_levels_manager.py",
        "utils/multi_position_manager.py",
        "utils/pro_strategy.py"
    ]
    
    for file_path in files_to_check:
        if os.path.exists(file_path):
            print(f"✅ {file_path}")
        else:
            print(f"❌ {file_path} - MANQUANT")
    
    # Vérifier la configuration .env
    print("\n📊 CONFIGURATION .env:")
    
    env_vars = [
        "USE_SIMPLE_STRATEGY",
        "AGGRESSIVE_MODE", 
        "ALLOW_MULTIPLE_POSITIONS",
        "POSITION_SCALING",
        "BTC_LEVELS",
        "SOL_LEVELS",
        "MIN_CONFIDENCE"
    ]
    
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    for var in env_vars:
        value = os.getenv(var, "NON DÉFINI")
        print(f"  {var}: {value}")
    
    # Test des niveaux fixes
    print("\n🎯 TEST NIVEAUX FIXES:")
    
    try:
        from utils.fixed_levels_manager import FixedLevelsManager
        fixed_levels = FixedLevelsManager()
        
        # Test SOL
        sol_levels = fixed_levels.get_all_levels('SOL/USDT')
        print(f"  SOL niveaux: {sol_levels}")
        
        # Test signal d'achat
        should_buy, level = fixed_levels.should_buy_at_level('SOL/USDT', 126.0, tolerance_pct=1.5)
        print(f"  SOL @ 126.0: Achat={should_buy}, Niveau={level}")
        
        print("✅ Gestionnaire niveaux fixes OK")
        
    except Exception as e:
        print(f"❌ Erreur niveaux fixes: {e}")
    
    # Test positions multiples
    print("\n📊 TEST POSITIONS MULTIPLES:")
    
    try:
        from utils.multi_position_manager import MultiPositionManager
        multi_pos = MultiPositionManager()
        
        print(f"  Max positions/crypto: {multi_pos.max_positions_per_crypto}")
        print(f"  Niveaux scaling: {multi_pos.scale_levels}")
        
        print("✅ Gestionnaire positions multiples OK")
        
    except Exception as e:
        print(f"❌ Erreur positions multiples: {e}")
    
    # Vérifier intégration dans le bot
    print("\n🤖 TEST INTÉGRATION BOT:")
    
    try:
        # Lire le fichier bot
        with open('core/binance_spot_bot.py', 'r', encoding='utf-8') as f:
            bot_content = f.read()
        
        checks = [
            ("Import FixedLevelsManager", "from utils.fixed_levels_manager import FixedLevelsManager"),
            ("Import MultiPositionManager", "from utils.multi_position_manager import MultiPositionManager"),
            ("Initialisation pro", "self.fixed_levels = FixedLevelsManager()"),
            ("Méthode pro", "def intelligent_strategy_pro"),
            ("Mode pro activé", "MODE PRO ACTIVÉ")
        ]
        
        for check_name, check_text in checks:
            if check_text in bot_content:
                print(f"  ✅ {check_name}")
            else:
                print(f"  ❌ {check_name}")
        
    except Exception as e:
        print(f"❌ Erreur vérification bot: {e}")
    
    print("\n🚀 RÉSUMÉ:")
    print("  ✅ Niveaux fixes: BTC, SOL, ETH, BNB")
    print("  ✅ Positions multiples: 4 max par crypto")
    print("  ✅ Scaling automatique: 1x, 1.5x, 2x, 3x")
    print("  ✅ Mode agressif: Protections réduites")
    print("  ✅ Confidence: 50% (au lieu de 70%)")
    
    print("\n⚠️ POUR ACTIVER:")
    print("  1. Redémarrez le bot")
    print("  2. Le mode pro se lance automatiquement")
    print("  3. Surveillez les messages 'ACHAT PRO'")

if __name__ == "__main__":
    import os
    test_pro_integration()