import json

with open('data/paper_bot_state.json', 'r') as f:
    state = json.load(f)

positions = state.get('positions', [])
by_symbol = {}
for p in positions:
    sym = p.get('symbol')
    side = p.get('side')
    amt = float(p.get('amount', 0))
    if side == 'buy':
        by_symbol[sym] = by_symbol.get(sym, 0) + amt
    elif side == 'sell':
        by_symbol[sym] = max(0, by_symbol.get(sym, 0) - amt)

open_positions = {k: v for k, v in by_symbol.items() if v > 1e-6}
print("CURRENT OPEN POSITIONS:", open_positions)
print("EXIT RECOMMENDATIONS IN STATE:", state.get('exit_recommendations'))
