import os
import unittest
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from core.websocket import WebSocketManager
from core.managers.execution_manager import ExecutionManager
from core.ml_engine import MLEngine
from utils.capital_manager import CapitalManager


ROOT = Path(__file__).resolve().parents[1]


class FakeThread:
    def is_alive(self):
        return True


class FakeWebSocket:
    def __init__(self, bid=99.9, ask=100.1, last=100.0):
        self.bid = bid
        self.ask = ask
        self.last = last

    def is_connected(self):
        return True

    def get_ticker(self, symbol):
        return {"bid": self.bid, "ask": self.ask, "last": self.last, "symbol": symbol}


class FakeExchange:
    def __init__(self):
        self.limit_calls = 0
        self.market_calls = 0

    def create_limit_buy_order(self, symbol, amount, price):
        self.limit_calls += 1
        return {"id": "limit-1", "status": "open", "price": price, "amount": amount}

    def fetch_order(self, order_id, symbol):
        return {"id": order_id, "status": "closed", "price": 99.9, "amount": 1.0}

    def cancel_order(self, order_id, symbol):
        return None

    def fetch_trading_fees(self):
        return {"BTC/USD": {"maker": 0.0016, "taker": 0.0026}}


class FakeCapital:
    def can_open_new_position(self, symbol, amount):
        return True


class FakeBot:
    def __init__(self, p_win=70.0):
        self.paper_trading = False
        self.websocket = FakeWebSocket()
        self.exchange = FakeExchange()
        self.capital_manager = FakeCapital()
        self.state = {"positions": []}
        self.trailing_stop_manager = None
        self.ml_live_logger = None
        self._p_win = p_win
        self.last_order_type = None

    def get_symbol_cooldown_remaining(self, symbol):
        return 0

    def can_open_position(self, symbol):
        return True

    def get_price(self, symbol):
        return 100.0

    def get_ticker(self, symbol):
        return self.websocket.get_ticker(symbol)

    def buy_market(self, symbol, amount, sizing_reason=None, ml_buy_prob=None):
        self.exchange.market_calls += 1
        return {"id": "market-1", "status": "closed", "price": 100.1, "amount": amount}

    def _resolve_exchange_execution(self, symbol, order, amount, fallback_price, side="buy"):
        return {
            "price": float(order.get("price") or fallback_price),
            "amount": float(order.get("amount") or amount),
            "fee_amount": 0.01,
        }

    def _record_live_order_accounting(self, *args, **kwargs):
        return None

    def set_symbol_cooldown(self, *args, **kwargs):
        return None

    def get_real_buy_price(self, symbol):
        return 100.0

    def record_decision(self, *args, **kwargs):
        return None

    def save_state(self):
        return None


class LiveFixTests(unittest.TestCase):
    def test_websocket_ticker_exposes_bid_and_ask(self):
        ws = object.__new__(WebSocketManager)
        ws.prices = {"BTCUSD": 100.0}
        ws.market_meta = {"BTCUSD": {"bid": 99.9, "ask": 100.1, "spread": 0.2, "spread_percent": 0.2}}
        ticker = ws.get_ticker("BTC/USD")
        self.assertEqual(ticker["bid"], 99.9)
        self.assertEqual(ticker["ask"], 100.1)
        self.assertEqual(ticker["last"], 100.0)

    def test_websocket_klines_do_not_cross_timeframes(self):
        ws = object.__new__(WebSocketManager)
        ws.klines = {
            "BTCUSD": deque(
                [{"timestamp": i, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1} for i in range(20)],
                maxlen=100,
            )
        }
        self.assertEqual(len(ws.get_klines("BTC/USD", 10, timeframe="1m")), 10)
        self.assertEqual(ws.get_klines("BTC/USD", 10, timeframe="15m"), [])
        self.assertEqual(ws.get_klines("BTC/USD", 10, timeframe="1h"), [])

    def test_is_connected_requires_real_connected_flag(self):
        ws = object.__new__(WebSocketManager)
        ws.running = True
        ws.ws = object()
        ws.ws_thread = FakeThread()
        ws.is_ws_connected = False
        self.assertFalse(ws.is_connected())
        ws.is_ws_connected = True
        self.assertTrue(ws.is_connected())

    def test_execution_spread_uses_websocket_bid_ask(self):
        bot = FakeBot()
        manager = ExecutionManager(bot)
        micro = manager.get_market_microstructure("BTC/USD")
        self.assertAlmostEqual(micro["bid"], 99.9)
        self.assertAlmostEqual(micro["ask"], 100.1)
        self.assertGreater(micro["spread_pct"], 0.0)

    def _position_data(self, p_win):
        return {
            "position_size_crypto": 1.0,
            "position_size_usd": 100.0,
            "ml_buy_prob": p_win,
            "sizing_reason": "test",
            "stop_loss_price": 95.0,
            "stop_loss_percent": 5.0,
            "risk_reward_ratio": 2.0,
        }

    def test_execution_uses_limit_below_80_percent(self):
        bot = FakeBot()
        manager = ExecutionManager(bot)
        manager.limit_fill_timeout = 0.05
        manager.max_allowed_spread_pct = 1.0
        with patch("core.managers.execution_manager.time.sleep", return_value=None):
            ok = manager.execute_smart_buy(
                "BTC/USD", self._position_data(70.0), 100.0, "test"
            )
        self.assertTrue(ok)
        self.assertEqual(bot.exchange.limit_calls, 1)
        self.assertEqual(bot.exchange.market_calls, 0)

    def test_execution_uses_market_at_or_above_80_percent(self):
        bot = FakeBot()
        manager = ExecutionManager(bot)
        manager.max_allowed_spread_pct = 1.0
        ok = manager.execute_smart_buy(
            "BTC/USD", self._position_data(80.0), 100.0, "test"
        )
        self.assertTrue(ok)
        self.assertEqual(bot.exchange.limit_calls, 0)
        self.assertEqual(bot.exchange.market_calls, 1)

    def test_online_fees_take_precedence(self):
        bot = SimpleNamespace(
            paper_trading=False,
            exchange=FakeExchange(),
            safe_request=lambda fn, *a, **kw: fn(*a, **kw),
        )
        manager = CapitalManager(bot)
        fees = manager.get_real_trading_fees("BTC/USD")
        self.assertAlmostEqual(fees["maker"], 0.0016)
        self.assertAlmostEqual(fees["taker"], 0.0026)

    def test_fee_fallback_uses_configured_value(self):
        bot = SimpleNamespace(paper_trading=True)
        with patch.dict(os.environ, {"TRADING_FEE_PERCENT": "0.4"}, clear=False):
            manager = CapitalManager(bot)
            fees = manager.get_real_trading_fees("BTC/USD")
        self.assertAlmostEqual(fees["taker"], 0.004)
        self.assertAlmostEqual(fees["maker"], 0.0036)

    def test_temporal_holdout_keeps_future_in_test(self):
        engine = MLEngine(model_dir="data/nonexistent-test-model")
        X = np.arange(500).reshape(100, 5)
        y = np.array([0, 1] * 50)
        w = np.arange(100, dtype=float)
        with patch.dict(os.environ, {"ML_TEMPORAL_TEST_RATIO": "0.20"}, clear=False):
            X_train, X_test, y_train, y_test, w_train, w_test = engine._temporal_holdout_split(X, y, w)
        self.assertTrue(np.array_equal(X_train, X[:80]))
        self.assertTrue(np.array_equal(X_test, X[80:]))
        self.assertTrue(np.array_equal(y_train, y[:80]))
        self.assertTrue(np.array_equal(y_test, y[80:]))
        self.assertTrue(np.array_equal(w_train, w[:80]))
        self.assertTrue(np.array_equal(w_test, w[80:]))

    def test_unified_env_and_removed_dl_are_clean(self):
        targets = [
            "start.py",
            "ui/server.py",
            "scripts/walk_forward_validation.py",
            "scripts/analyze_ml_live_performance.py",
            "scripts/promote_challenger.py",
            "scripts/train_and_evaluate_ml_model.py",
        ]
        for rel in targets:
            source = (ROOT / rel).read_text(encoding="utf-8")
            self.assertNotIn(".env.local", source, rel)
            self.assertNotIn(".env.ui", source, rel)

        core_source = (ROOT / "core/trading_bot.py").read_text(encoding="utf-8")
        self.assertNotIn("DL_SHADOW", core_source)
        self.assertNotIn("deep_learning", core_source)

        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("lightgbm", requirements.lower())
        self.assertNotIn("torch", requirements.lower())

    def test_training_uses_time_series_validation(self):
        source = (ROOT / "core/ml_engine.py").read_text(encoding="utf-8")
        self.assertIn("TimeSeriesSplit", source)
        self.assertNotIn("train_test_split(", source)
        pipeline = (ROOT / "scripts/train_and_evaluate_ml_model.py").read_text(encoding="utf-8")
        self.assertIn("temporal_order = np.argsort", pipeline)
        self.assertIn("<= int(ts)", pipeline)


if __name__ == "__main__":
    unittest.main()
