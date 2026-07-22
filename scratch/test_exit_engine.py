import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath('.'))

from utils.exit_engine import ExitDecisionEngine

def run_tests():
    print("[TEST] Running unit tests for ExitDecisionEngine...")
    engine = ExitDecisionEngine(shadow_mode=True, fragile_max_net_pct=0.40, time_stop_minutes=12)

    # Generate synthetic klines
    now = datetime.now()
    klines = []
    base_price = 1000.0
    for i in range(30):
        t = now - timedelta(minutes=(30 - i) * 15)
        price = base_price + i * 2.0
        klines.append({
            'open': price - 1.0,
            'high': price + 2.0,
            'low': price - 1.5,
            'close': price,
            'volume': 100.0 + i * 5.0,
            'time': t.isoformat()
        })

    btc_klines = []
    for i in range(30):
        t = now - timedelta(minutes=(30 - i) * 15)
        price = 60000.0 + i * 50.0
        btc_klines.append({
            'open': price - 20.0,
            'high': price + 50.0,
            'low': price - 30.0,
            'close': price,
            'volume': 500.0,
            'time': t.isoformat()
        })

    # Test 1: High Continuation Score (Uptrend)
    current_price = 1062.0
    score = engine.compute_continuation_score('ETH/USD', current_price, klines, btc_klines)
    print(f"[OK] Test 1 Score (Uptrend): {score}/100")
    assert score >= 60, f"Expected score >= 60, got {score}"

    # Test 2: Position evaluation - HOLD
    position_data = {
        'buy_price': 1000.0,
        'fee_rate': 0.001,
        'created_at': (now - timedelta(minutes=5)).isoformat()
    }
    eval_result = engine.evaluate_position('ETH/USD', current_price, position_data, klines, btc_klines)
    print(f"[OK] Test 2 Eval Result: Decision={eval_result['decision']}, Score={eval_result['continuation_score']}, Net PnL={eval_result['net_pnl_pct']}%")
    assert eval_result['decision'] == 'HOLD', f"Expected HOLD, got {eval_result['decision']}"

    # Test 3: Fragile Profit Zone with Weak Score -> TIGHTEN_STOP
    # Drop current price so net PnL is in fragile zone (+0.15%) and klines exhibit downtrend
    weak_klines = []
    for i in range(30):
        t = now - timedelta(minutes=(30 - i) * 15)
        price = 1000.0 - i * 1.5
        weak_klines.append({
            'open': price + 1.0,
            'high': price + 1.5,
            'low': price - 2.0,
            'close': price,
            'volume': 200.0,
            'time': t.isoformat()
        })
    position_fragile = {
        'buy_price': 997.0,
        'fee_rate': 0.001,
        'created_at': (now - timedelta(minutes=5)).isoformat()
    }
    eval_fragile = engine.evaluate_position('ETH/USD', 1000.0, position_fragile, weak_klines, btc_klines)
    print(f"[OK] Test 3 Fragile Profit Result: Decision={eval_fragile['decision']}, Score={eval_fragile['continuation_score']}, Net PnL={eval_fragile['net_pnl_pct']}%")
    assert eval_fragile['decision'] in ['TIGHTEN_STOP', 'PROTECT_BREAKEVEN'], f"Expected TIGHTEN_STOP or PROTECT_BREAKEVEN, got {eval_fragile['decision']}"

    # Test 4: Time Stop (Stagnation past 12 min)
    position_stagnant = {
        'buy_price': 1000.0,
        'fee_rate': 0.001,
        'created_at': (now - timedelta(minutes=15)).isoformat()
    }
    eval_time = engine.evaluate_position('ETH/USD', 1000.5, position_stagnant, weak_klines, btc_klines)
    print(f"[OK] Test 4 Time Stop Result: Decision={eval_time['decision']}, Score={eval_time['continuation_score']}, Duration={eval_time['duration_minutes']}m")
    assert eval_time['decision'] in ['FORCE_EXIT', 'TIGHTEN_STOP'], f"Expected FORCE_EXIT or TIGHTEN_STOP, got {eval_time['decision']}"

    print("[SUCCESS] All 4 ExitDecisionEngine unit tests passed successfully!")

if __name__ == '__main__':
    run_tests()
