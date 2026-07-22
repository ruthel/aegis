import json

with open('data/paper_bot_state.json', 'r') as f:
    state = json.load(f)

positions = state.get('positions', [])
for i in range(40, len(positions)):
    p = positions[i]
    print(f"Index {i}: {p}")
