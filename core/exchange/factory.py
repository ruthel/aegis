"""Factory pour créer le client exchange approprié"""
import os
import sys

# Fix encodage Windows pour emojis
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def create_exchange_client(api_key, api_secret, testnet=False, verbose=True):
    """Crée le client exchange selon la config EXCHANGE dans .env"""
    exchange_name = os.getenv('EXCHANGE', 'binance').lower()

    if exchange_name == 'kraken':
        from core.exchange.kraken import KrakenClient
        if verbose:
            print("Exchange: Kraken (Canada compatible)")
        return KrakenClient(api_key, api_secret, testnet)
    else:
        from core.exchange.binance import BinanceClient
        if verbose:
            print("Exchange: Binance")
        return BinanceClient(api_key, api_secret, testnet)
