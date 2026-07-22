import json

with open('data/paper_bot_state.json', 'r') as f:
    state = json.load(f)

# Initial balance = 1000.0
initial_balance = 1000.0

# Total net PnL on closed trades = -8.4703 USD
# Open position cost = 610.009 USD (ETH/USD 0.31563 @ 1932.6714)
# Correct Cash balance (paper_balance) = initial_balance + total_pnl_net - open_position_cost
# 1000.0 - 8.4703 - 610.009083 = 381.520617 USD

correct_paper_balance = 381.520617
state['paper_balance'] = correct_paper_balance

with open('data/paper_bot_state.json', 'w') as f:
    json.dump(state, f, indent=2)

print(f"Corrected paper_balance stored: ${correct_paper_balance:.2f} USD")
print(f"Total Portfolio Value (Cash + ETH): ${correct_paper_balance + 610.009083:.2f} USD")
