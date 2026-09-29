"""Technical entry gate: indicator warmup, freshness and action boundaries."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from utils.timeframe_analyzer import TimeframeAnalyzer
from utils.pattern_analyzer import PatternAnalyzer
from core.trading_bot import TradingBot
from scripts.trade_signals import _detect_reversal_rebound_5m, detect_all_trade_signals


def candles(count=100):
    return [{'timestamp': i * 900000, 'open': 100 + i * 0.1,
             'close': 100.08 + i * 0.1, 'high': 100.15 + i * 0.1,
             'low': 99.95 + i * 0.1, 'volume': 10 + i % 5}
            for i in range(count)]


class TechnicalSignalTests(unittest.TestCase):
    def setUp(self):
        self.analyzer = TimeframeAnalyzer()

    def test_rsi_updates_after_initial_window(self):
        prices = list(range(15)) + list(range(13, -1, -1))
        self.assertAlmostEqual(self.analyzer.calculate_rsi(prices), 100 * (13 / 14) ** 14)
        self.assertLess(self.analyzer.calculate_rsi(prices), 40)

    def test_rsi_flat_up_and_down(self):
        self.assertEqual(self.analyzer.calculate_rsi([100] * 100), 50)
        self.assertEqual(self.analyzer.calculate_rsi(list(range(100))), 100)
        self.assertEqual(self.analyzer.calculate_rsi(list(range(100, 0, -1))), 0)
        self.assertIsNone(self.analyzer.calculate_rsi([100] * 14))

    def test_full_history_activates_ema99_and_ichimoku(self):
        rows = candles()
        result = self.analyzer.analyze_timeframe(rows, rows[-1]['close'])
        self.assertTrue(result['data_available'])
        self.assertEqual(result['factors']['ema_ribbon']['signal'], 'strong_uptrend')
        self.assertEqual(result['factors']['ichimoku']['signal'], 'ichimoku_bullish')

    def test_short_history_is_unknown_not_neutral_market(self):
        result = self.analyzer.analyze_timeframe(candles(50), 105)
        self.assertFalse(result['data_available'])
        self.assertEqual(result['trend'], 'unknown')
        self.assertEqual(result['candle_count'], 50)

    def test_runtime_requests_enough_candles_for_every_indicator(self):
        bot = SimpleNamespace(get_klines=Mock(return_value=candles()))
        self.analyzer.calculate_volatility = Mock(return_value=2)
        result = self.analyzer.analyze_all_timeframes(bot, 'BTC/USD', 110)
        self.assertTrue(result['global_signal']['data_available'])
        self.assertEqual(bot.get_klines.call_count, 3)
        for call in bot.get_klines.call_args_list:
            self.assertEqual(call.args[1], 100)

    def test_missing_timeframe_is_explicit_even_if_others_are_bullish(self):
        bot = SimpleNamespace(get_klines=lambda symbol, count, tf: [] if tf == '1h' else candles())
        self.analyzer.calculate_volatility = Mock(return_value=2)
        result = self.analyzer.analyze_all_timeframes(bot, 'BTC/USD', 110)['global_signal']
        self.assertFalse(result['data_available'])
        self.assertEqual(result['missing_timeframes'], ['1h'])
        self.assertEqual(result['action'], 'HOLD')

    def test_failed_fetch_does_not_reuse_unbounded_old_cache(self):
        bot = SimpleNamespace(get_klines=Mock(return_value=candles()))
        self.analyzer.get_klines_for_timeframe(bot, 'BTC/USD', '15m', 100)
        bot.get_klines.return_value = []
        self.assertEqual(self.analyzer.get_klines_for_timeframe(bot, 'BTC/USD', '15m', 100), [])
        bot.get_klines.side_effect = RuntimeError('offline')
        self.assertEqual(self.analyzer.get_klines_for_timeframe(bot, 'BTC/USD', '15m', 100), [])

    def test_aroon_uses_latest_occurrence_of_repeated_extreme(self):
        result = self.analyzer.calculate_aroon([24] + list(range(1, 25)), list(range(25)))
        self.assertEqual(result['signal'], 'aroon_uptrend')

    def test_hold_is_not_overridden_by_high_confidence(self):
        frames = {'15m': {'trend': 'neutral', 'strength': 0.1, 'signals': ['signal'] * 8}}
        result = self.analyzer.generate_global_signal(frames, 100)
        self.assertEqual(result['action'], 'HOLD')
        self.assertGreater(result['confidence'], 50)

    def _reversal_5m_rows(self):
        price = 100.0
        prices = []
        for _ in range(20):
            price -= 0.12
            prices.append(price)
        for delta in (-0.08, -0.05, 0.02, 0.08, 0.12, 0.16, 0.18, 0.20):
            price += delta
            prices.append(price)

        rows = []
        for index, close in enumerate(prices):
            open_price = close - 0.05 if index >= 23 else close + 0.03
            rows.append({
                'timestamp': index * 300000,
                'open': open_price,
                'high': max(open_price, close) + 0.04,
                'low': min(open_price, close) - 0.04,
                'close': close,
                'volume': 120.0 if index >= 23 else 100.0,
            })
        return rows

    def test_reversal_rebound_detects_confirmed_5m_turn(self):
        rows = self._reversal_5m_rows()
        signal = _detect_reversal_rebound_5m(rows, rows[-1]['close'] + 0.10)
        self.assertIsNotNone(signal)
        self.assertEqual(signal['type'], 'reversal_rebound_5m')
        self.assertGreater(signal['previous_drop_pct'], 0.45)
        self.assertGreater(signal['rebound_from_low_pct'], 0.20)
        self.assertTrue(signal['higher_low'])

    def test_reversal_rebound_rejects_weak_noise(self):
        rows = []
        price = 100.0
        for index in range(24):
            price -= 0.10
            rows.append({
                'timestamp': index * 300000,
                'open': price + 0.04,
                'high': price + 0.06,
                'low': price - 0.03,
                'close': price,
                'volume': 100.0,
            })
        weak_price = rows[-1]['close'] * 1.001
        self.assertIsNone(_detect_reversal_rebound_5m(rows, weak_price))

    def test_reversal_rebound_can_survive_bearish_15m_legacy_filter(self):
        rows_5m = self._reversal_5m_rows()
        history_15m = []
        price = 105.0
        for index in range(30):
            price -= 0.20
            history_15m.append({
                'timestamp': index * 900000,
                'open': price + 0.08,
                'high': price + 0.10,
                'low': price - 0.10,
                'close': price,
                'volume': 100.0,
            })
        current_price = rows_5m[-1]['close'] + 0.10
        signals = detect_all_trade_signals(
            PatternAnalyzer(bot=None),
            history_15m,
            current_price,
            history_5m=rows_5m,
        )
        self.assertIn('reversal_rebound_5m', {item['type'] for item in signals})

    def test_buy_sell_and_hold_boundaries_remain_unchanged(self):
        for strength, action in ((0.299, 'HOLD'), (0.3, 'BUY'), (1.5, 'STRONG_BUY'),
                                 (-0.3, 'SELL'), (-1.5, 'STRONG_SELL')):
            self.assertEqual(self.analyzer.determine_action(strength, 'bullish', {}, trend_consistency=1), action)

    def test_entry_strategy_treats_market_and_technical_signals_as_advisory(self):
        class ReachedPostTechnicalPipeline(Exception):
            pass

        for action, confidence, score, available, should_continue in (
            ('BUY', 80, 80, True, True),
            ('HOLD', 99, 80, True, True),
            ('SELL', 80, 80, True, True),
            ('STRONG_SELL', 80, 80, True, True),
            ('BUY', 20, 80, True, True),
            ('HOLD', 20, 10, True, True),
            ('BUY', 99, 80, False, False),
        ):
            with self.subTest(
                action=action,
                confidence=confidence,
                score=score,
                available=available,
            ):
                bot = SimpleNamespace(
                    get_market_context=lambda symbol: {'falling_knife': {'is_falling': False},
                                                       'reversal': {'confirmed': False}},
                    stuck_manager=SimpleNamespace(_calculate_atr=lambda symbol: {'atr_percent': 2}),
                    get_symbol_cooldown_remaining=lambda symbol: 0,
                    can_open_position=lambda symbol: True,
                    check_support_touch=lambda symbol, price: {},
                    market_analyzer=SimpleNamespace(
                        score_crypto=lambda *args, _score=score: _score,
                        last_dynamic_threshold=40,
                    ),
                    _append_score_history=Mock(),
                    get_cached_analysis=lambda *args: {'global_signal': {
                        'action': action, 'confidence': confidence, 'data_available': available}},
                    risk_manager=SimpleNamespace(get_adaptive_confidence_threshold=lambda *args: 50),
                    record_decision=Mock(),
                    get_signal_strength=Mock(side_effect=ReachedPostTechnicalPipeline),
                )
                if should_continue:
                    with self.assertRaises(ReachedPostTechnicalPipeline):
                        TradingBot._intelligent_strategy_locked(bot, 'BTC/USD', 1, 100)
                else:
                    TradingBot._intelligent_strategy_locked(bot, 'BTC/USD', 1, 100)
                    self.assertEqual(bot.record_decision.call_args.args[3], 'technical_data_unavailable')
                    bot.get_signal_strength.assert_not_called()


if __name__ == '__main__':
    unittest.main()
