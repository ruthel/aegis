import requests
import os
from datetime import datetime

class NotificationManager:
    def __init__(self):
        self.telegram_token = "8048049962:AAGUNfTjlkADCRZEVKieM-t9Nvn8oTPzKpI"
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.enabled = bool(self.chat_id)
        
    def notify(self, message):
        if not self.enabled:
            print(f"📢 {message}")
            return False
            
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            data = {
                'chat_id': self.chat_id,
                'text': f"🤖 {message}",
                'parse_mode': 'HTML'
            }
            response = requests.post(url, data=data, timeout=10)
            return response.status_code == 200
        except:
            print(f"📢 {message}")
            return False