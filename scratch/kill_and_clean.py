import os
import json
import psutil

print("[KILL & CLEAN] Starting deep cleanup...")

# 1. Kill any running python process running run.py or TradingBot
killed_count = 0
for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        cmd = proc.info.get('cmdline') or []
        cmd_str = ' '.join(cmd)
        if 'run.py' in cmd_str:
            print(f"  -> Terminating background bot process PID {proc.info['pid']}: {cmd_str}")
            proc.kill()
            killed_count += 1
    except Exception as e:
        pass

print(f"  -> Killed {killed_count} background bot process(es).")

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

print("[KILL & CLEAN] Completed successfully!")
