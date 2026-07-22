"""
Gestionnaire d'événements macro - Détection automatique via données crypto
"""
import time
import os
from datetime import datetime
from core.managers.notification import NotificationManager

class MacroEventManager:
    """Détecte et gère les événements macro via analyse des patterns crypto"""
    
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
                
                self.current_event = None
                self.current_event_info = None
                self.event_start_time = None

        # B. Vérification PRIORITAIRE du calendrier macro-économique 2026
        cal_event, cal_info, cal_start_ts = self._check_calendar_events()
        if cal_event:
            # Si c'est un nouvel événement macro du calendrier
            if self.current_event != cal_event:
                self.current_event = cal_event
                self.current_event_info = cal_info
                self.event_start_time = cal_start_ts
                self.last_detection_time = time.time()
                
                print(f"🚨 MACRO EVENT CALENDRIER DÉTECTÉ: {cal_event}")
                print(f"   📋 {cal_info['description']}")
                print(f"   🎁 Bonus score: +{cal_info['score_bonus']}")
                print(f"   🎯 Réduction seuil: -{cal_info['threshold_reduction']}")
                
                # Notification Telegram directe
                try:
                    notifier = NotificationManager()
                    if notifier.enabled:
                        notifier.notify_macro_event_start(cal_event, cal_info)
                        print(f"   📨 Notification Telegram envoyée")
                except Exception as e:
                    print(f"   ⚠️ Erreur notification: {e}")
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
            self.current_event = detected_event
            self.event_start_time = time.time()
            self.last_detection_time = time.time()
            
            event_info = self.event_adjustments[detected_event]
            self.current_event_info = event_info
            
            print(f"🚨 MACRO EVENT DÉTECTÉ: {detected_event}")
            print(f"   📋 {event_info['description']}")
            print(f"   🎁 Bonus score: +{event_info['score_bonus']}")
            print(f"   🎯 Réduction seuil: -{event_info['threshold_reduction']}")
            print(f"   ⏰ Durée estimée: {event_info['duration_hours']}h")
            
            try:
                notifier = NotificationManager()
                if notifier.enabled:
                    notifier.notify_macro_event_start(detected_event, event_info)
                    print(f"   📨 Notification Telegram envoyée")
            except Exception as e:
                print(f"   ⚠️ Erreur notification: {e}")
        
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
        
        print(f"🔧 MACRO EVENT FORCÉ: {event_type}")
        print(f"   📋 {event_info['description']}")
        print(f"   ⏰ Durée: {event_info['duration_hours']}h")
        
        return True
    
    def clear_event(self):
        """Annule l'événement macro actuel"""
        if self.current_event:
            print(f"🔄 ANNULATION MACRO EVENT: {self.current_event}")
            self.current_event = None
            self.current_event_info = None
            self.event_start_time = None
            return True
        return False