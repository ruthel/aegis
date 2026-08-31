"""Client Kraken - Implémentation de l'interface ExchangeBase"""
import threading

import ccxt
from core.exchange.base import ExchangeBase


# Mapping des symboles Kraken vers format standard
KRAKEN_SYMBOL_MAP = {
    'BTC/USD': 'BTC/USD',
    'ETH/USD': 'ETH/USD',
    'SOL/USD': 'SOL/USD',
    'ADA/USD': 'ADA/USD',
    'ADA/USD': 'ADA/USD',
    'DOT/USD': 'DOT/USD',
    'AVAX/USD': 'AVAX/USD',
}


class KrakenClient(ExchangeBase):
    """Client Kraken via ccxt - Compatible Canada"""

    def __init__(self, api_key, api_secret, testnet=False):
        self._exchange = ccxt.kraken({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,
            # Nonce en microsecondes: granularité plus fine que les millisecondes
            # par défaut, réduit fortement le risque de collision entre appels rapprochés.
            'nonce': lambda: ccxt.Exchange.microseconds(),
        })
        # Verrou global sérialisant TOUS les appels ccxt de cette instance.
        # Kraken exige un nonce strictement croissant par clé API; sans ce verrou,
        # deux threads (fetch klines, balance, ordres...) peuvent générer des nonces
        # concurrents/dans le désordre -> "EAPI:Invalid nonce".
        self._api_lock = threading.RLock()
        self._markets = {}
        # Kraken n'a pas de testnet public, on ignore le flag
        if testnet:
            print("⚠️ Kraken n'a pas de testnet - Mode live uniquement")

    def _call(self, fn, *args, **kwargs):
        """Exécute un appel ccxt sous verrou pour garantir un nonce strictement croissant."""
        with self._api_lock:
            return fn(*args, **kwargs)

    @property
    def name(self):
        return 'kraken'

    @property
    def markets(self):
        return self._markets or self._exchange.markets or {}

    def connect(self):
        self.load_markets()

    def fetch_balance(self, params=None):
        return self._call(self._exchange.fetch_balance, params or {})

    def fetch_ticker(self, symbol):
        return self._call(self._exchange.fetch_ticker, symbol)

    def fetch_ohlcv(self, symbol, timeframe='15m', limit=50):
        # Kraken supporte: 1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w
        supported_tf = ['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w']
        if timeframe not in supported_tf:
            # Mapper vers le timeframe supporté le plus proche
            tf_map = {'3m': '5m', '2h': '1h', '6h': '4h', '8h': '4h', '12h': '4h', '1M': '1w'}
            timeframe = tf_map.get(timeframe, '15m')
        return self._call(self._exchange.fetch_ohlcv, symbol, timeframe, limit=limit)

    def create_market_buy_order(self, symbol, amount):
        return self._call(self._exchange.create_market_buy_order, symbol, amount)

    def create_market_sell_order(self, symbol, amount):
        return self._call(self._exchange.create_market_sell_order, symbol, amount)

    def create_limit_sell_order(self, symbol, amount, price):
        return self._call(self._exchange.create_limit_sell_order, symbol, amount, price)

    def fetch_open_orders(self, symbol=None):
        return self._call(self._exchange.fetch_open_orders, symbol)

    def fetch_order(self, order_id, symbol=None):
        return self._call(self._exchange.fetch_order, order_id, symbol)

    def cancel_order(self, order_id, symbol=None):
        return self._call(self._exchange.cancel_order, order_id, symbol)

    def fetch_my_trades(self, symbol, since=None, limit=100):
        return self._call(self._exchange.fetch_my_trades, symbol, since=since, limit=limit)

    def fetch_ledger(self, code=None, since=None, limit=100, params=None):
        return self._call(self._exchange.fetch_ledger, code=code, since=since, limit=limit, params=params or {})

    def fetch_deposits(self, code=None, since=None, limit=100, params=None):
        return self._call(self._exchange.fetch_deposits, code=code, since=since, limit=limit, params=params or {})

    def fetch_withdrawals(self, code=None, since=None, limit=100, params=None):
        return self._call(self._exchange.fetch_withdrawals, code=code, since=since, limit=limit, params=params or {})

    def fetch_transactions(self, code=None, since=None, limit=100, params=None):
        return self._call(self._exchange.fetch_transactions, code=code, since=since, limit=limit, params=params or {})

    def load_markets(self):
        self._markets = self._call(self._exchange.load_markets) or {}
        return self._markets

    def fetch_trading_fees(self):
        """Retourne les frais maker/taker par paire au format attendu par le bot."""
        fees = {}
        try:
            if hasattr(self._exchange, 'fetch_trading_fees'):
                raw_fees = self._call(self._exchange.fetch_trading_fees)
                if isinstance(raw_fees, dict) and raw_fees:
                    for symbol, item in raw_fees.items():
                        if not isinstance(item, dict):
                            continue
                        fees[symbol] = {
                            'maker': float(item.get('maker') if item.get('maker') is not None else 0.0016),
                            'taker': float(item.get('taker') if item.get('taker') is not None else 0.0026),
                        }
                    if fees:
                        return fees
        except Exception:
            pass

        markets = self.markets or self.load_markets()
        for symbol, market in (markets or {}).items():
            if not isinstance(market, dict):
                continue
            fees[symbol] = {
                'maker': float(market.get('maker') if market.get('maker') is not None else 0.0016),
                'taker': float(market.get('taker') if market.get('taker') is not None else 0.0026),
            }
        return fees

    def get_ws_url(self):
        return "wss://ws.kraken.com"

    def get_ws_streams(self, symbols):
        """Retourne les paires pour souscription WebSocket Kraken"""
        # Kraken WebSocket utilise le format XBT/USD pour BTC
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
        # XBT/USD -> BTC/USD
        return ws_pair.replace('XBT', 'BTC')

    def normalize_symbol(self, pair):
        """BTCUSD -> BTC/USD"""
        if '/' in pair:
            return pair
        for quote in ['USDT', 'USDC', 'USD', 'CAD', 'BTC', 'ETH']:
            if pair.endswith(quote):
                return f"{pair[:-len(quote)]}/{quote}"
        return pair

    def get_market_limits(self, symbol):
        try:
            symbol = self.normalize_symbol(symbol)
            markets = self.markets or self.load_markets()
            market = markets.get(symbol)
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
            'BTC/USD': {'min_amount': 0.0001, 'min_cost': 0.5},
            'ETH/USD': {'min_amount': 0.001, 'min_cost': 0.5},
            'SOL/USD': {'min_amount': 0.01, 'min_cost': 0.5},
            'ADA/USD': {'min_amount': 0.01, 'min_cost': 0.5},
        }
        return fallback.get(symbol, {'min_amount': 0.001, 'min_cost': 0.5})
