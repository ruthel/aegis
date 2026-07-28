"""
Gestionnaire d'événements macro - Détection automatique via données crypto
"""
import time
import os
import json
import sqlite3
from datetime import datetime
from core.managers.notification import NotificationManager

class MacroEventManager:
    """Détecte et gère les événements macro via analyse des patterns crypto"""
    _active_events_by_type = {}
    
    def __init__(self):
        self.current_event = None
        self.current_event_info = None
        self.event_start_time = None
        self.last_detection_time = 0
        
        # Configuration des événements et leurs ajustements
        self.event_adjustments = {
            'FED_MEETING': {
                'score_bonus': 15,
                'threshold_reduction': 10, 
                'duration_hours': 48,
                'description': 'Réunion FED - Attente décision taux'
            },
            'INFLATION_DATA': {
                'score_bonus': 10,
                'threshold_reduction': 8,
                'duration_hours': 24,
                'description': 'Publication données inflation'
            },
            'MARKET_UNCERTAINTY': {
                'score_bonus': 8,
                'threshold_reduction': 6,
                'duration_hours': 12,
                'description': 'Incertitude marché généralisée'
            }
        }

        # Liste des dates macro-économiques majeures pour 2026 (UTC ISO 8601)
        self.macro_calendar_2026 = [
            # Réunions FED (FOMC Decisions) - 19:00 UTC ou 18:00 UTC (14:00 heure de New York)
            {"date": "2026-01-28T19:00:00", "event": "FED_MEETING", "description": "Décision taux d'intérêt FOMC (FED)"},
            {"date": "2026-03-18T18:00:00", "event": "FED_MEETING", "description": "Décision taux d'intérêt FOMC (FED)"},
            {"date": "2026-04-29T18:00:00", "event": "FED_MEETING", "description": "Décision taux d'intérêt FOMC (FED)"},
            {"date": "2026-06-17T18:00:00", "event": "FED_MEETING", "description": "Décision taux d'intérêt FOMC (FED)"},
            {"date": "2026-07-29T18:00:00", "event": "FED_MEETING", "description": "Décision taux d'intérêt FOMC (FED)"},
            {"date": "2026-09-16T18:00:00", "event": "FED_MEETING", "description": "Décision taux d'intérêt FOMC (FED)"},
            {"date": "2026-10-28T18:00:00", "event": "FED_MEETING", "description": "Décision taux d'intérêt FOMC (FED)"},
            {"date": "2026-12-09T19:00:00", "event": "FED_MEETING", "description": "Décision taux d'intérêt FOMC (FED)"},

            # Données Inflation US (CPI Release) - 13:30 UTC ou 12:30 UTC (08:30 heure de New York)
            {"date": "2026-01-13T13:30:00", "event": "INFLATION_DATA", "description": "Publication indice des prix CPI (USA)"},
            {"date": "2026-02-13T13:30:00", "event": "INFLATION_DATA", "description": "Publication indice des prix CPI (USA)"},
            {"date": "2026-03-11T13:30:00", "event": "INFLATION_DATA", "description": "Publication indice des prix CPI (USA)"},
            {"date": "2026-04-10T12:30:00", "event": "INFLATION_DATA", "description": "Publication indice des prix CPI (USA)"},
            {"date": "2026-05-12T12:30:00", "event": "INFLATION_DATA", "description": "Publication indice des prix CPI (USA)"},
            {"date": "2026-06-10T12:30:00", "event": "INFLATION_DATA", "description": "Publication indice des prix CPI (USA)"},
            {"date": "2026-07-14T12:30:00", "event": "INFLATION_DATA", "description": "Publication indice des prix CPI (USA)"},
            {"date": "2026-08-12T12:30:00", "event": "INFLATION_DATA", "description": "Publication indice des prix CPI (USA)"},
            {"date": "2026-09-11T12:30:00", "event": "INFLATION_DATA", "description": "Publication indice des prix CPI (USA)"},
            {"date": "2026-10-14T12:30:00", "event": "INFLATION_DATA", "description": "Publication indice des prix CPI (USA)"},
            {"date": "2026-11-10T13:30:00", "event": "INFLATION_DATA", "description": "Publication indice des prix CPI (USA)"},
            {"date": "2026-12-10T13:30:00", "event": "INFLATION_DATA", "description": "Publication indice des prix CPI (USA)"},
        ]
        self._hydrate_active_event_from_store()

    def _is_same_event_active(self, event_type, now=None):
        """Retourne True si le même événement est déjà actif et non expiré."""
        if not event_type:
            return False
        now = now or time.time()
        active = self._active_events_by_type.get(event_type)
        if active:
            started_at = float(active.get('started_at') or 0)
            duration_hours = float(active.get('duration_hours') or 0)
            if started_at and duration_hours and now < started_at + duration_hours * 3600:
                return True
            self._active_events_by_type.pop(event_type, None)

        if self.current_event == event_type and self.event_start_time:
            duration_hours = float(self.get_adjustments(event_type).get('duration_hours') or 0)
            if duration_hours and now < float(self.event_start_time) + duration_hours * 3600:
                return True
        persistent = self._read_persistent_active_event(event_type)
        if persistent:
            started_at = float(persistent.get('started_at') or 0)
            duration_hours = float(persistent.get('duration_hours') or 0)
            if started_at and duration_hours and now < started_at + duration_hours * 3600:
                self._active_events_by_type[event_type] = persistent
                return True
            self._clear_persistent_active_event(event_type)
        return False

    def _mark_event_active(self, event_type, started_at, event_info):
        duration_hours = float((event_info or {}).get('duration_hours') or 0)
        payload = {
            'started_at': float(started_at or time.time()),
            'duration_hours': duration_hours,
        }
        self._active_events_by_type[event_type] = payload
        self._write_persistent_active_event(event_type, payload)

    def _event_state_key(self, event_type):
        return f"macro_active_event:{event_type}"

    def _with_app_state(self, callback):
        db_path = os.getenv('AEGIS_DB_PATH', 'data/aegis_db.sqlite3')
        try:
            with sqlite3.connect(db_path, timeout=5) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS bot_app_state (
                        state_key TEXT PRIMARY KEY,
                        state_value TEXT,
                        created_at TEXT,
                        updated_at TEXT
                    )
                """)
                return callback(conn)
        except Exception:
            return None

    def _read_persistent_active_event(self, event_type):
        def read(conn):
            row = conn.execute(
                "SELECT state_value FROM bot_app_state WHERE state_key=?",
                (self._event_state_key(event_type),)
            ).fetchone()
            if not row or not row[0]:
                return None
            return json.loads(row[0])
        return self._with_app_state(read)

    def _read_any_persistent_active_event(self):
        def read(conn):
            rows = conn.execute(
                "SELECT state_key, state_value FROM bot_app_state WHERE state_key LIKE 'macro_active_event:%'"
            ).fetchall()
            events = []
            for key, value in rows:
                try:
                    event_type = key.split(':', 1)[1]
                    payload = json.loads(value or '{}')
                    events.append((event_type, payload))
                except Exception:
                    continue
            return events
        return self._with_app_state(read) or []

    def _hydrate_active_event_from_store(self):
        now = time.time()
        for event_type, payload in self._read_any_persistent_active_event():
            started_at = float(payload.get('started_at') or 0)
            duration_hours = float(payload.get('duration_hours') or 0)
            if not started_at or not duration_hours:
                self._clear_persistent_active_event(event_type)
                continue
            if now >= started_at + duration_hours * 3600:
                self._clear_persistent_active_event(event_type)
                continue

            self._active_events_by_type[event_type] = payload
            self.current_event = event_type
            self.current_event_info = self.event_adjustments.get(event_type)
            self.event_start_time = started_at
            break

    def _write_persistent_active_event(self, event_type, payload):
        def write(conn):
            stamp = datetime.now().isoformat()
            conn.execute(
                """
                INSERT INTO bot_app_state (state_key, state_value, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(state_key) DO UPDATE SET
                    state_value = excluded.state_value,
                    updated_at = excluded.updated_at
                """,
                (self._event_state_key(event_type), json.dumps(payload), stamp, stamp)
            )
            return True
        return self._with_app_state(write)

    def _clear_persistent_active_event(self, event_type):
        def clear(conn):
            conn.execute("DELETE FROM bot_app_state WHERE state_key=?", (self._event_state_key(event_type),))
            return True
        return self._with_app_state(clear)

    def _format_macro_event_line(self, event_type, event_info, notification_status=None, calendar=False):
        """Construit une ligne unique pour éviter les blocs multi-lignes dans bot.log."""
        prefix = "🚨 MACRO EVENT CALENDRIER DÉTECTÉ" if calendar else "🚨 MACRO EVENT DÉTECTÉ"
        parts = [
            f"{prefix}: {event_type}",
            f"📋 {event_info.get('description', event_type)}",
            f"🎁 Bonus score: +{event_info.get('score_bonus', 0)}",
            f"🎯 Réduction seuil: -{event_info.get('threshold_reduction', 0)}",
            f"⏰ Durée estimée: {event_info.get('duration_hours', 0)}h",
        ]
        if notification_status:
            parts.append(notification_status)
        parts.append(f"🎯 Ajustement macro: -{event_info.get('threshold_reduction', 0)} (Événement: {event_type})")
        return " | ".join(parts)
    
    def _check_calendar_events(self):
        """Vérifie si un événement du calendrier 2026 est imminent (2h) ou en cours"""
        from datetime import timezone
        now = time.time()
        
        for item in self.macro_calendar_2026:
            try:
                # Extraire le timestamp de l'événement (supposé en UTC)
                event_dt = datetime.fromisoformat(item['date']).replace(tzinfo=timezone.utc)
                event_ts = event_dt.timestamp()
                
                # Durée de l'événement en secondes
                adjustments = self.event_adjustments.get(item['event'], {})
                duration_seconds = adjustments.get('duration_hours', 24) * 3600
                
                # 1. Événement IMMINENT (dans les 2 heures à venir)
                if event_ts - 7200 <= now < event_ts:
                    imminent_info = adjustments.copy()
                    imminent_info['description'] = f"IMMINENT: {item['description']}"
                    return item['event'], imminent_info, event_ts
                    
                # 2. Événement EN COURS (depuis l'heure exacte et pendant toute sa durée)
                elif event_ts <= now < event_ts + duration_seconds:
                    return item['event'], adjustments, event_ts
            except Exception as e:
                print(f"⚠️ Erreur parsing date calendrier macro: {e}")
                
        return None, None, None

    def detect_macro_event(self, market_conditions):
        """Détecte événement macro via calendrier ou patterns crypto anormaux"""
        
        # A. Vérifier d'abord si l'événement actuel (calendrier ou pattern) a expiré
        if self.current_event and self.event_start_time:
            duration_hours = self.get_adjustments()['duration_hours']
            elapsed_hours = (time.time() - self.event_start_time) / 3600
            
            if elapsed_hours > duration_hours:
                print(f"✅ FIN MACRO EVENT: {self.current_event} (durée: {elapsed_hours:.1f}h)")
                
                # Notification fin d'événement directe
                try:
                    notifier = NotificationManager()
                    if notifier.enabled:
                        notifier.notify_macro_event_end(self.current_event, elapsed_hours)
                        print(f"   📨 Notification fin envoyée")
                except Exception as e:
                    print(f"   ⚠️ Erreur notification fin: {e}")
                
                self._active_events_by_type.pop(self.current_event, None)
                self._clear_persistent_active_event(self.current_event)
                self.current_event = None
                self.current_event_info = None
                self.event_start_time = None

        # B. Vérification PRIORITAIRE du calendrier macro-économique 2026
        cal_event, cal_info, cal_start_ts = self._check_calendar_events()
        if cal_event:
            if self._is_same_event_active(cal_event):
                self.current_event = cal_event
                self.current_event_info = cal_info
                if not self.event_start_time:
                    self.event_start_time = cal_start_ts
                return self.current_event

            # Si c'est un nouvel événement macro du calendrier
            if self.current_event != cal_event:
                self.current_event = cal_event
                self.current_event_info = cal_info
                self.event_start_time = cal_start_ts
                self.last_detection_time = time.time()
                self._mark_event_active(cal_event, cal_start_ts, cal_info)
                
                # Notification Telegram directe
                notification_status = None
                try:
                    notifier = NotificationManager()
                    if notifier.enabled:
                        notifier.notify_macro_event_start(cal_event, cal_info)
                        notification_status = "📨 Notification Telegram envoyée"
                except Exception as e:
                    notification_status = f"⚠️ Erreur notification: {e}"
                print(self._format_macro_event_line(cal_event, cal_info, notification_status, calendar=True))
            return self.current_event

        # C. Repli sur la détection automatique par patterns
        if not market_conditions:
            return self.current_event
        
        # Éviter détections de patterns trop fréquentes (1h minimum)
        if time.time() - self.last_detection_time < 3600:
            return self.current_event
        
        avg_vol_ratio = market_conditions.get('avg_volume_ratio', 1.0)
        avg_volatility = market_conditions.get('avg_volatility', 2.0)
        
        very_low_volume = avg_vol_ratio < 0.5
        low_volume = avg_vol_ratio < 0.7
        very_low_volatility = avg_volatility < 1.0
        low_volatility = avg_volatility < 1.5
        
        if very_low_volume and very_low_volatility:
            detected_event = 'FED_MEETING'
        elif low_volume and low_volatility:
            detected_event = 'MARKET_UNCERTAINTY'
        else:
            detected_event = None
        
        if detected_event and not self.current_event:
            if self._is_same_event_active(detected_event):
                self.current_event = detected_event
                self.current_event_info = self.event_adjustments[detected_event]
                active = self._active_events_by_type.get(detected_event, {})
                self.event_start_time = active.get('started_at') or time.time()
                return self.current_event

            self.current_event = detected_event
            self.event_start_time = time.time()
            self.last_detection_time = time.time()
            
            event_info = self.event_adjustments[detected_event]
            self.current_event_info = event_info
            self._mark_event_active(detected_event, self.event_start_time, event_info)
            
            notification_status = None
            try:
                notifier = NotificationManager()
                if notifier.enabled:
                    notifier.notify_macro_event_start(detected_event, event_info)
                    notification_status = "📨 Notification Telegram envoyée"
            except Exception as e:
                notification_status = f"⚠️ Erreur notification: {e}"
            print(self._format_macro_event_line(detected_event, event_info, notification_status))
        
        return self.current_event
    
    def get_adjustments(self, event_type=None):
        """Retourne ajustements pour événement actuel ou spécifié"""
        event = event_type or self.current_event
        # Retourner l'info cache dynamique si elle correspond à l'événement recherché
        if not event_type and self.current_event_info:
            return self.current_event_info
        return self.event_adjustments.get(event, {
            'score_bonus': 0,
            'threshold_reduction': 0,
            'duration_hours': 0,
            'description': 'Aucun événement'
        })
    
    def get_event_status(self):
        """Retourne statut détaillé de l'événement actuel"""
        if not self.current_event:
            return None
        
        adjustments = self.get_adjustments()
        elapsed_hours = (time.time() - self.event_start_time) / 3600
        remaining_hours = max(0, adjustments['duration_hours'] - elapsed_hours)
        
        return {
            'event': self.current_event,
            'description': adjustments['description'],
            'score_bonus': adjustments['score_bonus'],
            'threshold_reduction': adjustments['threshold_reduction'],
            'elapsed_hours': elapsed_hours,
            'remaining_hours': remaining_hours,
            'progress_pct': min(100, (elapsed_hours / adjustments['duration_hours']) * 100)
        }
    
    def force_event(self, event_type, duration_hours=None):
        """Force un événement macro manuellement"""
        if event_type not in self.event_adjustments:
            print(f"❌ Événement inconnu: {event_type}")
            return False
        
        self.current_event = event_type
        self.event_start_time = time.time()
        
        if duration_hours:
            self.event_adjustments[event_type]['duration_hours'] = duration_hours
        
        event_info = self.event_adjustments[event_type]
        self.current_event_info = event_info
        self._mark_event_active(event_type, self.event_start_time, event_info)
        
        print(f"🔧 MACRO EVENT FORCÉ: {event_type}")
        print(f"   📋 {event_info['description']}")
        print(f"   ⏰ Durée: {event_info['duration_hours']}h")
        
        return True
    
    def clear_event(self):
        """Annule l'événement macro actuel"""
        if self.current_event:
            print(f"🔄 ANNULATION MACRO EVENT: {self.current_event}")
            self._active_events_by_type.pop(self.current_event, None)
            self._clear_persistent_active_event(self.current_event)
            self.current_event = None
            self.current_event_info = None
            self.event_start_time = None
            return True
        return False
