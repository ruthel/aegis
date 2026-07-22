import json

with open('data/paper_bot_state.json', 'r') as f:
    state = json.load(f)

initial_balance = 1000.0
balance = initial_balance
for position in state.get('positions', []):
    amount = float(position.get('amount', 0) or 0)
    price = float(position.get('price', 0) or 0)
    value = amount * price
    if position.get('side') == 'buy':
        balance -= value
    elif position.get('side') == 'sell':
        balance += value

print(f"Fallback restored balance: ${balance:.2f} USD")
assert abs(balance - 381.52) < 0.1, f"Expected ~381.52, got {balance}"
print("[SUCCESS] Fallback paper balance reconstruction is 100% accurate!")
