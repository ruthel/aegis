import sys
import os
import json

sys.path.insert(0, os.path.abspath('.'))

from dashboard.app import trade_stats, weighted_positions, active_state_file, read_json

state = read_json(active_state_file(), {'positions': []})
stats = trade_stats(state.get('positions', []))
open_pos = weighted_positions(state.get('positions', []), state.get('trailing_stops'), state.get('pending_orders'))

initial_balance = float(os.getenv('PAPER_BALANCE', '1000'))
net_pnl = stats['total_pnl_net']
open_cost = sum(p['entry_value'] for p in open_pos)

exact_cash = initial_balance + net_pnl - open_cost
print(f"Initial Balance: ${initial_balance:.2f}")
print(f"Total Net PnL:   ${net_pnl:.4f}")
print(f"Open Cost:       ${open_cost:.4f}")
print(f"Exact Cash:      ${exact_cash:.4f}")

assert abs(exact_cash - 381.52) < 0.1, f"Expected 381.52, got {exact_cash}"
print("[SUCCESS] Exact paper balance calculation verified!")
