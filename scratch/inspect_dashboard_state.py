import json
import urllib.request
import sys
import os

sys.path.insert(0, os.path.abspath('.'))
from dashboard.app import trade_stats, weighted_positions, active_state_file, read_json

state = read_json(active_state_file(), {'positions': []})
print("=== LOCAL FILE INSPECTION ===")
print("paper_balance in file:", state.get('paper_balance'))
print("trailing_stops in file:", list(state.get('trailing_stops', {}).keys()))
print("exit_recommendations in file:", list(state.get('exit_recommendations', {}).keys()))

pos = weighted_positions(state.get('positions', []), state.get('trailing_stops'), state.get('pending_orders'), state.get('exit_recommendations'))
print("weighted_positions count:", len(pos))
for p in pos:
    print("  -> Open Pos:", p)

try:
    req = urllib.request.urlopen('http://127.0.0.1:8080/api/status')
    data = json.loads(req.read().decode('utf-8'))
    print("\n=== HTTP API ENDPOINT INSPECTION ===")
    print("  paper_balance:", data.get('balance', {}).get('paper_balance'))
    print("  positions count:", len(data.get('positions', [])))
    for p in data.get('positions', []):
        print("  -> API Pos:", p['symbol'], "Amount:", p['amount'], "Entry Value:", p['entry_value'])
except Exception as e:
    print("\nHTTP API Request Error:", e)
