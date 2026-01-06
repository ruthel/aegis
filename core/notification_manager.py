import requests
import os
import time
import threading
from datetime import datetime, timedelta
from config import BOT_NAME

class NotificationManager:
    def __init__(self):
        self.telegram_token = "8048049962:AAGUNfTjlkADCRZEVKieM-t9Nvn8oTPzKpI"
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.enabled = bool(self.chat_id)
        self.periodic_interval = int(os.getenv('TELEGRAM_STATUS_INTERVAL', '300'))
        self.last_status_time = 0
        self.bot_ref = None
        self.daily_stats = {'start_balance': 0, 'trades': [], 'start_time': None}
        
    def set_bot(self, bot):
        """Référence au bot pour status périodique"""
        self.bot_ref = bot
        
    def notify(self, message, emoji="🤖"):
        if not self.enabled:
            print(f"📢 {message}")
            return False
            
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            data = {
                'chat_id': self.chat_id,
                'text': f"{emoji} {message}",
                'parse_mode': 'HTML'
            }
            response = requests.post(url, data=data, timeout=10)
            return response.status_code == 200
        except:
            print(f"📢 {message}")
            return False
    
    def notify_trade_buy(self, symbol, amount, price, total, signal_data):
        """Notification achat avec contexte"""
        crypto = symbol.split('/')[0]
        msg = f"🟢 ACHAT {crypto}\n\n"
        msg += f"💰 Montant: {amount:.6f} {crypto}\n"
        msg += f"💵 Prix: {price:.2f} USDT\n"
        msg += f"📊 Total: {total:.2f} USDT\n\n"
        msg += f"📈 Signal: {signal_data.get('trend', 'N/A')} {signal_data.get('confidence', 0):.0f}%\n"
        msg += f"⚡ Vol: {signal_data.get('volatility', 0):.1f}/5 | Conf: {signal_data.get('confidence', 0):.0f}%\n\n"
        msg += f"⏱️ {datetime.now().strftime('%H:%M:%S')}"
        self.notify(msg, "")
    
    def notify_trade_sell(self, symbol, amount, price, total, buy_price, pnl, hold_time):
        """Notification vente avec P&L"""
        crypto = symbol.split('/')[0]
        pnl_pct = ((price - buy_price) / buy_price) * 100
        emoji = "🟢" if pnl > 0 else "🔴"
        
        msg = f"🔴 VENTE {crypto}\n\n"
        msg += f"💰 Montant: {amount:.6f} {crypto}\n"
        msg += f"💵 Prix: {price:.2f} USDT\n"
        msg += f"📊 Total: {total:.2f} USDT\n\n"
        msg += f"💸 P&L: {emoji} {pnl:+.2f} USDT ({pnl_pct:+.1f}%)\n"
        msg += f"⏱️ Détention: {hold_time}\n\n"
        msg += f"⏱️ {datetime.now().strftime('%H:%M:%S')}"
        self.notify(msg, "")
    
    def notify_limit_order(self, symbol, amount, price, profit_pct, estimation):
        """Notification ordre limite placé"""
        crypto = symbol.split('/')[0]
        msg = f"🎯 ORDRE LIMITE {crypto}\n\n"
        msg += f"📤 Vente @ {price:.2f} USDT\n"
        msg += f"💰 Quantité: {amount:.6f} {crypto}\n"
        msg += f"🎯 Profit cible: +{profit_pct:.2f}%\n\n"
        
        if estimation:
            msg += f"⏳ Estimation: {estimation.get('time_estimate', 'N/A')}\n"
            msg += f"📊 Probabilité: {estimation.get('probability', 0)}%\n\n"
        
        msg += f"⏱️ {datetime.now().strftime('%H:%M:%S')}"
        self.notify(msg, "")
    
    def notify_silent_error(self, error_type, details):
        """Notification silencieuse pour erreurs non-critiques (logs seulement)"""
        # Log seulement, pas de notification Telegram
        print(f"⚠️ Erreur {error_type}: {details}")
    
    def notify_error(self, error_type, details):
        """Notification erreur critique"""
        msg = f"⚠️ ALERTE CRITIQUE\n\n"
        msg += f"❌ Erreur: {error_type}\n"
        msg += f"📍 Détails: {details}\n\n"
        msg += f"🔧 Action: Vérifier le bot\n\n"
        msg += f"⏱️ {datetime.now().strftime('%H:%M:%S')}"
        self.notify(msg, "")
    
    def notify_stuck_position(self, symbol, loss_pct, loss_amount, duration, action):
        """Notification position bloquée"""
        crypto = symbol.split('/')[0]
        msg = f"⚠️ POSITION BLOQUÉE\n\n"
        msg += f"🪙 Crypto: {crypto}\n"
        msg += f"💸 Perte: {loss_pct:.1f}% ({loss_amount:.2f} USDT)\n"
        msg += f"⏳ Durée: {duration}\n\n"
        msg += f"🎯 Action: {action}\n\n"
        msg += f"⏱️ {datetime.now().strftime('%H:%M:%S')}"
        self.notify(msg, "")
    
    def notify_daily_summary(self):
        """Résumé journalier automatique"""
        if not self.bot_ref:
            return
        
        bot = self.bot_ref
        balance = bot.balance_manager.get_balance()
        current_balance = balance.get('USDT', {}).get('free', 0)
        
        # Calculer capital total (USDT + cryptos)
        total_value = current_balance
        for pair in os.getenv('TRADING_PAIRS', 'BTCUSDT,ETHUSDT').split(','):
            symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
            crypto = symbol.split('/')[0]
            amount = balance.get(crypto, {}).get('free', 0)
            if amount > 0.00001:
                price = bot.get_price(symbol)
                total_value += amount * price
        
        start_balance = self.daily_stats.get('start_balance', total_value)
        variation = total_value - start_balance
        variation_pct = (variation / start_balance * 100) if start_balance > 0 else 0
        
        win_rate = (bot.winning_trades / bot.total_trades * 100) if bot.total_trades > 0 else 0
        
        msg = f"📊 {BOT_NAME} | RÉSUMÉ JOURNALIER\n"
        msg += f"{datetime.now().strftime('%d %b %Y')}\n\n"
        msg += f"💰 Capital\n"
        msg += f"├─ Début: {start_balance:.2f} USDT\n"
        msg += f"├─ Fin: {total_value:.2f} USDT\n"
        msg += f"└─ Variation: {variation:+.2f} ({variation_pct:+.1f}%)\n\n"
        msg += f"📈 Trading\n"
        msg += f"├─ Trades: {bot.total_trades} ({win_rate:.0f}% win)\n"
        msg += f"├─ P&L: {bot.daily_pnl:+.2f} USDT\n"
        msg += f"└─ Frais: ~{bot.total_trades * 0.02:.2f} USDT\n\n"
        msg += f"⏰ {datetime.now().strftime('%H:%M:%S')}"
        
        self.notify(msg, "")
        
        # Reset stats pour demain
        self.daily_stats['start_balance'] = total_value
        self.daily_stats['start_time'] = datetime.now()
    
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
        """Construit message status ultra-compact"""
        bot = self.bot_ref
        balance = bot.balance_manager.get_balance()
        usdt = balance.get('USDT', {}).get('free', 0)
        
        # Portfolio
        portfolio_items = [f"USDT: {usdt:.2f}"]
        total_value = usdt
        
        for pair in os.getenv('TRADING_PAIRS', 'BTCUSDT,ETHUSDT').split(','):
            symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
            crypto = symbol.split('/')[0]
            free = balance.get(crypto, {}).get('free', 0)
            locked = balance.get(crypto, {}).get('used', 0)
            total = free + locked
            
            if total > 0.00001:
                price = bot.get_price(symbol)
                value = total * price
                if value >= bot.get_min_amount(symbol)['min_cost']:
                    status = " (ordre actif)" if locked > 0 else ""
                    portfolio_items.append(f"{crypto}: {total:.3f}{status}")
                    total_value += value
        
        # Stats
        win_rate = (bot.winning_trades / bot.total_trades * 100) if bot.total_trades > 0 else 0
        
        msg = f"🤖 {BOT_NAME} | STATUS {datetime.now().strftime('%H:%M')}\n\n"
        msg += f"💼 Portfolio\n"
        for i, item in enumerate(portfolio_items):
            prefix = "├─" if i < len(portfolio_items) - 1 else "└─"
            msg += f"{prefix} {item}\n"
        msg += f"└─ Total: ~{total_value:.2f} USDT\n\n"
        
        msg += f"📈 Performance\n"
        msg += f"├─ P&L: {bot.daily_pnl:+.2f} USDT\n"
        msg += f"├─ Trades: {bot.total_trades} ({win_rate:.0f}% win)\n"
        
        if bot.total_trades > 0:
            msg += f"└─ Meilleur: N/A\n\n"
        else:
            msg += f"└─ Aucun trade\n\n"
        
        # Double Investment Stats (réelles + simulées)
        if hasattr(bot, 'double_investment_manager'):
            # Récupérer positions réelles de l'API
            real_positions = bot.double_investment_manager.get_dual_investment_positions_from_api()
            simulated_positions = bot.double_investment_manager.positions
            
            total_positions = len(real_positions) + len(simulated_positions)
            
            if total_positions > 0:
                msg += f"💎 Double Investment\n"
                msg += f"├─ Positions: {total_positions}\n"
                
                # Calculer montants investis
                real_invested = sum(float(p.get('amount', 0)) for p in real_positions)
                sim_invested = sum(p.get('amount', 0) for p in simulated_positions if p.get('status', 'active') == 'active')
                total_invested = real_invested + sim_invested
                
                if total_invested > 0:
                    msg += f"├─ Investi: {total_invested:.2f} USDT\n"
                
                # Détail par type (réelles)
                real_calls = [p for p in real_positions if p.get('productType') == 'CALL']
                real_puts = [p for p in real_positions if p.get('productType') == 'PUT']
                
                # Détail par type (simulées)
                sim_calls = [p for p in simulated_positions if p.get('type') == 'covered_call' and p.get('status', 'active') == 'active']
                sim_puts = [p for p in simulated_positions if p.get('type') == 'cash_secured_put' and p.get('status', 'active') == 'active']
                
                total_calls = len(real_calls) + len(sim_calls)
                total_puts = len(real_puts) + len(sim_puts)
                
                if total_calls > 0:
                    calls_amount = sum(float(p.get('amount', 0)) for p in real_calls) + sum(p.get('amount', 0) for p in sim_calls)
                    msg += f"├─ Calls: {total_calls} ({calls_amount:.1f} USDT)\n"
                if total_puts > 0:
                    puts_amount = sum(float(p.get('amount', 0)) for p in real_puts) + sum(p.get('amount', 0) for p in sim_puts)
                    msg += f"├─ Puts: {total_puts} ({puts_amount:.1f} USDT)\n"
                
                # Détail des positions actives
                position_details = []
                
                # Positions réelles
                for p in real_positions:
                    invest_coin = p.get('investCoin', 'UNKNOWN')
                    exercised_coin = p.get('exercisedCoin', 'UNKNOWN')
                    option_type = p.get('optionType', 'UNKNOWN')
                    amount = float(p.get('subscriptionAmount', 0))
                    apr = float(p.get('apr', 0))
                    duration = p.get('duration', 0)
                    
                    # CORRECTION: APR est déjà en pourcentage dans l'API
                    potential_gain_usdt = amount * (apr / 100) * (duration / 365)
                    
                    # Calculer jours restants
                    settle_date = p.get('settleDate', 0)
                    if settle_date:
                        settle_datetime = datetime.fromtimestamp(settle_date / 1000)
                        days_left = (settle_datetime - datetime.now()).days
                        if days_left > 0:
                            time_display = f"[{days_left}j]"
                        else:
                            time_display = "[Expiré]"
                    else:
                        time_display = f"[{duration}j]"
                    
                    gain_display = f"+{potential_gain_usdt:.3f} USDT {time_display}"
                    
                    if option_type == 'CALL':
                        position_details.append(f"📞 Call {exercised_coin} {amount:.2f} USDT ({gain_display})")
                    elif option_type == 'PUT':
                        position_details.append(f"📉 PUT {exercised_coin} {amount:.2f} USDT ({gain_display})")
                    else:
                        position_details.append(f"💎 {exercised_coin} {amount:.2f} USDT ({gain_display})")
                
                # Positions simulées
                for p in simulated_positions:
                    if p.get('status', 'active') == 'active':
                        crypto = p.get('symbol', 'N/A').replace('USDT', '')
                        ptype = 'CALL' if p.get('type') == 'covered_call' else 'PUT'
                        amount = p.get('amount', 0)
                        if ptype == 'CALL':
                            position_details.append(f"📞 Call {crypto} {amount:.1f} USDT")
                        else:
                            position_details.append(f"📉 PUT {crypto} {amount:.1f} USDT")
                
                if position_details:
                    for i, detail in enumerate(position_details):
                        prefix = "├─" if i < len(position_details) - 1 else "└─"
                        msg += f"{prefix} {detail}\n"
                    msg += "\n"
                else:
                    msg += f"└─ Positions actives\n\n"
            else:
                msg += f"💎 Double Investment: Aucune position\n\n"
        
        # Opportunités
        msg += f"🔮 Opportunités\n"
        opps = []
        
        for pair in os.getenv('TRADING_PAIRS', 'BTCUSDT,ETHUSDT').split(','):
            symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
            crypto = symbol.split('/')[0]
            
            try:
                prediction = bot.predict_next_buy_opportunity(symbol)
                
                if prediction['status'] == 'READY':
                    opps.append(f"{crypto}: Maintenant ({prediction['confidence']:.0f}%)")
                elif prediction['status'] == 'WAITING':
                    price = prediction.get('target_price', 0)
                    opps.append(f"{crypto}: {prediction['time_estimate']} (↓ {price:.0f})")
            except:
                pass
        
        if opps:
            for i, opp in enumerate(opps):
                prefix = "├─" if i < len(opps) - 1 else "└─"
                msg += f"{prefix} {opp}\n"
        else:
            msg += "└─ Aucune\n"
        
        msg += f"\n⏰ Prochain: {self.periodic_interval//60}min"
        
        return msg