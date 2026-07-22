import json
import os

state_path = 'data/paper_bot_state.json'
daily_stats_path = 'data/daily_stats.json'

fresh_state = {
  "paper_balance": 996.35,
  "positions": [],
  "trailing_stops": {},
  "exit_recommendations": {},
  "pending_orders": {},
  "symbol_cooldowns": {},
  "support_touch_filter": {},
  "market_context": {}
}

os.makedirs('data', exist_ok=True)

with open(state_path, 'w', encoding='utf-8') as f:
    json.dump(fresh_state, f, indent=2)

print(f"[SUCCESS] Recreated clean {state_path} with paper_balance = 996.35 USD and 0 open positions.")

# Also ensure daily_stats is clean
fresh_daily_stats = {
  "date": "2026-07-22",
  "trades_count": 0,
  "total_profit": 0.0,
  "total_loss": 0.0,
  "emergency_stop": False
}

with open(daily_stats_path, 'w', encoding='utf-8') as f:
    json.dump(fresh_daily_stats, f, indent=2)

print(f"[SUCCESS] Recreated clean {daily_stats_path} for today.")
