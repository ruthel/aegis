import json
import os

with open('data/paper_bot_state.json', 'r') as f:
    state = json.load(f)

print("state.get('paper_balance'):", state.get('paper_balance'))
print("PAPER_BALANCE env:", os.getenv('PAPER_BALANCE'))

# Compute paper balance calculation in TradingBot / app.py
positions = state.get('positions', [])
buys_sum = 0
sells_sum = 0
open_buy_cost = 0

by_symbol = {}
for p in positions:
    amt = float(p.get('amount', 0) or 0)
    px = float(p.get('price', 0) or 0)
    val = amt * px
    side = p.get('side')
    if side == 'buy':
        buys_sum += val
        by_symbol[p['symbol']] = by_symbol.get(p['symbol'], 0) + amt
    elif side == 'sell':
        sells_sum += val
        by_symbol[p['symbol']] = max(0, by_symbol.get(p['symbol'], 0) - amt)

print("Total Buys Value:", buys_sum)
print("Total Sells Value:", sells_sum)
print("Open Positions Qty:", by_symbol)
