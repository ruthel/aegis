#!/usr/bin/env python3
"""
Point d'entrée principal pour le bot de trading Binance
Démarrage sécurisé avec vérifications et gestion d'erreurs
"""
import sys
import os
import shutil
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

# Vider le terminal au démarrage
os.system('cls' if os.name == 'nt' else 'clear')

# Vider les caches Python
clear_python_cache()

# Charger les variables d'environnement
def main():
    """Point d'entrée principal"""
    print("🚀 Démarrage du bot TETANIS...")
    
    # Forcer le rechargement de la configuration
    load_dotenv(override=True)
    
    # Vérification mode
    testnet = os.getenv('TESTNET', 'False').lower() == 'true'
    if testnet:
        print("⚠️ MODE TESTNET DÉTECTÉ")
    else:
        print("💰 MODE MAINNET ACTIVÉ")
    
    # Vérification configuration
    
    # Import du bot (après vérification config)
    try:
        from core.binance_spot_bot import BinanceSpotBot
    except ImportError as e:
        print(f"❌ Erreur import: {e}")
        print("📝 Vérifiez que tous les modules sont installés: pip install -r requirements.txt")
        sys.exit(1)
    
    # Récupération configuration
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')
    testnet = os.getenv('TESTNET', 'False').lower() == 'true'
    
    print(f"🔑 API Key: {api_key[:10]}...")
    print(f"🌍 Mode: {'TESTNET' if testnet else 'MAINNET'}")
    
    # Démarrage du bot
    try:
        bot = BinanceSpotBot(api_key, api_secret, testnet)
        bot.run()
    except KeyboardInterrupt:
        print("\n🛑 Arrêt du bot...")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Erreur: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()