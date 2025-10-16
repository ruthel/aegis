"""Détecteur de Pullback pour Scalping - Votre stratégie"""
import time

class PullbackDetector:
    def __init__(self):
        self.pullback_min = -0.005  # -0.5%
        self.pullback_max = -0.001  # -0.1%
        self.profit_target = 0.003   # +0.3%
        self.timeout = 300           # 5 minutes
        self.pending_orders = {}
    
    def detect_pullback(self, bot, symbol, current_price, ema_analysis):
        """Détecte si c'est un pullback valide pour scalping"""
        
        # Vérifier si c'est le Cas 3 (Pullback Haussier)
        if ema_analysis['case'] != 3:
            return None
        
        # Récupérer données récentes
        klines = bot.get_klines(symbol, 20)
        if len(klines) < 10:
            return None
        
        closes = [k['close'] for k in klines]
        volumes = [k['volume'] for k in klines]
        
        # Calculer le pullback depuis le récent high
        recent_high = max(closes[-10:])
        pullback_pct = (current_price - recent_high) / recent_high
        
        # Vérifier si pullback dans la fourchette
        if not (self.pullback_min <= pullback_pct <= self.pullback_max):
            return None
        
        # Vérifier volume (doit être faible = pas de panique)
        avg_volume = sum(volumes[-10:]) / 10
        current_volume = volumes[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1
        
        if volume_ratio > 1.5:  # Volume trop élevé = panique
            return None
        
        # Calculer RSI
        rsi = self.calculate_rsi(closes)
        if rsi and rsi < 40:  # Trop de survente
            return None
        
        # Calculer support optimal (EMA 25 ou Bollinger basse)
        support_price = ema_analysis['ema_25']
        
        # Vérifier distance du high journalier
        if not self.check_distance_to_high(bot, symbol, current_price):
            return None
        
        return {
            'is_valid': True,
            'pullback_pct': pullback_pct * 100,
            'support_price': support_price,
            'entry_price': max(support_price, current_price * 0.999),  # Légèrement au-dessus support
            'target_price': current_price * (1 + self.profit_target),
            'volume_ratio': volume_ratio,
            'rsi': rsi,
            'recent_high': recent_high
        }
    
    def calculate_rsi(self, closes, period=14):
        """Calcule le RSI"""
        if len(closes) < period + 1:
            return None
        
        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def check_distance_to_high(self, bot, symbol, current_price):
        """Vérifie qu'on n'est pas trop proche du high journalier"""
        try:
            # Récupérer données 24h
            if not bot.paper_trading:
                ticker = bot.safe_request(bot.exchange.fetch_ticker, symbol)
                high_24h = ticker.get('high', current_price * 1.05)
            else:
                high_24h = current_price * 1.02
            
            distance_pct = (high_24h - current_price) / current_price
            
            # Au moins 1% de marge vers le high
            return distance_pct >= 0.01
        except:
            return True  # En cas d'erreur, on autorise
    
    def place_limit_buy_order(self, bot, symbol, entry_price, amount):
        """Place un ordre limite d'achat"""
        try:
            print(f"📊 Scalping Pullback: Ordre limite ACHAT")
            print(f"   Prix entrée: {entry_price:.2f}")
            print(f"   Montant: {amount:.6f}")
            print(f"   Timeout: {self.timeout}s")
            
            if bot.paper_trading:
                order = {
                    'id': f"pullback_{int(time.time())}",
                    'symbol': symbol,
                    'type': 'limit',
                    'side': 'buy',
                    'price': entry_price,
                    'amount': amount,
                    'status': 'open',
                    'timestamp': time.time()
                }
            else:
                order = bot.safe_request(
                    bot.exchange.create_limit_buy_order,
                    symbol,
                    amount,
                    entry_price
                )
            
            # Enregistrer l'ordre avec timeout
            self.pending_orders[order['id']] = {
                'order': order,
                'timestamp': time.time(),
                'timeout': self.timeout,
                'symbol': symbol,
                'type': 'pullback_buy'
            }
            
            return order
        except Exception as e:
            print(f"❌ Erreur ordre limite: {e}")
            return None
    
    def check_and_cancel_expired_orders(self, bot):
        """Annule les ordres expirés"""
        now = time.time()
        expired = []
        
        for order_id, data in self.pending_orders.items():
            if now - data['timestamp'] > data['timeout']:
                expired.append(order_id)
        
        for order_id in expired:
            data = self.pending_orders[order_id]
            
            # Vérifier si l'ordre existe encore sur Binance
            if not bot.paper_trading:
                try:
                    order_status = bot.safe_request(bot.exchange.fetch_order, order_id, data['symbol'])
                    if order_status['status'] in ['closed', 'canceled', 'expired']:
                        # Ordre déjà fermé, juste le retirer localement
                        del self.pending_orders[order_id]
                        continue
                except:
                    # Ordre n'existe pas, le retirer localement
                    del self.pending_orders[order_id]
                    continue
            
            # Annuler l'ordre s'il est toujours ouvert
            try:
                print(f"⏱️ Timeout ordre pullback {data['symbol']} - Annulation")
                
                if not bot.paper_trading:
                    bot.safe_request(bot.exchange.cancel_order, order_id, data['symbol'])
                
                del self.pending_orders[order_id]
            except Exception as e:
                # Si erreur -2011 (ordre inconnu), le retirer quand même
                if '-2011' in str(e) or 'Unknown order' in str(e):
                    del self.pending_orders[order_id]
                else:
                    print(f"⚠️ Erreur annulation: {e}")
