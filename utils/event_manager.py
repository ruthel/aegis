"""
Gestionnaire d'événements macro - Détection automatique via données crypto
"""
import time
import os
from datetime import datetime
from core.notification_manager import NotificationManager

class MacroEventManager:
    """Détecte et gère les événements macro via analyse des patterns crypto"""
    
    def __init__(self):
        self.current_event = None
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
    
    def detect_macro_event(self, market_conditions):
        """Détecte événement macro via patterns crypto anormaux"""
        if not market_conditions:
            return None
        
        # Éviter détections trop fréquentes
        if time.time() - self.last_detection_time < 3600:  # 1h minimum
            return self.current_event
        
        avg_vol_ratio = market_conditions.get('avg_volume_ratio', 1.0)
        avg_volatility = market_conditions.get('avg_volatility', 2.0)
        
        # Critères de détection d'événement macro
        very_low_volume = avg_vol_ratio < 0.5    # Volume 50% plus bas
        low_volume = avg_vol_ratio < 0.7         # Volume 30% plus bas  
        very_low_volatility = avg_volatility < 1.0  # Volatilité très faible
        low_volatility = avg_volatility < 1.5   # Volatilité faible
        
        # Détection par sévérité
        if very_low_volume and very_low_volatility:
            detected_event = 'FED_MEETING'
        elif low_volume and low_volatility:
            detected_event = 'MARKET_UNCERTAINTY'
        else:
            detected_event = None
        
        # Nouveau événement détecté
        if detected_event and not self.current_event:
            self.current_event = detected_event
            self.event_start_time = time.time()
            self.last_detection_time = time.time()
            
            event_info = self.event_adjustments[detected_event]
            print(f"🚨 MACRO EVENT DÉTECTÉ: {detected_event}")
            print(f"   📋 {event_info['description']}")
            print(f"   🎁 Bonus score: +{event_info['score_bonus']}")
            print(f"   🎯 Réduction seuil: -{event_info['threshold_reduction']}")
            print(f"   ⏰ Durée estimée: {event_info['duration_hours']}h")
            
            # Notification Telegram directe
            try:
                if os.getenv('TELEGRAM_BOT_TOKEN') and os.getenv('TELEGRAM_CHAT_ID'):
                    notifier = NotificationManager()
                    notifier.notify_macro_event_start(detected_event, event_info)
                    print(f"   📨 Notification Telegram envoyée")
            except Exception as e:
                print(f"   ⚠️ Erreur notification: {e}")
            
            return self.current_event
        
        # Vérifier expiration événement actuel
        if self.current_event and self.event_start_time:
            duration_hours = self.event_adjustments[self.current_event]['duration_hours']
            elapsed_hours = (time.time() - self.event_start_time) / 3600
            
            if elapsed_hours > duration_hours:
                print(f"✅ FIN MACRO EVENT: {self.current_event} (durée: {elapsed_hours:.1f}h)")
                
                # Notification fin d'événement directe
                try:
                    if os.getenv('TELEGRAM_BOT_TOKEN') and os.getenv('TELEGRAM_CHAT_ID'):
                        notifier = NotificationManager()
                        notifier.notify_macro_event_end(self.current_event, elapsed_hours)
                        print(f"   📨 Notification fin envoyée")
                except Exception as e:
                    print(f"   ⚠️ Erreur notification fin: {e}")
                
                self.current_event = None
                self.event_start_time = None
        
        return self.current_event
    
    def get_adjustments(self, event_type=None):
        """Retourne ajustements pour événement actuel ou spécifié"""
        event = event_type or self.current_event
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
        print(f"🔧 MACRO EVENT FORCÉ: {event_type}")
        print(f"   📋 {event_info['description']}")
        print(f"   ⏰ Durée: {event_info['duration_hours']}h")
        
        return True
    
    def clear_event(self):
        """Annule l'événement macro actuel"""
        if self.current_event:
            print(f"🔄 ANNULATION MACRO EVENT: {self.current_event}")
            self.current_event = None
            self.event_start_time = None
            return True
        return False