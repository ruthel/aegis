"""Offline exit regressions: no credentials, exchange calls or production database."""
import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from core.bot.trading import TradingMixin
from core.bot.sync import SyncMixin
from core.trading_bot import TradingBot
from core.ml_live_logger import MLLiveLogger
from core.ml_engine import MLEngine
from utils.risk_manager import TrailingStopManager
from utils.exit_engine import ExitDecisionEngine


class ExitBot(TradingMixin, SyncMixin):
    _prepare_exit_amount = TradingBot._prepare_exit_amount
    _check_dynamic_breakeven_lock = TradingBot._check_dynamic_breakeven_lock
    _get_position_safety_stop_price = TradingBot._get_position_safety_stop_price
    _confirm_safety_stop_breach = TradingBot._confirm_safety_stop_breach
    _update_trailing_stop_from_tick = TradingBot._update_trailing_stop_from_tick
    _apply_ml_exit_management = TradingBot._apply_ml_exit_management
    _rehydrate_open_positions_for_exit_evaluation = TradingBot._rehydrate_open_positions_for_exit_evaluation

    def __init__(self):
        self.paper_trading = False
        self.trading_fee = 0.004
        self.state = {'positions': [{'symbol': 'BTC/USD', 'side': 'buy', 'amount': 1,
                                    'price': 100, 'timestamp': '2026-01-01T00:00:00'}]}
        self.trailing_stop_manager = TrailingStopManager()
        self.trailing_stop_manager.positions['BTC/USD'] = {
            'buy_price': 100, 'amount': 1, 'stop_price': 95,
            'highest_price': 104, 'highest_net_pnl_pct': 3,
            'trailing_active': True, 'trailing_percent': 2,
            'initial_trailing_percent': 3, 'breakeven_active': True,
            'fee_rate': 0.004, 'created_at': '2026-01-01T00:00:00',
        }
        self.exchange = Mock()
        self.exchange.create_market_sell_order.return_value = {'id': 'sell-1', 'amount': 1, 'status': 'open'}
        self.exchange.fetch_order.return_value = {'id': 'sell-1', 'amount': 1, 'filled': 0, 'status': 'open'}
        self.exchange.fetch_my_trades.return_value = []
        self.balance_manager = Mock()
        self.balance_manager.get_balance.return_value = {'BTC': {'free': 1, 'used': 0}}
        self.save_state = Mock(return_value=True)
        self.get_price = Mock(return_value=102)
        self.get_real_buy_price = Mock(return_value=100)
        self.get_min_amount = Mock(return_value={'min_amount': 0.001, 'min_cost': 0.5})
        self._cancel_sell_orders_for_symbol = Mock(return_value=True)
        self._reconcile_live_dust_position = Mock()
        self._record_live_order_accounting = Mock()
        self.calculate_pnl = Mock(return_value=1)
        self.record_decision = Mock()
        self.record_ml_exit_learning_sample = Mock()
        self.set_symbol_cooldown = Mock()
        self.total_trades = 0
        self._last_trailing_stop_save = 0
        self._evaluate_exit_engine_for_symbol = Mock(return_value=None)

    def safe_request(self, function, *args, **kwargs):
        return function(*args, **kwargs)


class ExitSafetyTests(unittest.TestCase):
    def setUp(self):
        self.sleep = patch('core.bot.trading.time.sleep')
        self.sleep.start()
        self.addCleanup(self.sleep.stop)
        self.bot = ExitBot()

    def test_acknowledged_unfilled_sell_is_not_success_or_duplicate(self):
        for _ in range(2):
            self.assertIsNone(self.bot.sell_market('BTC/USD', 1))
        self.bot.exchange.create_market_sell_order.assert_called_once()
        self.assertIn('BTC/USD', self.bot.trailing_stop_manager.positions)
        self.assertNotIn('closed_at', self.bot.state['positions'][0])
        self.bot._record_live_order_accounting.assert_not_called()
        self.bot.set_symbol_cooldown.assert_not_called()

    def test_delayed_fill_completes_original_order(self):
        self.bot.sell_market('BTC/USD', 1)
        self.bot.exchange.fetch_order.return_value.update(status='closed', filled=1, average=102)
        self.assertTrue(self.bot.sell_market('BTC/USD', 1))
        self.bot.exchange.create_market_sell_order.assert_called_once()
        self.assertEqual(self.bot.state['positions'][0]['status'], 'closed')
        self.assertNotIn('BTC/USD', self.bot.trailing_stop_manager.positions)
        self.assertEqual(self.bot.state['live_exit_orders'], {})

    def test_paper_market_sell_keeps_simulation_accounting(self):
        self.bot.paper_trading = True
        self.bot.paper_balance = 0
        self.bot._paper_execution_snapshot = Mock(return_value={
            'price': 102, 'amount': 1, 'fee_rate': 0.004,
            'spread_pct': 0, 'slippage_pct': 0, 'latency_ms': 0,
        })
        self.assertTrue(self.bot.sell_market('BTC/USD', 1))
        self.assertAlmostEqual(self.bot.paper_balance, 101.592)
        self.bot.exchange.create_market_sell_order.assert_not_called()
        self.assertEqual(self.bot.state['positions'][0]['status'], 'closed')

    def test_closed_status_without_filled_quantity_is_not_proof(self):
        self.bot.exchange.fetch_order.return_value = {'id': 'sell-1', 'amount': 1, 'status': 'closed', 'average': 102}
        self.assertIsNone(self.bot.sell_market('BTC/USD', 1))
        self.bot._record_live_order_accounting.assert_not_called()

    def test_partial_fill_preserves_remaining_position_and_protection(self):
        self.bot.exchange.fetch_order.return_value.update(status='canceled', filled=0.4, average=102)
        self.assertIsNone(self.bot.sell_market('BTC/USD', 1))
        self.assertAlmostEqual(self.bot.state['positions'][0]['amount'], 0.6)
        position = self.bot.trailing_stop_manager.positions['BTC/USD']
        self.assertAlmostEqual(position['amount'], 0.6)
        self.assertEqual(position['highest_net_pnl_pct'], 3)
        self.bot.record_ml_exit_learning_sample.assert_not_called()
        self.bot.set_symbol_cooldown.assert_not_called()

    def test_open_partial_fill_waits_for_terminal_snapshot(self):
        self.bot.exchange.fetch_order.return_value.update(filled=0.4, average=102)
        self.assertIsNone(self.bot.sell_market('BTC/USD', 1))
        self.bot._record_live_order_accounting.assert_not_called()
        self.assertIn('BTC/USD', self.bot.state['live_exit_orders'])

    def test_submission_timeout_never_blindly_resubmits(self):
        self.bot.exchange.create_market_sell_order.side_effect = TimeoutError('response lost')
        self.assertIsNone(self.bot.sell_market('BTC/USD', 1))
        self.assertIsNone(self.bot.sell_market('BTC/USD', 1))
        self.bot.exchange.create_market_sell_order.assert_called_once()

    def test_explicit_rejection_allows_later_retry(self):
        from ccxt import InsufficientFunds
        self.bot.exchange.create_market_sell_order.side_effect = InsufficientFunds('rejected')
        self.assertIsNone(self.bot.sell_market('BTC/USD', 1))
        self.assertEqual(self.bot.state['live_exit_orders'], {})

    def test_closed_order_can_confirm_from_matching_trades(self):
        self.bot.exchange.fetch_order.return_value.update(status='closed')
        self.bot.exchange.fetch_my_trades.return_value = [
            {'order': 'sell-1', 'side': 'sell', 'amount': 1, 'price': 102},
            {'order': 'other', 'side': 'sell', 'amount': 10, 'price': 102},
        ]
        self.assertTrue(self.bot.sell_market('BTC/USD', 1))
        self.assertEqual(self.bot.state['positions'][-1]['amount'], 1)

    def test_manual_partial_sale_does_not_remove_whole_position(self):
        self.bot.exchange.create_market_sell_order.return_value['amount'] = 0.4
        self.bot.exchange.fetch_order.return_value.update(status='closed', amount=0.4, filled=0.4, average=102)
        self.assertIsNone(self.bot.sell_market('BTC/USD', 0.4))
        self.assertAlmostEqual(self.bot.trailing_stop_manager.positions['BTC/USD']['amount'], 0.6)

    def test_failed_durable_save_prevents_submission(self):
        self.bot.save_state.return_value = False
        self.assertIsNone(self.bot.sell_market('BTC/USD', 1))
        self.bot.exchange.create_market_sell_order.assert_not_called()

    def test_locked_balance_does_not_discard_break_even_position(self):
        self.bot.balance_manager.get_balance.return_value = {'BTC': {'free': 0, 'used': 1}}
        self.assertFalse(self.bot._check_dynamic_breakeven_lock('BTC/USD', 101, self.bot.trailing_stop_manager.positions['BTC/USD']))
        self.assertIn('BTC/USD', self.bot.trailing_stop_manager.positions)
        self.bot._reconcile_live_dust_position.assert_not_called()
        self.bot.exchange.create_market_sell_order.assert_not_called()

    def test_failed_cancellation_blocks_ml_exit_without_discarding_position(self):
        self.bot._cancel_sell_orders_for_symbol.return_value = False
        self.assertFalse(self.bot._apply_ml_exit_management('BTC/USD', 101, {'decision': 'FORCE_EXIT'}))
        self.assertIn('BTC/USD', self.bot.trailing_stop_manager.positions)
        self.bot.exchange.create_market_sell_order.assert_not_called()

    def test_successful_cancellation_uses_refreshed_free_balance(self):
        self.assertEqual(self.bot._prepare_exit_amount('BTC/USD', 101), 1)
        self.bot._cancel_sell_orders_for_symbol.assert_called_once_with('BTC/USD')
        self.bot.balance_manager.get_balance.assert_called_once_with(force_refresh=True, skip_ledger_sync=True)

    def test_unavailable_open_orders_does_not_confirm_cancellation(self):
        self.bot.pending_orders = {'limit-1': {'symbol': 'BTC/USD', 'side': 'sell', 'status': 'opened'}}
        self.bot.exchange.fetch_open_orders.return_value = None
        self.assertFalse(TradingBot._cancel_sell_orders_for_symbol(self.bot, 'BTC/USD'))
        self.assertIn('limit-1', self.bot.pending_orders)

    def test_rehydrate_legacy_state_preserves_known_safety_fields(self):
        self.bot.paper_trading = True
        original = copy.deepcopy(self.bot.trailing_stop_manager.positions['BTC/USD'])
        self.bot.state['positions'][0].update(original)
        self.bot.trailing_stop_manager.positions.clear()
        self.bot._rehydrate_open_positions_for_exit_evaluation()
        restored = self.bot.trailing_stop_manager.positions['BTC/USD']
        for key in ('stop_price', 'highest_price', 'trailing_active', 'highest_net_pnl_pct',
                    'trailing_percent', 'initial_trailing_percent', 'breakeven_active', 'fee_rate'):
            self.assertEqual(restored[key], original[key])

    def test_peak_change_is_saved_even_when_ml_holds(self):
        with patch.dict(os.environ, {'ML_OWNS_EXITS': 'true', 'DYNAMIC_BREAKEVEN_ENABLED': 'true'}):
            self.bot._update_trailing_stop_from_tick('BTC/USD', 106)
        self.assertGreater(self.bot.trailing_stop_manager.positions['BTC/USD']['highest_net_pnl_pct'], 5)
        self.bot.save_state.assert_called_once()

    def test_throttled_peak_is_saved_on_next_tick_without_new_high(self):
        self.bot._last_trailing_stop_save = 100
        with patch.dict(os.environ, {'ML_OWNS_EXITS': 'true', 'DYNAMIC_BREAKEVEN_ENABLED': 'true',
                                     'TRAILING_STOP_SAVE_INTERVAL_SECONDS': '1'}):
            with patch('core.trading_bot.time.time', return_value=100.5):
                self.bot._update_trailing_stop_from_tick('BTC/USD', 106)
            self.bot.save_state.assert_not_called()
            with patch('core.trading_bot.time.time', return_value=102):
                self.bot._update_trailing_stop_from_tick('BTC/USD', 106)
            self.bot.save_state.assert_called_once()

    def test_pending_exit_is_checked_without_another_ml_signal(self):
        self.bot.state['live_exit_orders'] = {'BTC/USD': {'id': 'sell-1', 'amount': 1}}
        self.bot._update_trailing_stop_from_tick('BTC/USD', 102)
        self.bot.exchange.create_market_sell_order.assert_not_called()
        self.bot.exchange.fetch_order.assert_called()
        self.bot._evaluate_exit_engine_for_symbol.assert_not_called()

    def test_generic_order_sync_does_not_book_pending_market_exit_twice(self):
        self.bot.state['live_exit_orders'] = {'BTC/USD': {'id': 'sell-1', 'amount': 1}}
        self.bot._confirm_order_execution = Mock()
        self.assertFalse(self.bot._handle_disappeared_order('sell-1', {'symbol': 'BTC/USD'}))
        self.bot._confirm_order_execution.assert_not_called()

    def test_sqlite_restart_roundtrip_is_mode_isolated(self):
        with tempfile.TemporaryDirectory() as td, MLLiveLogger(data_dir=td, sqlite_file=str(Path(td) / 'test.sqlite3')) as logger:
            self.bot.ml_live_logger = logger
            self.bot.state['live_exit_orders'] = {'BTC/USD': {'id': 'sell-1', 'amount': 1, 'status': 'open'}}
            expected = copy.deepcopy(self.bot.trailing_stop_manager.positions)
            self.assertTrue(SyncMixin.save_state(self.bot))
            with MLLiveLogger(data_dir=td, sqlite_file=str(Path(td) / 'test.sqlite3')) as restarted:
                self.assertEqual(restarted.load_bot_state('live')['trailing_stops'], expected)
            other = ExitBot()
            other.ml_live_logger = logger
            other.trailing_stop_manager.positions = {}
            SyncMixin.load_state(other)
            self.assertEqual(other.trailing_stop_manager.positions, expected)
            self.assertEqual(other.state['live_exit_orders'], self.bot.state['live_exit_orders'])
            self.assertTrue(logger.save_bot_state({'trailing_stops': {}}, 'paper'))
            self.assertEqual(logger.load_bot_state('paper')['trailing_stops'], {})
            self.assertEqual(logger.load_bot_state('live')['trailing_stops'], expected)
            other.trailing_stop_manager.positions.clear()
            SyncMixin.save_state(other)
            self.assertEqual(logger.load_bot_state('live')['trailing_stops'], {})
            logger.close()

    def test_ml_threshold_matches_profit_protection_and_boundary(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {
            'ML_EXIT_SELL_THRESHOLD': '35', 'ML_EXIT_PROFIT_PROTECT_THRESHOLD': '70',
            'ML_EXIT_PROFIT_PROTECT_MIN_NET_PCT': '0.35',
        }):
            engine = MLEngine(model_dir=td)
            engine.is_exit_trained = True
            engine.exit_model = Mock()
            engine.exit_model.predict_proba.return_value = np.array([[0.30, 0.70]])
            engine.exit_scaler = None
            engine.exit_calibrator = None
            engine.extract_exit_features = Mock(return_value=np.zeros(37))
            engine._align_exit_features_for_loaded_model = lambda x: x
            for price, threshold in ((100, 35), (102, 70)):
                result = engine.predict_exit_decision([], price, {'buy_price': 100, 'fee_rate': 0.004}, 50)
                self.assertEqual(result['min_p_continue'], threshold)
                self.assertEqual(result['decision'], 'HOLD')
                forwarded = ExitDecisionEngine().evaluate_position('BTC/USD', price, {'buy_price': 100}, [], ml_exit=result)
                self.assertEqual(forwarded['min_p_continue'], threshold)
            engine.exit_model.predict_proba.return_value = np.array([[0.3001, 0.6999]])
            result = engine.predict_exit_decision([], 102, {'buy_price': 100, 'fee_rate': 0.004}, 50)
            self.assertEqual(result['decision'], 'FORCE_EXIT')
            self.assertEqual(result['p_continue'], 70)  # UI uses the decision, not rounded probability.


if __name__ == '__main__':
    unittest.main()
