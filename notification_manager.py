import json
import time
import requests
import smtplib
import os
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

class NotificationManager:
    def __init__(self):
        self.config = self.load_config()
        self.last_notifications = {}
        self.notification_cooldown = 300  # 5 minutes entre notifications similaires
        
    def load_config(self):
        """Charge la configuration des notifications"""
        try:
            with open('notification_config.json', 'r') as f:
                return json.load(f)
        except:
            # Configuration par défaut
            config = {
                "telegram": {
                    "enabled": True,
                    "bot_token": os.getenv('TELEGRAM_BOT_TOKEN', ''),
                    "chat_id": os.getenv('TELEGRAM_CHAT_ID', '')
                },
                "discord": {
                    "enabled": False,
                    "webhook_url": ""
                },
                "email": {
                    "enabled": False,
                    "smtp_server": "smtp.gmail.com",
                    "smtp_port": 587,
                    "email": "",
                    "password": "",
                    "to_email": ""
                }
            }
            with open('notification_config.json', 'w') as f:
                json.dump(config, f, indent=2)
            return config
    
    def should_send_notification(self, notification_type, message):
        """Vérifie si on doit envoyer la notification (cooldown)"""
        key = f"{notification_type}_{hash(message)}"
        now = time.time()
        
        if key in self.last_notifications:
            if now - self.last_notifications[key] < self.notification_cooldown:
                return False
        
        self.last_notifications[key] = now
        return True
    
    def send_telegram(self, message, priority="normal"):
        """Envoie notification Telegram"""
        if not self.config["telegram"]["enabled"]:
            print("Telegram désactivé")
            return False
            
        try:
            bot_token = self.config["telegram"]["bot_token"]
            chat_id = self.config["telegram"]["chat_id"]
            
            if not bot_token or not chat_id:
                print(f"Config Telegram manquante: token={bool(bot_token)}, chat_id={bool(chat_id)}")
                return False
            
            # Ajouter emoji selon priorité
            if priority == "critical":
                message = f"🚨 CRITIQUE: {message}"
            elif priority == "important":
                message = f"⚠️ IMPORTANT: {message}"
            else:
                message = f"ℹ️ {message}"
            
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            data = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            
            print(f"Envoi Telegram: {message[:50]}...")
            response = requests.post(url, data=data, timeout=10)
            print(f"Réponse Telegram: {response.status_code}")
            
            if response.status_code != 200:
                print(f"Erreur Telegram: {response.text}")
            
            return response.status_code == 200
            
        except Exception as e:
            print(f"Erreur Telegram: {e}")
            return False
    
    def send_discord(self, message, priority="normal"):
        """Envoie notification Discord"""
        if not self.config["discord"]["enabled"]:
            return False
            
        try:
            webhook_url = self.config["discord"]["webhook_url"]
            
            # Couleur selon priorité
            color = 0x00ff00  # Vert par défaut
            if priority == "critical":
                color = 0xff0000  # Rouge
            elif priority == "important":
                color = 0xff9900  # Orange
            
            data = {
                "embeds": [{
                    "title": "Bot Trading Binance",
                    "description": message,
                    "color": color,
                    "timestamp": datetime.now().isoformat()
                }]
            }
            
            response = requests.post(webhook_url, json=data, timeout=10)
            return response.status_code == 204
            
        except Exception as e:
            print(f"Erreur Discord: {e}")
            return False
    
    def send_email(self, subject, message, priority="normal"):
        """Envoie notification Email"""
        if not self.config["email"]["enabled"]:
            return False
            
        try:
            smtp_server = self.config["email"]["smtp_server"]
            smtp_port = self.config["email"]["smtp_port"]
            email = self.config["email"]["email"]
            password = self.config["email"]["password"]
            to_email = self.config["email"]["to_email"]
            
            # Ajouter priorité au sujet
            if priority == "critical":
                subject = f"🚨 CRITIQUE - {subject}"
            elif priority == "important":
                subject = f"⚠️ IMPORTANT - {subject}"
            
            msg = MIMEMultipart()
            msg['From'] = email
            msg['To'] = to_email
            msg['Subject'] = subject
            
            msg.attach(MIMEText(message, 'plain'))
            
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
            server.login(email, password)
            server.send_message(msg)
            server.quit()
            
            return True
            
        except Exception as e:
            print(f"Erreur Email: {e}")
            return False
    
    def notify(self, message, priority="normal", notification_type="general"):
        """Envoie notification sur tous les canaux configurés"""
        if not self.should_send_notification(notification_type, message):
            return
        
        print(f"📢 Notification ({priority}): {message}")
        
        # Envoyer sur tous les canaux
        if priority == "critical":
            # Notifications critiques sur tous les canaux
            self.send_telegram(message, priority)
            self.send_discord(message, priority)
            self.send_email("Alerte Bot Trading", message, priority)
        elif priority == "important":
            # Notifications importantes sur Telegram et Discord
            self.send_telegram(message, priority)
            self.send_discord(message, priority)
        else:
            # Notifications normales sur Telegram seulement
            self.send_telegram(message, priority)

class AlertManager:
    def __init__(self):
        self.notifier = NotificationManager()
        self.thresholds = {
            "loss_critical": -100,      # Perte critique
            "loss_important": -50,      # Perte importante
            "profit_important": 100,    # Profit important
            "disconnection_time": 300   # 5 minutes de déconnexion
        }
        self.last_connection_check = time.time()
        
    def check_profit_loss(self, current_pnl, daily_pnl):
        """Vérifie les seuils de profit/perte"""
        if current_pnl <= self.thresholds["loss_critical"]:
            self.notifier.notify(
                f"Perte critique: ${current_pnl:.2f} (Journalier: ${daily_pnl:.2f})",
                priority="critical",
                notification_type="loss_critical"
            )
        elif current_pnl <= self.thresholds["loss_important"]:
            self.notifier.notify(
                f"Perte importante: ${current_pnl:.2f}",
                priority="important", 
                notification_type="loss_important"
            )
        elif current_pnl >= self.thresholds["profit_important"]:
            self.notifier.notify(
                f"Profit important: +${current_pnl:.2f} (Journalier: +${daily_pnl:.2f})",
                priority="important",
                notification_type="profit_important"
            )
    
    def check_bot_status(self, is_connected, error_message=None):
        """Vérifie le statut du bot"""
        now = time.time()
        
        if not is_connected:
            if now - self.last_connection_check > self.thresholds["disconnection_time"]:
                message = "Bot déconnecté depuis plus de 5 minutes"
                if error_message:
                    message += f" - Erreur: {error_message}"
                
                self.notifier.notify(
                    message,
                    priority="critical",
                    notification_type="disconnection"
                )
        else:
            self.last_connection_check = now
    
    def notify_trade(self, action, symbol, amount, price, profit=None):
        """Notifie les trades importants"""
        if profit and abs(profit) > 20:  # Trades > $20
            message = f"{action} {symbol}: {amount:.4f} @ ${price:.2f}"
            if profit:
                message += f" (P&L: ${profit:+.2f})"
            
            self.notifier.notify(
                message,
                priority="normal",
                notification_type="trade"
            )
    
    def notify_signal(self, symbol, signal_type, strength, reason):
        """Notifie les signaux forts"""
        if strength >= 3:  # Signaux très forts seulement
            self.notifier.notify(
                f"{symbol}: Signal {signal_type} fort (Force: {strength:.1f}) - {reason}",
                priority="important",
                notification_type="signal"
            )