import os
import json

print("[UPDATE CONFIG] Setting MAX_DAILY_TRADES = 50...")

# 1. Update .env.dashboard and .env
env_files = ['.env.dashboard', '.env']
for env_path in env_files:
    lines = []
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    
    updated = False
    new_lines = []
    for line in lines:
        if line.strip().startswith('MAX_DAILY_TRADES='):
            new_lines.append('MAX_DAILY_TRADES=50\n')
            updated = True
        else:
            new_lines.append(line)
            
    if not updated:
        new_lines.append('\nMAX_DAILY_TRADES=50\n')
        
    with open(env_path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    print(f"  -> Updated {env_path} with MAX_DAILY_TRADES=50")

# 2. Update RiskManager in core/trading_bot.py default if 15 was hardcoded
bot_path = 'core/trading_bot.py'
if os.path.exists(bot_path):
    with open(bot_path, 'r', encoding='utf-8') as f:
        content = f.read()
    content = content.replace("os.getenv('MAX_DAILY_TRADES', '15')", "os.getenv('MAX_DAILY_TRADES', '50')")
    with open(bot_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  -> Updated {bot_path} defaults")

print("[SUCCESS] MAX_DAILY_TRADES updated to 50 per day!")
