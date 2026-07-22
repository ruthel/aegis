import json
import os

state_path = 'data/paper_bot_state.json'
if not os.path.exists(state_path):
    print("State file does not exist.")
else:
    with open(state_path, 'r', encoding='utf-8') as f:
        try:
            state = json.load(f)
            print("=== PAPER BOT STATE ===")
            print("Keys in state:", list(state.keys()))
            print("paper_balance:", state.get('paper_balance'))
            print("positions count:", len(state.get('positions', [])))
        except Exception as e:
            print(f"Error reading JSON: {e}")
