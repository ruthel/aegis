"""Interface abstraite pour les exchanges - Pattern Strategy"""
from abc import ABC, abstractmethod


class ExchangeBase(ABC):
    """Contrat commun pour tous les exchanges"""

    @abstractmethod
    def connect(self):
        """Établit la connexion à l'exchange"""
        pass

    @abstractmethod
    def fetch_balance(self, params=None):
        """Récupère les balances du compte"""
        pass

    @abstractmethod
    def fetch_ticker(self, symbol):
        """Récupère le ticker d'un symbole"""
        pass

    @abstractmethod
    def fetch_ohlcv(self, symbol, timeframe='15m', limit=50):
        """Récupère les bougies OHLCV"""
        pass

    @abstractmethod
    def create_market_buy_order(self, symbol, amount):
        """Crée un ordre d'achat au marché"""
        pass

    @abstractmethod
    def create_market_sell_order(self, symbol, amount):
        """Crée un ordre de vente au marché"""
        pass

    @abstractmethod
    def create_limit_sell_order(self, symbol, amount, price):
        """Crée un ordre limite de vente"""
        pass

    @abstractmethod
    def fetch_open_orders(self, symbol=None):
        """Récupère les ordres ouverts"""
        pass

    @abstractmethod
    def cancel_order(self, order_id, symbol=None):
        """Annule un ordre"""
        pass

    @abstractmethod
    def fetch_my_trades(self, symbol, since=None, limit=100):
        """Récupère l'historique des trades"""
        pass

    @abstractmethod
    def load_markets(self):
        """Charge les informations des marchés"""
        pass

    @abstractmethod
    def get_ws_url(self):
        """Retourne l'URL WebSocket pour les prix temps réel"""
        pass

    @abstractmethod
    def get_ws_streams(self, symbols):
        """Retourne les streams WebSocket à souscrire"""
        pass

    @abstractmethod
    def parse_ws_message(self, message):
        """Parse un message WebSocket et retourne les données normalisées"""
        pass

    @abstractmethod
    def normalize_symbol(self, pair):
        """Convertit un pair config (ex: BTCUSDT) en format exchange"""
        pass

    @abstractmethod
    def get_market_limits(self, symbol):
        """Retourne les limites min/max pour un symbole"""
        pass

    @property
    @abstractmethod
    def name(self):
        """Nom de l'exchange"""
        pass

    @property
    def markets(self):
        """Accès aux marchés chargés"""
        return getattr(self, '_markets', {})
