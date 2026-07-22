import json

with open('data/paper_bot_state.json', 'r') as f:
    state = json.load(f)

positions = state.get('positions', [])
initial_balance = 1000.0
balance = initial_balance

print(f"Starting balance: ${initial_balance:.2f}\n")
print(f"{'Idx':<4} {'Type':<6} {'Symbol':<8} {'Qty':<10} {'Price':<10} {'Value':<12} {'New Balance':<12}")
print("-" * 70)

for idx, p in enumerate(positions):
    side = p.get('side')
    sym = p.get('symbol')
    amt = float(p.get('amount', 0) or 0)
    px = float(p.get('price', 0) or 0)
    val = amt * px
    if side == 'buy':
        balance -= val
    elif side == 'sell':
        balance += val
    print(f"{idx:<4} {side:<6} {sym:<8} {amt:<10.4f} ${px:<9.2f} ${val:<11.2f} ${balance:<11.2f}")

print("-" * 70)
print(f"Final calculated paper_balance: ${balance:.2f}")
print(f"Stored paper_balance in JSON:   ${state.get('paper_balance')}")
