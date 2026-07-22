import os
import json
import subprocess
import sys

sys.path.insert(0, os.path.abspath('.'))

print("[DEEP PURGE] Stopping all bot processes and purging open position 610$...")

# 1. Kill background run.py process
try:
    cmd = "Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -like '*run.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
    subprocess.run(["powershell", "-Command", cmd], capture_output=True)
    print("  -> Powershell stop-process executed for run.py")
except Exception as e:
    print("  -> Error stopping process:", e)

# 2. Load paper_bot_state.json and remove Index 45 & 46
state_path = 'data/paper_bot_state.json'
with open(state_path, 'r', encoding='utf-8') as f:
    state = json.load(f)

positions = state.get('positions', [])
print(f"  -> Total positions before purge: {len(positions)}")

clean_positions = [
    p for p in positions 
    if not (p.get('symbol') == 'ETH/USD' and (p.get('order_id') in ['paper_1784682636', 'paper_1784683573'] or p.get('amount') in [0.16767, 0.14796]))
]

print(f"  -> Total positions after purge: {len(clean_positions)}")

state['positions'] = clean_positions
state['paper_balance'] = 996.35
state['trailing_stops'] = {}
state['exit_recommendations'] = {}
state['pending_orders'] = {}

# Save to main state file AND tmp file
for path in [state_path, state_path + '.tmp']:
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)
    print(f"  -> Cleaned and saved {path}")

# Verify weighted_positions
from dashboard.app import weighted_positions
pos = weighted_positions(clean_positions)
print(f"\n[VERIFICATION] Open positions count in weighted_positions: {len(pos)}")
for p in pos:
    print("  -> Open Pos:", p)

if len(pos) == 0:
    print("[SUCCESS] All 610$ open positions completely purged! Paper balance = $996.35 USD.")
