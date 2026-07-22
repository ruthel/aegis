import json
import os
import sys

sys.path.insert(0, os.path.abspath('.'))

state_path = 'data/paper_bot_state.json'
with open(state_path, 'r', encoding='utf-8') as f:
    state = json.load(f)

target_balance = 996.35
state['paper_balance'] = target_balance

with open(state_path, 'w', encoding='utf-8') as f:
    json.dump(state, f, indent=2)

print(f"[EXACT SET] Updated paper_bot_state.json paper_balance = ${target_balance:.2f} USD")
