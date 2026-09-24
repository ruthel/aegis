"""Shared candidate-signal engine used by live, training and backtests.

The implementation intentionally delegates to the canonical signal functions in
scripts.trade_signals so every path evaluates the same support/breakout/EMA
candidate rules. Keeping this tiny adapter in core prevents the live bot from
inventing a second, divergent candidate universe.
"""
from typing import Dict, List, Optional


class SignalEngine:
    def __init__(self, pattern_analyzer):
        self.pattern_analyzer = pattern_analyzer

    def detect_all(self, history: List[Dict], current_price: float) -> List[Dict]:
        from scripts.trade_signals import detect_all_trade_signals
        return detect_all_trade_signals(self.pattern_analyzer, history, current_price) or []

    def detect_best(self, history: List[Dict], current_price: float) -> Optional[Dict]:
        signals = self.detect_all(history, current_price)
        if not signals:
            return None
        return max(
            signals,
            key=lambda item: (
                float(item.get('confidence') or 0.0),
                float(item.get('volume_ratio') or 0.0),
            )
        )

    def is_candidate(self, history: List[Dict], current_price: float) -> bool:
        return bool(self.detect_all(history, current_price))
