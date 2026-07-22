import json
import os
import sys

sys.path.insert(0, os.path.abspath('.'))

from dashboard.app import trade_stats, weighted_positions, active_state_file, read_json

print("[CANCEL TRADES] Cancelling open ETH/USD position...")

state_path = 'data/paper_bot_state.json'
with open(state_path, 'r', encoding='utf-8') as f:
    state = json.load(f)

positions = state.get('positions', [])

# Remove open ETH/USD buy entries (Index 45 and Index 46)
new_positions = []
cancelled_count = 0
refunded_cost = 0.0

for p in positions:
    if p.get('symbol') == 'ETH/USD' and p.get('order_id') in ['paper_1784682636', 'paper_1784683573']:
        amt = float(p.get('amount', 0))
        px = float(p.get('price', 0))
        refunded_cost += amt * px
        cancelled_count += 1
        print(f"  -> Cancelling trade: {p.get('order_id')} | {amt} ETH @ {px} (${amt*px:.2f})")
    else:
        new_positions.append(p)

state['positions'] = new_positions

# Clear trailing stops and exit recommendations for ETH/USD
if 'trailing_stops' in state:
    state['trailing_stops'].pop('ETH/USD', None)
if 'exit_recommendations' in state:
    state['exit_recommendations'].pop('ETH/USD', None)

# Update paper_balance
initial_balance = float(os.getenv('PAPER_BALANCE', '1000'))
stats = trade_stats(new_positions)
net_pnl = stats['total_pnl_net']

new_cash = initial_balance + net_pnl
state['paper_balance'] = new_cash

with open(state_path, 'w', encoding='utf-8') as f:
    json.dump(state, f, indent=2)

print(f"\n[OK] Cancelled {cancelled_count} open buy trade(s).")
print(f"     Refunded cost: ${refunded_cost:.2f} USD")
print(f"     New Solde Paper (Cash Libre): ${new_cash:.2f} USD")
print(f"     Open positions count: 0")
