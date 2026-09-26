import os
import sqlite3
import tempfile
import time
import threading
import unittest
from collections import deque
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import joblib

from core.websocket import WebSocketManager
from core.managers.execution_manager import ExecutionManager
from core.ml_engine import MLEngine
from utils.capital_manager import CapitalManager
from utils.timeframe_analyzer import TimeframeAnalyzer
from utils.pattern_analyzer import PatternAnalyzer
from core.exchange.kraken import KrakenClient
from core.ml_live_logger import MLLiveLogger
from scripts.promote_challenger import compute_shadow_comparison
from core.bot.trading import TradingMixin
from utils.market_structure import detect_falling_knife, detect_reversal_confirmation
from scripts.train_and_evaluate_ml_model import build_training_bot_context
from scripts.walk_forward_validation import _historical_spread_pct


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
            "price": float(order.get("average") or order.get("price") or fallback_price),
            "amount": float(order.get("filled") or order.get("amount") or amount),
            "fee_amount": 0.01,
        }

    def _confirm_live_order_execution(self, symbol, order, side=None):
        return self._resolve_exchange_execution(
            symbol,
            order,
            float(order.get("amount") or order.get("filled") or 0.0),
            float(order.get("average") or order.get("price") or self.get_price(symbol)),
            side=side or "buy",
        )

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


class PaperFeeManager:
    def get_fee_for_trade(self, symbol, order_type='market'):
        return 0.0015 if order_type == 'limit' else 0.0025


class PaperSimulationHarness(TradingMixin):
    def __init__(self):
        self.paper_trading = True
        self.trading_fee = 0.004
        self.capital_manager = PaperFeeManager()

    def get_ticker(self, symbol):
        return {'bid': 99.9, 'ask': 100.1, 'last': 100.0, 'symbol': symbol}

    def get_price(self, symbol):
        return 100.0


def _trend_klines(count, start, step, timeframe_ms):
    rows = []
    for i in range(count):
        close = start + step * i
        rows.append({
            'timestamp': i * timeframe_ms,
            'open': close - step * 0.2,
            'high': close + abs(step) * 0.3 + 0.1,
            'low': close - abs(step) * 0.3 - 0.1,
            'close': close,
            'volume': 100.0 + i,
        })
    return rows


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

    def _minimal_ws_manager(self):
        ws = object.__new__(WebSocketManager)
        ws.running = True
        ws.is_ws_connected = False
        ws.ws = None
        ws.ws_thread = None
        ws.reconnect_attempts = 0
        ws.last_connected_ts = time.time() - 60
        ws.connected_since_ts = 0.0
        ws.last_message_ts = 0.0
        ws.last_market_data_ts = 0.0
        ws.last_heartbeat_ts = 0.0
        ws.last_disconnect_ts = 0.0
        ws.last_disconnect_reason = None
        ws.last_close_code = None
        ws._rate_limited_until = 0.0
        ws._next_reconnect_ts = 0.0
        ws._reconnect_state_lock = threading.Lock()
        ws._reconnect_pending = False
        ws._reconnect_thread = None
        ws._reconnect_history = deque(maxlen=50)
        return ws

    def test_websocket_heartbeat_counts_as_connection_activity(self):
        ws = self._minimal_ws_manager()
        current = object()
        ws.ws = current
        before = time.time()
        ws.on_message_kraken(current, '{"event":"heartbeat"}')
        self.assertGreaterEqual(ws.last_message_ts, before)
        self.assertEqual(ws.last_heartbeat_ts, ws.last_message_ts)

    def test_websocket_reconnect_is_single_flight(self):
        ws = self._minimal_ws_manager()

        class ThreadStub:
            def __init__(self, *args, **kwargs):
                pass
            def start(self):
                pass

        with patch("core.websocket.threading.Thread", ThreadStub):
            self.assertTrue(ws._schedule_reconnect("first"))
            self.assertFalse(ws._schedule_reconnect("duplicate"))
        self.assertTrue(ws._reconnect_pending)

    def test_websocket_open_does_not_reset_backoff_until_stable(self):
        ws = self._minimal_ws_manager()
        ws.reconnect_attempts = 4
        ws.symbols = ["BTCUSD"]

        class SocketStub:
            def __init__(self):
                self.messages = []
            def send(self, message):
                self.messages.append(message)

        socket = SocketStub()
        ws.ws = socket
        ws._on_open_kraken(socket)
        self.assertTrue(ws.is_ws_connected)
        self.assertEqual(ws.reconnect_attempts, 4)
        self.assertEqual(len(socket.messages), 3)

        ws.connected_since_ts = time.time() - 200
        ws._reconnect_history.extend([time.time() - 20, time.time() - 10])
        with patch.dict(os.environ, {"WS_STABLE_CONNECTION_SECONDS": "30"}, clear=False):
            self.assertTrue(ws._maybe_mark_connection_stable())
        self.assertEqual(ws.reconnect_attempts, 0)
        self.assertEqual(len(ws._reconnect_history), 0)

    def test_websocket_stale_stream_is_not_reported_connected(self):
        ws = self._minimal_ws_manager()
        ws.ws = object()
        ws.ws_thread = FakeThread()
        ws.is_ws_connected = True
        ws.last_message_ts = time.time() - 120
        with patch.dict(os.environ, {"WS_STALE_TIMEOUT_SECONDS": "30"}, clear=False):
            self.assertFalse(ws.is_connected())

    def test_websocket_ignores_close_from_stale_socket(self):
        ws = self._minimal_ws_manager()
        current = object()
        ws.ws = current
        with patch.object(ws, "_schedule_reconnect") as schedule:
            ws.on_close(object(), 1006, "old socket")
        schedule.assert_not_called()

    def test_rest_ticker_fallback_is_cached_during_ws_outage(self):
        from core.trading_bot import TradingBot

        class ExchangeStub:
            def __init__(self):
                self.calls = 0
            def fetch_ticker(self, symbol):
                self.calls += 1
                return {"last": 123.45, "symbol": symbol}

        bot = object.__new__(TradingBot)
        bot.exchange = ExchangeStub()
        bot.paper_trading = False
        bot._rest_ticker_cache = {}
        bot._rest_ticker_cache_lock = threading.Lock()
        bot._last_rest_ticker_request_ts = 0.0
        bot.safe_request = lambda fn, *args, **kwargs: fn(*args, **kwargs)

        with patch.dict(
            os.environ,
            {
                "TICKER_REST_CACHE_TTL_SECONDS": "10",
                "TICKER_REST_MIN_INTERVAL_SECONDS": "0",
            },
            clear=False,
        ):
            self.assertEqual(bot.get_price("BTC/USD"), 123.45)
            self.assertEqual(bot.get_price("BTC/USD"), 123.45)
        self.assertEqual(bot.exchange.calls, 1)

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
            self.assertIn('test_baseline_brier', engine.model_metadata)
            self.assertIn('test_brier_skill', engine.model_metadata)
            self.assertIn('edge_baseline_mae_pct', engine.model_metadata)
            self.assertIn('edge_mae_skill', engine.model_metadata)
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
            self.assertIn("exit_test_baseline_brier", engine.model_metadata)
            self.assertIn("exit_test_brier_skill", engine.model_metadata)
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

    def test_shared_falling_knife_features_match_training_context(self):
        daily = _trend_klines(80, 200.0, -1.0, 86_400_000)
        h4 = _trend_klines(80, 150.0, -0.5, 14_400_000)
        h1 = _trend_klines(40, 120.0, -0.2, 3_600_000)
        falling = detect_falling_knife(daily, h4)
        reversal = detect_reversal_confirmation(h1)
        self.assertTrue(falling['is_falling'])
        self.assertFalse(reversal['confirmed'])

        context = build_training_bot_context(
            history=_trend_klines(80, 100.0, -0.1, 900_000),
            signal={'type': 'ema_pullback_15m', 'confidence': 70.0},
            ts=daily[-1]['timestamp'],
            h1_history=h1,
            h4_history=h4,
            d1_history=daily,
        )
        self.assertTrue(context['falling_knife_active'])
        self.assertFalse(context['reversal_confirmed'])

    def test_live_has_hard_anti_falling_knife_gate(self):
        source = (ROOT / 'core/trading_bot.py').read_text(encoding='utf-8')
        self.assertIn('falling_knife_without_reversal', source)
        self.assertIn('HARD_ANTI_FALLING_KNIFE', source)

    def test_paper_market_execution_uses_bid_ask_slippage_and_online_fee(self):
        bot = PaperSimulationHarness()
        with patch.dict(os.environ, {
            'PAPER_MARKET_SLIPPAGE_PCT': '0.03',
            'PAPER_SPREAD_SLIPPAGE_FACTOR': '0.25',
            'PAPER_MARKET_LATENCY_MS': '150',
        }, clear=False):
            snap = bot._paper_execution_snapshot('BTC/USD', 'buy', 'market', amount=1.0)
        self.assertGreater(snap['price'], 100.1)
        self.assertAlmostEqual(snap['fee_rate'], 0.0025)
        self.assertEqual(snap['latency_ms'], 150.0)
        self.assertGreater(snap['spread_pct'], 0.0)

    def test_paper_limit_execution_simulates_partial_maker_fill(self):
        bot = PaperSimulationHarness()
        with patch.dict(os.environ, {
            'PAPER_SIMULATE_PARTIAL_FILLS': 'True',
            'PAPER_LIMIT_PARTIAL_FILL_RATIO': '0.50',
            'PAPER_LIMIT_FULL_FILL_PENETRATION_PCT': '0.05',
        }, clear=False):
            snap = bot._paper_execution_snapshot(
                'BTC/USD', 'buy', 'limit', amount=2.0, limit_price=100.1
            )
        self.assertAlmostEqual(snap['amount'], 1.0)
        self.assertAlmostEqual(snap['fill_ratio'], 0.5)
        self.assertAlmostEqual(snap['fee_rate'], 0.0015)

    def test_model_contract_is_persisted_and_schema_mismatch_is_rejected(self):
        rng = np.random.default_rng(123)
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {
            'ML_SKIP_MODEL_METADATA': 'true',
            'ML_STRICT_MODEL_SCHEMA': 'True',
            'ML_TEMPORAL_TEST_RATIO': '0.20',
        }, clear=False):
            engine = MLEngine(model_dir=td)
            X = rng.normal(size=(260, len(engine.feature_names)))
            y = (X[:, 0] > 0).astype(int)
            engine.model_metadata = {
                'training_start': '2026-01-01T00:00:00+00:00',
                'training_end': '2026-09-01T00:00:00+00:00',
                'data_provider': 'test',
            }
            self.assertTrue(engine.train_model(X, y, use_lightgbm=False))
            payload = joblib.load(engine.model_path)
            self.assertEqual(payload['model_contract']['model_format_version'], 5)
            self.assertEqual(
                payload['model_contract']['feature_schema_hash'],
                engine.feature_schema_hash(),
            )
            reloaded = MLEngine(model_dir=td)
            self.assertTrue(reloaded.is_trained)

            payload['model_contract']['feature_schema_hash'] = 'bad-schema'
            joblib.dump(payload, engine.model_path)
            rejected = MLEngine(model_dir=td)
            self.assertFalse(rejected.is_trained)

    def test_full_strategy_walk_forward_covers_all_ml_heads(self):
        source = (ROOT / 'scripts/walk_forward_validation.py').read_text(encoding='utf-8')
        self.assertIn('FULL_STRATEGY_WALK_FORWARD', source)
        self.assertIn('train_sizing_model', source)
        self.assertIn('generate_exit_training_samples', source)
        self.assertIn('predict_exit_decision', source)
        self.assertIn('predict_position_size_factor', source)
        self.assertIn('FULL_STRATEGY_ROUNDTRIP_SLIPPAGE_PCT', source)

    def test_irreproducible_live_gates_are_not_ml_features(self):
        engine = MLEngine(model_dir='data/nonexistent-feature-schema-test')
        forbidden = {
            'crypto_score',
            'dynamic_min_score',
            'score_vs_threshold',
            'technical_action_code',
            'technical_confidence',
            'technical_min_confidence',
            'technical_confidence_edge',
        }
        self.assertTrue(forbidden.isdisjoint(set(engine.feature_names)))
        self.assertTrue({
            'crypto_score',
            'score_vs_threshold',
            'technical_action_code',
            'technical_confidence',
            'technical_confidence_edge',
        }.isdisjoint(set(engine.exit_feature_names)))

    def test_sizing_has_temporal_oos_metrics(self):
        rng = np.random.default_rng(222)
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {
            'ML_SKIP_MODEL_METADATA': 'true',
            'ML_STRICT_MODEL_SCHEMA': 'True',
            'ML_TEMPORAL_TEST_RATIO': '0.20',
        }, clear=False):
            engine = MLEngine(model_dir=td)
            X = rng.normal(size=(260, len(engine.feature_names)))
            y_entry = (X[:, 0] > 0).astype(int)
            self.assertTrue(engine.train_model(X, y_entry, use_lightgbm=False))

            y_sizing = np.clip(0.75 + 0.15 * X[:, 0], 0.25, 1.25)
            self.assertTrue(engine.train_sizing_model(X, y_sizing, use_lightgbm=False))
            self.assertEqual(engine.model_metadata.get('sizing_validation_type'), 'temporal_holdout')
            self.assertIn('sizing_test_mae', engine.model_metadata)
            self.assertIn('sizing_test_rmse', engine.model_metadata)
            self.assertIn('sizing_baseline_mae', engine.model_metadata)
            self.assertIn('sizing_mae_skill', engine.model_metadata)


    def test_p_target_removed_from_runtime_and_training(self):
        engine_source = (ROOT / 'core/ml_engine.py').read_text(encoding='utf-8')
        training_source = (ROOT / 'scripts/train_and_evaluate_ml_model.py').read_text(encoding='utf-8')
        live_source = (ROOT / 'core/trading_bot.py').read_text(encoding='utf-8')
        walk_source = (ROOT / 'scripts/walk_forward_validation.py').read_text(encoding='utf-8')
        for source in (engine_source, training_source, live_source, walk_source):
            self.assertNotIn('P_target', source)
            self.assertNotIn('ML_TARGET_', source)
            self.assertNotIn('predict_target', source)
            self.assertNotIn('train_target_model', source)
        self.assertNotIn('target_model', engine_source)
        self.assertNotIn('is_target_trained', engine_source)

    def test_exit_training_uses_live_continuation_score(self):
        source = (ROOT / 'scripts/train_and_evaluate_ml_model.py').read_text(encoding='utf-8')
        generator = source[
            source.index('def generate_exit_training_samples'):
            source.index('def train_challenger_model')
        ]
        self.assertIn('exit_engine.compute_continuation_score', generator)
        self.assertNotIn('continuation_score=50.0', generator)

    def test_partial_fill_accounting_keeps_order_open_until_complete(self):
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, 'partial.sqlite3')
            logger = MLLiveLogger(data_dir=td, sqlite_file=db)
            order_id = logger.record_order_transaction(
                'BTC/USD', 'buy', 2.0, 100.0,
                order_type='limit', status='open',
                order_id='partial-test', mode='live',
                source='test', recalculate_balances=False,
            )
            logger.record_fill_transaction(
                order_id, 'BTC/USD', 'buy', 0.5, 100.0,
                fee_amount=0.0, mode='live', source='test',
                write_ledger=False, recalculate_balances=False,
            )
            conn = logger._get_conn()
            account_id = logger._account_id('live')
            row = conn.execute(
                'SELECT status, filled_amount, avg_fill_price FROM orders WHERE account_id=? AND order_id=?',
                (account_id, order_id),
            ).fetchone()
            self.assertEqual(row[0], 'partially_filled')
            self.assertAlmostEqual(float(row[1]), 0.5)
            self.assertAlmostEqual(float(row[2]), 100.0)

            logger.record_fill_transaction(
                order_id, 'BTC/USD', 'buy', 1.5, 102.0,
                fee_amount=0.0, mode='live', source='test',
                write_ledger=False, recalculate_balances=False,
            )
            row = conn.execute(
                'SELECT status, filled_amount, avg_fill_price FROM orders WHERE account_id=? AND order_id=?',
                (account_id, order_id),
            ).fetchone()
            self.assertEqual(row[0], 'filled')
            self.assertAlmostEqual(float(row[1]), 2.0)
            self.assertAlmostEqual(float(row[2]), 101.5)
            logger.close()

    def test_walk_forward_uses_archived_or_fallback_spread(self):
        with patch.dict(os.environ, {'FULL_STRATEGY_FALLBACK_SPREAD_PCT': '0.04'}, clear=False):
            self.assertAlmostEqual(_historical_spread_pct({'close': 100.0}), 0.04)
        spread = _historical_spread_pct({'bid': 99.9, 'ask': 100.1})
        self.assertGreater(spread, 0.19)
        self.assertLess(spread, 0.21)

    def test_promotion_has_schema_bootstrap_and_aux_oos_guard(self):
        source = (ROOT / 'scripts/promote_challenger.py').read_text(encoding='utf-8')
        self.assertIn('ML_ALLOW_SCHEMA_BOOTSTRAP_PROMOTION', source)
        self.assertIn('bootstrap_heads_ready', source)
        self.assertIn('aux_oos_validation', source)
        self.assertIn('aux_oos_skill', source)
        self.assertIn('ML_PROMOTION_MAX_OOS_BASELINE_RATIO', source)
        self.assertIn('oos_skill_checks', source)
        self.assertIn("sizing_validation_type", source)

    def test_extracted_feature_vectors_match_v5_schema(self):
        engine = MLEngine(model_dir='data/nonexistent-vector-schema-test')
        h15 = _trend_klines(120, 100.0, 0.05, 900_000)
        h5 = _trend_klines(120, 100.0, 0.02, 300_000)
        h1 = _trend_klines(80, 100.0, 0.15, 3_600_000)
        h4 = _trend_klines(80, 100.0, 0.4, 14_400_000)
        h1d = _trend_klines(80, 100.0, 1.0, 86_400_000)
        entry = engine.extract_features_from_klines(
            h15,
            float(h15[-1]['close']),
            klines_5m=h5,
            klines_1h=h1,
            klines_4h=h4,
            klines_1d=h1d,
            bot_context={
                'symbol_regime': 'BULL',
                'btc_regime': 'BULL',
                'reversal_confirmed': True,
            },
        )
        self.assertIsNotNone(entry)
        self.assertEqual(len(entry), len(engine.feature_names))

        exit_features = engine.extract_exit_features(
            h15,
            float(h15[-1]['close']),
            {
                'entry_price': 100.0,
                'buy_price': 100.0,
                'fee_rate': 0.004,
                'duration_minutes': 60.0,
                'stop_loss_price': 95.0,
                'target_price': 105.0,
            },
            continuation_score=65.0,
            entry_p_win=60.0,
            btc_klines=h15[-30:],
            bot_context={'symbol_regime': 'BULL', 'btc_regime': 'BULL'},
        )
        self.assertIsNotNone(exit_features)
        self.assertEqual(len(exit_features), len(engine.exit_feature_names))

    def test_grid_search_resume_skips_completed_candidates(self):
        rng = np.random.default_rng(501)
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {
            'ML_GRID_CACHE_ENABLED': 'True',
            'ML_GRID_CACHE_DIR': td,
            'ML_GRID_RESUME': 'True',
            'ML_GRID_REUSE_BEST': 'False',
            'ML_GRID_RESEARCH_ON_DRIFT': 'False',
            'ML_GRID_FORCE_SEARCH': 'False',
        }, clear=False):
            engine = MLEngine(model_dir=td)
            X = rng.normal(size=(140, 6))
            y = (X[:, 0] > 0).astype(int)
            grid = {
                'n_estimators': [10, 20],
                'max_depth': [2],
                'min_samples_split': [2],
                'min_samples_leaf': [1],
            }
            cv_splits = 2
            checkpoint_path, _ = engine._grid_cache_paths('random_forest')
            signature = {
                **engine._grid_reuse_signature('random_forest', grid, cv_splits),
                'data_fingerprint': engine._grid_data_fingerprint(X, y, None),
            }
            first = {
                'n_estimators': 10,
                'max_depth': 2,
                'min_samples_split': 2,
                'min_samples_leaf': 1,
            }
            engine._atomic_write_json(checkpoint_path, {
                'version': 1,
                'signature': signature,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat(),
                'status': 'running',
                'completed': {
                    engine._grid_param_key(first): {
                        'status': 'completed',
                        'params': first,
                        'mean_precision': 0.95,
                        'fold_scores': [0.95, 0.95],
                        'completed_at': datetime.now().isoformat(),
                    }
                },
                'best_params': first,
                'best_score': 0.95,
            })

            scored = []
            def fake_score(model_type, params, X_train, y_train, sample_weight, splits):
                scored.append(dict(params))
                return 0.60, [0.60, 0.60]

            with patch.object(engine, '_score_grid_candidate', side_effect=fake_score):
                best, score, mode, tested, total = engine._select_entry_grid_params(
                    X, y, None, 'random_forest', grid, cv_splits
                )

            self.assertEqual(mode, 'resume_search')
            self.assertEqual(tested, 1)
            self.assertEqual(total, 2)
            self.assertEqual(len(scored), 1)
            self.assertEqual(scored[0]['n_estimators'], 20)
            self.assertEqual(best['n_estimators'], 10)
            self.assertAlmostEqual(score, 0.95)

    def test_grid_search_reuses_recent_best_without_rescoring(self):
        rng = np.random.default_rng(502)
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {
            'ML_GRID_CACHE_ENABLED': 'True',
            'ML_GRID_CACHE_DIR': td,
            'ML_GRID_RESUME': 'True',
            'ML_GRID_REUSE_BEST': 'True',
            'ML_GRID_FULL_SEARCH_INTERVAL_DAYS': '30',
            'ML_GRID_RESEARCH_ON_DRIFT': 'False',
            'ML_GRID_FORCE_SEARCH': 'False',
        }, clear=False):
            engine = MLEngine(model_dir=td)
            X = rng.normal(size=(140, 6))
            y = (X[:, 0] > 0).astype(int)
            grid = {
                'n_estimators': [10, 20],
                'max_depth': [2],
                'min_samples_split': [2],
                'min_samples_leaf': [1],
            }
            cv_splits = 2
            _, best_path = engine._grid_cache_paths('random_forest')
            best_params = {
                'n_estimators': 20,
                'max_depth': 2,
                'min_samples_split': 2,
                'min_samples_leaf': 1,
            }
            engine._atomic_write_json(best_path, {
                'version': 1,
                'reuse_signature': engine._grid_reuse_signature(
                    'random_forest', grid, cv_splits
                ),
                'data_fingerprint': 'previous-dataset-is-allowed-for-reuse',
                'best_params': best_params,
                'best_score': 0.81,
                'completed_at': datetime.now().isoformat(),
                'candidates_total': 2,
                'successful_candidates': 2,
            })

            with patch.object(
                engine,
                '_score_grid_candidate',
                side_effect=AssertionError('reuse should not rescore candidates'),
            ):
                best, score, mode, tested, total = engine._select_entry_grid_params(
                    X, y, None, 'random_forest', grid, cv_splits
                )

            self.assertEqual(mode, 'reuse_best')
            self.assertEqual(tested, 0)
            self.assertEqual(total, 2)
            self.assertEqual(best, best_params)
            self.assertAlmostEqual(score, 0.81)

    def test_grid_resume_signature_changes_with_dataset(self):
        engine = MLEngine(model_dir='data/nonexistent-grid-fingerprint-test')
        X1 = np.zeros((120, 4), dtype=np.float64)
        X2 = X1.copy()
        X2[-1, -1] = 1.0
        y = np.zeros(120, dtype=np.int64)
        self.assertNotEqual(
            engine._grid_data_fingerprint(X1, y),
            engine._grid_data_fingerprint(X2, y),
        )

    def test_grid_runtime_has_current_checkpoint_controls_and_no_dead_keys(self):
        engine = (ROOT / 'core/ml_engine.py').read_text(encoding='utf-8')
        runtime = "\n".join([
            engine,
            (ROOT / 'scripts/train_and_evaluate_ml_model.py').read_text(encoding='utf-8'),
            (ROOT / 'scripts/analyze_ml_live_performance.py').read_text(encoding='utf-8'),
            (ROOT / 'core/trading_bot.py').read_text(encoding='utf-8'),
        ])

        for key in (
            'ML_GRID_CACHE_ENABLED',
            'ML_GRID_CACHE_DIR',
            'ML_GRID_RESUME',
            'ML_GRID_REUSE_BEST',
            'ML_GRID_FULL_SEARCH_INTERVAL_DAYS',
            'ML_GRID_RESEARCH_ON_DRIFT',
            'ML_GRID_FORCE_SEARCH',
        ):
            self.assertIn(key, engine)

        for dead_key in (
            'HARD_STOP_EXIT_ENABLED',
            'ML_EXIT_LABEL_SLOPE_MIN_PCT_PER_BAR',
            'ML_EXIT_LABEL_SLOPE_MIN_BARS',
            'ML_KRAKEN_ARCHIVE_MIN_COVERAGE_DAYS',
        ):
            self.assertNotIn(dead_key, runtime)

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


    def test_ml_entry_pipeline_fails_closed_on_runtime_exception(self):
        source = (ROOT / "core/trading_bot.py").read_text(encoding="utf-8")
        start = source.index('except Exception as e:\n                # Aegis est ML-first')
        end = source.index("final_size_usd =", start)
        failure_block = source[start:end]
        self.assertIn("'ml_pipeline_error'", failure_block)
        self.assertIn("return", failure_block)

    def test_exit_uses_probability_attached_to_open_position(self):
        source = (ROOT / "core/trading_bot.py").read_text(encoding="utf-8")
        start = source.index("def _evaluate_exit_engine_for_symbol")
        end = source.index("def _apply_ml_exit_management", start)
        block = source[start:end]
        self.assertIn("position_data.get('ml_buy_prob')", block)
        self.assertNotIn("self.state.get('ml_predictions', {}).get(symbol", block)

    def test_rehydration_preserves_entry_timestamp_and_probability(self):
        source = (ROOT / "core/trading_bot.py").read_text(encoding="utf-8")
        start = source.index("def _rehydrate_open_positions_for_exit_evaluation")
        end = source.index("def _check_dynamic_breakeven_lock", start)
        block = source[start:end]
        self.assertIn("data.get('opened_at')", block)
        self.assertIn("'ml_buy_prob': data.get('ml_buy_prob')", block)
        self.assertNotIn("'buy_time': time.time()", block)

    def test_ml_lineage_contract_allows_only_one_logical_position_per_symbol(self):
        env_source = (ROOT / ".env.example").read_text(encoding="utf-8")
        bot_source = (ROOT / "core/trading_bot.py").read_text(encoding="utf-8")
        self.assertIn("MAX_POSITIONS_PER_CRYPTO=1", env_source)
        self.assertIn("max_pos_per_crypto = min(1, max(1, configured_max_per_crypto))", bot_source)

    def test_ui_ml_threshold_default_matches_runtime(self):
        ui_source = (ROOT / "ui/server.py").read_text(encoding="utf-8")
        self.assertNotIn("os.getenv('ML_MIN_PROBABILITY', '65.0')", ui_source)
        self.assertIn("os.getenv('ML_MIN_PROBABILITY', '50.0')", ui_source)

    def test_telegram_refresh_and_restart_are_not_racy(self):
        source = (ROOT / "core/managers/notification.py").read_text(encoding="utf-8")
        self.assertIn("if include_positions and hasattr(bot, 'sync_positions_from_exchange')", source)
        self.assertIn("if include_history and hasattr(bot, 'sync_trade_history')", source)
        self.assertNotIn("elif include_history and hasattr(bot, 'sync_trade_history')", source)
        self.assertIn("def _handle_telegram_command(self, command, args=None, update_id=None):", source)
        self.assertIn("int(update_id) + 1", source)
        self.assertIn("ThreadPoolExecutor", source)

    def test_ml_logger_has_no_duplicate_runtime_methods(self):
        import ast
        source = (ROOT / "core/ml_live_logger.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MLLiveLogger")
        names = [node.name for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for name in ("save_daily_stats", "load_daily_stats", "load_open_entries", "log_execution_metric"):
            self.assertEqual(names.count(name), 1, name)

    def test_execution_metric_contract_is_fully_persisted(self):
        orm = (ROOT / "core/db_orm.py").read_text(encoding="utf-8")
        logger = (ROOT / "core/ml_live_logger.py").read_text(encoding="utf-8")
        for field in (
            "executed_price",
            "execution_side",
            "execution_amount",
            "execution_success",
            "execution_reason",
        ):
            self.assertIn(field, orm)
            self.assertIn(field, logger)


    def test_quote_currency_migration_archives_and_restores_state(self):
        import sqlite3
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from scripts.migrate_quote_currency import migrate_quote_currency_database

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "aegis_test.sqlite3"
            base_env = {
                "ML_LIVE_SQLITE_FILE": str(db_path),
                "PAPER_BALANCE": "1000",
                "EXCHANGE": "kraken",
            }

            with patch.dict(os.environ, {**base_env, "AEGIS_QUOTE_CURRENCY": "USD"}, clear=False):
                first = migrate_quote_currency_database(db_path)
                self.assertEqual(first["quote_currency"], "USD")
                con = sqlite3.connect(db_path)
                con.execute(
                    "UPDATE bot_state SET paper_balance=850, initial_balance=1000 WHERE mode='paper'"
                )
                con.commit()
                con.close()

            with patch.dict(os.environ, {**base_env, "AEGIS_QUOTE_CURRENCY": "CAD"}, clear=False):
                cad = migrate_quote_currency_database(db_path)
                self.assertEqual(cad["quote_currency"], "CAD")
                con = sqlite3.connect(db_path)
                row = con.execute(
                    "SELECT quote_currency, paper_balance FROM bot_state WHERE mode='paper'"
                ).fetchone()
                self.assertEqual(row[0], "CAD")
                self.assertEqual(float(row[1]), 1000.0)
                archived_usd = con.execute(
                    """
                    SELECT paper_balance
                    FROM bot_state_quote_archive
                    WHERE mode='paper' AND quote_currency='USD'
                    """
                ).fetchone()
                self.assertEqual(float(archived_usd[0]), 850.0)
                accounts = {
                    r[0]
                    for r in con.execute("SELECT account_id FROM accounts").fetchall()
                }
                self.assertIn("paper:kraken:USD", accounts)
                self.assertIn("paper:kraken:CAD", accounts)
                con.execute(
                    "UPDATE bot_state SET paper_balance=1200 WHERE mode='paper'"
                )
                con.commit()
                con.close()

            with patch.dict(os.environ, {**base_env, "AEGIS_QUOTE_CURRENCY": "USD"}, clear=False):
                usd_again = migrate_quote_currency_database(db_path)
                self.assertEqual(usd_again["quote_currency"], "USD")
                con = sqlite3.connect(db_path)
                row = con.execute(
                    "SELECT quote_currency, paper_balance FROM bot_state WHERE mode='paper'"
                ).fetchone()
                self.assertEqual(row[0], "USD")
                self.assertEqual(float(row[1]), 850.0)
                archived_cad = con.execute(
                    """
                    SELECT paper_balance
                    FROM bot_state_quote_archive
                    WHERE mode='paper' AND quote_currency='CAD'
                    """
                ).fetchone()
                self.assertEqual(float(archived_cad[0]), 1200.0)
                integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
                con.close()
                self.assertEqual(integrity, "ok")

    def test_startup_runs_quote_currency_migration_before_bot_logger(self):
        source = (ROOT / "run.py").read_text(encoding="utf-8")
        env_pos = source.index("load_dotenv('.env', override=True)")
        migration_pos = source.index("migrate_quote_currency_database()")
        logger_pos = source.index("process_logger = MLLiveLogger")
        self.assertLess(env_pos, migration_pos)
        self.assertLess(migration_pos, logger_pos)

        start_source = (ROOT / "start.py").read_text(encoding="utf-8")
        self.assertIn("migrate_quote_currency_database()", start_source)


if __name__ == "__main__":
    unittest.main()
