import json

with open('data/paper_bot_state.json', 'r', encoding='utf-8') as f:
    state = json.load(f)

positions = state.get('positions', [])
pending_orders = state.get('pending_orders', {})

print("=== LAST 5 POSITIONS ===")
for idx, p in enumerate(positions[-5:]):
    print(f"Index {len(positions)-5+idx}: {p}")

print("\n=== PENDING ORDERS ===")
print(json.dumps(pending_orders, indent=2))
