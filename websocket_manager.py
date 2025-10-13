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
        self.running = False
        self.reconnect_attempts = 0
        self.max_reconnect = 5
        
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
        print("✅ WebSocket connecté - Données temps réel actives")
        self.reconnect_attempts = 0
    
    def on_message(self, ws, message):
        """Traite les messages reçus"""
        try:
            data = json.loads(message)
            
            # Prix en temps réel (ticker)
            if 'c' in data:  # Prix de clôture
                symbol = data['s']  # BTCUSDT
                price = float(data['c'])
                self.prices[symbol] = price
                
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
                    
        except Exception as e:
            print(f"Erreur traitement message: {e}")
    
    def on_error(self, ws, error):
        """Gère les erreurs WebSocket"""
        print(f"❌ Erreur WebSocket: {error}")
    
    def on_close(self, ws, close_status_code, close_msg):
        """Gère la fermeture de connexion"""
        print("⚠️ WebSocket fermé")
        if self.running:
            self.reconnect()
    
    def reconnect(self):
        """Reconnexion automatique"""
        if self.reconnect_attempts < self.max_reconnect:
            self.reconnect_attempts += 1
            print(f"🔄 Reconnexion WebSocket {self.reconnect_attempts}/{self.max_reconnect}...")
            time.sleep(2 ** self.reconnect_attempts)  # Backoff exponentiel
            self.connect()
        else:
            print("❌ Échec reconnexion WebSocket - Passage en mode REST")
            self.running = False
    
    def get_price(self, symbol):
        """Récupère le prix en temps réel"""
        # Convertir BTC/USDT -> BTCUSDT
        ws_symbol = symbol.replace('/', '')
        return self.prices.get(ws_symbol, None)
    
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