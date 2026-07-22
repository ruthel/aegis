import json
import shutil
from datetime import datetime

# Backup
shutil.copyfile('data/paper_bot_state.json', f'data/paper_bot_state.json.bak_{datetime.now().strftime("%Y%m%d_%H%M%S")}')

with open('data/paper_bot_state.json', 'r') as f:
    state = json.load(f)

positions = state.get('positions', [])

# Fix Index 44: amount should be 0.06203 (the quantity of buy #42)
for p in positions:
    if p.get('order_id') == 'paper_1784682315' or (p.get('side') == 'sell' and p.get('amount') == 0.89539):
        print("Found ghost sell entry:", p)
        p['amount'] = 0.06203
        px = float(p.get('price', 1937.51))
        p['sell_fee'] = 0.06203 * px * 0.001
        p['fee'] = p.get('buy_fee', 0) + p['sell_fee']

# Recalculate running balance
initial_balance = 1000.0
balance = initial_balance

for p in positions:
    amt = float(p.get('amount', 0) or 0)
    px = float(p.get('price', 0) or 0)
    val = amt * px
    if p.get('side') == 'buy':
        balance -= val
    elif p.get('side') == 'sell':
        balance += val

state['paper_balance'] = balance

with open('data/paper_bot_state.json', 'w') as f:
    json.dump(state, f, indent=2)

print(f"Corrected paper_balance: ${balance:.2f} USD")
