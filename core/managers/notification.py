import requests
import os
import time
import threading
from datetime import datetime, timedelta
from config import BOT_NAME

class NotificationManager:
    def __init__(self):
        self.telegram_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
        
        # Ignorer si ce sont des valeurs par défaut / templates (.env)
        is_placeholder = (
            not self.telegram_token or
            not self.chat_id or
            'votre_token' in self.telegram_token or
            'votre_chat_id' in self.chat_id
        )
        self.enabled = not is_placeholder
        self.periodic_interval = int(os.getenv('TELEGRAM_STATUS_INTERVAL', '7200'))
        self.last_status_time = 0
        self._status_lock = threading.Lock()
        self.bot_ref = None
        self.daily_stats = {'start_balance': 0, 'trades': [], 'start_time': None}
        self._last_update_id = None
        
    def set_bot(self, bot):
        """Référence au bot pour status périodique et écoute des commandes"""
        self.bot_ref = bot
        if self.enabled:
            # Lancer l'écouteur de commandes Telegram en arrière-plan
            threading.Thread(target=self._poll_telegram_commands, daemon=True).start()
        
    def _poll_telegram_commands(self):
        """Boucle d'écoute (long-polling) des commandes Telegram"""
        offset = 0
        
        # Consommer tous les anciens messages en attente au démarrage pour ne pas les réexécuter
        try:
            init_url = f"https://api.telegram.org/bot{self.telegram_token}/getUpdates"
            res = requests.get(init_url, params={'offset': -1, 'timeout': 0}, timeout=5)
            if res.status_code == 200:
                data = res.json()
                results = data.get('result', [])
                if results:
                    last_update = results[-1]
                    offset = last_update['update_id'] + 1
                    print(f"🧹 Telegram : messages en attente ignorés au démarrage.")
        except Exception as e:
            print(f"⚠️ Erreur initialisation offset Telegram : {e}")

        url = f"https://api.telegram.org/bot{self.telegram_token}/getUpdates"
        
        # Petit délai au démarrage pour s'assurer que le bot est initialisé
        time.sleep(2)
        print("🤖 Écouteur de commandes Telegram démarré.")
        
        while self.enabled:
            try:
                params = {'offset': offset, 'timeout': 20}
                response = requests.get(url, params=params, timeout=25)
                
                if response.status_code != 200:
                    time.sleep(5)
                    continue
                    
                data = response.json()
                if not data.get('ok'):
                    time.sleep(5)
                    continue
                    
                for update in data.get('result', []):
                    update_id = update['update_id']
                    self._last_update_id = update_id
                    offset = update_id + 1
                    
                    message = update.get('message', {})
                    text = message.get('text', '').strip()
                    chat = message.get('chat', {})
                    chat_id = str(chat.get('id', ''))
                    
                    # Sécurité : N'accepter que les messages provenant du chat_id autorisé
                    if chat_id != self.chat_id:
                        continue
                        
                    if text:
                        msg_id = message.get('message_id')
                        msg_date = message.get('date')
                        self.save_telegram_message_history(msg_id, text, msg_date, direction="incoming")
                    
                    if text.startswith('/'):
                        command = text.split()[0].lower()
                        self._handle_telegram_command(command)
                        
            except Exception as e:
                # Éviter de saturer la boucle en cas d'erreur réseau
                time.sleep(10)

    def _handle_telegram_command(self, command):
        """Traite une commande reçue depuis Telegram"""
        if command == '/events':
            try:
                from utils.event_manager import MacroEventManager
                macro_mgr = MacroEventManager()
                now = time.time()
                upcoming = []
                from datetime import timezone
                
                for item in macro_mgr.macro_calendar_2026:
                    event_dt = datetime.fromisoformat(item['date']).replace(tzinfo=timezone.utc)
                    event_ts = event_dt.timestamp()
                    if event_ts > now:
                        local_dt = datetime.fromtimestamp(event_ts)
                        upcoming.append((event_ts, item, local_dt))
                
                upcoming.sort(key=lambda x: x[0])
                next_events = upcoming[:5]
                
                msg = "📅 <b>ÉVÉNEMENTS MACRO PROGRAMMÉS (2026)</b>\n\n"
                if next_events:
                    for i, (event_ts, item, local_dt) in enumerate(next_events):
                        event_type = item['event']
                        event_name = "Réunion FED" if event_type == "FED_MEETING" else "CPI Inflation" if event_type == "INFLATION_DATA" else "Incertitude Marché"
                        date_display = local_dt.strftime("%d/%m/%Y à %H:%M")
                        
                        # Récupérer les paramètres correspondants
                        params = macro_mgr.event_adjustments.get(event_type, {})
                        bonus = params.get('score_bonus', 10)
                        reduction = params.get('threshold_reduction', 8)
                        duration = params.get('duration_hours', 24)
                        desc = item.get('description', '')
                        
                        msg += f"<b>{i+1}. {event_name}</b>\n"
                        msg += f"Le <b>{date_display}</b> (heure locale) aura lieu l'événement <i>\"{desc}\"</i>. Pour y faire face, le bot s'adaptera pendant une durée de <b>{duration}h</b> en augmentant son score de <b>+{bonus} points</b> et en réduisant son seuil de déclenchement de <b>-{reduction} points</b>.\n\n"
                else:
                    msg += "Aucun événement futur recensé pour le moment.\n"
                
                msg += "<i>Le bot s'adapte automatiquement et se met en mode sécurité 2h avant chaque événement.</i>"
                self.notify(msg, "")
            except Exception as e:
                self.notify(f"⚠️ Erreur lors de la récupération des événements : {e}", "")
                
        elif command == '/status':
            try:
                status_msg = self._build_status_message()
                self.notify(status_msg, "")
            except Exception as e:
                self.notify(f"⚠️ Erreur lors de la génération du statut : {e}", "")
                
        elif command == '/restart':
            try:
                self.notify("🔄 <b>Redémarrage du bot en cours...</b>", "")
                time.sleep(1)
                
                # IMPORTANT: Confirmer la lecture du message à Telegram avant de couper le bot.
                # Sinon, au redémarrage, getUpdates renverra à nouveau ce message de /restart en boucle.
                if hasattr(self, '_last_update_id') and self._last_update_id:
                    try:
                        confirm_url = f"https://api.telegram.org/bot{self.telegram_token}/getUpdates"
                        confirm_params = {'offset': self._last_update_id + 1, 'limit': 1, 'timeout': 0}
                        requests.get(confirm_url, params=confirm_params, timeout=2)
                    except Exception:
                        pass
                
                import urllib.request
                port = os.getenv('DASHBOARD_PORT', '8080')
                url = f"http://127.0.0.1:{port}/api/bot/restart"
                
                req = urllib.request.Request(url, method='POST')
                try:
                    with urllib.request.urlopen(req, timeout=2) as response:
                        pass
                except Exception:
                    pass
            except Exception as e:
                self.notify(f"⚠️ Échec du redémarrage : {e}", "")
                
        elif command == '/help' or command == '/start':
            msg = "🤖 <b>COMMANDES DISPONIBLES</b>\n\n"
            msg += "• /status - Voir le portefeuille et la performance\n"
            msg += "• /events - Voir les 5 prochains événements macroéconomiques répertoriés\n"
            msg += "• /restart - Redémarrer le bot à distance\n"
            msg += "• /help - Afficher ce message d'aide"
            self.notify(msg, "")
        
    def save_telegram_message_history(self, message_id, text, timestamp=None, direction="outgoing"):
        """Enregistre tout message Telegram dans SQLite."""
        try:
            if self.bot_ref and hasattr(self.bot_ref, 'ml_live_logger'):
                self.bot_ref.ml_live_logger.record_telegram_message(
                    message_id=message_id,
                    text=text,
                    timestamp=timestamp,
                    direction=direction
                )
        except Exception as e:
            print(f"⚠️ Erreur enregistrement historique Telegram: {e}")

    def notify(self, message, emoji="🤖"):
        full_text = f"{emoji} {message}".strip() if emoji else message
        if not self.enabled:
            print(f"📢 {full_text}")
            return False
            
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            data = {
                'chat_id': self.chat_id,
                'text': full_text,
                'parse_mode': 'HTML'
            }
            response = requests.post(url, data=data, timeout=10)
            if response.status_code == 200:
                res_json = response.json()
                if res_json.get('ok') and 'result' in res_json:
                    msg_id = res_json['result'].get('message_id')
                    ts = res_json['result'].get('date')
                    self.save_telegram_message_history(msg_id, full_text, ts)
                return True
            return False
        except Exception as e:
            print(f"📢 {full_text}")
            return False
    
    def notify_trade_buy(self, symbol, amount, price, total, signal_data):
        """Notification achat avec contexte"""
        crypto = symbol.split('/')[0]
        msg = f"🟢 ACHAT {crypto}\n\n"
        msg += f"💰 Montant: {amount:.6f} {crypto}\n"
        msg += f"💵 Prix: {price:.2f} USD\n"
        msg += f"📊 Total: {total:.2f} USD\n\n"
        msg += f"📈 Signal: {signal_data.get('trend', 'N/A')} {signal_data.get('confidence', 0):.0f}%\n"
        msg += f"⚡ Vol: {signal_data.get('volatility', 0):.1f}/5 | Conf: {signal_data.get('confidence', 0):.0f}%\n\n"
        msg += f"⏱️ {datetime.now().strftime('%H:%M:%S')}"
        self.notify(msg, "")
    
    def notify_trade_sell(self, symbol, amount, price, total, buy_price, pnl, hold_time):
        """Notification vente (le profit pnl est déjà déduit des frais)"""
        crypto = symbol.split('/')[0]
        
        # Calcul de la base de coût d'achat initiale pour déterminer le % de P&L exact
        if buy_price and buy_price > 0 and buy_price != price and amount > 0:
            cost_basis = buy_price * amount
        elif total and total > 0:
            cost_basis = total - pnl
        else:
            cost_basis = (price * amount) - pnl if (price and amount) else 0.0

        pnl_pct = (pnl / cost_basis * 100.0) if (cost_basis and cost_basis > 0) else 0.0

        if pnl >= 0.0001:
            emoji = "🟢"
            sign = "+"
        elif pnl <= -0.0001:
            emoji = "🔴"
            sign = ""
        else:
            emoji = "⚪"
            sign = ""

        msg = f"🔴 VENTE {crypto}\n\n"
        msg += f"💰 Montant: {amount:.6f} {crypto}\n"
        msg += f"💵 Prix: {price:.2f} USD\n"
        msg += f"📊 Total: {total:.2f} USD\n\n"
        msg += f"💸 P&L: {emoji} {pnl:+.2f} USD ({sign}{pnl_pct:.2f}%)\n"
        if hold_time and hold_time != "N/A":
            msg += f"⏱️ Détention: {hold_time}\n\n"
        msg += f"⏱️ {datetime.now().strftime('%H:%M:%S')}"
        self.notify(msg, "")
    
    def notify_smart_limit_order(self, symbol, amount, price, profit_pct, prediction):
        """Notification ordre limite intelligent avec prédiction"""
        crypto = symbol.split('/')[0]
        method_names = {
            'resistance_based': 'Résistance',
            'fibonacci_based': 'Fibonacci', 
            'atr_based': 'ATR',
            'fallback': 'Minimum'
        }
        
        method_display = method_names.get(prediction['method_used'], prediction['method_used'])
        confidence_emoji = "🎯" if prediction['probability'] >= 75 else "📊" if prediction['probability'] >= 60 else "❓"
        
        msg = f"🎯 ORDRE LIMITE INTELLIGENT\n\n"
        msg += f"🪙 Crypto: {crypto}\n"
        msg += f"📤 Prix: {price:.6f} USD\n"
        msg += f"💰 Quantité: {amount:.6f} {crypto}\n"
        msg += f"🎯 Profit: +{profit_pct:.2f}%\n\n"
        msg += f"🧠 Analyse:\n"
        msg += f"├─ Méthode: {method_display}\n"
        msg += f"├─ Probabilité: {confidence_emoji} {prediction['probability']}%\n"
        msg += f"├─ Confiance: {prediction['confidence_level']}\n"
        msg += f"└─ Horizon: {prediction['time_horizon']}\n\n"
        
        # Détail des facteurs
        factors = prediction.get('factors', {})
        if factors:
            msg += f"📊 Facteurs:\n"
            msg += f"├─ Volatilité: {factors.get('volatility_score', 0)}/100\n"
            msg += f"├─ Volume: {factors.get('volume_score', 0)}/100\n"
            msg += f"├─ Technique: {factors.get('technical_score', 0)}/100\n"
            msg += f"└─ Momentum: {factors.get('momentum_score', 0)}/100\n\n"
        
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
        msg += f"💸 Perte: {loss_pct:.1f}% ({loss_amount:.2f} USD)\n"
        msg += f"⏳ Durée: {duration}\n\n"
        msg += f"🎯 Action: {action}\n\n"
        msg += f"⏱️ {datetime.now().strftime('%H:%M:%S')}"
        self.notify(msg, "")
    
    def notify_cumulative_trend(self, symbol, direction, count, total_change_pct, current_price, start_price=None):
        """Notification tendance cumulative détectée - Désactivé (spam)"""
        return
        
        # Calcul valeur absolue si prix de départ disponible
        if start_price:
            price_change_abs = current_price - start_price
            change_display = f"{total_change_pct:.2f}% ({price_change_abs:+.2f} USD)"
            price_detail = f"├─ Prix départ: {start_price:.2f} USD\n"
        else:
            change_display = f"{total_change_pct:.2f}%"
            price_detail = ""
        
        msg = f"{direction_emoji} {direction_text.upper()}\n\n"
        msg += f"🪙 Crypto: {crypto}\n"
        msg += f"💰 Prix actuel: {current_price:.2f} USD\n"
        msg += price_detail
        msg += f"🎯 Élan: {count} impulsions\n"
        msg += f"📈 Cumul: {change_display}\n\n"
        msg += f"⚡ Analyse en cours...\n\n"
        msg += f"⏱️ {datetime.now().strftime('%H:%M:%S')}"
        self.notify(msg, "")
    
    def notify_volume_prediction(self, symbol, prediction):
        """Notification prédiction récupération volume avec valeurs absolues"""
        crypto = symbol.split('/')[0]
        
        # Anti-spam: max 1 notification par crypto par 30min
        notification_key = f"volume_{crypto}"
        now = time.time()
        if hasattr(self, 'last_volume_notifications'):
            if notification_key in self.last_volume_notifications:
                if now - self.last_volume_notifications[notification_key] < 1800:  # 30min
                    return False
        else:
            self.last_volume_notifications = {}
        
        self.last_volume_notifications[notification_key] = now
        
        # Formatage message avec valeurs absolues
        decline_duration = prediction['decline_duration_min']
        decline_pct = prediction['decline_pct']
        recovery_time = prediction['recovery_time_str']
        confidence = prediction['confidence']
        price_momentum = prediction['price_momentum']
        divergence = prediction['divergence_detected']
        current_price = prediction.get('current_price', 0)
        current_volume = prediction.get('current_volume', 0)
        previous_volume = prediction.get('previous_volume', 0)
        
        # SUPPRIMÉ: Code dupliqué et incorrect (previous_volume n'est pas défini ici)
        # Le volume_display est déjà calculé plus bas avec les bonnes valeurs
        
        if current_price > 0:
            price_change_abs = current_price * (price_momentum / 100)
            price_display = f"{price_momentum:+.1f}% ({price_change_abs:+.2f} USD)"
        else:
            price_display = f"{price_momentum:+.1f}%"
        
        # Émojis selon contexte
        trend_emoji = "📈" if price_momentum > 0 else "📉" if price_momentum < -0.5 else "➡️"
        confidence_emoji = "🎯" if confidence >= 80 else "📊" if confidence >= 60 else "❓"
        
        msg = f"📉 VOLUME EN BAISSE | {crypto}\n\n"
        msg += f"🔍 Analyse:\n"
        msg += f"├─ Baisse depuis: {decline_duration}min\n"
        
        # Récupérer le prix actuel
        current_price = self.bot_ref.get_price(symbol) if self.bot_ref else 0
        
        # Formater les volumes (CORRECTION: utiliser les bons champs)
        estimated_vol = prediction.get('estimated_vol_15m', 0)  # Volume actuel 15min
        avg_vol_24h = prediction.get('avg_volume_24h', 0)       # Moyenne 24h (volume par 15min)
        
        # RECALCULER le pourcentage basé sur les valeurs AFFICHÉES pour cohérence
        if avg_vol_24h > 0:
            decline_pct_display = ((estimated_vol - avg_vol_24h) / avg_vol_24h) * 100
        else:
            decline_pct_display = decline_pct  # Fallback sur valeur originale
        
        def format_volume(vol):
            if vol >= 1000000:
                return f"{vol/1000000:.1f}M"
            elif vol >= 1000:
                return f"{vol/1000:.0f}K"
            else:
                return f"{vol:.0f}"
        
        # Pour une BAISSE: afficher moyenne → volume actuel (ordre chronologique)
        volume_display = f"({format_volume(avg_vol_24h)} → {format_volume(estimated_vol)})"
        
        msg += f"├─ Intensité: {decline_pct_display:.1f}% {volume_display}\n"
        msg += f"└─ Prix: {current_price:.2f} USD ({trend_emoji} {price_momentum:+.1f}%)"
        
        if divergence:
            msg += " (divergence!)\n\n"
        else:
            msg += "\n\n"
        
        msg += f"⏰ Prédiction:\n"
        msg += f"├─ Récupération: {recovery_time}\n"
        msg += f"├─ Confiance: {confidence_emoji} {confidence}%\n"
        
        if prediction['historical_cycles'] > 0:
            msg += f"└─ Basé sur: {prediction['historical_cycles']} cycles\n\n"
        else:
            msg += f"└─ Basé sur: Analyse temps réel\n\n"
        
        # Action recommandée
        if divergence and confidence >= 70:
            msg += f"🎯 Action: Patience - Opportunité proche\n"
        elif confidence >= 60:
            msg += f"⏳ Action: Attendre récupération\n"
        else:
            msg += f"👀 Action: Surveiller évolution\n"
        return self.notify(msg, "")
    
    def notify_dynamic_level(self, symbol, level_type, price, distance_pct, current_price=None):
        """Notification niveau dynamique avec distance absolue"""
        crypto = symbol.split('/')[0]
        
        # FILTRAGE ANTI-SPAM
        # 1. Seulement si très proche (< 1% au lieu de 2%)
        if abs(distance_pct) >= 1.0:
            return False
        
        # 2. Seulement niveaux importants
        important_types = ['Pivot S1', 'Pivot R1', 'Support fort', 'Résistance forte', 'EMA 25', 'EMA 99']
        if level_type not in important_types:
            return False
        
        # 3. Limiter à 1 notification par crypto par heure
        notification_key = f"dynamic_{crypto}"
        now = time.time()
        if hasattr(self, 'last_dynamic_spam_check'):
            if notification_key in self.last_dynamic_spam_check:
                if now - self.last_dynamic_spam_check[notification_key] < 3600:  # 1 heure
                    return False
        else:
            self.last_dynamic_spam_check = {}
        
        self.last_dynamic_spam_check[notification_key] = now
        
        # Calcul distance absolue
        if current_price:
            distance_abs = abs(current_price - price)
            distance_display = f"{distance_pct:.1f}% ({distance_abs:.2f} USD)"
            current_price_line = f"💰 Prix actuel: {current_price:.2f} USD\n"
        else:
            distance_display = f"{distance_pct:.1f}%"
            current_price_line = ""
        
        msg = f"🎯 NIVEAU CRITIQUE\n\n"
        msg += f"🪙 Crypto: {crypto}\n"
        msg += f"📊 Type: {level_type}\n"
        msg += current_price_line
        msg += f"🎯 Niveau: {price:.2f} USD\n"
        msg += f"📏 Distance: {distance_display}\n\n"
        msg += f"⏱️ {datetime.now().strftime('%H:%M:%S')}"
        return self.notify(msg, "")
    
    def format_price_change(self, current_price, previous_price=None, change_pct=None):
        """Formateur unifié pour changements de prix"""
        if previous_price and change_pct:
            change_abs = current_price - previous_price
            return f"{change_pct:+.2f}% ({change_abs:+.2f} USD)"
        elif change_pct:
            change_abs = current_price * (change_pct / 100)
            return f"{change_pct:+.2f}% ({change_abs:+.2f} USD)"
        else:
            return f"{current_price:.2f} USD"

    def format_volume_change(self, current_volume, previous_volume=None, change_pct=None):
        """Formateur unifié pour changements de volume"""
        if previous_volume and change_pct:
            change_abs = current_volume - previous_volume
            if abs(change_abs) >= 1000000:
                change_display = f"{change_abs/1000000:+.1f}M"
            elif abs(change_abs) >= 1000:
                change_display = f"{change_abs/1000:+.0f}K"
            else:
                change_display = f"{change_abs:+.0f}"
            return f"{change_pct:+.1f}% ({change_display})"
        else:
            return f"{change_pct:+.1f}%" if change_pct else "N/A"
    
    def notify_daily_summary(self):
        if not self.bot_ref:
            return
        
        bot = self.bot_ref
        balance = bot.balance_manager.get_balance()
        current_balance = balance.get('USD', balance.get('USD', {})).get('free', 0)
        
        # Calculer capital total (USD + cryptos)
        total_value = current_balance
        for pair in os.getenv('TRADING_PAIRS', 'BTCUSD,ETHUSD').split(','):
            symbol = pair if '/' in pair else (f"{pair.strip()[:-3]}/{pair.strip()[-3:]}" if pair.strip().endswith('USD') else f"{pair.strip()[:3]}/{pair.strip()[3:]}")
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
        msg += f"├─ Début: {start_balance:.2f} USD\n"
        msg += f"├─ Fin: {total_value:.2f} USD\n"
        msg += f"└─ Variation: {variation:+.2f} ({variation_pct:+.1f}%)\n\n"
        msg += f"📈 Trading\n"
        msg += f"├─ Trades: {bot.total_trades} ({win_rate:.0f}% win)\n"
        msg += f"├─ P&L: {bot.daily_pnl:+.2f} USD\n"
        msg += f"└─ Frais: ~{bot.total_trades * 0.02:.2f} USD\n\n"
        msg += f"⏰ {datetime.now().strftime('%H:%M:%S')}"
        
        self.notify(msg, "")
        
        # Reset stats pour demain
        self.daily_stats['start_balance'] = total_value
        self.daily_stats['start_time'] = datetime.now()
    
    def notify_macro_event_start(self, event_type, event_info):
        """Notification début d'événement macro"""
        event_name = "Réunion FED" if event_type == "FED_MEETING" else "CPI Inflation" if event_type == "INFLATION_DATA" else "Incertitude Marché" if event_type == "MARKET_UNCERTAINTY" else event_type
        message = f"🤖 🚨 <b>MACRO EVENT DÉTECTÉ</b>\n\n"
        message += f"🏷️ <b>Type</b>: {event_name}\n"
        message += f"📋 <b>Description</b>: {event_info['description']}\n\n"
        message += f"🎁 <b>Bonus Score</b>: +{event_info['score_bonus']} points\n"
        message += f"🎯 <b>Réduction Seuil</b>: -{event_info['threshold_reduction']} points\n"
        message += f"⏰ <b>Durée Estimée</b>: {event_info['duration_hours']}h\n\n"
        message += f"🤖 Le bot s'adapte automatiquement aux conditions macro."
        return self.notify(message, "")
    
    def notify_macro_event_end(self, event_type, elapsed_hours):
        """Notification fin d'événement macro"""
        event_name = "Réunion FED" if event_type == "FED_MEETING" else "CPI Inflation" if event_type == "INFLATION_DATA" else "Incertitude Marché" if event_type == "MARKET_UNCERTAINTY" else event_type
        message = f"✅ <b>FIN MACRO EVENT</b>\n\n"
        message += f"🏷️ <b>Type</b>: {event_name}\n"
        message += f"⏱️ <b>Durée</b>: {elapsed_hours:.1f}h\n\n"
        message += f"🔄 Le bot reprend ses paramètres normaux."
        return self.notify(message, "")
    
    def send_status_update(self):
        """Envoie le status périodique selon TELEGRAM_STATUS_INTERVAL."""
        with self._status_lock:
            now = time.time()
            logger = getattr(self.bot_ref, 'ml_live_logger', None) if self.bot_ref else None
            if logger:
                claimed = logger.claim_interval(
                    'telegram_last_status_time',
                    self.periodic_interval,
                    now=now,
                    initialize_only=self.last_status_time <= 0
                )
                self.last_status_time = now
                if not claimed:
                    return False
            else:
                if now - self.last_status_time < self.periodic_interval:
                    return False
                self.last_status_time = now

        if not self.bot_ref:
            return False

        try:
            status = self._build_status_message()
            return self.notify(status, "")
        except Exception:
            return False
            
    def _get_historical_performance(self):
        """Calcule les statistiques de performance réelles basées sur l'historique des positions du bot"""
        if not self.bot_ref or not hasattr(self.bot_ref, 'state'):
            return None
            
        positions = self.bot_ref.state.get('positions', [])
        buys = {}
        trades = []
        
        # Parcourir les positions triées chronologiquement
        for pos in sorted(positions, key=lambda p: p.get('timestamp', '')):
            symbol = pos.get('symbol')
            side = pos.get('side')
            amount = float(pos.get('amount') or 0)
            px = float(pos.get('price') or 0)
            if not symbol or amount <= 0 or px <= 0:
                continue
                
            if side == 'buy':
                buys.setdefault(symbol, []).append({
                    'amount': amount, 'price': px
                })
            elif side == 'sell':
                remaining = amount
                queue = buys.get(symbol, [])
                while remaining > 1e-12 and queue:
                    entry = queue[0]
                    filled = min(remaining, entry['amount'])
                    
                    # Estimer les frais (0.4% taker Kraken par défaut)
                    fee_rate = getattr(self.bot_ref, 'trading_fee', 0.004)
                    buy_cost = entry['price'] * filled * (1 + fee_rate)
                    sell_revenue = px * filled * (1 - fee_rate)
                    pnl = sell_revenue - buy_cost
                    
                    trades.append({
                        'pnl': pnl,
                        'profitable': pnl > 0
                    })
                    
                    entry['amount'] -= filled
                    remaining -= filled
                    if entry['amount'] <= 1e-12:
                        queue.pop(0)
                        
        if not trades:
            return None
            
        wins = [t for t in trades if t['profitable']]
        total_pnl = sum(t['pnl'] for t in trades)
        best_trade = max(t['pnl'] for t in trades) if trades else 0
        
        return {
            'total_pnl': total_pnl,
            'total_trades': len(trades),
            'winrate': (len(wins) / len(trades)) * 100 if trades else 0,
            'best_trade': best_trade
        }

    def _build_status_message(self):
        """Construit message status ultra-compact"""
        
        def format_amount(amount, crypto):
            """Formate la quantité avec décimales adaptatives"""
            if amount < 0.001:
                return f"{amount:.8f}".rstrip('0').rstrip('.')
            elif amount < 0.01:
                return f"{amount:.6f}".rstrip('0').rstrip('.')
            elif amount < 1:
                return f"{amount:.4f}".rstrip('0').rstrip('.')
            else:
                return f"{amount:.3f}".rstrip('0').rstrip('.')
        
        bot = self.bot_ref
        balance = bot.balance_manager.get_balance()
        usd = balance.get('USD', balance.get('USD', {})).get('free', 0)
        
        # Portfolio avec détail des ordres et P&L
        portfolio_items = []
        total_value = usd
        
        for pair in os.getenv('TRADING_PAIRS', 'BTCUSD,ETHUSD').split(','):
            symbol = pair if '/' in pair else (f"{pair.strip()[:-3]}/{pair.strip()[-3:]}" if pair.strip().endswith('USD') else f"{pair.strip()[:3]}/{pair.strip()[3:]}")
            crypto = symbol.split('/')[0]
            free = balance.get(crypto, {}).get('free', 0)
            locked = balance.get(crypto, {}).get('used', 0)
            total = free + locked
            
            if total > 0.00001:
                price = bot.get_price(symbol)
                value = total * price
                if value >= bot.get_min_amount(symbol)['min_cost']:
                    # Calculer P&L de la position
                    try:
                        avg_buy_price = bot.get_real_buy_price(symbol)
                        if avg_buy_price and avg_buy_price > 0:
                            pnl_pct = ((price - avg_buy_price) / avg_buy_price) * 100
                            pnl_usd = (price - avg_buy_price) * total
                            pnl_display = f" • {pnl_pct:+.1f}% ({pnl_usd:+.1f} USD)"
                        else:
                            pnl_display = ""
                    except:
                        pnl_display = ""
                    
                    portfolio_items.append({
                        'crypto': crypto,
                        'symbol': symbol,
                        'amount': total,
                        'value': value,
                        'pnl_display': pnl_display,
                        'has_orders': locked > 0
                    })
                    total_value += value
        
        # Macro Security section
        macro_text = ""
        try:
            if hasattr(bot, 'market_analyzer') and bot.market_analyzer is not None:
                macro_mgr = bot.market_analyzer._get_macro_manager()
            else:
                from utils.event_manager import MacroEventManager
                macro_mgr = MacroEventManager()
                
            if macro_mgr and macro_mgr.current_event:
                event_type = macro_mgr.current_event
                event_name = "Réunion FED" if event_type == "FED_MEETING" else "CPI Inflation" if event_type == "INFLATION_DATA" else "Incertitude Marché" if event_type == "MARKET_UNCERTAINTY" else event_type
                info = macro_mgr.current_event_info or {}
                desc = info.get('description', '')
                elapsed = (time.time() - macro_mgr.event_start_time) / 3600 if macro_mgr.event_start_time else 0
                duration = info.get('duration_hours', 24)
                remaining = max(0, duration - elapsed)
                bonus = info.get('score_bonus', 0)
                reduction = info.get('threshold_reduction', 0)
                
                macro_text = f"🤖 🔴 <b>Macro-Securité : {event_name}</b>\n"
                macro_text += f"──────────────────────────\n"
                if desc:
                    macro_text += f"{desc}\n\n"
                macro_text += f"⏱️ <b>Temps restant</b> : {remaining:.1f}h / {duration}h\n"
                macro_text += f"⚖️ <b>Ajustements appliqués</b> :\n"
                macro_text += f"   • Bonus de Score : +{bonus}\n"
                macro_text += f"   • Seuil d'Entrée : -{reduction}\n"
                macro_text += f"──────────────────────────\n\n"
        except Exception as e:
            pass

        msg = f"🤖 {BOT_NAME} | STATUS {datetime.now().strftime('%H:%M')}\n\n"
        msg += macro_text
        msg += f"💼 Portfolio ({total_value:.2f} USD)\n"
        msg += f"├─ USD: {usd:.2f}\n"
        
        # Afficher chaque crypto avec détail des ordres
        for i, item in enumerate(portfolio_items):
            is_last = (i == len(portfolio_items) - 1)
            prefix = "└─" if is_last else "├─"
            
            msg += f"{prefix} {item['crypto']}: {format_amount(item['amount'], item['crypto'])} • {item['value']:.2f} USD{item['pnl_display']}\n"
            
            # Détail des ordres pour cette crypto
            if item['has_orders']:
                try:
                    open_orders = bot.exchange.fetch_open_orders(f"{item['crypto']}/USD")
                    if open_orders:
                        for j, order in enumerate(open_orders):
                            is_last_order = (j == len(open_orders) - 1)
                            order_prefix = "     └─" if (is_last and is_last_order) else "   ├─" if is_last else "│  └─" if is_last_order else "│  ├─"
                            
                            order_price = float(order['price'])
                            try:
                                avg_buy_price = bot.get_real_buy_price(item['symbol'])
                                if avg_buy_price and avg_buy_price > 0:
                                    gross_profit_pct = ((order_price - avg_buy_price) / avg_buy_price) * 100
                                    profit_pct = gross_profit_pct - 0.2
                                else:
                                    current_price = bot.get_price(item['symbol'])
                                    profit_pct = ((order_price - current_price) / current_price) * 100
                            except:
                                current_price = bot.get_price(item['symbol'])
                                profit_pct = ((order_price - current_price) / current_price) * 100
                            
                            order_time = datetime.fromtimestamp(order['timestamp'] / 1000)
                            time_diff = datetime.now() - order_time
                            
                            if time_diff.days > 0:
                                hours = time_diff.seconds // 3600
                                time_display = f"{time_diff.days}j {hours}h"
                            elif time_diff.seconds >= 3600:
                                hours = time_diff.seconds // 3600
                                minutes = (time_diff.seconds % 3600) // 60
                                time_display = f"{hours}h {minutes}min"
                            else:
                                time_display = f"{time_diff.seconds // 60}min"
                            
                            msg += f"{order_prefix} Limite: {format_amount(float(order['amount']), item['crypto'])} @ {order_price:.2f}\n"
                            detail_prefix = "     │  ├─" if (is_last and not is_last_order) else "        ├─" if is_last else "│  │  ├─" if not is_last_order else "│     ├─"
                            msg += f"{detail_prefix} Profit: +{profit_pct:.1f}%\n"
                            detail_prefix2 = "     │  └─" if (is_last and not is_last_order) else "        └─" if is_last else "│  │  └─" if not is_last_order else "│     └─"
                            msg += f"{detail_prefix2} Durée: {time_display}\n"
                    else:
                        order_prefix = "   └─" if is_last else "│  └─"
                        msg += f"{order_prefix} 🤖 Ordre actif (détails indisponibles)\n"
                except Exception as e:
                    order_prefix = "   └─" if is_last else "│  └─"
                    msg += f"{order_prefix} 🤖 Ordre actif\n"
        
        msg += f"\n"
        msg += f"📈 Performance\n"
        
        stats = self._get_historical_performance()
        if stats:
            msg += f"├─ P&L: {stats['total_pnl']:+.2f} USD\n"
            msg += f"├─ Trades: {stats['total_trades']} ({stats['winrate']:.0f}% win)\n"
            if stats['best_trade'] > 0 or stats['total_trades'] > 0:
                msg += f"└─ Meilleur: {stats['best_trade']:+.2f} USD\n\n"
            else:
                msg += f"└─ Aucun trade\n\n"
        else:
            msg += f"├─ P&L: +0.00 USD\n"
            msg += f"├─ Trades: 0 (0% win)\n"
            msg += f"└─ Aucun trade\n\n"
            
        # Section Prochains Événements Macro
        try:
            from utils.event_manager import MacroEventManager
            macro_mgr = MacroEventManager()
            now = time.time()
            upcoming = []
            from datetime import timezone
            
            for item in macro_mgr.macro_calendar_2026:
                event_dt = datetime.fromisoformat(item['date']).replace(tzinfo=timezone.utc)
                event_ts = event_dt.timestamp()
                if event_ts > now:
                    local_dt = datetime.fromtimestamp(event_ts)
                    event_name = "FED" if item['event'] == "FED_MEETING" else "CPI Inflation" if item['event'] == "INFLATION_DATA" else "Incertitude Marché"
                    date_display = local_dt.strftime("%d/%m à %H:%M")
                    upcoming.append((event_ts, f"{event_name} : {date_display}"))
            
            upcoming.sort(key=lambda x: x[0])
            next_events = upcoming[:2]
            
            msg += f"📅 <b>Événements Macro à venir</b>\n"
            if next_events:
                for i, (_, text) in enumerate(next_events):
                    prefix = "├─" if i < len(next_events) - 1 else "└─"
                    msg += f"{prefix} {text}\n"
            else:
                msg += "└─ Aucun événement à venir\n"
        except Exception as e:
            pass
        
        return msg
