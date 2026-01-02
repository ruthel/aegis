"""Moniteur d'Événements Macro-Économiques"""
import time
from datetime import datetime, timedelta
import requests

class MacroEventMonitor:
    def __init__(self):
        self.risk_off_mode = False
        self.risk_off_start = None
        self.risk_off_duration = 2 * 3600  # 2h par défaut
        self.last_check = 0
        self.check_interval = 3600  # Vérifier toutes les heures
        self.last_message_time = 0  # Pour éviter spam messages
        self.message_interval = 300  # Message toutes les 5min max
        
        # Événements critiques (UTC)
        self.critical_events = {
            'fed_meeting': {'duration': 4 * 3600, 'impact': 'high'},
            'cpi_release': {'duration': 2 * 3600, 'impact': 'high'},
            'employment': {'duration': 2 * 3600, 'impact': 'medium'},
            'gdp_release': {'duration': 1 * 3600, 'impact': 'medium'}
        }
    
    def check_macro_events(self):
        """Vérifie les événements macro imminents"""
        current_time = time.time()
        
        # Vérifier seulement toutes les heures
        if current_time - self.last_check < self.check_interval:
            return self.risk_off_mode
        
        self.last_check = current_time
        
        try:
            # Vérifier événements programmés
            upcoming_events = self._get_upcoming_events()
            
            for event in upcoming_events:
                time_to_event = event['timestamp'] - current_time
                
                # Si événement dans les 2 prochaines heures
                if 0 <= time_to_event <= 2 * 3600:
                    self._activate_risk_off_mode(event)
                    return True
            
            # Vérifier si sortie du mode risk-off
            if self.risk_off_mode and self.risk_off_start:
                if current_time - self.risk_off_start > self.risk_off_duration:
                    self._deactivate_risk_off_mode()
            
            return self.risk_off_mode
            
        except Exception as e:
            print(f"⚠️ Erreur vérification événements macro: {e}")
            return self.risk_off_mode
    
    def _get_upcoming_events(self):
        """Récupère les événements économiques à venir depuis API réelle"""
        events = []
        
        try:
            # 1. API Economic Calendar (gratuite)
            response = requests.get(
                'https://api.tradingeconomics.com/calendar',
                params={
                    'c': 'guest:guest',  # Clé gratuite
                    'country': 'united states',
                    'importance': '3',  # Haute importance
                    'format': 'json'
                },
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                now = datetime.now()
                
                for item in data:
                    event_date = datetime.fromisoformat(item['Date'].replace('T', ' '))
                    if event_date > now:
                        # Filtrer événements critiques
                        event_name = item['Event'].lower()
                        if any(keyword in event_name for keyword in ['employment', 'payroll', 'unemployment', 'cpi', 'inflation', 'fed']):
                            events.append({
                                'name': item['Event'],
                                'timestamp': event_date.timestamp(),
                                'type': self._classify_event(item['Event'])
                            })
                            
                return events[:5]  # Max 5 événements
                
        except Exception as e:
            print(f"⚠️ API Economic Calendar échouée: {e}")
        
        try:
            # 2. Fallback: Fed Reserve API (gratuite)
            response = requests.get(
                'https://api.stlouisfed.org/fred/releases/dates',
                params={
                    'api_key': 'demo',  # Clé demo
                    'file_type': 'json',
                    'limit': '10'
                },
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                now = datetime.now()
                
                for release in data.get('release_dates', []):
                    release_date = datetime.strptime(release['date'], '%Y-%m-%d')
                    if release_date > now:
                        events.append({
                            'name': f"Fed Release: {release['release_name']}",
                            'timestamp': release_date.timestamp(),
                            'type': 'fed_release'
                        })
                        
                return events[:3]
                
        except Exception as e:
            print(f"⚠️ Fed API échouée: {e}")
        
        # 3. Fallback final: Dates fixes 2025 (si APIs échouent)
        print("⚠️ APIs indisponibles - Utilisation calendrier fixe")
        now = datetime.now()
        real_dates = [
            (datetime(2025, 1, 3, 14, 30), 'Employment Data (NFP)'),
            (datetime(2025, 1, 15, 14, 30), 'CPI Release'),
            (datetime(2025, 1, 29, 20, 0), 'Fed Meeting'),
            (datetime(2025, 2, 7, 14, 30), 'Employment Data (NFP)'),
        ]
        
        for date, name in real_dates:
            if date > now:
                events.append({
                    'name': name,
                    'timestamp': date.timestamp(),
                    'type': self._classify_event(name)
                })
                break
                
        return events
    
    def _classify_event(self, event_name):
        """Classifie le type d'événement"""
        event_lower = event_name.lower()
        if 'employment' in event_lower or 'payroll' in event_lower:
            return 'employment'
        elif 'cpi' in event_lower or 'inflation' in event_lower:
            return 'cpi_release'
        elif 'fed' in event_lower:
            return 'fed_meeting'
        else:
            return 'other'
    
    def _get_first_wednesday_of_month(self, year, month):
        """Trouve le premier mercredi du mois"""
        for day in range(1, 8):
            date = datetime(year, month, day)
            if date.weekday() == 2:  # Mercredi = 2
                return day
        return 1
    
    def _get_first_friday_of_month(self, year, month):
        """Trouve le premier vendredi du mois"""
        for day in range(1, 8):
            date = datetime(year, month, day)
            if date.weekday() == 4:  # Vendredi = 4
                return day
        return 1
    
    def _activate_risk_off_mode(self, event):
        """Active le mode risk-off avant événement critique"""
        if not self.risk_off_mode:
            self.risk_off_mode = True
            self.risk_off_start = time.time()
            
            event_config = self.critical_events.get(event['type'], {'duration': 2 * 3600})
            self.risk_off_duration = event_config['duration']
            
            time_to_event = (event['timestamp'] - time.time()) / 3600
            print(f"🚨 MODE RISK-OFF ACTIVÉ")
            print(f"📅 Événement: {event['name']} dans {time_to_event:.1f}h")
            print(f"⏳ Durée protection: {self.risk_off_duration/3600:.1f}h")
    
    def _deactivate_risk_off_mode(self):
        """Désactive le mode risk-off"""
        self.risk_off_mode = False
        self.risk_off_start = None
        print("✅ MODE RISK-OFF DÉSACTIVÉ - Reprise trading normal")
    
    def can_trade(self):
        """Vérifie si trading autorisé (pas en mode risk-off)"""
        self.check_macro_events()  # Mise à jour automatique
        
        if self.risk_off_mode:
            remaining_time = (self.risk_off_duration - (time.time() - self.risk_off_start)) / 3600
            if remaining_time > 0:
                # Limiter les messages pour éviter le spam
                current_time = time.time()
                if current_time - self.last_message_time > self.message_interval:
                    print(f"🚫 Mode RISK-OFF actif ({remaining_time:.1f}h restantes)")
                    self.last_message_time = current_time
                return False
        
        return True
    
    def get_risk_level(self):
        """Retourne le niveau de risque actuel"""
        if self.risk_off_mode:
            return 'HIGH'
        elif self.check_macro_events():
            return 'MEDIUM'
        else:
            return 'LOW'