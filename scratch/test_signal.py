import sys, os
sys.path.insert(0, os.getcwd())
import ccxt
from utils.market_analyzer import MarketAnalyzer

exchange = ccxt.kraken({'enableRateLimit': True})
exchange.load_markets()

symbol = 'ETH/USD'
ohlcv = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
klines = [{'timestamp': r[0], 'open': r[1], 'high': r[2], 'low': r[3], 'close': r[4], 'volume': r[5]} for r in ohlcv]

analyzer = MarketAnalyzer()
analysis = analyzer.analyze_market(klines, current_price=klines[-1]['close'])
score = analyzer.score_crypto(None, symbol, klines)

print(f"=== LIVE ANALYSIS FOR {symbol} ===")
print(f"Current Price: {klines[-1]['close']}")
print(f"Global Signal Action: {analysis['global_signal'].get('action')}")
print(f"Global Signal Confidence: {analysis['global_signal'].get('confidence')}%")
print(f"Crypto Score: {score}/100")
print(f"Regime: {analysis.get('market_regime')}")
