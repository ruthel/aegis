import json

backup_path = 'data/paper_bot_state.json.bak_fee_rate_trailing_20260721_110041'
with open(backup_path, 'r') as f:
    state = json.load(f)

print("BACKUP 11:00 paper_balance:", state.get('paper_balance'))

positions = state.get('positions', [])
print("Total positions in backup:", len(positions))

buys = [p for p in positions if p.get('side') == 'buy']
sells = [p for p in positions if p.get('side') == 'sell']
print(f"Buys: {len(buys)}, Sells: {len(sells)}")

by_symbol = {}
for p in positions:
    sym = p.get('symbol')
    amt = float(p.get('amount', 0) or 0)
    side = p.get('side')
    if side == 'buy':
        by_symbol[sym] = by_symbol.get(sym, 0) + amt
    elif side == 'sell':
        by_symbol[sym] = max(0, by_symbol.get(sym, 0) - amt)

print("Open quantities in 11:00 backup:", by_symbol)
