import json
import os

state_path = 'data/paper_bot_state.json'
if os.path.exists(state_path):
    with open(state_path, 'r', encoding='utf-8') as f:
        state = json.load(f)
    
    state['pending_orders'] = {}
    
    with open(state_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)
    print("[SUCCESS] Set pending_orders = {} in state!")
