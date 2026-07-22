import json
import os

state_path = 'data/paper_bot_state.json'
with open(state_path, 'r', encoding='utf-8') as f:
    state = json.load(f)

positions = state.get('positions', [])

print(f"Total positions in file: {len(positions)}")
print("\nLast 6 positions:")
for i, p in enumerate(positions[-6:], start=len(positions)-6):
    status = p.get('status', 'open')
    print(f"  [{i}] {p.get('side')} {p.get('amount')} {p.get('symbol')} @ {p.get('price')} (status={status})")

# Identify open buys (buys without closed status or matching sells)
buys = {}
open_buys = []

for i, pos in enumerate(positions):
    sym = pos.get('symbol')
    side = pos.get('side')
    amount = float(pos.get('amount') or 0)
    px = float(pos.get('price') or 0)
    status = pos.get('status')
    
    if not sym or amount <= 0 or px <= 0:
        continue
        
    if side == 'buy' and status != 'closed':
        buys.setdefault(sym, []).append({'index': i, 'amount': amount, 'price': px, 'entry': pos})
    elif side == 'sell':
        rem = amount
        queue = buys.get(sym, [])
        while rem > 1e-12 and queue:
            entry = queue[0]
            filled = min(rem, entry['amount'])
            entry['amount'] -= filled
            rem -= filled
            if entry['amount'] <= 1e-12:
                queue.pop(0)

# Check remaining open buy entries
for sym, q in buys.items():
    for item in q:
        if item['amount'] > 1e-12:
            open_buys.append(item)

print(f"\nUnclosed open buys found: {len(open_buys)}")
for ob in open_buys:
    print("  ->", ob)

# Remove unclosed open buys from positions
if open_buys:
    indices_to_remove = set(ob['index'] for ob in open_buys)
    new_positions = [p for idx, p in enumerate(positions) if idx not in indices_to_remove]
    state['positions'] = new_positions
    print(f"\n[CANCELED] Removed {len(open_buys)} unclosed buy positions from state!")

state['paper_balance'] = 996.35
state['trailing_stops'] = {}
state['exit_recommendations'] = {}
state['pending_orders'] = []

with open(state_path, 'w', encoding='utf-8') as f:
    json.dump(state, f, indent=2)

print(f"[SUCCESS] Cleaned state saved. Paper Balance set to exactly 996.35 USD with 0 open positions!")
