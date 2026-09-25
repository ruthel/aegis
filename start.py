#!/usr/bin/env python3
"""Point d'entrée unique Aegis — lance le ui et le bot automatiquement."""
import os
import sys
import shutil
import subprocess
import warnings
from pathlib import Path

warnings.filterwarnings(
    "ignore",
    message=".*sklearn.utils.parallel.delayed.*",
    category=UserWarning,
    module="sklearn.utils.parallel"
)

from dotenv import load_dotenv
load_dotenv('.env', override=True)

ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT / 'ui' / 'app'
FRONTEND_SRC = FRONTEND_DIR / 'src'
FRONTEND_DIST = ROOT / 'ui' / 'public' / 'spa'
FRONTEND_INDEX = FRONTEND_DIST / 'index.html'

def _latest_mtime(path: Path) -> float:
    if not path.exists():
        return 0.0
    if path.is_file():
        return path.stat().st_mtime
    latest = 0.0
    for item in path.rglob('*'):
        try:
            if item.is_file():
                latest = max(latest, item.stat().st_mtime)
        except OSError:
            pass
    return latest

def frontend_needs_build() -> bool:
    if not FRONTEND_INDEX.exists():
        return True

    build_mtime = FRONTEND_INDEX.stat().st_mtime
    watched = [
        FRONTEND_SRC,
        FRONTEND_DIR / 'index.html',
        FRONTEND_DIR / 'package.json',
        FRONTEND_DIR / 'pnpm-lock.yaml',
        FRONTEND_DIR / 'vite.config.ts',
        FRONTEND_DIR / 'tsconfig.json',
        FRONTEND_DIR / 'tsconfig.app.json',
    ]
    return any(_latest_mtime(path) > build_mtime for path in watched)

def ensure_frontend_built():
    if not frontend_needs_build():
        print("🟢 Frontend → Déjà à jour")
        return

    pnpm = shutil.which('pnpm')
    if not pnpm:
        print("❌ Frontend → pnpm introuvable. Installez pnpm puis relancez start.py.")
        sys.exit(1)

    node_modules = FRONTEND_DIR / 'node_modules'
    if not node_modules.exists():
        print("📦 Frontend → Dépendances absentes, installation...")
        try:
            subprocess.run(
                [pnpm, 'install', '--frozen-lockfile'],
                cwd=FRONTEND_DIR,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            print(f"❌ Frontend → Installation échouée (code {exc.returncode})")
            sys.exit(exc.returncode or 1)

    print("🔨 Frontend → Compilation...")
    try:
        subprocess.run(
            [pnpm, 'build'],
            cwd=FRONTEND_DIR,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"❌ Frontend → Build échoué (code {exc.returncode})")
        sys.exit(exc.returncode or 1)

    print("✅ Frontend → Build terminé")

ensure_frontend_built()

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
