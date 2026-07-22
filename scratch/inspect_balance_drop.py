import json
import os

state_path = 'data/paper_bot_state.json'
if not os.path.exists(state_path):
    print("State file not found.")
    exit(0)

with open(state_path, 'r', encoding='utf-8') as f:
    state = json.load(f)

balance = state.get('paper_balance')
positions = state.get('positions', [])

print(f"=== PAPER STATE INSPECTION ===")
print(f"Paper Balance in JSON: {balance} USD")
print(f"Total positions in state history: {len(positions)}")

# Open positions vs closed positions
open_pos = [p for p in positions if p.get('status') != 'closed' and p.get('side') == 'buy']
print(f"\nOpen positions count: {len(open_pos)}")
for i, op in enumerate(open_pos):
    print(f"  [{i+1}] {op.get('symbol')} | Qty: {op.get('amount')} | Entry: {op.get('price')} USD | Cost: {float(op.get('amount',0))*float(op.get('price',0)):.2f} USD")

# Show last 15 entries in positions
print("\nLast 15 position entries:")
for idx, p in enumerate(positions[-15:], start=len(positions)-15):
    print(f"  [{idx}] {p.get('side')} {p.get('amount')} {p.get('symbol')} @ {p.get('price')} | status={p.get('status')} | ts={p.get('timestamp')}")
