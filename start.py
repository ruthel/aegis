#!/usr/bin/env python3
"""Point d'entrée unique Aegis — lance le dashboard, contrôle le bot depuis l'UI."""
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
load_dotenv('.env.dashboard', override=True)

port = int(os.getenv('DASHBOARD_PORT', '8080'))
print(f"🚀 Aegis Dashboard → http://127.0.0.1:{port}")
print(f"   Cliquez ▶ Démarrer dans l'interface pour lancer le bot")
print(f"   Ctrl+C pour tout arrêter\n")

from dashboard.app import app
app.run(host='127.0.0.1', port=port, debug=False)
