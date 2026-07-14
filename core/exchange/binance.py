"""Client Binance - Implémentation de l'interface ExchangeBase"""
import ccxt
from core.exchange.base import ExchangeBase


class BinanceClient(ExchangeBase):
    """Client Binance via ccxt"""

    def __init__(self, api_key, api_secret, testnet=False):
        self._exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': api_secret,
            'sandbox': testnet,
            'enableRateLimit': True,
        })
        self._markets = {}

    @property
    def name(self):
        return 'binance'

    @property
    def markets(self):
        return self._exchange.markets or {}

    def connect(self):
        self._exchange.load_markets()

    def fetch_balance(self, params=None):
        return self._exchange.fetch_balance(params or {})

    def fetch_ticker(self, symbol):
        return self._exchange.fetch_ticker(symbol)

    def fetch_ohlcv(self, symbol, timeframe='15m', limit=50):
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

    def get_ws_url(self):
        return "wss://stream.binance.com:9443/ws"

    def get_ws_streams(self, symbols):
        return [f"{s.lower()}@kline_1m" for s in symbols]

    def parse_ws_message(self, message):
        """Parse message WebSocket Binance"""
        if 'k' not in message:
            return None
        kline = message['k']
        return {
            'type': 'kline',
            'symbol': kline['s'],
            'price': float(kline['c']),
            'open': float(kline['o']),
            'high': float(kline['h']),
            'low': float(kline['l']),
            'volume': float(kline['v']),
            'is_closed': kline['x'],
            'timestamp': kline['t']
        }

    def normalize_symbol(self, pair):
        """BTCUSD -> BTC/USD"""
        if '/' in pair:
            return pair
        for quote in ['USD', 'USDC', 'BTC', 'ETH']:
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
                    'min_cost': limits.get('cost', {}).get('min', 1.0)
                }
        except:
            pass
        return None
