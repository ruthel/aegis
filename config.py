import os
from dotenv import load_dotenv

load_dotenv()

# Configuration API Binance
BINANCE_API_KEY = os.getenv('BINANCE_API_KEY')
BINANCE_API_SECRET = os.getenv('BINANCE_API_SECRET')
TESTNET = os.getenv('TESTNET', 'True').lower() == 'true'

# Configuration mainnet (production)
BINANCE_MAINNET_API_KEY = os.getenv('BINANCE_MAINNET_API_KEY', BINANCE_API_KEY)
BINANCE_MAINNET_API_SECRET = os.getenv('BINANCE_MAINNET_API_SECRET', BINANCE_API_SECRET)

# Configuration testnet
BINANCE_TESTNET_API_KEY = os.getenv('BINANCE_TESTNET_API_KEY', BINANCE_API_KEY)
BINANCE_TESTNET_API_SECRET = os.getenv('BINANCE_TESTNET_API_SECRET', BINANCE_API_SECRET)

# Mode de démarrage
AUTO_MODE = os.getenv('AUTO_MODE', 'false').lower() == 'true'
TRADING_MODE = os.getenv('TRADING_MODE', 'SCALPING')
TRADING_PAIR = os.getenv('TRADING_PAIR', 'BTC/USDT')
TRADE_AMOUNT = float(os.getenv('TRADE_AMOUNT', '10'))

# Paramètres de trading
TRADING_PAIRS = ['BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT']
MIN_PROFIT_PERCENT = 0.5  # 0.5%
TRADE_AMOUNT_USDT = 10    # Montant par trade en USDT