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
        msg += f"📤 Prix: {price:.6f} USDT\n"
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
        msg += f"💸 Perte: {loss_pct:.1f}% ({loss_amount:.2f} USDT)\n"
        msg += f"⏳ Durée: {duration}\n\n"
        msg += f"🎯 Action: {action}\n\n"
        msg += f"⏱️ {datetime.now().strftime('%H:%M:%S')}"
        self.notify(msg, "")
    
    def notify_cumulative_trend(self, symbol, direction, count, total_change_pct, current_price, start_price=None):
        """Notification tendance cumulative détectée"""
        crypto = symbol.split('/')[0]
        direction_text = "tendance baissière" if direction < 0 else "tendance haussière"
        direction_emoji = "📉" if direction < 0 else "📈"
        
        # Calcul valeur absolue si prix de départ disponible
        if start_price:
            price_change_abs = current_price - start_price
            change_display = f"{total_change_pct:.2f}% ({price_change_abs:+.2f} USDT)"
            price_detail = f"├─ Prix départ: {start_price:.2f} USDT\n"
        else:
            change_display = f"{total_change_pct:.2f}%"
            price_detail = ""
        
        msg = f"{direction_emoji} {direction_text.upper()}\n\n"
        msg += f"🪙 Crypto: {crypto}\n"
        msg += f"💰 Prix actuel: {current_price:.2f} USDT\n"
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
            price_display = f"{price_momentum:+.1f}% ({price_change_abs:+.2f} USDT)"
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
        msg += f"└─ Prix: {current_price:.2f} USDT ({trend_emoji} {price_momentum:+.1f}%)"
        
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
            distance_display = f"{distance_pct:.1f}% ({distance_abs:.2f} USDT)"
            current_price_line = f"💰 Prix actuel: {current_price:.2f} USDT\n"
        else:
            distance_display = f"{distance_pct:.1f}%"
            current_price_line = ""
        
        msg = f"🎯 NIVEAU CRITIQUE\n\n"
        msg += f"🪙 Crypto: {crypto}\n"
        msg += f"📊 Type: {level_type}\n"
        msg += current_price_line
        msg += f"🎯 Niveau: {price:.2f} USDT\n"
        msg += f"📏 Distance: {distance_display}\n\n"
        msg += f"⏱️ {datetime.now().strftime('%H:%M:%S')}"
        return self.notify(msg, "")
    
    def format_price_change(self, current_price, previous_price=None, change_pct=None):
        """Formateur unifié pour changements de prix"""
        if previous_price and change_pct:
            change_abs = current_price - previous_price
            return f"{change_pct:+.2f}% ({change_abs:+.2f} USDT)"
        elif change_pct:
            change_abs = current_price * (change_pct / 100)
            return f"{change_pct:+.2f}% ({change_abs:+.2f} USDT)"
        else:
            return f"{current_price:.2f} USDT"

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
    
    def notify_macro_event_start(self, event_type, event_info):
        """Notification début d'événement macro"""
        message = f"🚨 **MACRO EVENT DÉTECTÉ**\n\n"
        message += f"🏷️ **Type**: {event_type}\n"
        message += f"📋 **Description**: {event_info['description']}\n\n"
        message += f"🎁 **Bonus Score**: +{event_info['score_bonus']} points\n"
        message += f"🎯 **Réduction Seuil**: -{event_info['threshold_reduction']} points\n"
        message += f"⏰ **Durée Estimée**: {event_info['duration_hours']}h\n\n"
        message += f"🤖 Le bot s'adapte automatiquement aux conditions macro."
        return self.notify(message)
    
    def notify_macro_event_end(self, event_type, elapsed_hours):
        """Notification fin d'événement macro"""
        message = f"✅ **FIN MACRO EVENT**\n\n"
        message += f"🏷️ **Type**: {event_type}\n"
        message += f"⏱️ **Durée**: {elapsed_hours:.1f}h\n\n"
        message += f"🔄 Le bot reprend ses paramètres normaux."
        return self.notify(message)
    
    def send_status_update(self):
        """Envoie status périodique synchronisé sur XX:00 et XX:30"""
        # Vérifier si on est à une heure ronde (XX:00 ou XX:30)
        current_minute = datetime.now().minute
        
        # Tolérance de ±1 minute pour éviter de rater l'heure
        if current_minute not in [0, 30]:
            return  # Pas l'heure, skip
        
        # Anti-spam : éviter envois multiples dans la même minute
        now = time.time()
        if now - self.last_status_time < 50:  # 50 secondes minimum entre envois
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
        
        # Portfolio avec détail des ordres et P&L
        portfolio_items = []
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
                    # Calculer P&L de la position
                    try:
                        avg_buy_price = bot.position_manager.get_average_buy_price(crypto)
                        if avg_buy_price > 0:
                            pnl_pct = ((price - avg_buy_price) / avg_buy_price) * 100
                            pnl_usdt = (price - avg_buy_price) * total
                            pnl_display = f" • {pnl_pct:+.1f}% ({pnl_usdt:+.1f} USDT)"
                        else:
                            pnl_display = ""
                    except:
                        pnl_display = ""
                    
                    portfolio_items.append({
                        'crypto': crypto,
                        'amount': total,
                        'value': value,
                        'pnl_display': pnl_display,
                        'has_orders': locked > 0
                    })
                    total_value += value
        
        # Stats
        win_rate = (bot.winning_trades / bot.total_trades * 100) if bot.total_trades > 0 else 0
        
        msg = f"🤖 {BOT_NAME} | STATUS {datetime.now().strftime('%H:%M')}\n\n"
        msg += f"💼 Portfolio ({total_value:.2f} USDT)\n"
        msg += f"├─ USDT: {usdt:.2f}\n"
        
        # Afficher chaque crypto avec détail des ordres
        for i, item in enumerate(portfolio_items):
            is_last = (i == len(portfolio_items) - 1)
            prefix = "└─" if is_last else "├─"
            
            msg += f"{prefix} {item['crypto']}: {item['amount']:.6f} • {item['value']:.2f} USDT{item['pnl_display']}\n"
            
            # Détail des ordres pour cette crypto
            if item['has_orders']:
                try:
                    # Récupérer les ordres ouverts pour cette crypto
                    open_orders = bot.exchange.fetch_open_orders(f"{item['crypto']}/USDT")
                    if open_orders:
                        for j, order in enumerate(open_orders):
                            is_last_order = (j == len(open_orders) - 1)
                            order_prefix = "   └─" if (is_last and is_last_order) else "   ├─" if is_last else "│  └─" if is_last_order else "│  ├─"
                            
                            # Déterminer source de l'ordre
                            source = "🤖" if order.get('clientOrderId', '').startswith('bot_') else "👤"
                            
                            # Calculer profit potentiel
                            current_price = bot.get_price(f"{item['crypto']}/USDT")
                            order_price = float(order['price'])
                            profit_pct = ((order_price - current_price) / current_price) * 100
                            
                            # Calculer temps depuis création
                            order_time = datetime.fromtimestamp(order['timestamp'] / 1000)
                            time_diff = datetime.now() - order_time
                            if time_diff.days > 0:
                                time_display = f"{time_diff.days}j"
                            elif time_diff.seconds > 3600:
                                time_display = f"{time_diff.seconds // 3600}h"
                            else:
                                time_display = f"{time_diff.seconds // 60}min"
                            
                            msg += f"{order_prefix} {source} Limite: {float(order['amount']):.3f} @ {order_price:.2f} • +{profit_pct:.1f}% • {time_display}\n"
                    else:
                        # Pas d'ordres trouvés mais balance locked > 0
                        order_prefix = "   └─" if is_last else "│  └─"
                        msg += f"{order_prefix} 🤖 Ordre actif (détails indisponibles)\n"
                except Exception as e:
                    # Fallback si erreur récupération ordres
                    order_prefix = "   └─" if is_last else "│  └─"
                    msg += f"{order_prefix} 🤖 Ordre actif\n"
        
        msg += f"\n"
        msg += f"📈 Performance\n"
        msg += f"├─ P&L: {bot.daily_pnl:+.2f} USDT\n"
        
        # Utiliser win rate global 30j si disponible
        if hasattr(bot, 'global_stats_30d') and bot.global_stats_30d:
            stats = bot.global_stats_30d
            msg += f"├─ Trades: {stats['total_cycles']} ({stats['winrate']:.0f}% win) [30j]\n"
            if stats['best_trade'] > 0:
                msg += f"└─ Meilleur: +{stats['best_trade']:.2f} USDT\n\n"
            else:
                msg += f"└─ Aucun trade\n\n"
        else:
            win_rate = (bot.winning_trades / bot.total_trades * 100) if bot.total_trades > 0 else 0
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
                real_invested = sum(float(p.get('subscriptionAmount', 0)) for p in real_positions)
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
                    calls_amount = sum(float(p.get('subscriptionAmount', 0)) for p in real_calls) + sum(p.get('amount', 0) for p in sim_calls)
                    msg += f"├─ Calls: {total_calls} ({calls_amount:.1f} USDT)\n"
                if total_puts > 0:
                    puts_amount = sum(float(p.get('subscriptionAmount', 0)) for p in real_puts) + sum(p.get('amount', 0) for p in sim_puts)
                    msg += f"├─ Puts: {total_puts} ({puts_amount:.1f} USDT)\n"
                
                # Détail des positions actives avec structure hiérarchique par type
                position_details = []
                
                # Grouper par type d'option
                calls_positions = []
                puts_positions = []
                
                # Positions réelles
                for p in real_positions:
                    invest_coin = p.get('investCoin', 'UNKNOWN')
                    exercised_coin = p.get('exercisedCoin', 'UNKNOWN')
                    option_type = p.get('optionType', 'UNKNOWN')
                    amount = float(p.get('subscriptionAmount', 0))
                    apr = float(p.get('apr', 0))
                    duration = p.get('duration', 0)
                    
                    # CORRECTION: APR vient comme 1.05 (pas 105%), donc pas besoin de /100
                    potential_gain_usdt = amount * apr * (duration / 365)
                    
                    # Calculer temps restant
                    settle_date = p.get('settleDate', 0)
                    if settle_date:
                        settle_datetime = datetime.fromtimestamp(settle_date / 1000)
                        time_remaining = settle_datetime - datetime.now()
                        total_seconds = time_remaining.total_seconds()
                        
                        if total_seconds <= 0:
                            time_display = "Expiré"
                        elif total_seconds < 3600:  # < 1 heure
                            minutes = int(total_seconds // 60)
                            time_display = f"{minutes}min"
                        elif total_seconds < 86400:  # < 24 heures
                            hours = int(total_seconds // 3600)
                            time_display = f"{hours}h"
                        else:  # >= 24 heures
                            days = int(total_seconds // 86400)
                            time_display = f"{days}j"
                    else:
                        time_display = f"{duration}j"
                    
                    gain_display = f"+{potential_gain_usdt:.3f} (+{apr*100:.1f}%) • {time_display}"
                    
                    position_info = f"{exercised_coin} • {amount:.2f} USDT • {gain_display}"
                    
                    if option_type == 'CALL':
                        calls_positions.append(position_info)
                    elif option_type == 'PUT':
                        puts_positions.append(position_info)
                
                # Positions simulées
                for p in simulated_positions:
                    if p.get('status', 'active') == 'active':
                        crypto = p.get('symbol', 'N/A').replace('USDT', '')
                        ptype = 'CALL' if p.get('type') == 'covered_call' else 'PUT'
                        amount = p.get('amount', 0)
                        position_info = f"{crypto} • {amount:.1f} USDT"
                        
                        if ptype == 'CALL':
                            calls_positions.append(position_info)
                        else:
                            puts_positions.append(position_info)
                
                # Affichage hiérarchique par type
                if puts_positions or calls_positions:
                    # Afficher PUT en premier
                    if puts_positions:
                        if calls_positions:  # Il y a aussi des CALL après
                            msg += f"├─ 📉 PUT ({len(puts_positions)} position{'s' if len(puts_positions) > 1 else ''})\n"
                        else:  # Seulement des PUT
                            msg += f"└─ 📉 PUT ({len(puts_positions)} position{'s' if len(puts_positions) > 1 else ''})\n"
                        
                        for i, pos in enumerate(puts_positions):
                            is_last_put = (i == len(puts_positions) - 1)
                            if calls_positions:  # Il y a des CALL après
                                prefix = "│  ├─" if not is_last_put else "│  └─"
                            else:  # Pas de CALL après
                                prefix = "   ├─" if not is_last_put else "   └─"
                            msg += f"{prefix} {pos}\n"
                    
                    # Afficher CALL en second
                    if calls_positions:
                        msg += f"└─ 📞 CALL ({len(calls_positions)} position{'s' if len(calls_positions) > 1 else ''})\n"
                        
                        for i, pos in enumerate(calls_positions):
                            is_last_call = (i == len(calls_positions) - 1)
                            prefix = "   ├─" if not is_last_call else "   └─"
                            msg += f"{prefix} {pos}\n"
                    
                    msg += "\n"
                else:
                    msg += f"└─ Positions actives\n\n"
            else:
                msg += f"💎 Double Investment: Aucune position\n\n"
        
        # Opportunités - LIMITER AUX TRADABLE PAIRS
        msg += f"🔮 Opportunités\n"
        opps = []
        
        # Récupérer les cryptos tradables du bot
        try:
            trading_pairs = os.getenv('TRADING_PAIRS', 'BTCUSDT,ETHUSDT').split(',')
            stuck_positions = []
            tradable_pairs = bot.crypto_scorer.rank_cryptos(bot, trading_pairs, stuck_positions)
        except:
            tradable_pairs = []
        
        # Seulement les cryptos tradables
        for symbol in tradable_pairs:
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
        
        return msg