#!/usr/bin/env python3
"""Point d'entrée unique Aegis — lance le ui et le bot automatiquement."""
import os
import sys
import warnings

warnings.filterwarnings(
    "ignore",
    message=".*sklearn.utils.parallel.delayed.*",
    category=UserWarning,
    module="sklearn.utils.parallel"
)

from dotenv import load_dotenv
load_dotenv(override=True)
load_dotenv('.env.local', override=True)
load_dotenv('.env.ui', override=True)

port = int(os.getenv('DASHBOARD_PORT', '8080'))
auto_start = os.getenv('AUTO_START_BOT', 'True').lower() in ('true', '1', 'yes', 'y')

from ui.server import app, start_bot_process, bot_is_running

print(f"🚀 Aegis UI → http://127.0.0.1:{port}")

if auto_start:
    if not bot_is_running():
        print(f"🤖 Bot Engine → Démarrage automatique du serveur bot...")
        try:
            res = start_bot_process()
            if res.get('started'):
                print(f"✅ Bot Engine démarré avec succès (PID: {res.get('pid')}) !")
            else:
                print(f"🟢 Bot Engine déjà en cours d'exécution.")
        except Exception as e:
            print(f"⚠️ Erreur lors du démarrage automatique: {e}")
    else:
        print(f"🟢 Bot Engine → Déjà en cours d'exécution.")
else:
    print(f"   Cliquez ▶ Démarrer dans l'interface pour lancer le bot")

print(f"   Ctrl+C pour tout arrêter\n")

app.run(host='127.0.0.1', port=port, debug=False)
