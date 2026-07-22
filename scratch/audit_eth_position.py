import json

with open('data/paper_bot_state.json', 'r') as f:
    state = json.load(f)

positions = state.get('positions', [])

eth_buys = 0.0
eth_sells = 0.0
eth_buy_cost = 0.0
eth_sell_income = 0.0

print(f"{'Idx':<4} {'Type':<6} {'Qty':<10} {'Price':<10} {'Val':<10} {'Cumul Qty':<10}")
print("-" * 60)
cumul = 0.0
for idx, p in enumerate(positions):
    if p.get('symbol') != 'ETH/USD':
        continue
    side = p.get('side')
    amt = float(p.get('amount', 0) or 0)
    px = float(p.get('price', 0) or 0)
    val = amt * px
    if side == 'buy':
        cumul += amt
        eth_buys += amt
        eth_buy_cost += val
    else:
        cumul -= amt
        eth_sells += amt
        eth_sell_income += val
    print(f"{idx:<4} {side:<6} {amt:<10.4f} ${px:<9.2f} ${val:<9.2f} {cumul:<10.4f}")

print("-" * 60)
print(f"Total ETH Buys:  {eth_buys:.4f} ETH (${eth_buy_cost:.2f})")
print(f"Total ETH Sells: {eth_sells:.4f} ETH (${eth_sell_income:.2f})")
print(f"Net ETH Position: {eth_buys - eth_sells:.4f} ETH")
print(f"Net PnL on ETH: ${eth_sell_income - eth_buy_cost:.2f}")
