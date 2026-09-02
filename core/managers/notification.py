import requests
import os
import time
import threading
import io
from datetime import datetime, timedelta
from config import BOT_NAME

# Import matplotlib avec backend non-interactif
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

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
        self.daily_status_enabled = os.getenv('TELEGRAM_DAILY_STATUS_ENABLED', 'true').lower() == 'true'
        self.daily_status_hour = int(os.getenv('TELEGRAM_DAILY_STATUS_HOUR', '8'))
        self.last_status_time = 0
        self.last_status_day = None
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
                        parts = text.split()
                        command = parts[0].lower()
                        args = parts[1:] if len(parts) > 1 else []
                        self._handle_telegram_command(command, args)
                        
            except Exception as e:
                # Éviter de saturer la boucle en cas d'erreur réseau
                time.sleep(10)

    def _handle_telegram_command(self, command, args=None):
        """Traite une commande reçue depuis Telegram"""
        args = args or []
        
        # Afficher "en train d'écrire" pour toutes les commandes
        self.send_typing_action()
        
        if command == '/pause':
            try:
                if not self.bot_ref:
                    self.notify("⚠️ Bot non disponible", "")
                    return
                self.bot_ref.paused = True
                self.notify("⏸️ <b>Bot en PAUSE</b>\n\nLe trading est suspendu. Les positions ouvertes restent surveillées.\nUtilisez /resume pour reprendre.", "")
            except Exception as e:
                self.notify(f"⚠️ Erreur pause : {e}", "")
                
        elif command == '/resume':
            try:
                if not self.bot_ref:
                    self.notify("⚠️ Bot non disponible", "")
                    return
                self.bot_ref.paused = False
                self.notify("▶️ <b>Bot ACTIF</b>\n\nLe trading a repris normalement.", "")
            except Exception as e:
                self.notify(f"⚠️ Erreur resume : {e}", "")
                
        elif command == '/balance':
            try:
                msg = self._build_balance_message()
                self.notify(msg, "")
            except Exception as e:
                self.notify(f"⚠️ Erreur balance : {e}", "")
                
        elif command == '/pnl':
            try:
                msg = self._build_pnl_message()
                self.notify(msg, "")
            except Exception as e:
                self.notify(f"⚠️ Erreur PnL : {e}", "")
                
        elif command == '/ml':
            try:
                msg = self._build_ml_status_message()
                self.notify(msg, "")
            except Exception as e:
                self.notify(f"⚠️ Erreur ML status : {e}", "")
                
        elif command == '/health':
            try:
                msg = self._build_health_message()
                self.notify(msg, "")
            except Exception as e:
                self.notify(f"⚠️ Erreur health : {e}", "")
                
        elif command == '/sell':
            try:
                if not args:
                    self.notify("⚠️ Usage: /sell SYMBOL\nExemple: /sell ADA", "")
                    return
                symbol_arg = args[0].upper()
                msg = self._execute_force_sell(symbol_arg)
                self.notify(msg, "")
            except Exception as e:
                self.notify(f"⚠️ Erreur sell : {e}", "")
                
        elif command == '/cooldown':
            try:
                if len(args) < 2:
                    self.notify("⚠️ Usage: /cooldown SYMBOL MINUTES\nExemple: /cooldown ADA 30", "")
                    return
                symbol_arg = args[0].upper()
                try:
                    minutes = int(args[1])
                except ValueError:
                    self.notify("⚠️ Les minutes doivent être un nombre entier", "")
                    return
                msg = self._execute_add_cooldown(symbol_arg, minutes)
                self.notify(msg, "")
            except Exception as e:
                self.notify(f"⚠️ Erreur cooldown : {e}", "")
                
        elif command == '/events':
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
                # Générer le graphique PnL
                pnl_chart = self._generate_pnl_chart(days=30)
                
                if pnl_chart:
                    # Mode compact (caption max 1024 chars) + image
                    status_msg = self._build_status_message(compact=True)
                    
                    # Envoyer en arrière-plan
                    def send_status_with_chart():
                        try:
                            if not self.send_photo(pnl_chart, caption=status_msg):
                                # Fallback : texte seul si envoi échoue
                                self.notify(status_msg, "")
                        except Exception:
                            self.notify(status_msg, "")
                    
                    threading.Thread(target=send_status_with_chart, daemon=True).start()
                else:
                    # Pas d'image : message complet
                    status_msg = self._build_status_message(compact=False)
                    self.notify(status_msg, "")
            except Exception as e:
                self.notify(f"⚠️ Erreur status : {e}", "")
                
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

        elif command in ('/positions', '/open', '/attentes'):
            try:
                msg = self._build_positions_message()
                self.notify(msg, "")
            except Exception as e:
                self.notify(f"⚠️ Erreur lors de la récupération des positions : {e}", "")

        elif command in ('/history', '/trades', '/ventes'):
            try:
                msg = self._build_history_message()
                self.notify(msg, "")
            except Exception as e:
                self.notify(f"⚠️ Erreur lors de la génération de l'historique : {e}", "")
                
        elif command == '/help' or command == '/start':
            msg = "🤖 <b>COMMANDES DISPONIBLES</b>\n\n"
            msg += "<b>📊 Informations</b>\n"
            msg += "• /status - État du bot et portefeuille\n"
            msg += "• /balance - Solde détaillé (USD + cryptos)\n"
            msg += "• /positions - Positions ouvertes\n"
            msg += "• /history - Derniers trades fermés\n"
            msg += "• /pnl - PnL jour/semaine/mois\n"
            msg += "• /events - Événements macro\n\n"
            msg += "<b>🧠 ML & Santé</b>\n"
            msg += "• /ml - Statut modèle ML\n"
            msg += "• /health - Santé du bot\n\n"
            msg += "<b>⚙️ Contrôle</b>\n"
            msg += "• /pause - Suspendre le trading\n"
            msg += "• /resume - Reprendre le trading\n"
            msg += "• /sell &lt;SYM&gt; - Forcer vente (ex: /sell ADA)\n"
            msg += "• /cooldown &lt;SYM&gt; &lt;min&gt; - Cooldown manuel\n"
            msg += "• /restart - Redémarrer le bot"
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

    def _build_balance_message(self):
        """Construit le message de solde détaillé"""
        if not self.bot_ref:
            return "⚠️ Bot non disponible"
        
        bot = self.bot_ref
        balance = bot.balance_manager.get_balance()
        usd_free = balance.get('USD', {}).get('free', 0)
        
        msg = "💰 <b>SOLDE DÉTAILLÉ</b>\n\n"
        msg += f"💵 <b>USD</b>: {usd_free:.2f} $\n\n"
        
        total_crypto_value = 0
        pairs = os.getenv('TRADING_PAIRS', 'BTCUSD,ETHUSD,SOLUSD,ADAUSD').split(',')
        
        for pair in pairs:
            pair = pair.strip()
            if '/' in pair:
                symbol = pair
            elif pair.endswith('USD'):
                symbol = f"{pair[:-3]}/{pair[-3:]}"
            else:
                symbol = f"{pair[:3]}/{pair[3:]}"
            
            crypto = symbol.split('/')[0]
            amount = balance.get(crypto, {}).get('free', 0)
            
            if amount > 0.000001:
                price = bot.get_price(symbol)
                value = amount * price
                total_crypto_value += value
                msg += f"🪙 <b>{crypto}</b>: {amount:.6f} (~{value:.2f} $)\n"
        
        total = usd_free + total_crypto_value
        msg += f"\n📊 <b>TOTAL</b>: {total:.2f} $"
        
        return msg
    
    def _build_pnl_message(self):
        """Construit le message PnL jour/semaine/mois"""
        if not self.bot_ref:
            return "⚠️ Bot non disponible"
        
        try:
            from ui.server import compute_trade_history, load_accounting_state
            state = load_accounting_state({'positions': []}, view_mode='live')
            positions = state.get('positions', [])
            trades = compute_trade_history(positions)
        except Exception:
            trades = []
        
        now = datetime.now()
        today = now.date()
        week_ago = today - timedelta(days=7)
        month_ago = today - timedelta(days=30)
        
        pnl_day = 0
        pnl_week = 0
        pnl_month = 0
        trades_day = 0
        trades_week = 0
        trades_month = 0
        
        for t in trades:
            try:
                closed_at = t.get('closed_at') or t.get('sell_time')
                if not closed_at:
                    continue
                if isinstance(closed_at, str):
                    trade_date = datetime.fromisoformat(closed_at.replace('Z', '')).date()
                else:
                    trade_date = closed_at.date() if hasattr(closed_at, 'date') else today
                
                pnl = float(t.get('pnl_net') or t.get('pnl') or 0)
                
                if trade_date == today:
                    pnl_day += pnl
                    trades_day += 1
                if trade_date >= week_ago:
                    pnl_week += pnl
                    trades_week += 1
                if trade_date >= month_ago:
                    pnl_month += pnl
                    trades_month += 1
            except Exception:
                continue
        
        def fmt_pnl(pnl):
            emoji = "🟢" if pnl >= 0 else "🔴"
            return f"{emoji} {pnl:+.2f} $"
        
        msg = "📈 <b>PERFORMANCE P&L</b>\n\n"
        msg += f"📅 <b>Aujourd'hui</b>\n"
        msg += f"   {fmt_pnl(pnl_day)} ({trades_day} trades)\n\n"
        msg += f"📆 <b>7 derniers jours</b>\n"
        msg += f"   {fmt_pnl(pnl_week)} ({trades_week} trades)\n\n"
        msg += f"🗓️ <b>30 derniers jours</b>\n"
        msg += f"   {fmt_pnl(pnl_month)} ({trades_month} trades)"
        
        return msg
    
    def _build_ml_status_message(self):
        """Construit le message de statut ML"""
        if not self.bot_ref:
            return "⚠️ Bot non disponible"
        
        bot = self.bot_ref
        ml_engine = getattr(bot, 'ml_engine', None)
        
        msg = "🧠 <b>STATUT ML</b>\n\n"
        
        if not ml_engine:
            msg += "⚠️ ML Engine non disponible"
            return msg
        
        # Modèle entry
        has_entry = ml_engine.model is not None
        msg += f"📥 <b>Entry Model</b>: {'✅ Actif' if has_entry else '❌ Absent'}\n"
        
        # Modèle exit
        has_exit = ml_engine.exit_model is not None
        msg += f"📤 <b>Exit Model</b>: {'✅ Actif' if has_exit else '❌ Absent'}\n"
        
        # Modèle sizing
        has_sizing = ml_engine.sizing_model is not None
        msg += f"📊 <b>Sizing Model</b>: {'✅ Actif' if has_sizing else '❌ Absent'}\n"
        
        # Modèle target
        has_target = ml_engine.target_model is not None
        msg += f"🎯 <b>Target Model</b>: {'✅ Actif' if has_target else '❌ Absent'}\n\n"
        
        # Dernières prédictions
        try:
            logger = getattr(bot, 'ml_live_logger', None)
            if logger:
                from sqlalchemy import select, desc
                from core.db_orm import DecisionLog
                with logger._orm_session() as session:
                    last_decision = session.scalars(
                        select(DecisionLog)
                        .where(DecisionLog.mode == ('live' if not bot.paper_trading else 'paper'))
                        .order_by(desc(DecisionLog.created_at))
                        .limit(1)
                    ).first()
                    
                    if last_decision:
                        msg += f"<b>Dernière décision</b>\n"
                        msg += f"├─ Symbole: {last_decision.symbol}\n"
                        msg += f"├─ Décision: {last_decision.decision}\n"
                        if last_decision.p_win:
                            msg += f"├─ P_win: {float(last_decision.p_win):.1f}%\n"
                        msg += f"└─ {last_decision.created_at[:16]}"
        except Exception:
            pass
        
        return msg
    
    def _build_health_message(self):
        """Construit le message de santé du bot"""
        if not self.bot_ref:
            return "⚠️ Bot non disponible"
        
        bot = self.bot_ref
        health_mgr = getattr(bot, 'health_manager', None)
        
        if not health_mgr:
            return "⚠️ HealthManager non disponible"
        
        try:
            results = health_mgr.run_checks()
            summary = health_mgr.get_summary_text(results)
            return summary
        except Exception as e:
            return f"⚠️ Erreur health check : {e}"
    
    def _execute_force_sell(self, symbol_arg):
        """Force la vente d'une position"""
        if not self.bot_ref:
            return "⚠️ Bot non disponible"
        
        bot = self.bot_ref
        
        # Trouver le symbole complet
        symbol = None
        pairs = os.getenv('TRADING_PAIRS', 'BTCUSD,ETHUSD,SOLUSD,ADAUSD').split(',')
        for pair in pairs:
            pair = pair.strip()
            if '/' in pair:
                s = pair
            elif pair.endswith('USD'):
                s = f"{pair[:-3]}/{pair[-3:]}"
            else:
                s = f"{pair[:3]}/{pair[3:]}"
            
            if s.startswith(symbol_arg + '/') or s.split('/')[0] == symbol_arg:
                symbol = s
                break
        
        if not symbol:
            return f"⚠️ Symbole {symbol_arg} non trouvé dans les paires tradées"
        
        # Vérifier qu'il y a une position ouverte
        positions = getattr(bot, 'state', {}).get('positions', [])
        position = None
        for p in positions:
            if p.get('symbol') == symbol and p.get('status') == 'open':
                position = p
                break
        
        if not position:
            return f"⚠️ Aucune position ouverte sur {symbol_arg}"
        
        # Exécuter la vente
        try:
            amount = position.get('amount', 0)
            price = bot.get_price(symbol)
            
            if bot.paper_trading:
                # Vente paper
                result = bot.sell_market(symbol, amount, reason='telegram_force_sell')
            else:
                # Vente live
                result = bot.sell_market(symbol, amount, reason='telegram_force_sell')
            
            if result:
                return f"✅ <b>VENTE FORCÉE</b>\n\n🪙 {symbol_arg}\n💰 {amount:.6f}\n💵 ~{amount * price:.2f} $\n\n<i>Ordre envoyé avec succès</i>"
            else:
                return f"⚠️ Échec de la vente de {symbol_arg}"
        except Exception as e:
            return f"⚠️ Erreur vente : {e}"
    
    def _execute_add_cooldown(self, symbol_arg, minutes):
        """Ajoute un cooldown manuel sur un symbole"""
        if not self.bot_ref:
            return "⚠️ Bot non disponible"
        
        bot = self.bot_ref
        
        # Trouver le symbole complet
        symbol = None
        pairs = os.getenv('TRADING_PAIRS', 'BTCUSD,ETHUSD,SOLUSD,ADAUSD').split(',')
        for pair in pairs:
            pair = pair.strip()
            if '/' in pair:
                s = pair
            elif pair.endswith('USD'):
                s = f"{pair[:-3]}/{pair[-3:]}"
            else:
                s = f"{pair[:3]}/{pair[3:]}"
            
            if s.startswith(symbol_arg + '/') or s.split('/')[0] == symbol_arg:
                symbol = s
                break
        
        if not symbol:
            return f"⚠️ Symbole {symbol_arg} non trouvé dans les paires tradées"
        
        # Ajouter le cooldown
        try:
            cooldown_until = time.time() + (minutes * 60)
            
            # Utiliser le système de cooldown existant
            if hasattr(bot, 'cooldowns'):
                bot.cooldowns[symbol] = cooldown_until
            elif hasattr(bot, 'state') and 'cooldowns' in bot.state:
                bot.state['cooldowns'][symbol] = cooldown_until
            else:
                return f"⚠️ Système de cooldown non disponible"
            
            end_time = datetime.fromtimestamp(cooldown_until).strftime('%H:%M:%S')
            return f"⏳ <b>COOLDOWN AJOUTÉ</b>\n\n🪙 {symbol_arg}\n⏰ Durée: {minutes} min\n🔚 Fin: {end_time}"
        except Exception as e:
            return f"⚠️ Erreur cooldown : {e}"

    def _generate_pnl_chart(self, days=30):
        """Génère un graphique du PnL NET cumulé sur X jours"""
        if not MATPLOTLIB_AVAILABLE:
            return None
        
        try:
            from ui.server import compute_trade_history, load_accounting_state
            state = load_accounting_state({'positions': []}, view_mode='live')
            positions = state.get('positions', [])
            trades = compute_trade_history(positions)
        except Exception:
            return None
        
        if not trades:
            return None
        
        # Filtrer les trades des X derniers jours
        cutoff = datetime.now() - timedelta(days=days)
        daily_pnl = {}
        
        for t in trades:
            try:
                closed_at = t.get('closed_at') or t.get('sell_time')
                if not closed_at:
                    continue
                if isinstance(closed_at, str):
                    trade_dt = datetime.fromisoformat(closed_at.replace('Z', ''))
                else:
                    trade_dt = closed_at
                
                if trade_dt < cutoff:
                    continue
                
                trade_date = trade_dt.date()
                # Utiliser pnl_net (après frais) en priorité
                pnl = float(t.get('pnl_net') or t.get('pnl') or 0)
                daily_pnl[trade_date] = daily_pnl.get(trade_date, 0) + pnl
            except Exception:
                continue
        
        if not daily_pnl:
            return None
        
        # Trier par date et calculer le cumulé
        sorted_dates = sorted(daily_pnl.keys())
        cumulative = []
        total = 0
        for d in sorted_dates:
            total += daily_pnl[d]
            cumulative.append(total)
        
        # Créer le graphique
        fig, ax = plt.subplots(figsize=(8, 4), facecolor='#1a1a2e')
        ax.set_facecolor('#1a1a2e')
        
        # Couleur selon PnL final
        color = '#00d26a' if total >= 0 else '#ff4757'
        
        ax.plot(sorted_dates, cumulative, color=color, linewidth=2.5, marker='o', markersize=4)
        ax.fill_between(sorted_dates, cumulative, alpha=0.3, color=color)
        
        # Ligne zéro
        ax.axhline(y=0, color='#ffffff', linewidth=0.5, alpha=0.3, linestyle='--')
        
        # Style - Titre clarifié (PnL NET)
        ax.set_title(f'PnL Net Cumulé ({days}j)', color='white', fontsize=14, fontweight='bold', pad=10)
        ax.set_xlabel('', color='#888888', fontsize=10)  # Pas de label X
        ax.set_ylabel('PnL Net (USD)', color='#888888', fontsize=10)
        ax.tick_params(colors='#888888', labelsize=9)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['bottom'].set_color('#333333')
        ax.spines['left'].set_color('#333333')
        ax.grid(True, alpha=0.1, color='white')
        
        # Format des dates - Max 4 ticks, pas de rotation
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m'))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=4))
        plt.xticks(rotation=0)  # Pas d'inclinaison
        
        # Annotation du total
        ax.annotate(f'{total:+.2f} $', xy=(sorted_dates[-1], cumulative[-1]), 
                    xytext=(10, 0), textcoords='offset points',
                    color=color, fontsize=12, fontweight='bold')
        
        plt.tight_layout()
        
        # Sauvegarder en buffer
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, facecolor='#1a1a2e', edgecolor='none')
        buf.seek(0)
        plt.close(fig)
        
        return buf
    
    def _generate_portfolio_chart(self):
        """Génère un pie chart de répartition du portfolio"""
        if not MATPLOTLIB_AVAILABLE or not self.bot_ref:
            return None
        
        bot = self.bot_ref
        balance = bot.balance_manager.get_balance()
        usd = balance.get('USD', {}).get('free', 0)
        
        labels = ['USD']
        sizes = [usd]
        colors = ['#4ecdc4']
        
        pairs = os.getenv('TRADING_PAIRS', 'BTCUSD,ETHUSD,SOLUSD,ADAUSD').split(',')
        color_map = {'BTC': '#f7931a', 'ETH': '#627eea', 'SOL': '#00ffa3', 'ADA': '#0033ad'}
        
        for pair in pairs:
            pair = pair.strip()
            if '/' in pair:
                symbol = pair
            elif pair.endswith('USD'):
                symbol = f"{pair[:-3]}/{pair[-3:]}"
            else:
                symbol = f"{pair[:3]}/{pair[3:]}"
            
            crypto = symbol.split('/')[0]
            amount = balance.get(crypto, {}).get('free', 0) + balance.get(crypto, {}).get('used', 0)
            
            if amount > 0.000001:
                price = bot.get_price(symbol)
                value = amount * price
                if value >= 0.5:  # Minimum 0.5$ pour apparaître
                    labels.append(crypto)
                    sizes.append(value)
                    colors.append(color_map.get(crypto, '#888888'))
        
        if sum(sizes) < 1:
            return None
        
        # Créer le graphique
        fig, ax = plt.subplots(figsize=(6, 6), facecolor='#1a1a2e')
        
        wedges, texts, autotexts = ax.pie(
            sizes, 
            labels=labels, 
            autopct=lambda pct: f'{pct:.1f}%' if pct > 5 else '',
            colors=colors,
            startangle=90,
            wedgeprops=dict(width=0.6, edgecolor='#1a1a2e', linewidth=2),
            textprops={'color': 'white', 'fontsize': 10}
        )
        
        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontweight('bold')
        
        # Total au centre
        total = sum(sizes)
        ax.text(0, 0, f'{total:.2f}$', ha='center', va='center', 
                fontsize=16, fontweight='bold', color='white')
        
        ax.set_title('Répartition Portfolio', color='white', fontsize=14, fontweight='bold', pad=10)
        
        plt.tight_layout()
        
        # Sauvegarder en buffer
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, facecolor='#1a1a2e', edgecolor='none')
        buf.seek(0)
        plt.close(fig)
        
        return buf
    
    def send_photo(self, photo_buffer, caption=""):
        """Envoie une photo via Telegram"""
        if not self.enabled or not photo_buffer:
            return False
        
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendPhoto"
            files = {'photo': ('chart.png', photo_buffer, 'image/png')}
            data = {'chat_id': self.chat_id}
            if caption:
                data['caption'] = caption
                data['parse_mode'] = 'HTML'
            
            response = requests.post(url, files=files, data=data, timeout=10)
            return response.status_code == 200
        except Exception as e:
            print(f"⚠️ Erreur envoi photo Telegram: {e}")
            return False

    def send_media_group(self, images, caption=""):
        """Envoie plusieurs images groupées avec un caption sur la première"""
        if not self.enabled or not images:
            return False
        
        try:
            import json as json_module
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMediaGroup"
            
            files = {}
            media = []
            
            for i, img_buffer in enumerate(images):
                if img_buffer is None:
                    continue
                attach_name = f"photo{i}"
                files[attach_name] = (f'chart{i}.png', img_buffer, 'image/png')
                
                media_item = {
                    "type": "photo",
                    "media": f"attach://{attach_name}"
                }
                # Caption seulement sur la première image
                if i == 0 and caption:
                    media_item["caption"] = caption
                    media_item["parse_mode"] = "HTML"
                
                media.append(media_item)
            
            if not media:
                return False
            
            data = {
                'chat_id': self.chat_id,
                'media': json_module.dumps(media)
            }
            
            response = requests.post(url, data=data, files=files, timeout=15)
            return response.status_code == 200
        except Exception as e:
            print(f"⚠️ Erreur envoi media group Telegram: {e}")
            return False

    def send_typing_action(self):
        """Envoie l'indicateur 'en train d'écrire' à Telegram"""
        if not self.enabled:
            return False
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendChatAction"
            data = {'chat_id': self.chat_id, 'action': 'typing'}
            requests.post(url, data=data, timeout=3)
            return True
        except Exception:
            return False

    def notify(self, message, emoji="🤖"):
        full_text = f"{emoji} {message}".strip() if emoji else message
        if not self.enabled:
            print(f"📢 {full_text}")
            return False
            
        def _send():
            try:
                url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
                data = {
                    'chat_id': self.chat_id,
                    'text': full_text,
                    'parse_mode': 'HTML'
                }
                response = requests.post(url, data=data, timeout=5)
                if response.status_code == 200:
                    res_json = response.json()
                    if res_json.get('ok') and 'result' in res_json:
                        msg_id = res_json['result'].get('message_id')
                        ts = res_json['result'].get('date')
                        self.save_telegram_message_history(msg_id, full_text, ts)
            except Exception as e:
                print(f"📢 {full_text}")

        import threading
        threading.Thread(target=_send, daemon=True).start()
        return True
    
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
    
    def notify_trade_sell(self, symbol, amount, price, total, buy_price, pnl, hold_time, reason=None):
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

        title = "🔴 SORTIE" if reason else "🔴 VENTE"
        msg = f"{title} {crypto}\n\n"
        msg += f"💰 Montant: {amount:.6f} {crypto}\n"
        msg += f"💵 Prix: {price:.2f} USD\n"
        msg += f"📊 Total: {total:.2f} USD\n\n"
        msg += f"💸 P&L: {emoji} {pnl:+.2f} USD ({sign}{pnl_pct:.2f}%)\n"
        if reason:
            readable_reason = str(reason).replace('_', ' ')
            msg += f"🧠 Raison: {readable_reason}\n"
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
        msg += f"💸 Perte: {loss_pct:.2f}% ({loss_amount:.2f} USD)\n"
        msg += f"⏳ Durée: {duration}\n\n"
        msg += f"🎯 Action: {action}\n\n"
        msg += f"⏱️ {datetime.now().strftime('%H:%M:%S')}"
        self.notify(msg, "")

    def notify_ml_drift(self, drift_data):
        """Notification pour alerte de drift ML."""
        if not isinstance(drift_data, dict):
            return
        status = drift_data.get('status', 'WARN')
        msg = f"📉 ALERTE DRIFT ML [{status}]\n\n"
        msg += f"📊 Message: {drift_data.get('message', 'Non spécifié')}\n"
        if drift_data.get('live_win_rate') is not None:
            msg += f"🎯 Win Rate Live: {drift_data.get('live_win_rate'):.1f}%\n"
        if drift_data.get('avg_pnl_pct') is not None:
            msg += f"💰 PnL Moyen: {drift_data.get('avg_pnl_pct'):+.2f}%\n"
        msg += f"\n⏱️ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        self.notify(msg, "")

    def notify_health_status(self, summary_text):
        """Notification bilan de santé."""
        self.notify(summary_text, "")
    
    def notify_cumulative_trend(self, symbol, direction, count, total_change_pct, current_price, start_price=None):
        """Notification tendance cumulative détectée - Désactivé (spam)"""
        return
    
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
        """Envoie un seul bilan Telegram quotidien apres TELEGRAM_DAILY_STATUS_HOUR."""
        with self._status_lock:
            if not self.daily_status_enabled:
                return False

            now_dt = datetime.now()
            if now_dt.hour < self.daily_status_hour:
                return False

            day_key = now_dt.strftime('%Y-%m-%d')
            if self.last_status_day == day_key:
                return False

            logger = getattr(self.bot_ref, 'ml_live_logger', None) if self.bot_ref else None
            store_key = 'telegram_last_daily_status_day'
            if logger:
                claimed = logger.claim_daily_key(store_key, day_key)
                self.last_status_day = day_key
                if not claimed:
                    return False
            else:
                self.last_status_day = day_key

        if not self.bot_ref:
            return False

        try:
            status = self._build_status_message()
            return self.notify(status, "")
        except Exception:
            return False
            
    def _get_historical_performance(self):
        """Calcule les statistiques de performance réelles basées sur l'équité Kraken (comme le web)"""
        try:
            from ui.server import trade_stats, load_accounting_state, apply_live_balance_pnl, get_live_market_data
            # Utiliser le mode live pour correspondre au web
            state = load_accounting_state({'positions': []}, view_mode='live')
            positions = state.get('positions', [])
            stats = trade_stats(positions)
            
            # Appliquer le PnL basé sur l'équité Kraken (comme le web)
            live = get_live_market_data()
            adjusted_stats = apply_live_balance_pnl(stats, state, live)
            
            if not adjusted_stats:
                return None
            return {
                'total_pnl': adjusted_stats.get('total_pnl_net', 0),  # PnL NET basé sur équité Kraken
                'total_trades': stats.get('total_trades', 0) if stats else 0,
                'winrate': stats.get('win_rate', 0) if stats else 0,
                'best_trade': stats.get('best_trade_net', 0) if stats else 0,
            }
        except Exception:
            return None

    def _build_status_message(self, compact=False):
        """Construit message status. compact=True pour caption image (max 1024 chars)"""
        
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
                    # Calculer P&L NET de la position (avec frais estimés)
                    try:
                        avg_buy_price = bot.get_real_buy_price(symbol)
                        if avg_buy_price and avg_buy_price > 0:
                            fee_rate = getattr(bot, 'trading_fee', 0.004)
                            cost_basis = avg_buy_price * total
                            buy_fee = cost_basis * fee_rate
                            sell_fee = value * fee_rate
                            total_fees = buy_fee + sell_fee
                            pnl_brut = (price - avg_buy_price) * total
                            pnl_net = pnl_brut - total_fees
                            pnl_pct = (pnl_net / cost_basis) * 100 if cost_basis > 0 else 0
                            pnl_display = f" • {pnl_pct:+.2f}% ({pnl_net:+.2f}$)"
                        else:
                            pnl_display = ""
                    except:
                        pnl_display = ""
                    
                    portfolio_items.append({
                        'crypto': crypto,
                        'symbol': symbol,
                        'amount': total,
                        'value': value,
                        'price': price,
                        'pnl_display': pnl_display,
                        'has_orders': locked > 0
                    })
                    total_value += value

        msg = f"🤖 {BOT_NAME} | {datetime.now().strftime('%d/%m %H:%M')}\n\n"
        msg += f"💼 <b>Portfolio</b> ({total_value:.2f}$)\n"
        msg += f"┆\n├─ USD: <code>{usd:.2f}$</code>\n"
        
        for i, item in enumerate(portfolio_items):
            is_last = (i == len(portfolio_items) - 1)
            # prefix = "└─" if is_last else "├─"
            prefix = "├─"
            # Crypto et valeur sur la première ligne, PnL sur la deuxième
            line1 = f"{prefix} {item['crypto']}: {format_amount(item['amount'], item['crypto'])} • {item['value']:.2f}$"
            msg += f"{line1}\n"
            if item['pnl_display']:
                pnl_text = item['pnl_display'].strip(' •')
                pnl_icon = "🟢" if '+' in pnl_text else "◉"
                msg += f"{"└─" if is_last else "├─"}{pnl_icon} {pnl_text}"
            msg += f"\n{""if is_last else "┆"}\n"
        
        if not portfolio_items:
            msg += "└─ Aucune crypto\n"
        
        msg += f"\n📈 <b>Performance</b>\n"
        stats = self._get_historical_performance()
        if stats:
            msg += f"├─ P&L: {stats['total_pnl']:+.2f}$\n"
            msg += f"├─ Trades: {stats['total_trades']} ({stats['winrate']:.0f}% win)\n"
            msg += f"└─ Best: {stats['best_trade']:+.2f}$"
        else:
            msg += f"├─ P&L: +0.00$\n"
            msg += f"├─ Trades: 0\n"
            msg += f"└─ Aucun trade"
        
        # Mode compact : on s'arrête là (~400-500 chars)
        if compact:
            return msg
        
        # Mode complet : ajouter les détails des ordres et macro events
        msg += "\n"
        
        # Détail des ordres limite (si présents)
        for item in portfolio_items:
            if item['has_orders']:
                try:
                    open_orders = bot.exchange.fetch_open_orders(f"{item['crypto']}/USD")
                    if open_orders:
                        msg += f"\n📋 Ordres {item['crypto']}\n"
                        for j, order in enumerate(open_orders):
                            order_price = float(order['price'])
                            try:
                                avg_buy_price = bot.get_real_buy_price(item['symbol'])
                                if avg_buy_price and avg_buy_price > 0:
                                    profit_pct = ((order_price - avg_buy_price) / avg_buy_price) * 100 - 0.2
                                else:
                                    profit_pct = 0
                            except:
                                profit_pct = 0
                            
                            prefix = "└─" if j == len(open_orders) - 1 else "├─"
                            msg += f"{prefix} Limite @ {order_price:.2f}$ (+{profit_pct:.2f}%)\n"
                except:
                    pass
        
        # Section Macro Event actif
        try:
            if hasattr(bot, 'market_analyzer') and bot.market_analyzer is not None:
                macro_mgr = bot.market_analyzer._get_macro_manager()
            else:
                from utils.event_manager import MacroEventManager
                macro_mgr = MacroEventManager()
                
            if macro_mgr and macro_mgr.current_event:
                event_type = macro_mgr.current_event
                event_name = "FED" if event_type == "FED_MEETING" else "CPI" if event_type == "INFLATION_DATA" else "Incertitude"
                info = macro_mgr.current_event_info or {}
                elapsed = (time.time() - macro_mgr.event_start_time) / 3600 if macro_mgr.event_start_time else 0
                duration = info.get('duration_hours', 24)
                remaining = max(0, duration - elapsed)
                
                msg += f"\n🔴 <b>Macro: {event_name}</b> ({remaining:.1f}h restant)\n"
        except:
            pass
        
        # Prochains événements macro
        try:
            from utils.event_manager import MacroEventManager
            from datetime import timezone
            macro_mgr = MacroEventManager()
            now = time.time()
            upcoming = []
            
            for item in macro_mgr.macro_calendar_2026:
                event_dt = datetime.fromisoformat(item['date']).replace(tzinfo=timezone.utc)
                event_ts = event_dt.timestamp()
                if event_ts > now:
                    local_dt = datetime.fromtimestamp(event_ts)
                    event_name = "FED" if item['event'] == "FED_MEETING" else "CPI"
                    date_display = local_dt.strftime("%d/%m %H:%M")
                    upcoming.append((event_ts, f"{event_name} {date_display}"))
            
            upcoming.sort(key=lambda x: x[0])
            if upcoming[:2]:
                msg += f"\n📅 <b>À venir</b>\n"
                for i, (_, text) in enumerate(upcoming[:2]):
                    prefix = "└─" if i == 1 else "├─"
                    msg += f"{prefix} {text}\n"
        except:
            pass
        
        return msg

    def _build_positions_message(self):
        """Construit le message d'affichage des positions ouvertes en attente de vente."""
        try:
            from ui.server import load_bot_state, live_status, weighted_positions
            
            if self.bot_ref and hasattr(self.bot_ref, 'state'):
                state = self.bot_ref.state
            else:
                state = load_bot_state({'positions': []})

            live = live_status()

            open_positions = weighted_positions(
                state.get('positions', []),
                state.get('trailing_stops'),
                state.get('pending_orders'),
                state.get('exit_recommendations'),
                live.get('symbols', {})
            )

            if not open_positions:
                return "📦 <b>POSITIONS ACTIVES</b>\n\nAucune position ouverte pour le moment."

            msg = "📦 <b>POSITIONS ACTIVES</b>\n\n"

            total_val = 0.0
            total_pnl_net = 0.0

            for i, p in enumerate(open_positions, 1):
                symbol = p.get('symbol', 'Inconnu')
                crypto = symbol.split('/')[0]
                avg_entry = float(p.get('avg_entry_price') or p.get('price') or 0.0)
                amount = float(p.get('amount') or 0.0)
                entry_val = float(p.get('entry_value') or (avg_entry * amount))
                target_price = float(p.get('target_price') or 0.0)
                stop_loss = float(p.get('stop_loss_price') or 0.0)
                curr_price = float(p.get('current_price') or avg_entry)

                pnl_gross = float(p.get('pnl_gross') if p.get('pnl_gross') is not None else 0.0)
                pnl_gross_pct = float(p.get('pnl_gross_pct') if p.get('pnl_gross_pct') is not None else 0.0)
                pnl_net = float(p.get('pnl_net') if p.get('pnl_net') is not None else 0.0)
                pnl_net_pct = float(p.get('pnl_net_pct') if p.get('pnl_net_pct') is not None else 0.0)

                pnl_emoji = "🟢" if pnl_net >= 0 else "🔴"
                sign_gross = "+" if pnl_gross > 0 else ""
                sign_net = "+" if pnl_net > 0 else ""

                total_val += entry_val
                total_pnl_net += pnl_net

                msg += f"<b>{i}. {symbol}</b>\n"
                msg += f"├─ Prix Achat: <code>{avg_entry:.4f} USD</code>\n"
                msg += f"├─ Prix Actuel: <code>{curr_price:.4f} USD</code>\n"
                msg += f"├─ Quantité: <code>{amount:.6f} {crypto}</code> ({entry_val:.2f} USD)\n"
                if target_price > 0:
                    msg += f"├─ Objectif Vente: <code>{target_price:.4f} USD</code>\n"
                msg += f"├─ PnL Brut: {pnl_emoji} <b>{sign_gross}{pnl_gross_pct:.2f}%</b> ({sign_gross}{pnl_gross:.2f} USD)\n"
                msg += f"└─ PnL Net: {pnl_emoji} <b>{sign_net}{pnl_net_pct:.2f}%</b> ({sign_net}{pnl_net:.2f} USD)\n\n"

            total_sign = "+" if total_pnl_net > 0 else ""
            total_emoji = "🟢" if total_pnl_net >= 0 else "🔴"

            msg += f"📊 <b>Total: {len(open_positions)} position(s) ouverte(s)</b>\n"
            msg += f"• Capital Engagé: <b>{total_val:.2f} USD</b>\n"
            msg += f"• PnL Net Total en cours: {total_emoji} <b>{total_sign}{total_pnl_net:.2f} USD</b>"

            return msg
        except Exception as e:
            return f"⚠️ Erreur lors de la récupération des positions : {e}"

    def _build_history_message(self):
        """Construit le message d'affichage de l'historique des trades fermés."""
        try:
            from ui.server import compute_trade_history, load_bot_state
            state = load_bot_state({'positions': []})
            positions = state.get('positions', [])
            all_trades = compute_trade_history(positions)

            closed_trades = [t for t in all_trades if t.get('status') == 'closed']

            if not closed_trades:
                return "📜 <b>HISTORIQUE DES TRADES</b>\n\nAucun trade fermé enregistré pour le moment."

            recent_trades = closed_trades[:8]

            msg = "📜 <b>HISTORIQUE DES TRADES</b>\n\n"

            for i, t in enumerate(recent_trades, 1):
                symbol = t.get('symbol', 'Inconnu')
                crypto = symbol.split('/')[0]
                buy_px = float(t.get('buy_price') or 0.0)
                sell_px = float(t.get('sell_price') or 0.0)
                amount = float(t.get('amount') or 0.0)
                pnl_net = float(t.get('pnl') or t.get('pnl_net') or 0.0)
                pnl_pct = float(t.get('pnl_net_pct') or t.get('pnl_pct') or 0.0)
                usd_val = float(t.get('usd_value') or t.get('entry_value') or (buy_px * amount))
                timestamp = str(t.get('timestamp') or t.get('sell_time') or '')[:16].replace('T', ' ')

                pnl_emoji = "🟢" if pnl_net >= 0 else "🔴"
                sign = "+" if pnl_net > 0 else ""

                msg += f"<b>{i}. {pnl_emoji} {symbol}</b> ({timestamp})\n"
                msg += f"├─ Achat: {buy_px:.2f} USD → Vente: {sell_px:.2f} USD\n"
                msg += f"├─ Quantité: {amount:.6f} {crypto} ({usd_val:.2f} USD)\n"
                msg += f"└─ PnL Net: {pnl_emoji} <b>{sign}{pnl_net:.2f} USD</b> ({sign}{pnl_pct:.2f}%)\n\n"

            wins = len([t for t in closed_trades if float(t.get('pnl') or 0) > 0])
            total = len(closed_trades)
            win_rate = (wins / total * 100.0) if total > 0 else 0.0
            total_pnl = sum(float(t.get('pnl') or 0.0) for t in closed_trades)
            total_sign = "+" if total_pnl > 0 else ""

            msg += f"📊 <b>Bilan Global:</b>\n"
            msg += f"• Trades fermés: <b>{total}</b> ({wins} Gains / {total - wins} Pertes)\n"
            msg += f"• Win Rate: <b>{win_rate:.1f}%</b>\n"
            msg += f"• PnL Net Cumulé: <b>{total_sign}{total_pnl:.2f} USD</b>"

            return msg
        except Exception as e:
            return f"⚠️ Erreur lors de la récupération de l'historique : {e}"
