#!/usr/bin/env python3
"""Script d'arrêt propre Aegis — arrête l'UI et le Bot Engine en arrière-plan."""
import os
import sys
import subprocess

def stop_all():
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass
            
    # Étape 1 : Sauvegarde automatique de la BD avant arrêt
    try:
        sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
        from core.ml_live_logger import MLLiveLogger
        logger = MLLiveLogger()
        backup_path = logger.backup_db()
        if backup_path:
            print(f"💾 Backup SQLite créé: {backup_path}")
    except Exception as e:
        print(f"⚠️ Backup omis avant arrêt: {e}")

    print("🛑 Arrêt des processus Aegis (UI + Bot Engine)...")
    ps_script = """
    Get-CimInstance Win32_Process | Where-Object { 
        ($_.CommandLine -like "*start.py*" -or $_.CommandLine -like "*run.py*") -and $_.ProcessId -ne $PID 
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    """
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True)
        print("✅ Tous les processus Aegis ont été arrêtés avec succès !")
    except Exception as e:
        print(f"⚠️ Erreur lors de l'arrêt des processus: {e}")

if __name__ == '__main__':
    stop_all()
