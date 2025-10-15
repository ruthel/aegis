import json
import time
from datetime import datetime, timedelta
import statistics
from utils.volatility_calculator import VolatilityCalculator

class AdvancedRiskManager:
    def __init__(self):
        self.correlation_data = {}
        self.active_positions = {}
        
    def calculate_volatility(self, bot, symbol, periods=20):
        """Calcule la volatilité réelle sur les dernières périodes"""
        try:
            klines = bot.get_klines(symbol, periods)
            return VolatilityCalculator.calculate(klines, symbol) / 100  # Convertir en décimal
        except Exception as e:
            print(f"Erreur calcul volatilité {symbol}: {e}")
            return 0.02  # Volatilité par défaut (2%)

    def calculate_position_size(self, bot, symbol, base_amount=10, max_risk_percent=2):
        """Calcule la taille de position basée sur la volatilité et configuration"""
        from config import USE_FULL_BALANCE, MAX_BALANCE_PER_TRADE
        
        if USE_FULL_BALANCE:
            # Mode: Utiliser tout le solde disponible (comportement actuel)
            balance = bot.balance_manager.get_balance()
            usdt_available = balance.get('USDT', {}).get('free', 0)
            
            # Limiter selon MAX_BALANCE_PER_TRADE (% du solde)
            max_allowed = usdt_available * (MAX_BALANCE_PER_TRADE / 100)
            position_size = min(usdt_available, max_allowed)
            
            print(f"💰 {symbol}: Mode FULL_BALANCE → {position_size:.1f} USDT ({MAX_BALANCE_PER_TRADE}% max)")
            return max(base_amount, position_size)
        else:
            # Mode: Montant fixe basé sur volatilité (nouveau comportement)
            volatility = self.calculate_volatility(bot, symbol)
            
            # Plus la volatilité est élevée, plus on réduit la position
            risk_factor = max_risk_percent / (volatility * 100)
            adjusted_amount = base_amount * min(risk_factor, 2.0)  # Max 2x le montant de base
            
            # Minimums spécifiques par paire
            min_notionals = {
                'BTC/USDT': 5,
                'ETH/USDT': 10,
                'SOL/USDT': 8,
                'BNB/USDT': 12
            }
            min_required = min_notionals.get(symbol, 10)
            
            # Minimum selon la paire, maximum selon TRADE_AMOUNT
            max_amount = getattr(bot, 'trade_amount', base_amount) * 2
            position_size = max(min_required, min(max_amount, adjusted_amount))
            
            print(f"📊 {symbol}: Mode Fixed Amount → {position_size:.1f} USDT (vol: {volatility:.1%})")
            return position_size

class TrailingStopManager:
    def __init__(self, trailing_percent=3.0):
        self.trailing_percent = trailing_percent
        self.positions = {}  # {symbol: {'buy_price': price, 'highest_price': price, 'stop_price': price}}
    
    def add_position(self, symbol, buy_price):
        """Ajoute une nouvelle position avec trailing stop"""
        stop_price = buy_price * (1 - self.trailing_percent / 100)
        self.positions[symbol] = {
            'buy_price': buy_price,
            'highest_price': buy_price,
            'stop_price': stop_price,
            'created_at': datetime.now().isoformat()
        }
        print(f"🎯 Trailing stop activé pour {symbol}: Stop initial à {stop_price:.2f}")
    
    def update_position(self, symbol, current_price):
        """Met à jour le trailing stop si le prix monte"""
        if symbol not in self.positions:
            return False
            
        position = self.positions[symbol]
        
        # Si nouveau plus haut, on met à jour le trailing stop
        if current_price > position['highest_price']:
            position['highest_price'] = current_price
            new_stop = current_price * (1 - self.trailing_percent / 100)
            
            # Le stop ne peut que monter, jamais descendre
            if new_stop > position['stop_price']:
                old_stop = position['stop_price']
                position['stop_price'] = new_stop
                print(f"📈 {symbol}: Trailing stop mis à jour {old_stop:.2f} → {new_stop:.2f}")
        
        return False
    
    def should_stop_loss(self, symbol, current_price):
        """Vérifie si le trailing stop est déclenché"""
        if symbol not in self.positions:
            return False
            
        position = self.positions[symbol]
        
        if current_price <= position['stop_price']:
            profit_percent = ((current_price - position['buy_price']) / position['buy_price']) * 100
            print(f"🛑 Trailing stop déclenché pour {symbol}!")
            print(f"   Achat: {position['buy_price']:.2f}")
            print(f"   Plus haut: {position['highest_price']:.2f}")
            print(f"   Vente: {current_price:.2f}")
            print(f"   Profit: {profit_percent:.2f}%")
            return True
            
        return False
    
    def remove_position(self, symbol):
        """Supprime une position fermée"""
        if symbol in self.positions:
            del self.positions[symbol]

class CorrelationManager:
    def __init__(self, max_correlated_positions=2):
        self.max_correlated_positions = max_correlated_positions
        self.crypto_groups = {
            'major': ['BTC/USDT', 'ETH/USDT'],
            'altcoins': ['SOL/USDT', 'BNB/USDT']
        }
        self.active_positions = set()
        self.market_sentiment = 'neutral'  # 'bullish', 'bearish', 'neutral'
        self.last_sentiment_check = 0
    
    def update_market_sentiment(self, bot):
        """Analyse le sentiment du marché"""
        if time.time() - self.last_sentiment_check < 300:  # Check toutes les 5 minutes
            return
            
        try:
            btc_price = bot.get_price('BTC/USDT')
            eth_price = bot.get_price('ETH/USDT')
            
            # Logique simplifiée de sentiment (à améliorer avec de vrais indicateurs)
            # Pour l'instant, on reste neutre
            self.market_sentiment = 'neutral'
            self.last_sentiment_check = time.time()
            
        except Exception as e:
            print(f"Erreur analyse sentiment: {e}")
    
    def can_open_position(self, symbol, bot):
        """Vérifie si on peut ouvrir une position selon la corrélation"""
        # Synchroniser avec le solde réel
        balance = bot.balance_manager.get_balance()
        base_currency = symbol.split('/')[0]
        current_holding = balance.get(base_currency, {}).get('free', 0)
        
        # Si position déjà ouverte (solde réel), bloquer
        if current_holding > 0.00001:
            position_value = current_holding * bot.get_price(symbol)
            min_trade_value = bot.get_min_amount(symbol)['min_cost']
            if position_value >= min_trade_value:
                print(f"🔴 {base_currency} bloqué: position ouverte {current_holding:.6f} ({position_value:.2f} USDT)")
                return False
            else:
                print(f"🧹 {base_currency} poussière ignorée: {current_holding:.6f} ({position_value:.2f} < {min_trade_value:.2f})")
        
        self.update_market_sentiment(bot)
        
        # Trouver le groupe de la crypto
        symbol_group = None
        for group, symbols in self.crypto_groups.items():
            if symbol in symbols:
                symbol_group = group
                break
        
        if not symbol_group:
            return True
        
        # Compter positions réelles dans le même groupe
        group_positions = 0
        for group_symbol in self.crypto_groups[symbol_group]:
            if group_symbol == symbol:
                continue
            group_base = group_symbol.split('/')[0]
            group_holding = balance.get(group_base, {}).get('free', 0)
            if group_holding > 0.00001:
                group_value = group_holding * bot.get_price(group_symbol)
                if group_value >= bot.get_min_amount(group_symbol)['min_cost']:
                    group_positions += 1
        
        if group_positions >= self.max_correlated_positions:
            return False
        
        if self.market_sentiment == 'bearish':
            return False
            
        return True
    
    def add_position(self, symbol):
        """Ajoute une position active"""
        self.active_positions.add(symbol)
        print(f"📊 Position ajoutée: {symbol} (Total: {len(self.active_positions)})")
    
    def remove_position(self, symbol):
        """Supprime une position fermée"""
        self.active_positions.discard(symbol)
        print(f"📊 Position fermée: {symbol} (Total: {len(self.active_positions)})")