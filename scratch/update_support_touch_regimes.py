import json
import os
import sys

sys.path.insert(0, os.path.abspath('.'))

from core.trading_bot import TradingBot

print("[UPDATE REGIMES] Refreshing live symbol regimes in state...")

bot = TradingBot(api_key='mock', api_secret='mock')
bot.load_state()

symbols = ['ADA/USD', 'BTC/USD', 'ETH/USD', 'SOL/USD']
state_filter = bot.state.get('support_touch_filter', {})
pairs = state_filter.get('pairs', {})

for sym in symbols:
    regime = bot.detect_market_regime(sym)
    risk_regime = bot.risk_manager._detect_market_regime(sym)
    print(f"  -> {sym}: bot regime = {regime} | risk regime = {risk_regime}")
    
    if sym not in pairs:
        pairs[sym] = {'allowed': False, 'reason': 'not_evaluated'}
    pairs[sym]['regime'] = regime

state_filter['pairs'] = pairs
bot.state['support_touch_filter'] = state_filter
bot.save_state()

print("[SUCCESS] Successfully updated symbol regimes in state!")
