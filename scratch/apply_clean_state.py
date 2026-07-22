import json

state_path = 'data/paper_bot_state.json'
with open(state_path, 'r', encoding='utf-8') as f:
    state = json.load(f)

# Set correct free cash balance
correct_balance = 381.520617
state['paper_balance'] = correct_balance

with open(state_path, 'w', encoding='utf-8') as f:
    json.dump(state, f, indent=2)

print(f"[CLEAN APPLY] paper_bot_state.json updated with paper_balance = {correct_balance} USD")
