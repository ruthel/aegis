import os
import json
import subprocess

print("[KILL & CLEAN WIN] Starting deep cleanup...")

# 1. Kill any background run.py python process using wmic/powershell
try:
    cmd = "Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -like '*run.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
    subprocess.run(["powershell", "-Command", cmd], capture_output=True)
    print("  -> Powershell stop-process executed for run.py")
except Exception as e:
    print("  -> Error stopping process:", e)

# 2. Overwrite paper_bot_state.json and paper_bot_state.json.tmp
state_path = 'data/paper_bot_state.json'
tmp_path = 'data/paper_bot_state.json.tmp'

correct_balance = 381.520617

for path in [state_path, tmp_path]:
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                state = json.load(f)
            state['paper_balance'] = correct_balance
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
            print(f"  -> Cleaned {path} with paper_balance = {correct_balance} USD")
        except Exception as e:
            print(f"  -> Error cleaning {path}: {e}")

# 3. Clean bot.pid
pid_path = 'data/bot.pid'
if os.path.exists(pid_path):
    try:
        os.remove(pid_path)
        print("  -> Removed data/bot.pid")
    except Exception as e:
        print("  -> Error removing bot.pid:", e)

print("[KILL & CLEAN WIN] Completed successfully!")
