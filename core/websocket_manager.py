import json
import time
import threading
from collections import deque
import websocket

class WebSocketManager:
    def __init__(self, symbols=['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT']):
        self.symbols = symbols
        self.prices = {}
        self.klines = {symbol: deque(maxlen=100) for symbol in symbols}  # 100 dernières bougies
        self.ws = None
        self.ws_user = None  # WebSocket User Data Stream
        self.running = False
        self.reconnect_attempts = 0
        self.max_reconnect = 5
        self.balance_callback = None
        self.listen_key = None
        
    def start(self):
        """Démarre la connexion WebSocket"""
        self.running = True
        self.connect()
        
    def connect(self):
        """Établit la connexion WebSocket"""
        try:
            # Stream pour les prix en temps réel
            streams = [f"{symbol.lower()}@ticker" for symbol in self.symbols]
            # Ajouter les klines 1m pour les indicateurs
            streams.extend([f"{symbol.lower()}@kline_1m" for symbol in self.symbols])
            
            url = f"wss://stream.binance.com:9443/ws/{'/'.join(streams)}"
            
            self.ws = websocket.WebSocketApp(
                url,
                on_message=self.on_message,
                on_error=self.on_error,
                on_close=self.on_close,
                on_open=self.on_open
            )
            
            # Démarrer dans un thread séparé
            self.ws_thread = threading.Thread(target=self.ws.run_forever)
            self.ws_thread.daemon = True
            self.ws_thread.start()
            
        except Exception as e:
            print(f"Erreur connexion WebSocket: {e}")
            self.reconnect()
    
    def on_open(self, ws):
        """Callback à l'ouverture de la connexion"""
        self.reconnect_attempts = 0
    
    def on_message(self, ws, message):
        """Traite les messages reçus"""
        try:
            data = json.loads(message)
            
            # Prix en temps réel (ticker)
            if 'c' in data:  # Prix de clôture
                symbol = data['s']  # BTCUSDT
                price = float(data['c'])
                old_price = self.prices.get(symbol, price)
                self.prices[symbol] = price
                
                # Déclencher analyse temps réel sur CHAQUE changement de prix
                if price != old_price:  # Tout changement déclenche l'analyse
                    self.trigger_realtime_analysis(symbol, price)
                
            # Données kline pour indicateurs
            elif 'k' in data:
                kline = data['k']
                if kline['x']:  # Kline fermée
                    symbol = kline['s']
                    candle = {
                        'timestamp': kline['t'],
                        'open': float(kline['o']),
                        'high': float(kline['h']),
                        'low': float(kline['l']),
                        'close': float(kline['c']),
                        'volume': float(kline['v'])
                    }
                    self.klines[symbol].append(candle)
                    # Déclencher analyse sur nouvelle bougie
                    self.trigger_realtime_analysis(symbol, float(kline['c']))
                    
        except Exception as e:
            print(f"Erreur traitement message: {e}")
    
    def trigger_realtime_analysis(self, symbol, price):
        """Déclenche l'analyse temps réel"""
        if hasattr(self, 'bot_callback') and self.bot_callback:
            try:
                self.bot_callback(symbol, price)
            except Exception as e:
                print(f"Erreur callback temps réel: {e}")
    
    def set_bot_callback(self, callback):
        """Définit le callback pour le bot"""
        self.bot_callback = callback
    
    def set_balance_callback(self, callback):
        """Définit le callback pour les changements de solde"""
        self.balance_callback = callback
    
    def start_user_data_stream(self, bot):
        """Démarre le User Data Stream pour synchronisation temps réel"""
        if bot.paper_trading:
            print("📝 Paper trading - WebSocket User Data désactivé")
            return
        
        try:
            # Obtenir listen key pour SPOT (pas futures)
            response = bot.safe_request(bot.exchange.sapiPostUserDataStream)
            self.listen_key = response.get('listenKey')
            
            if not self.listen_key:
                print("❌ Impossible d'obtenir listen key")
                return
            
            # Connexion WebSocket User Data
            url = f"wss://stream.binance.com:9443/ws/{self.listen_key}"
            
            self.ws_user = websocket.WebSocketApp(
                url,
                on_message=self.on_user_message,
                on_error=self.on_user_error,
                on_close=self.on_user_close,
            )
            
            # Démarrer dans un thread séparé
            self.ws_user_thread = threading.Thread(target=self.ws_user.run_forever)
            self.ws_user_thread.daemon = True
            self.ws_user_thread.start()
            
            # Keepalive toutes les 30 minutes
            self.start_keepalive(bot)
            
        except Exception as e:
            print(f"❌ Erreur User Data Stream: {e}")
    
    def on_user_error(self, ws, error):
        # Silencieux - erreurs de connexion normales
        pass
    
    def on_user_close(self, ws, close_status_code, close_msg):
        # Silencieux - fermetures de connexion normales
        pass
    
    def on_user_message(self, ws, message):
        """Traite les messages User Data (solde, ordres, etc.)"""
        try:
            data = json.loads(message)
            event_type = data.get('e')
            
            print(f"📨 User Data reçu: {event_type}")
            
            # Mise à jour solde
            if event_type == 'outboundAccountPosition':
                print("💰 Changement de solde détecté")
                if self.balance_callback:
                    self.balance_callback(data)
            
            # Exécution ordre
            elif event_type == 'executionReport':
                order_status = data.get('X')  # Order status
                if order_status == 'CANCELED':
                    print("❌ Ordre annulé détecté")
                elif order_status == 'NEW':
                    symbol = data.get('s', '')
                    side = data.get('S', '')
                    price = data.get('p', '0')
                    print(f"✅ Nouvel ordre: {symbol} {side} @ {price}")
                elif order_status == 'REPLACED':
                    symbol = data.get('s', '')
                    price = data.get('p', '0')
                    print(f"🔄 {symbol}: Ordre modifié instantanément @ {price}")
                
                if self.balance_callback:
                    self.balance_callback(data)
            
            # Autres événements
            else:
                print(f"📊 Événement User Data: {event_type}")
                    
        except Exception as e:
            print(f"⚠️ Erreur traitement user message: {e}")
            print(f"📄 Message brut: {message[:200]}...")
    
    def start_keepalive(self, bot):
        """Maintient le listen key actif"""
        def keepalive():
            while self.running:
                try:
                    time.sleep(1800)  # 30 minutes
                    if self.listen_key:
                        print("🔄 Keepalive User Data Stream...")
                        bot.safe_request(bot.exchange.sapiPutUserDataStream, {'listenKey': self.listen_key})
                        print("✅ Keepalive OK")
                except Exception as e:
                    print(f"⚠️ Erreur keepalive: {e}")
        
        keepalive_thread = threading.Thread(target=keepalive)
        keepalive_thread.daemon = True
        keepalive_thread.start()
    
    def on_error(self, ws, error):
        """Gère les erreurs WebSocket (silencieux)"""
        pass
    
    def on_close(self, ws, close_status_code, close_msg):
        """Gère la fermeture de connexion (silencieux)"""
        if self.running:
            self.reconnect()
    
    def reconnect(self):
        """Reconnexion automatique (silencieux)"""
        if self.reconnect_attempts < self.max_reconnect:
            self.reconnect_attempts += 1
            time.sleep(2 ** self.reconnect_attempts)  # Backoff exponentiel
            self.connect()
        else:
            print("❌ WebSocket déconnecté - Mode REST")
            # Ne pas arrêter, continuer en mode REST
            self.reconnect_attempts = 0
            # Tenter reconnexion après délai
            time.sleep(30)
            if self.running:
                self.connect()
    
    def stop(self):
        """Arrête les connexions WebSocket"""
        self.running = False
        if self.ws:
            self.ws.close()
        if self.ws_user:
            self.ws_user.close()
    
    def is_connected(self):
        """Vérifie si WebSocket connecté"""
        return self.ws is not None and hasattr(self.ws, 'sock') and self.ws.sock
    
    def get_price(self, symbol):
        """Récupère prix depuis WebSocket"""
        return self.prices.get(symbol)
    
    def get_ticker(self, symbol):
        """Récupère ticker depuis WebSocket"""
        price = self.prices.get(symbol)
        if price:
            return {'last': price, 'symbol': symbol}
        return None
    
    def get_price(self, symbol):
        """Récupère le prix en temps réel"""
        # Convertir BTC/USDT -> BTCUSDT
        ws_symbol = symbol.replace('/', '')
        return self.prices.get(ws_symbol, None)
    
    def get_ticker(self, symbol):
        """Récupère les données ticker depuis WebSocket"""
        current_price = self.get_price(symbol)
        if current_price:
            return {
                'last': current_price,
                'percentage': 0,
                'symbol': symbol
            }
        return None
    
    def get_klines(self, symbol, count=50):
        """Récupère les dernières bougies"""
        ws_symbol = symbol.replace('/', '')
        klines = list(self.klines.get(ws_symbol, []))
        return klines[-count:] if len(klines) >= count else klines
    
    def is_connected(self):
        """Vérifie si WebSocket est connecté"""
        return self.running and len(self.prices) > 0
    
    def stop(self):
        """Arrête la connexion WebSocket"""
        self.running = False
        if self.ws:
            self.ws.close()
        if self.ws_user:
            self.ws_user.close()