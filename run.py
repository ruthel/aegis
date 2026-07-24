#!/usr/bin/env python3
"""
Point d'entrée principal pour le bot de trading Binance
Démarrage sécurisé avec vérifications et gestion d'erreurs
"""
import sys
import os
from datetime import datetime

# Forcer stdout/stderr unbuffered pour que les logs arrivent en temps réel
os.environ['PYTHONUNBUFFERED'] = '1'

from dotenv import load_dotenv

def clean_bot_states():
    """Historique: les états runtime sont maintenant dans SQLite."""
    return
    

# Vider le terminal au démarrage (seulement si terminal disponible)
if sys.stdout and sys.stdout.isatty():
    os.system('cls' if os.name == 'nt' else 'clear')

# Forcer UTF-8 + line-buffered si pas de terminal (mode background)
if not sys.stdout or not sys.stdout.isatty():
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True) if sys.stdout else open(os.devnull, 'w')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True) if sys.stderr else open(os.devnull, 'w')

# Charger les variables d'environnement
def main():
    """Point d'entrée principal"""
    import os as _os
    _os.makedirs('data', exist_ok=True)

    from core.ml_live_logger import MLLiveLogger
    process_logger = MLLiveLogger(data_dir='data', sqlite_file=_os.getenv('ML_LIVE_SQLITE_FILE', 'data/aegis_db.sqlite3'))

    # Vérification de sécurité : s'assurer qu'aucune autre instance du bot ne tourne
    tracked = process_logger.get_bot_process_state()
    old_pid = tracked.get('pid')
    if old_pid:
        try:
            if old_pid != _os.getpid():
                try:
                    # check si le processus est actif
                    _os.kill(old_pid, 0)
                    print(f"❌ ERREUR: Une autre instance du bot Aegis est déjà en cours d'exécution (PID {old_pid}).")
                    print("   Veuillez arrêter l'autre instance depuis le dashboard avant de démarrer.")
                    process_logger.close()
                    sys.exit(1)
                except (ProcessLookupError, OSError):
                    process_logger.clear_bot_process_state()
        except Exception:
            pass

    print("🚀 Démarrage du bot Aegis...")
    process_logger.set_bot_process_state({
        'pid': _os.getpid(),
        'started_at': datetime.now().isoformat(),
        'command': ' '.join(sys.argv) or 'run.py',
    })
    
    # Charger la configuration locale en dernier pour les secrets non versionnés.
    load_dotenv(override=True)
    load_dotenv('.env.local', override=True)
    load_dotenv('.env.dashboard', override=True)
    
    # Import du bot (après vérification config)
    try:
        from core.trading_bot import TradingBot
    except ImportError as e:
        print(f"❌ Erreur import: {e}")
        print("📝 Vérifiez que tous les modules sont installés: pip install -r requirements.txt")
        sys.exit(1)
    
    # Récupération configuration selon exchange
    exchange = os.getenv('EXCHANGE', 'binance').lower()
    
    if exchange == 'kraken':
        api_key = os.getenv('KRAKEN_API_KEY')
        api_secret = os.getenv('KRAKEN_API_SECRET')
    else:
        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')
    
    testnet = os.getenv('TESTNET', 'False').lower() == 'true'
    
    # Démarrage du bot
    try:
        bot = TradingBot(api_key, api_secret, testnet)
        bot.run()
    except KeyboardInterrupt:
        print("\n🛑 Arrêt du bot...")
        process_logger.clear_bot_process_state()
        process_logger.close()
        sys.exit(0)
    except Exception as e:
        print(f"❌ Erreur: {e}")
        process_logger.clear_bot_process_state()
        process_logger.close()
        sys.exit(1)
    finally:
        process_logger.close()

if __name__ == "__main__":
    main()
