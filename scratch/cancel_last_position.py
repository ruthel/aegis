import json
import os

state_path = 'data/paper_bot_state.json'
if not os.path.exists(state_path):
    print("State file not found.")
    exit(0)

with open(state_path, 'r', encoding='utf-8') as f:
    state = json.load(f)

positions = state.get('paper_positions', [])
history = state.get('paper_history', [])

print(f"Current open positions count: {len(positions)}")
print(f"Total history entries: {len(history)}")

if positions:
    print("Open positions found:")
    for pos in positions:
        print("  ->", pos)
else:
    print("No open positions in paper_positions list.")

# Check last entries in history
print("\nLast 5 history entries:")
for i, h in enumerate(history[-5:], start=len(history)-5):
    print(f"  [{i}] {h.get('side')} {h.get('amount')} {h.get('symbol')} @ {h.get('price')}")

# If the last history entry is a BUY without a matching SELL, remove it
if history and history[-1].get('side') == 'buy':
    last_buy = history.pop()
    print(f"\n[CANCELED] Removed last buy entry from history: {last_buy}")

# Reset open positions list to empty
state['paper_positions'] = []

# Recalculate paper_balance accurately based on net historical trades
initial_balance = 1000.0
buys = {}
trades = []

for pos in history:
    sym = pos.get('symbol')
    side = pos.get('side')
    amount = float(pos.get('amount') or 0)
    px = float(pos.get('price') or 0)
    if not sym or amount <= 0 or px <= 0:
        continue
    if side == 'buy':
        buys.setdefault(sym, []).append({'amount': amount, 'price': px})
    elif side == 'sell':
        rem = amount
        queue = buys.get(sym, [])
        while rem > 1e-12 and queue:
            entry = queue[0]
            filled = min(rem, entry['amount'])
            pnl_gross = filled * (px - entry['price'])
            fee_rate = pos.get('fee_rate')
            if fee_rate is not None:
                fees = (entry['price'] * filled * float(fee_rate)) + (px * filled * float(fee_rate))
            else:
                total_fee = float(pos.get('fee') or 0)
                fees = total_fee * (filled / amount) if amount > 0 else 0
            pnl_net = pnl_gross - fees
            trades.append(pnl_net)
            entry['amount'] -= filled
            rem -= filled
            if entry['amount'] <= 1e-12:
                queue.pop(0)

total_net_pnl = sum(trades)
new_balance = round(initial_balance + total_net_pnl, 2)
state['paper_balance'] = new_balance
state['trailing_stops'] = {}
state['exit_recommendations'] = {}
state['pending_orders'] = []

with open(state_path, 'w', encoding='utf-8') as f:
    json.dump(state, f, indent=2)

print(f"\n[SUCCESS] State updated successfully! Solde Paper exact = {new_balance:.2f} USD with 0 open positions.")
