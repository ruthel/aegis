import sys
import os
import json

sys.path.insert(0, os.path.abspath('.'))

from dashboard.app import active_state_file, read_json, trade_stats, weighted_positions

state = read_json(active_state_file(), {'positions': []})

stats = trade_stats(state.get('positions', []))
open_pos = weighted_positions(state.get('positions', []), state.get('trailing_stops'), state.get('pending_orders'), state.get('exit_recommendations'))

print("--- DASHBOARD APP STATS ---")
print("Total Trades:", stats['total_trades'])
print("Wins:", stats['wins'], "| Losses:", stats['losses'], "| Win Rate:", stats['win_rate'], "%")
print("Total PnL Gross:", stats['total_pnl_gross'], "USD")
print("Total Fees:     ", stats['total_fees'], "USD")
print("Total PnL Net:  ", stats['total_pnl_net'], "USD")
print("Stored paper_balance:", state.get('paper_balance'), "USD")
print("\n--- OPEN POSITIONS ---")
for p in open_pos:
    print(p['symbol'], "Amount:", p['amount'], "Entry Value:", p['entry_value'], "USD")
