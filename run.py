#!/usr/bin/env python3
"""
Point d'entrée principal pour le bot de trading Binance
Démarrage sécurisé avec vérifications et gestion d'erreurs
"""
import sys
import os
import shutil
import threading
from flask import Flask, jsonify
from dotenv import load_dotenv

def clear_python_cache():
    """Vider les caches Python au démarrage"""
    cache_dirs = ['__pycache__', '.pytest_cache']
    cache_files = ['.pyc', '.pyo', '.pyd']
    
    for root, dirs, files in os.walk('.'):
        # Supprimer dossiers cache
        for cache_dir in cache_dirs:
            if cache_dir in dirs:
                cache_path = os.path.join(root, cache_dir)
                try:
                    shutil.rmtree(cache_path)
                except:
                    pass
        
        # Supprimer fichiers cache
        for file in files:
            if any(file.endswith(ext) for ext in cache_files):
                file_path = os.path.join(root, file)
                try:
                    os.remove(file_path)
                except:
                    pass
    print(f"🧹 Cache supprimé")

def clean_bot_states():
    """Nettoie les états du bot selon le mode (paper/live)"""
    # Vérifier le mode paper trading
    paper_trading = os.getenv('PAPER_TRADING', 'False').lower() == 'true'
    
    if paper_trading:
        # En paper trading, nettoyer seulement les fichiers paper
        state_files = [
            'data/paper_bot_state.json',
            'data/paper_cache.json', 
            'data/paper_temp_state.json',
            'data/paper_positions.json'
        ]
        print("🧹 Mode PAPER - Nettoyage fichiers paper trading")
    else:
        # En trading réel, ne PAS nettoyer les fichiers (préserver l'état)
        print("💰 Mode LIVE - Conservation des états existants")
        return
    
    cleaned = 0
    for state_file in state_files:
        if os.path.exists(state_file):
            try:
                os.remove(state_file)
                print(f"🧹 État nettoyé: {state_file}")
                cleaned += 1
            except Exception as e:
                print(f"⚠️ Erreur nettoyage {state_file}: {e}")
    
    if cleaned > 0:
        print(f"✅ {cleaned} état(s) paper nettoyé(s)")
    else:
        print("ℹ️ Aucun état paper à nettoyer")

# Vider le terminal au démarrage (seulement en local)
if not os.environ.get('PORT'):
    os.system('cls' if os.name == 'nt' else 'clear')

# Vider les caches Python
clear_python_cache()

# Charger les variables d'environnement
def main():
    """Point d'entrée principal"""
    global bot_instance, bot_status
    print("🚀 Démarrage du bot TETANIS...")
    
    # Forcer le rechargement de la configuration
    load_dotenv(override=True)
    
    # Import du bot (après vérification config)
    try:
        from core.binance_spot_bot import BinanceSpotBot
    except ImportError as e:
        print(f"❌ Erreur import: {e}")
        print("📝 Vérifiez que tous les modules sont installés: pip install -r requirements.txt")
        bot_status = {"status": "error", "message": f"Import error: {e}"}
        return
    
    # Récupération configuration
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')
    testnet = os.getenv('TESTNET', 'False').lower() == 'true'
    
    # Démarrage du bot
    try:
        bot_instance = BinanceSpotBot(api_key, api_secret, testnet)
        bot_instance.run()
    except KeyboardInterrupt:
        print("\n🛑 Arrêt du bot...")
        bot_status = {"status": "stopped", "message": "Bot stopped by user"}
    except Exception as e:
        print(f"❌ Erreur: {e}")
        bot_status = {"status": "error", "message": str(e)}

# Flask app pour Render
app = Flask(__name__)
bot_instance = None
bot_status = {"status": "starting", "message": "Bot initializing..."}

@app.route('/')
def home():
    return jsonify({
        "service": "Binance Bot TETANIS v2",
        "status": bot_status["status"],
        "message": bot_status["message"]
    })

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "bot": bot_status})

def run_bot():
    """Lance le bot en arrière-plan"""
    global bot_instance, bot_status
    import time
    time.sleep(2)  # Attendre que Flask soit prêt
    try:
        bot_status = {"status": "running", "message": "Bot is active"}
        main()
    except Exception as e:
        bot_status = {"status": "error", "message": str(e)}

if __name__ == "__main__":
    # Démarrer le bot en thread non-daemon pour Render
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.start()
    
    # Démarrer Flask
    port = int(os.environ.get('PORT', 10000))
    host = '0.0.0.0' if os.environ.get('PORT') else '127.0.0.1'
    app.run(host=host, port=port, debug=False, threaded=True)