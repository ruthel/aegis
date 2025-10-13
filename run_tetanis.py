#!/usr/bin/env python3
"""
Tetanis - Trading Bot Dashboard
Lancement du serveur web avec hot reload
"""

import os
from dotenv import load_dotenv
from web_dashboard import WebDashboard, BotManager

def main():
    # Chargement des variables d'environnement
    load_dotenv()
    
    print("🚀 TETANIS - Trading Bot Dashboard")
    print("=" * 50)
    print(f"📊 Paire par défaut: {os.getenv('DEFAULT_TRADING_PAIR', 'SOLUSDT')}")
    print(f"🌐 Mode: {'TESTNET' if os.getenv('TESTNET', 'True') == 'True' else 'PRODUCTION'}")
    print(f"🔄 Hot Reload: Activé")
    print("=" * 50)
    
    # Initialisation
    bot_manager = BotManager()
    dashboard = WebDashboard(bot_manager)
    
    print("\n🌐 Interfaces disponibles:")
    print("  • Tetanis (Tailwind): http://localhost:8080/")
    print("  • Modern (Bootstrap): http://localhost:8080/modern")
    print("  • Classic: http://localhost:8080/classic")
    print("\n⚡ Hot reload activé - Les modifications sont automatiquement rechargées")
    print("🎨 Thème: Dark/Light disponible avec le bouton lune/soleil")
    print("\n🛑 Ctrl+C pour arrêter\n")
    
    # Lancement du serveur
    try:
        dashboard.run(host='0.0.0.0', port=8080, debug=True)
    except KeyboardInterrupt:
        print("\n👋 Tetanis arrêté")

if __name__ == "__main__":
    main()