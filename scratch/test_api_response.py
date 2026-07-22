import sys
import os
import json

sys.path.insert(0, os.path.abspath('.'))

from dashboard.app import active_state_file, read_json, weighted_positions

state = read_json(active_state_file(), {'positions': []})
positions = weighted_positions(state.get('positions', []), state.get('trailing_stops'), state.get('pending_orders'), state.get('exit_recommendations'))

print("API WEIGHTED POSITIONS COUNT:", len(positions))
for p in positions:
    print(f"Symbol: {p['symbol']} | Entry: {p['avg_entry_price']} | Exit Recommendation: {p.get('exit_recommendation')}")
