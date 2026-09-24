import os
import sqlite3
import tempfile
import threading
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
from utils.timeframe_analyzer import TimeframeAnalyzer
from utils.pattern_analyzer import PatternAnalyzer
from core.exchange.kraken import KrakenClient
from core.ml_live_logger import MLLiveLogger
from scripts.promote_challenger import compute_shadow_comparison


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

    def create_limit_buy_order(self, symbol, amount, price, params=None):
        self.limit_calls += 1
        self.last_limit_params = params or {}
        return {"id": "limit-1", "status": "open", "price": price, "amount": amount}

    def fetch_order(self, order_id, symbol):
        return {"id": order_id, "status": "closed", "price": 99.9, "amount": 1.0}

    def cancel_order(self, order_id, symbol):
        return None

    def create_market_buy_order(self, symbol, amount):
        self.market_calls += 1
        return {"id": "market-direct", "status": "closed", "price": 100.1, "amount": amount, "filled": amount}

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


class PartialFillExchange(FakeExchange):
    def __init__(self):
        super().__init__()
        self.market_amounts = []
        self.cancelled = False

    def create_limit_buy_order(self, symbol, amount, price, params=None):
        self.limit_calls += 1
        self.last_limit_params = params or {}
        return {
            "id": "limit-partial",
            "status": "open",
            "price": price,
            "amount": amount,
            "filled": 0.4,
            "remaining": max(0.0, amount - 0.4),
        }

    def cancel_order(self, order_id, symbol):
        self.cancelled = True
        return {"id": order_id, "status": "canceled"}

    def fetch_order(self, order_id, symbol):
        return {
            "id": order_id,
            "status": "canceled" if self.cancelled else "open",
            "price": 99.9,
            "average": 99.9,
            "amount": 1.0,
            "filled": 0.4,
            "remaining": 0.6,
        }

    def create_market_buy_order(self, symbol, amount):
        self.market_calls += 1
        self.market_amounts.append(float(amount))
        return {
            "id": "market-remainder",
            "status": "closed",
            "price": 100.2,
            "average": 100.2,
            "amount": amount,
            "filled": amount,
        }


class NativeTimeframeBot:
    def __init__(self):
        self.calls = []

    def get_klines(self, symbol, limit, timeframe):
        self.calls.append((symbol, limit, timeframe))
        return [
            {"timestamp": i, "open": i, "high": i + 1, "low": i - 1, "close": i + 0.5, "volume": 1}
            for i in range(limit)
        ]


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
        self.assertTrue(bot.exchange.last_limit_params.get("postOnly"))

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

    def test_native_timeframes_are_not_aggregated_twice(self):
        bot = NativeTimeframeBot()
        analyzer = TimeframeAnalyzer()
        rows = analyzer.get_klines_for_timeframe(bot, "BTC/USD", "15m", limit=50)
        self.assertEqual(bot.calls[-1], ("BTC/USD", 50, "15m"))
        self.assertEqual(len(rows), 50)
        self.assertEqual(rows[-1]["timestamp"], 49)

    def test_support_resistance_clusters_nearby_prices(self):
        analyzer = PatternAnalyzer(bot=None)
        highs = [101.0, 101.1, 101.2, 103.0]
        lows = [100.0, 100.2, 99.9, 98.0]
        volumes = [1.0, 1.0, 1.0, 1.0]
        supports = analyzer._find_pivot_lows(lows, volumes, bucket_size=0.5)
        self.assertTrue(any(level["touches"] >= 2 for level in supports))

    def test_kraken_limit_buy_wrapper_forwards_post_only(self):
        class RawExchange:
            def __init__(self):
                self.args = None
            def create_limit_buy_order(self, symbol, amount, price, params):
                self.args = (symbol, amount, price, params)
                return {"id": "x"}

        raw = RawExchange()
        client = object.__new__(KrakenClient)
        client._exchange = raw
        client._api_lock = threading.RLock()
        result = client.create_limit_buy_order("BTC/USD", 0.1, 100.0, {"postOnly": True})
        self.assertEqual(result["id"], "x")
        self.assertEqual(raw.args[3], {"postOnly": True})

    def test_partial_limit_fill_only_markets_remainder(self):
        bot = FakeBot()
        bot.exchange = PartialFillExchange()
        manager = ExecutionManager(bot)
        manager.max_allowed_spread_pct = 1.0
        manager.limit_fill_timeout = 0.0
        ok = manager.execute_smart_buy(
            "BTC/USD", self._position_data(70.0), 100.0, "partial-fill-test"
        )
        self.assertTrue(ok)
        self.assertEqual(bot.exchange.limit_calls, 1)
        self.assertEqual(bot.exchange.market_calls, 1)
        self.assertAlmostEqual(bot.exchange.market_amounts[0], 0.6, places=6)
        self.assertTrue(bot.exchange.last_limit_params.get("postOnly"))
        positions = bot.state.get("positions", [])
        self.assertTrue(positions)
        self.assertAlmostEqual(positions[-1]["amount"], 1.0, places=6)

    def test_calibrated_entry_and_expected_pnl_models_train(self):
        rng = np.random.default_rng(42)
        X = rng.normal(size=(260, 8))
        y = (X[:, 0] + X[:, 1] * 0.3 > 0).astype(int)
        pnl = X[:, 0] * 0.7 - 0.1
        with tempfile.TemporaryDirectory() as td, patch.dict(
            os.environ,
            {"ML_SKIP_MODEL_METADATA": "true", "ML_TEMPORAL_TEST_RATIO": "0.20"},
            clear=False,
        ):
            engine = MLEngine(model_dir=td)
            self.assertTrue(engine.train_model(X, y, use_lightgbm=False))
            self.assertIsNotNone(engine.probability_calibrator)
            self.assertTrue(engine.train_edge_model(X, pnl, use_lightgbm=False))
            pred = engine.predict_win_probability_from_features(X[-1])
            edge = engine.predict_expected_net_pnl(X[-1])
            self.assertGreaterEqual(pred, 0.0)
            self.assertLessEqual(pred, 100.0)
            self.assertTrue(edge["ml_edge_available"])

    def test_exit_model_uses_temporal_validation_and_calibration(self):
        rng = np.random.default_rng(7)
        engine = MLEngine(model_dir="data/nonexistent-exit-test")
        n_features = len(engine.exit_feature_names)
        X = rng.normal(size=(260, n_features))
        y = (X[:, 0] + 0.2 * X[:, 1] > 0).astype(int)
        ts = np.arange(260, dtype=float)
        with tempfile.TemporaryDirectory() as td, patch.dict(
            os.environ,
            {"ML_SKIP_MODEL_METADATA": "true", "ML_TEMPORAL_TEST_RATIO": "0.20"},
            clear=False,
        ):
            engine.model_dir = td
            engine.model_path = os.path.join(td, "aegis_model.joblib")
            # save_model requires an entry model; use a tiny trained one first.
            entry_X = rng.normal(size=(260, len(engine.feature_names)))
            entry_y = (entry_X[:, 0] > 0).astype(int)
            self.assertTrue(engine.train_model(entry_X, entry_y, use_lightgbm=False))
            self.assertTrue(engine.train_exit_model(X, y, timestamps=ts, use_lightgbm=False))
            self.assertEqual(engine.model_metadata.get("exit_validation_type"), "temporal_holdout")
            self.assertIn("exit_test_brier", engine.model_metadata)
            self.assertIsNotNone(engine.exit_calibrator)

    def test_shadow_comparison_uses_same_outcomes(self):
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "aegis.sqlite3")
            logger = MLLiveLogger(data_dir=td, sqlite_file=db)
            entry_id = logger.record_entry_decision(
                symbol="BTC/USD", decision="accepted", price=100.0,
                p_win=60.0, min_p_win=50.0, mode="paper"
            )
            logger.record_shadow_prediction(
                "BTC/USD", entry_id, champion_p_win=60.0,
                challenger_p_win=40.0, threshold=50.0, mode="paper"
            )
            logger.mark_entry_opened("BTC/USD", entry_id, order={"id": "o1"}, price=100.0, amount=1.0)
            logger.record_exit_outcome(
                "BTC/USD", sell_price=101.0, amount=1.0,
                buy_price=100.0, pnl=1.0, pnl_pct=1.0, mode="paper"
            )
            logger.close()
            shadow = compute_shadow_comparison(db)
            self.assertEqual(shadow["outcomes"], 1)
            self.assertEqual(shadow["champion"]["trades"], 1)
            self.assertEqual(shadow["challenger"]["trades"], 0)

    def test_training_pipeline_contains_shared_signals_and_robust_targets(self):
        source = (ROOT / "scripts/train_and_evaluate_ml_model.py").read_text(encoding="utf-8")
        self.assertNotIn("signals_here = signal_engine.detect_all", source)
        self.assertIn("best_signal = signal_engine.detect_best", source)
        self.assertIn("ML_TARGET_PATH_QUANTILE", source)
        self.assertIn("hold_advantage", source)
        self.assertIn("training_histories", source)

    def test_live_strategy_has_hard_gates_and_expected_edge(self):
        source = (ROOT / "core/trading_bot.py").read_text(encoding="utf-8")
        self.assertIn("crypto_score_below_threshold", source)
        self.assertIn("technical_action_", source)
        self.assertIn("technical_confidence_below_threshold", source)
        self.assertIn("no_shared_candidate_signal", source)
        self.assertIn("ml_expected_net_edge_below_threshold", source)
        self.assertIn("ML_SHADOW_CHALLENGER_ENABLED", source)

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
        self.assertIn("_cursor_at_or_before", pipeline)
        self.assertIn("<= int(candle_ts)", pipeline)


if __name__ == "__main__":
    unittest.main()
