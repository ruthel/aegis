#!/usr/bin/env python3
"""Test du mode professionnel integre"""

def test_pro_integration():
    """Teste l'integration du mode professionnel"""
    
    print("TEST MODE PROFESSIONNEL")
    print("=" * 50)
    
    # Verifier les fichiers crees
    import os
    files_to_check = [
        "utils/fixed_levels_manager.py",
        "utils/multi_position_manager.py", 
        "utils/pro_strategy.py"
    ]
    
    for file_path in files_to_check:
        if os.path.exists(file_path):
            print(f"OK {file_path}")
        else:
            print(f"MANQUE {file_path}")
    
    # Verifier la configuration .env
    print("\nCONFIGURATION .env:")
    
    env_vars = [
        "USE_SIMPLE_STRATEGY",
        "AGGRESSIVE_MODE", 
        "ALLOW_MULTIPLE_POSITIONS",
        "BTC_LEVELS",
        "SOL_LEVELS",
        "MIN_CONFIDENCE"
    ]
    
    from dotenv import load_dotenv
    load_dotenv()
    
    for var in env_vars:
        value = os.getenv(var, "NON DEFINI")
        print(f"  {var}: {value}")
    
    # Test des niveaux fixes
    print("\nTEST NIVEAUX FIXES:")
    
    try:
        from utils.fixed_levels_manager import FixedLevelsManager
        fixed_levels = FixedLevelsManager()
        
        # Test SOL
        sol_levels = fixed_levels.get_all_levels('SOL/USDT')
        print(f"  SOL niveaux: {sol_levels}")
        
        # Test signal d'achat
        should_buy, level = fixed_levels.should_buy_at_level('SOL/USDT', 126.0, tolerance_pct=1.5)
        print(f"  SOL @ 126.0: Achat={should_buy}, Niveau={level}")
        
        print("OK Gestionnaire niveaux fixes")
        
    except Exception as e:
        print(f"ERREUR niveaux fixes: {e}")
    
    print("\nRESUME:")
    print("  - Niveaux fixes: BTC, SOL, ETH, BNB")
    print("  - Positions multiples: 4 max par crypto")
    print("  - Scaling automatique: 1x, 1.5x, 2x, 3x")
    print("  - Mode agressif: Protections reduites")
    print("  - Confidence: 50% (au lieu de 70%)")
    
    print("\nPOUR ACTIVER:")
    print("  1. Redemarrez le bot")
    print("  2. Le mode pro se lance automatiquement")
    print("  3. Surveillez les messages 'ACHAT PRO'")

if __name__ == "__main__":
    test_pro_integration()