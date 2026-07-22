import json

state_path = 'data/paper_bot_state.json'
with open(state_path, 'r', encoding='utf-8') as f:
    state = json.load(f)

positions = state.get('positions', [])

# Remove open ETH/USD buy entries (order_id paper_1784682636 and paper_1784683573)
clean_positions = [
    p for p in positions 
    if not (p.get('symbol') == 'ETH/USD' and p.get('order_id') in ['paper_1784682636', 'paper_1784683573'])
]

state['positions'] = clean_positions
state['paper_balance'] = 996.35
state['trailing_stops'] = {}
state['exit_recommendations'] = {}

with open(state_path, 'w', encoding='utf-8') as f:
    json.dump(state, f, indent=2)

print("[CLEAN POSITIONS] Removed unclosed open buys. Paper balance set to $996.35 USD.")
