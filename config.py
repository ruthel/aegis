"""Configuration centralisée du bot - Toutes les variables depuis .env"""
import os
from dotenv import load_dotenv

load_dotenv()

# ===== CLÉS API BINANCE =====
BINANCE_API_KEY = os.getenv('BINANCE_API_KEY')
BINANCE_API_SECRET = os.getenv('BINANCE_API_SECRET')
TESTNET = os.getenv('TESTNET', 'True').lower() == 'true'

# ===== TRADING =====
TRADING_PAIRS = os.getenv('TRADING_PAIRS', 'BTCUSDT,ETHUSDT').split(',')
STRATEGY_TYPE = os.getenv('STRATEGY_TYPE', 'intelligent')

TRADE_AMOUNT = float(os.getenv('TRADE_AMOUNT', '5'))
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', '5'))
REALTIME_TRADING = os.getenv('REALTIME_TRADING', 'True').lower() == 'true'

# ===== GESTION SOLDE =====
USE_FULL_BALANCE = os.getenv('USE_FULL_BALANCE', 'False').lower() == 'true'
MAX_BALANCE_PER_TRADE = float(os.getenv('MAX_BALANCE_PER_TRADE', '50'))  # % max du solde par trade

# ===== GESTION DES RISQUES =====
MAX_DAILY_LOSS = float(os.getenv('MAX_DAILY_LOSS', '200'))
STOP_LOSS_PERCENT = float(os.getenv('STOP_LOSS_PERCENT', '5'))
TRAILING_STOP_PERCENT = float(os.getenv('TRAILING_STOP_PERCENT', '3'))
MAX_POSITION_SIZE = float(os.getenv('MAX_POSITION_SIZE', '50'))
MAX_DAILY_TRADES = int(os.getenv('MAX_DAILY_TRADES', '100'))
EMERGENCY_STOP_LOSS = float(os.getenv('EMERGENCY_STOP_LOSS', '500'))
TRADING_FEE_PERCENT = float(os.getenv('TRADING_FEE_PERCENT', '0.1'))
MIN_PROFIT_THRESHOLD = float(os.getenv('MIN_PROFIT_THRESHOLD', '0.8'))

# Variables supplémentaires du .env actuel
RISK_PER_TRADE = float(os.getenv('RISK_PER_TRADE', '2'))
ALERT_ON_LOSS = os.getenv('ALERT_ON_LOSS', 'True').lower() == 'true'

# ===== PAPER TRADING =====
PAPER_TRADING = os.getenv('PAPER_TRADING', 'False').lower() == 'true'
PAPER_BALANCE = float(os.getenv('PAPER_BALANCE', '1000'))

# ===== BINANCE EARN (TIRELIRE) =====
TIRELIRE_MODE = os.getenv('TIRELIRE_MODE', 'True').lower() == 'true'
ENABLE_EARN = os.getenv('ENABLE_EARN', 'True').lower() == 'true'
MIN_TRADING_BALANCE = float(os.getenv('MIN_TRADING_BALANCE', '5'))
EARN_ALLOCATION_PERCENT = float(os.getenv('EARN_ALLOCATION_PERCENT', '100'))
FLEXIBLE_SAVINGS_THRESHOLD = float(os.getenv('FLEXIBLE_SAVINGS_THRESHOLD', '5'))
LOCKED_STAKING_THRESHOLD = float(os.getenv('LOCKED_STAKING_THRESHOLD', '50'))
EARN_WITHDRAW_THRESHOLD = float(os.getenv('EARN_WITHDRAW_THRESHOLD', '5'))

# ===== POSITIONS BLOQUÉES =====
MAX_STUCK_LOSS = float(os.getenv('MAX_STUCK_LOSS', '15'))
STUCK_THRESHOLD_HOURS = int(os.getenv('STUCK_THRESHOLD_HOURS', '24'))

# ===== SÉLECTION CRYPTOS =====
MIN_CRYPTO_SCORE = int(os.getenv('MIN_CRYPTO_SCORE', '50'))
MAX_TRADEABLE_CRYPTOS = int(os.getenv('MAX_TRADEABLE_CRYPTOS', '2'))

# ===== ENVIRONNEMENT =====
CURRENT_ENVIRONMENT = os.getenv('CURRENT_ENVIRONMENT', 'testnet')

# ===== NOTIFICATIONS TELEGRAM =====
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
TELEGRAM_STATUS_INTERVAL = int(os.getenv('TELEGRAM_STATUS_INTERVAL', '300'))

# ===== MONITORING =====
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
SAVE_LOGS = os.getenv('SAVE_LOGS', 'True').lower() == 'true'
SHOW_PERFORMANCE = os.getenv('SHOW_PERFORMANCE', 'True').lower() == 'true'

# ===== SYNCHRONISATION =====
FORCE_BALANCE_REFRESH = os.getenv('FORCE_BALANCE_REFRESH', 'True').lower() == 'true'

# ===== OPTIMISATION LATENCE USA =====
BINANCE_BASE_URL = os.getenv('BINANCE_BASE_URL', 'https://api.binance.com')
BINANCE_WS_URL = os.getenv('BINANCE_WS_URL', 'wss://stream.binance.com:9443/ws')

# Optimisations réseau
CONNECTION_TIMEOUT = int(os.getenv('CONNECTION_TIMEOUT', '5'))
READ_TIMEOUT = int(os.getenv('READ_TIMEOUT', '10'))
MAX_RETRIES = int(os.getenv('MAX_RETRIES', '3'))
REQUEST_POOL_SIZE = int(os.getenv('REQUEST_POOL_SIZE', '20'))

# Cache optimisé
PRICE_CACHE_TTL = float(os.getenv('PRICE_CACHE_TTL', '1'))
BALANCE_CACHE_TTL = float(os.getenv('BALANCE_CACHE_TTL', '5'))
ORDER_BOOK_CACHE_TTL = float(os.getenv('ORDER_BOOK_CACHE_TTL', '0.5'))

# WebSocket optimisé
WS_PING_INTERVAL = int(os.getenv('WS_PING_INTERVAL', '20'))
WS_PING_TIMEOUT = int(os.getenv('WS_PING_TIMEOUT', '10'))
WS_RECONNECT_DELAY = int(os.getenv('WS_RECONNECT_DELAY', '5'))



# ===== COMPATIBILITÉ (anciens noms) =====
BINANCE_MAINNET_API_KEY = BINANCE_API_KEY
BINANCE_MAINNET_API_SECRET = BINANCE_API_SECRET
BINANCE_TESTNET_API_KEY = BINANCE_API_KEY
BINANCE_TESTNET_API_SECRET = BINANCE_API_SECRET
AUTO_MODE = False
TRADING_MODE = STRATEGY_TYPE
TRADING_PAIR = 'BTC/USDT'
TRADE_AMOUNT_USDT = TRADE_AMOUNT
MIN_PROFIT_PERCENT = MIN_PROFIT_THRESHOLD