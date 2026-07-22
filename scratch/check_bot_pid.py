import os
import json

pid_file = 'data/bot.pid'
if os.path.exists(pid_file):
    with open(pid_file, 'r') as f:
        pid = f.read().strip()
    print("Bot PID in file:", pid)
    try:
        os.kill(int(pid), 0)
        print("Bot process is RUNNING with PID:", pid)
    except Exception as e:
        print("Bot process is NOT running:", e)
else:
    print("No bot.pid file found.")

with open('data/paper_bot_state.json', 'r') as f:
    state = json.load(f)

print("Current paper_balance in paper_bot_state.json:", state.get('paper_balance'))
