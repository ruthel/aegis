import requests
import os
import time
import threading
from datetime import datetime

class NotificationManager:
    def __init__(self):
        self.telegram_token = "8048049962:AAGUNfTjlkADCRZEVKieM-t9Nvn8oTPzKpI"
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.enabled = bool(self.chat_id)
        self.periodic_interval = int(os.getenv('TELEGRAM_STATUS_INTERVAL', '300'))  # 5min par défaut
        self.last_status_time = 0
        self.bot_ref = None
        
    def set_bot(self, bot):
        """Référence au bot pour status périodique"""
        self.bot_ref = bot
        
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
    
    def send_status_update(self):
        """Envoie status périodique"""
        now = time.time()
        if now - self.last_status_time < self.periodic_interval:
            return
        
        self.last_status_time = now
        
        if not self.bot_ref:
            return
        
        try:
            status = self._build_status_message()
            self.notify(status)
        except Exception as e:
            pass
    
    def _build_status_message(self):
        """Construit message status"""
        bot = self.bot_ref
        balance = bot.get_balance()
        usdt = balance.get('USDT', {}).get('free', 0)
        
        # Positions
        positions = []
        for pair in os.getenv('TRADING_PAIRS', 'BTCUSDT,ETHUSDT').split(','):
            symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
            crypto = symbol.split('/')[0]
            amount = balance.get(crypto, {}).get('free', 0)
            if amount > 0.00001:
                price = bot.get_price(symbol)
                value = amount * price
                if value >= bot.get_min_amount(symbol)['min_cost']:
                    positions.append(f"{crypto}: {amount:.4f}")
        
        # Stats
        win_rate = (bot.winning_trades / bot.total_trades * 100) if bot.total_trades > 0 else 0
        
        msg = f"📊 STATUS {datetime.now().strftime('%H:%M')}\n\n"
        msg += f"💰 USDT: {usdt:.2f}\n"
        msg += f"📈 P&L: {bot.daily_pnl:+.2f} USDT\n"
        msg += f"🔄 Trades: {bot.total_trades} ({win_rate:.0f}% win)\n"
        
        if positions:
            msg += f"\n📦 Positions:\n"
            for pos in positions:
                msg += f"  • {pos}\n"
        else:
            msg += f"\n⏳ Aucune position\n"
        
        msg += f"\n⏰ Prochain: {self.periodic_interval//60}min"
        
        return msg