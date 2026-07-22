import json
import time

state_path = 'data/paper_bot_state.json'
with open(state_path, 'r') as f:
    state = json.load(f)

# Correct cash balance = 381.520617 USD
correct_cash = 381.520617
state['paper_balance'] = correct_cash

# Ensure trailing_stops has entry for open ETH/USD position
trailing = state.get('trailing_stops', {})
if 'ETH/USD' not in trailing:
    trailing['ETH/USD'] = {
        'buy_price': 1932.6714285714286,
        'highest_price': 1932.6714285714286,
        'stop_price': 1932.6714285714286 * 0.97, # 3% trailing stop
        'trailing_percent': 3.0,
        'initial_trailing_percent': 3.0,
        'breakeven_active': False,
        'fee_rate': 0.001,
        'created_at': '2026-07-21T21:26:13.516092'
    }
state['trailing_stops'] = trailing

# Ensure exit_recommendations has entry for open ETH/USD position
recs = state.get('exit_recommendations', {})
recs['ETH/USD'] = {
    'symbol': 'ETH/USD',
    'decision': 'HOLD',
    'continuation_score': 50,
    'net_pnl_pct': 0.0,
    'duration_minutes': 65.0,
    'reason': 'momentum_healthy',
    'shadow_mode': True,
    'timestamp': '2026-07-21T22:31:00.000000'
}
state['exit_recommendations'] = recs

with open(state_path, 'w') as f:
    json.dump(state, f, indent=2)

print(f"[OK] Successfully synchronized paper_bot_state.json:")
print(f"   - paper_balance (Cash): ${correct_cash:.2f} USD")
print(f"   - open position: ETH/USD (0.31563 ETH)")
print(f"   - trailing stop active for ETH/USD")
print(f"   - exit recommendation active for ETH/USD")
