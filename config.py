"""Configuration centralisée du bot - variables système + fichiers locaux."""
import os
from dotenv import load_dotenv

load_dotenv()
load_dotenv('.env.local', override=True)
load_dotenv('.env.dashboard', override=True)

# ===== EXCHANGE =====
EXCHANGE = os.getenv('EXCHANGE', 'binance').lower()  # binance ou kraken

# ===== CLÉS API =====
# Binance
BINANCE_API_KEY = os.getenv('BINANCE_API_KEY')
BINANCE_API_SECRET = os.getenv('BINANCE_API_SECRET')
# Kraken
KRAKEN_API_KEY = os.getenv('KRAKEN_API_KEY', '')
KRAKEN_API_SECRET = os.getenv('KRAKEN_API_SECRET', '')

# Clés actives selon exchange
if EXCHANGE == 'kraken':
    ACTIVE_API_KEY = KRAKEN_API_KEY
    ACTIVE_API_SECRET = KRAKEN_API_SECRET
else:
    ACTIVE_API_KEY = BINANCE_API_KEY
    ACTIVE_API_SECRET = BINANCE_API_SECRET

TESTNET = os.getenv('TESTNET', 'True').lower() == 'true'

# ===== TRADING =====
TRADING_PAIRS = os.getenv('TRADING_PAIRS', 'BTCUSD,ETHUSD').split(',')

TRADE_AMOUNT = float(os.getenv('TRADE_AMOUNT', '5'))

# ===== GESTION SOLDE =====
USE_FULL_BALANCE = os.getenv('USE_FULL_BALANCE', 'False').lower() == 'true'
MAX_BALANCE_PER_TRADE = float(os.getenv('MAX_BALANCE_PER_TRADE', '50'))  # % max du solde par trade

# ===== GESTION DES RISQUES =====
MAX_DAILY_LOSS = float(os.getenv('MAX_DAILY_LOSS', '200'))
STOP_LOSS_PERCENT = float(os.getenv('STOP_LOSS_PERCENT', '5'))
TRAILING_STOP_PERCENT = float(os.getenv('TRAILING_STOP_PERCENT', '3'))
MAX_DAILY_TRADES = int(os.getenv('MAX_DAILY_TRADES', '100'))
EMERGENCY_STOP_LOSS = float(os.getenv('EMERGENCY_STOP_LOSS', '500'))
TRADING_FEE_PERCENT = float(os.getenv('TRADING_FEE_PERCENT', '0.1'))
MIN_PROFIT_THRESHOLD = float(os.getenv('MIN_PROFIT_THRESHOLD', '0.8'))

# Variables supplémentaires du .env actuel
RISK_PER_TRADE = float(os.getenv('RISK_PER_TRADE', '2'))

# ===== PAPER TRADING =====
PAPER_TRADING = os.getenv('PAPER_TRADING', 'False').lower() == 'true'
PAPER_BALANCE = float(os.getenv('PAPER_BALANCE', '1000'))

# ===== POSITIONS BLOQUÉES =====
MAX_STUCK_LOSS = float(os.getenv('MAX_STUCK_LOSS', '15'))
STUCK_THRESHOLD_HOURS = int(os.getenv('STUCK_THRESHOLD_HOURS', '24'))

# ===== SÉLECTION CRYPTOS =====
MIN_CRYPTO_SCORE = int(os.getenv('MIN_CRYPTO_SCORE', '40'))  # Adaptatif par défaut

# ===== NOTIFICATIONS TELEGRAM =====
BOT_NAME = os.getenv('BOT_NAME', 'Aegis')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
TELEGRAM_STATUS_INTERVAL = int(os.getenv('TELEGRAM_STATUS_INTERVAL', '1800'))

# ===== MONITORING =====
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
SAVE_LOGS = os.getenv('SAVE_LOGS', 'True').lower() == 'true'

# ===== COMPATIBILITÉ (anciens noms) =====
BINANCE_MAINNET_API_KEY = BINANCE_API_KEY
BINANCE_MAINNET_API_SECRET = BINANCE_API_SECRET
BINANCE_TESTNET_API_KEY = BINANCE_API_KEY
BINANCE_TESTNET_API_SECRET = BINANCE_API_SECRET
TRADING_PAIR = 'BTC/USD'
