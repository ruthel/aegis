#!/usr/bin/env python3
"""
Point d'entrée principal pour le bot de trading Binance
"""
import subprocess
import sys
import os

def main():
    """Lance le script de déploiement"""
    script_path = os.path.join("scripts", "deploy.py")
    subprocess.run([sys.executable, script_path])

if __name__ == "__main__":
    main()