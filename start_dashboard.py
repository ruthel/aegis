#!/usr/bin/env python3
from web_dashboard import WebDashboard, BotManager
import threading

def main():
    print("🚀 Démarrage du dashboard web...")
    
    # Créer le gestionnaire de bot
    bot_manager = BotManager()
    
    # Créer le dashboard web
    dashboard = WebDashboard(bot_manager)
    
    print("📊 Dashboard disponible sur:")
    print("   http://localhost:8080")
    print("   http://127.0.0.1:8080")
    print("\n⚠️  Note: Le bot n'est pas encore connecté.")
    print("   Utilisez deploy.py pour connecter le bot au dashboard.")
    print("\n🛑 Appuyez sur Ctrl+C pour arrêter")
    
    try:
        # Démarrer le serveur web
        dashboard.run(host='127.0.0.1', port=8080, debug=False)
    except KeyboardInterrupt:
        print("\n👋 Dashboard arrêté")

if __name__ == "__main__":
    main()