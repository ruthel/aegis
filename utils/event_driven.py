"""
Optimisation 6: Architecture événementielle
Réagit uniquement aux changements significatifs (économie 70-80% analyses)
"""
import time
import threading
from queue import Queue, Empty

class EventDrivenEngine:
    def __init__(self, bot):
        self.bot = bot
        self.event_queue = Queue(maxsize=1000)
        self.price_thresholds = {}  # Seuil mouvement par paire
        self.last_prices = {}
        self.running = False
        self.worker_thread = None
        
        # Configuration triggers
        self.min_price_change = 0.005  # 0.5% mouvement minimum
        self.debounce_time = 2  # 2s entre événements similaires
        self.last_event_time = {}
    
    def start(self):
        """Démarre moteur événementiel"""
        self.running = True
        self.worker_thread = threading.Thread(target=self._event_worker, daemon=True)
        self.worker_thread.start()
    
    def stop(self):
        """Arrête moteur"""
        self.running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=2)
    
    def on_price_change(self, symbol, new_price):
        """Callback changement prix WebSocket"""
        if symbol not in self.last_prices:
            self.last_prices[symbol] = new_price
            return
        
        old_price = self.last_prices[symbol]
        price_change = abs(new_price - old_price) / old_price
        
        # Trigger seulement si mouvement significatif
        if price_change >= self.min_price_change:
            # Debouncing: éviter spam
            now = time.time()
            last_event = self.last_event_time.get(symbol, 0)
            
            if now - last_event >= self.debounce_time:
                self.emit_event('price_significant_change', {
                    'symbol': symbol,
                    'old_price': old_price,
                    'new_price': new_price,
                    'change_pct': price_change * 100
                })
                self.last_prices[symbol] = new_price
                self.last_event_time[symbol] = now
    
    def emit_event(self, event_type, data):
        """Émet événement dans la queue"""
        try:
            self.event_queue.put_nowait({
                'type': event_type,
                'data': data,
                'timestamp': time.time()
            })
        except:
            pass  # Queue pleine, ignorer
    
    def _event_worker(self):
        """Worker qui traite événements"""
        while self.running:
            try:
                event = self.event_queue.get(timeout=1)
                self._handle_event(event)
            except Empty:
                continue
            except Exception as e:
                print(f"⚠️ Erreur event worker: {e}")
    
    def _handle_event(self, event):
        """Traite événement selon type"""
        event_type = event['type']
        data = event['data']
        
        if event_type == 'price_significant_change':
            # Analyser seulement cette paire
            symbol = data['symbol']
            new_price = data['new_price']
            
            # Exécuter stratégie uniquement si mouvement significatif
            strategy_type = self.bot.strategy_type if hasattr(self.bot, 'strategy_type') else 'scalping'
            trade_amount = self.bot.trade_amount if hasattr(self.bot, 'trade_amount') else 10
            
            self.bot.execute_strategy(symbol, strategy_type, trade_amount)
        
        elif event_type == 'balance_change':
            # Sync positions
            self.bot.sync_positions_from_exchange()
        
        elif event_type == 'new_signal':
            # Signal fort détecté
            symbol = data['symbol']
            action = data['action']
            confidence = data['confidence']
            
            if confidence >= 75:  # Seuil élevé pour événementiel
                print(f"🔥 SIGNAL FORT: {symbol} {action} ({confidence}%)")
    
    def should_analyze(self, symbol):
        """Détermine si analyse nécessaire"""
        # Vérifier si prix a bougé significativement
        if symbol not in self.last_prices:
            return True
        
        current_price = self.bot.get_price(symbol)
        last_price = self.last_prices[symbol]
        change = abs(current_price - last_price) / last_price
        
        return change >= self.min_price_change
