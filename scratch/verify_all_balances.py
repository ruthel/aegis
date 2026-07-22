import json
import os

print("=== VERIFYING ALL BALANCES & STATES ===")

# 1. Inspect paper_bot_state.json
state_path = 'data/paper_bot_state.json'
if os.path.exists(state_path):
    with open(state_path, 'r') as f:
        state = json.load(f)
    print(f"1. paper_bot_state.json:")
    print(f"   - Stored paper_balance: {state.get('paper_balance')} USD")
    positions = state.get('positions', [])
    print(f"   - Total history length: {len(positions)} events")
    
    # Calculate open positions
    by_symbol = {}
    for p in positions:
        sym = p.get('symbol')
        amt = float(p.get('amount', 0) or 0)
        px = float(p.get('price', 0) or 0)
        side = p.get('side')
        if side == 'buy':
            by_symbol[sym] = by_symbol.get(sym, 0) + amt
        elif side == 'sell':
            by_symbol[sym] = max(0, by_symbol.get(sym, 0) - amt)
    
    open_pos = {k: v for k, v in by_symbol.items() if v > 1e-6}
    print(f"   - Open positions: {open_pos}")
    print(f"   - Trailing stops stored: {list(state.get('trailing_stops', {}).keys())}")
    print(f"   - Exit recommendations stored: {list(state.get('exit_recommendations', {}).keys())}")

# 2. Inspect daily_stats.json
daily_path = 'data/daily_stats.json'
if os.path.exists(daily_path):
    with open(daily_path, 'r') as f:
        daily = json.load(f)
    print(f"\n2. daily_stats.json:")
    print(f"   - Date: {daily.get('date')}")
    print(f"   - Trades count: {daily.get('trades_count')}")
    print(f"   - Total profit: {daily.get('total_profit')}")
    print(f"   - Total loss: {daily.get('total_loss')}")
    print(f"   - Emergency stop: {daily.get('emergency_stop')}")

# 3. Inspect live_status.json
live_path = 'data/live_status.json'
if os.path.exists(live_path):
    with open(live_path, 'r') as f:
        live = json.load(f)
    print(f"\n3. live_status.json:")
    print(f"   - Running: {live.get('running')}")
    print(f"   - Exchange: {live.get('exchange')}")
    print(f"   - Subscribed symbols: {live.get('subscribed_symbols')}")
    print(f"   - Live prices: {[f'{sym}: {data.get('price')}' for sym, data in live.get('symbols', {}).items()]}")

print("\n=== ALL BALANCE CHECKS COMPLETED ===")
