import os
import sys

sys.path.insert(0, os.path.abspath('.'))

from core.trading_bot import TradingBot

print("=== TESTING LIVE MARKET REGIME DETECTION ===")

bot = TradingBot(api_key='mock', api_secret='mock')

symbols = ['BTC/USD', 'ETH/USD', 'SOL/USD', 'ADA/USD']

for symbol in symbols:
    regime_bot = bot.detect_market_regime(symbol)
    regime_risk = bot.risk_manager._detect_market_regime(symbol)
    
    # Calculate slope details
    h1_klines = bot.get_klines(symbol, 24, '1h')
    if len(h1_klines) >= 12:
        h1_closes = [k['close'] for k in h1_klines]
        h1_ema20 = bot.calculate_ema(h1_closes, 10)
        h1_prev = bot.calculate_ema(h1_closes[:-3], 10)
        slope = (h1_ema20 - h1_prev) / h1_prev if h1_prev else 0
        slope_pct = slope * 100
    else:
        slope_pct = 0.0
        
    print(f"Symbol: {symbol:8s} | Bot Regime: {regime_bot:14s} | Risk Regime: {regime_risk:14s} | Slope 3h: {slope_pct:+.3f}%")

print("\n=== TEST COMPLETED ===")
