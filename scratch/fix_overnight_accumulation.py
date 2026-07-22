import json
import os

state_path = 'data/paper_bot_state.json'
if not os.path.exists(state_path):
    print("State file not found.")
    exit(0)

with open(state_path, 'r', encoding='utf-8') as f:
    state = json.load(f)

positions = state.get('positions', [])

print(f"[AUDIT] Initial positions count: {len(positions)}")

# Keep only closed historical trades (remove unclosed buy entries from overnight)
closed_positions = []
for p in positions:
    if p.get('status') == 'closed' or p.get('side') == 'sell':
        closed_positions.append(p)

state['positions'] = closed_positions
state['paper_balance'] = 996.35
state['trailing_stops'] = {}
state['exit_recommendations'] = {}
state['pending_orders'] = {}

with open(state_path, 'w', encoding='utf-8') as f:
    json.dump(state, f, indent=2)

print(f"[SUCCESS] State cleaned! Paper Balance restored to 996.35 USD with 0 open positions.")
