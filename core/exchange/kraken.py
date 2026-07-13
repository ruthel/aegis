"""Client Kraken - Implémentation de l'interface ExchangeBase"""
import ccxt
from core.exchange.base import ExchangeBase


# Mapping des symboles Kraken vers format standard
KRAKEN_SYMBOL_MAP = {
    'BTC/USDT': 'BTC/USDT',
    'ETH/USDT': 'ETH/USDT',
    'SOL/USDT': 'SOL/USDT',
    'BNB/USDT': 'BNB/USDT',
    'ADA/USDT': 'ADA/USDT',
    'DOT/USDT': 'DOT/USDT',
    'AVAX/USDT': 'AVAX/USDT',
}


class KrakenClient(ExchangeBase):
    """Client Kraken via ccxt - Compatible Canada"""

    def __init__(self, api_key, api_secret, testnet=False):
        self._exchange = ccxt.kraken({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,
        })
        self._markets = {}
        # Kraken n'a pas de testnet public, on ignore le flag
        if testnet:
            print("⚠️ Kraken n'a pas de testnet - Mode live uniquement")

    @property
    def name(self):
        return 'kraken'

    @property
    def markets(self):
        return self._exchange.markets or {}

    def connect(self):
        self._exchange.load_markets()

    def fetch_balance(self, params=None):
        # Kraken n'a pas de portefeuille "funding" séparé
        # On ignore le param type=funding silencieusement
        if params and params.get('type') == 'funding':
            return {}
        return self._exchange.fetch_balance(params or {})

    def fetch_ticker(self, symbol):
        return self._exchange.fetch_ticker(symbol)

    def fetch_ohlcv(self, symbol, timeframe='15m', limit=50):
        # Kraken supporte: 1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w
        supported_tf = ['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w']
        if timeframe not in supported_tf:
            # Mapper vers le timeframe supporté le plus proche
            tf_map = {'3m': '5m', '2h': '1h', '6h': '4h', '8h': '4h', '12h': '4h', '1M': '1w'}
            timeframe = tf_map.get(timeframe, '15m')
        return self._exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

    def create_market_buy_order(self, symbol, amount):
        return self._exchange.create_market_buy_order(symbol, amount)

    def create_market_sell_order(self, symbol, amount):
        return self._exchange.create_market_sell_order(symbol, amount)

    def create_limit_sell_order(self, symbol, amount, price):
        return self._exchange.create_limit_sell_order(symbol, amount, price)

    def fetch_open_orders(self, symbol=None):
        return self._exchange.fetch_open_orders(symbol)

    def cancel_order(self, order_id, symbol=None):
        return self._exchange.cancel_order(order_id, symbol)

    def fetch_my_trades(self, symbol, since=None, limit=100):
        return self._exchange.fetch_my_trades(symbol, since=since, limit=limit)

    def load_markets(self):
        self._exchange.load_markets()
        self._markets = self._exchange.markets

    def transfer(self, asset, amount, from_account, to_account):
        # Kraken n'a pas de transfert interne (pas de funding wallet)
        # Retourner silencieusement
        return {'id': None}

    def get_ws_url(self):
        return "wss://ws.kraken.com"

    def get_ws_streams(self, symbols):
        """Retourne les paires pour souscription WebSocket Kraken"""
        # Kraken WebSocket utilise le format XBT/USDT pour BTC
        pairs = []
        for s in symbols:
            pair = self.normalize_symbol(s)
            # Kraken utilise XBT au lieu de BTC dans certains contextes WS
            pairs.append(pair)
        return pairs

    def parse_ws_message(self, message):
        """Parse message WebSocket Kraken (format v2)"""
        # Kraken WS v2 format pour ticker/ohlc
        if isinstance(message, list) and len(message) >= 4:
            channel = message[-2]
            pair = message[-1]

            if 'ohlc' in channel:
                # Format: [channelID, [time, etime, open, high, low, close, vwap, volume, count], channelName, pair]
                data = message[1]
                symbol = self._ws_pair_to_symbol(pair)
                return {
                    'type': 'kline',
                    'symbol': symbol.replace('/', ''),
                    'price': float(data[5]),  # close
                    'open': float(data[2]),
                    'high': float(data[3]),
                    'low': float(data[4]),
                    'volume': float(data[7]),
                    'is_closed': False,  # Kraken ne signale pas la fermeture
                    'timestamp': int(float(data[0]) * 1000)
                }

            if 'ticker' in channel:
                data = message[1]
                symbol = self._ws_pair_to_symbol(pair)
                price = float(data['c'][0])  # last trade price
                return {
                    'type': 'kline',
                    'symbol': symbol.replace('/', ''),
                    'price': price,
                    'open': float(data['o'][0]),
                    'high': float(data['h'][0]),
                    'low': float(data['l'][0]),
                    'volume': float(data['v'][1]),  # volume today
                    'is_closed': False,
                    'timestamp': 0
                }

        return None

    def _ws_pair_to_symbol(self, ws_pair):
        """Convertit paire WS Kraken vers format standard"""
        # XBT/USDT -> BTC/USDT
        return ws_pair.replace('XBT', 'BTC')

    def normalize_symbol(self, pair):
        """BTCUSDT -> BTC/USDT"""
        if '/' in pair:
            return pair
        for quote in ['USDT', 'USDC', 'USD', 'BTC', 'ETH']:
            if pair.endswith(quote):
                return f"{pair[:-len(quote)]}/{quote}"
        return pair

    def get_market_limits(self, symbol):
        try:
            if not self._exchange.markets:
                self._exchange.load_markets()
            market = self._exchange.markets.get(symbol)
            if market and market.get('limits'):
                limits = market['limits']
                return {
                    'min_amount': limits.get('amount', {}).get('min', 0.001),
                    'min_cost': limits.get('cost', {}).get('min', 0.5)
                }
        except:
            pass
        # Fallback Kraken (minimums plus bas que Binance)
        fallback = {
            'BTC/USDT': {'min_amount': 0.0001, 'min_cost': 0.5},
            'ETH/USDT': {'min_amount': 0.001, 'min_cost': 0.5},
            'SOL/USDT': {'min_amount': 0.01, 'min_cost': 0.5},
            'BNB/USDT': {'min_amount': 0.01, 'min_cost': 0.5},
        }
        return fallback.get(symbol, {'min_amount': 0.001, 'min_cost': 0.5})

    # Méthodes spécifiques Kraken (pas de User Data Stream comme Binance)
    def sapi_post_user_data_stream(self):
        """Kraken n'a pas de User Data Stream - utilise WebSocket privé"""
        # Retourner un token pour le WS privé Kraken
        try:
            response = self._exchange.private_post_get_websockets_token()
            return {'listenKey': response.get('result', {}).get('token', '')}
        except:
            return {'listenKey': ''}

    def sapi_put_user_data_stream(self, params):
        """Kraken n'a pas besoin de keepalive pour le WS token"""
        pass

    def get_user_data_ws_url(self, listen_key):
        return "wss://ws-auth.kraken.com"
