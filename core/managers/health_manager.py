"""
HealthManager - Phase 8 : Health checks internes et surveillance de production
Vérifie la santé des composants clés du bot :
1. Base de données SQLite (connexion, réactivité, taille WAL)
2. WebSocket (connexion active, réception de données)
3. Exchange API (connectivité et clés)
4. Moteur ML (modèle chargé et fonctionnel)
5. Boucle d'exécution du bot (activité récente)
"""

import os
import time
import sqlite3
from html import escape
from datetime import datetime

class HealthManager:
    """Gestionnaire de bilans de santé (Health Checks) du bot Aegis."""

    def __init__(self, bot=None):
        self.bot = bot
        self.last_check_timestamp = 0
        self.last_results = {}

    def set_bot(self, bot):
        self.bot = bot

    def check_database(self) -> dict:
        """Vérifie la réactivité de la base SQLite et la santé des fichiers."""
        try:
            sqlite_file = os.getenv('ML_LIVE_SQLITE_FILE', 'data/aegis_db.sqlite3')
            if not os.path.exists(sqlite_file):
                return {'status': 'WARN', 'message': 'Fichier DB non trouvé encore', 'details': {}}

            start_t = time.time()
            conn = sqlite3.connect(sqlite_file, timeout=5.0)
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            
            # Vérifier mode journal & WAL size
            cur.execute("PRAGMA journal_mode")
            jmode_res = cur.fetchone()
            jmode = jmode_res[0] if jmode_res else 'unknown'
            conn.close()

            latency_ms = (time.time() - start_t) * 1000.0

            wal_size_mb = 0.0
            wal_file = f"{sqlite_file}-wal"
            if os.path.exists(wal_file):
                wal_size_mb = round(os.path.getsize(wal_file) / (1024 * 1024), 2)

            status = 'OK'
            # Seuils tolérants: SQLite peut avoir des pics transitoires (WAL, écritures concurrentes)
            db_warn_ms = float(os.getenv('HEALTH_DB_WARN_MS', '3000'))
            db_warn_wal_mb = float(os.getenv('HEALTH_DB_WARN_WAL_MB', '100'))
            if latency_ms > db_warn_ms or wal_size_mb > db_warn_wal_mb:
                status = 'WARN'

            return {
                'status': status,
                'message': f"DB réactive ({latency_ms:.1f}ms)",
                'details': {
                    'latency_ms': round(latency_ms, 2),
                    'journal_mode': jmode,
                    'wal_size_mb': wal_size_mb
                }
            }
        except Exception as e:
            return {'status': 'CRITICAL', 'message': f"Erreur DB: {e}", 'details': {}}

    def check_websocket(self) -> dict:
        """Vérifie le statut de la connexion WebSocket."""
        if not self.bot or not hasattr(self.bot, 'websocket') or not self.bot.websocket:
            return {'status': 'INFO', 'message': 'WebSocket non configuré', 'details': {}}

        try:
            ws = self.bot.websocket
            is_alive = hasattr(ws, 'is_alive') and ws.is_alive()
            is_connected = getattr(ws, 'connected', True) or (callable(getattr(ws, 'is_connected', None)) and ws.is_connected())
            
            if is_alive or is_connected:
                return {'status': 'OK', 'message': 'WebSocket connecté et actif', 'details': {'alive': True}}
            else:
                return {'status': 'WARN', 'message': 'WebSocket déconnecté ou inactif', 'details': {'alive': False}}
        except Exception as e:
            return {'status': 'WARN', 'message': f"Incapacité de vérifier WS: {e}", 'details': {}}

    def check_exchange(self) -> dict:
        """Vérifie la connexion et l'accès à l'exchange."""
        if not self.bot:
            return {'status': 'UNKNOWN', 'message': 'Bot non rattaché', 'details': {}}

        if getattr(self.bot, 'paper_trading', True):
            return {'status': 'OK', 'message': 'Mode Paper (Exchange simulé OK)', 'details': {'paper': True}}

        try:
            if hasattr(self.bot, 'exchange') and self.bot.exchange:
                return {'status': 'OK', 'message': 'Exchange API configuré', 'details': {'exchange': getattr(self.bot.exchange, 'id', 'unknown')}}
            else:
                return {'status': 'CRITICAL', 'message': 'Client Exchange non initialisé', 'details': {}}
        except Exception as e:
            return {'status': 'CRITICAL', 'message': f"Erreur Exchange: {e}", 'details': {}}

    def check_ml_engine(self) -> dict:
        """Vérifie le statut du moteur ML."""
        if not self.bot or not hasattr(self.bot, 'ml_engine') or not self.bot.ml_engine:
            return {'status': 'WARN', 'message': 'Moteur ML non initialisé', 'details': {}}

        try:
            engine = self.bot.ml_engine
            model_path = getattr(engine, 'model_path', os.path.join(getattr(engine, 'model_dir', 'data'), 'aegis_model.joblib'))
            has_model_object = getattr(engine, 'model', None) is not None
            is_trained = bool(getattr(engine, 'is_trained', False))
            has_model_file = bool(model_path and os.path.exists(model_path))
            feature_count = None
            if has_model_object and hasattr(engine.model, 'n_features_in_'):
                feature_count = int(engine.model.n_features_in_)
            
            if is_trained and has_model_object:
                detail = f" ({feature_count} features)" if feature_count else ""
                return {
                    'status': 'OK',
                    'message': f"Champion ML actif{detail}",
                    'details': {
                        'champion': True,
                        'is_trained': True,
                        'model_path': model_path,
                        'feature_count': feature_count,
                    }
                }
            if has_model_file:
                return {
                    'status': 'WARN',
                    'message': 'Fichier Champion présent, mais modèle non chargé',
                    'details': {'champion': False, 'is_trained': is_trained, 'model_path': model_path}
                }
            return {
                'status': 'WARN',
                'message': 'Aucun fichier Champion ML trouvé',
                'details': {'champion': False, 'is_trained': is_trained, 'model_path': model_path}
            }
        except Exception as e:
            return {'status': 'WARN', 'message': f"Erreur check ML: {e}", 'details': {}}

    def check_bot_loop(self) -> dict:
        """Vérifie que la boucle principale du bot n'est pas bloquée."""
        if not self.bot:
            return {'status': 'UNKNOWN', 'message': 'Bot non rattaché', 'details': {}}

        try:
            last_activity = getattr(self.bot, 'last_analysis_timestamp', 0) or getattr(self.bot, '_last_loop_time', 0)
            if last_activity == 0:
                return {'status': 'OK', 'message': 'Bot démarré, première itération en cours', 'details': {}}

            elapsed = time.time() - last_activity
            if elapsed < 300:
                return {'status': 'OK', 'message': f"Dernière boucle il y a {int(elapsed)}s", 'details': {'elapsed_s': int(elapsed)}}
            else:
                return {'status': 'WARN', 'message': f"Boucle inactive depuis {int(elapsed)}s", 'details': {'elapsed_s': int(elapsed)}}
        except Exception as e:
            return {'status': 'WARN', 'message': f"Erreur check boucle: {e}", 'details': {}}

    def run_checks(self) -> dict:
        """Exécute tous les health checks et retourne un rapport complet."""
        results = {
            'timestamp': datetime.now().isoformat(),
            'database': self.check_database(),
            'websocket': self.check_websocket(),
            'exchange': self.check_exchange(),
            'ml_engine': self.check_ml_engine(),
            'bot_loop': self.check_bot_loop(),
        }

        statuses = [v['status'] for k, v in results.items() if isinstance(v, dict) and 'status' in v]
        if 'CRITICAL' in statuses:
            global_status = 'CRITICAL'
        elif 'WARN' in statuses:
            global_status = 'WARN'
        else:
            global_status = 'OK'

        results['global_status'] = global_status
        self.last_results = results
        self.last_check_timestamp = time.time()

        return results

    def get_summary_text(self, results=None) -> str:
        """Retourne un résumé formaté des health checks pour Telegram ou logs."""
        results = results or self.run_checks()
        icon = "✅" if results['global_status'] == 'OK' else "⚠️" if results['global_status'] == 'WARN' else "🚨"
        lines = [
            f"{icon} <b>AEGIS HEALTH CHECK</b>",
            f"Statut global : <b>{escape(str(results['global_status']))}</b>",
            ""
        ]

        for comp in ['database', 'websocket', 'exchange', 'ml_engine', 'bot_loop']:
            if comp in results:
                c_data = results[comp]
                st = c_data.get('status', 'UNK')
                msg = c_data.get('message', '')
                c_icon = "🟢" if st == 'OK' else "🟡" if st == 'WARN' else "🔴" if st == 'CRITICAL' else "🔵"
                label = comp.upper().replace('_', ' ')
                lines.append(f"{c_icon} <b>{escape(label)}</b> · {escape(str(st))}")
                lines.append(f"   {escape(str(msg))}")

        return "\n".join(lines)
