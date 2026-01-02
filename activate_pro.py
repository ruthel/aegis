#!/usr/bin/env python3
"""Script d'activation du mode professionnel"""

def activate_pro_mode():
    """Active le mode professionnel dans le bot"""
    
    print("🚀 ACTIVATION MODE PROFESSIONNEL")
    print("=" * 50)
    
    # Lire le fichier bot principal
    bot_file = "core/binance_spot_bot.py"
    
    with open(bot_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Ajouter l'import de la stratégie pro
    if "from utils.pro_strategy import add_pro_strategy_to_bot" not in content:
        import_line = "from utils.pro_strategy import add_pro_strategy_to_bot"
        
        # Trouver la ligne des imports utils
        lines = content.split('\n')
        insert_index = -1
        
        for i, line in enumerate(lines):
            if "from utils.market_calculator import MarketCalculator" in line:
                insert_index = i + 1
                break
        
        if insert_index > 0:
            lines.insert(insert_index, import_line)
            content = '\n'.join(lines)
            print("✅ Import ajouté")
    
    # Ajouter l'activation dans __init__
    if "add_pro_strategy_to_bot(self)" not in content:
        # Trouver la fin de __init__
        init_end = content.find("except Exception as e:")
        if init_end > 0:
            # Insérer avant la gestion d'erreur
            insertion_point = content.rfind("self.websocket.start_user_data_stream(self)", 0, init_end)
            if insertion_point > 0:
                # Trouver la fin de cette ligne
                line_end = content.find('\n', insertion_point)
                if line_end > 0:
                    pro_code = """
        
        # ACTIVATION MODE PROFESSIONNEL
        if os.getenv('USE_SIMPLE_STRATEGY', 'False') == 'True':
            add_pro_strategy_to_bot(self)
            print("🚀 MODE PRO ACTIVÉ - Niveaux fixes + Scaling")"""
                    
                    content = content[:line_end] + pro_code + content[line_end:]
                    print("✅ Mode pro intégré dans __init__")
    
    # Sauvegarder
    with open(bot_file, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("\n📊 MODIFICATIONS APPLIQUÉES:")
    print("  ✅ Niveaux fixes activés")
    print("  ✅ Positions multiples autorisées") 
    print("  ✅ Scaling automatique")
    print("  ✅ Protections réduites")
    print("  ✅ Confidence abaissée à 50%")
    print("  ✅ 20 trades/jour max")
    
    print("\n🎯 NIVEAUX FIXES CONFIGURÉS:")
    print("  BTC: 90K, 85K, 80K, 75K")
    print("  SOL: 130, 125, 120, 115") 
    print("  ETH: 3200, 3000, 2800, 2600")
    print("  BNB: 900, 850, 800, 750")
    
    print("\n⚠️ ATTENTION:")
    print("  - Plus de risque = Plus d'opportunités")
    print("  - Surveillez les positions multiples")
    print("  - Testez en paper trading d'abord")
    
    print("\n🚀 REDÉMARREZ LE BOT POUR ACTIVER !")

if __name__ == "__main__":
    activate_pro_mode()