import time
import os
import json
from datetime import datetime
import numpy as np

EXIT_DECISION_RANK = {
    "HOLD": 0,
    "PROTECT_BREAKEVEN": 1,
    "TIGHTEN_STOP": 2,
    "TAKE_PROFIT": 3,
    "FORCE_EXIT": 4,
}

class ExitDecisionEngine:
    """
    Exit Decision Engine for Aegis Bot.
    Evaluates open positions in real time, computes a Continuation Score (0-100),
    and determines recommended exit management actions.
    """
    
    def __init__(self, fragile_max_net_pct=0.40, time_stop_minutes=12):
        self.fragile_max_net_pct = fragile_max_net_pct
        self.time_stop_minutes = time_stop_minutes
        
    def calculate_vwap(self, klines):
        """Calculates approximate VWAP from recent klines."""
        if not klines:
            return None
        total_pv = 0.0
        total_vol = 0.0
        for k in klines:
            high = float(k.get('high', k.get('close', 0)))
            low = float(k.get('low', k.get('close', 0)))
            close = float(k.get('close', 0))
            vol = float(k.get('volume', 0))
            typical_price = (high + low + close) / 3.0
            total_pv += typical_price * vol
            total_vol += vol
        if total_vol <= 0:
            return float(klines[-1].get('close', 0))
        return total_pv / total_vol

    def calculate_ema(self, prices, period=9):
        """Calculates Exponential Moving Average for a period."""
        if len(prices) < period:
            return float(np.mean(prices)) if len(prices) > 0 else 0.0
        weights = np.exp(np.linspace(-1., 0., period))
        weights /= weights.sum()
        a = np.convolve(prices, weights, mode='full')[:len(prices)]
        a[:period] = a[period]
        return float(a[-1])

    def calculate_rsi(self, prices, period=14):
        """Calculates Relative Strength Index (RSI)."""
        if len(prices) < period + 1:
            return 50.0
        deltas = np.diff(prices)
        seed = deltas[:period+1]
        up = seed[seed >= 0].sum() / period
        down = -seed[seed < 0].sum() / period
        if down == 0:
            return 100.0
        rs = up / down
        rsi = np.zeros_like(prices)
        rsi[:period] = 100. - 100. / (1. + rs)

        for i in range(period, len(prices)):
            delta = deltas[i - 1]
            if delta > 0:
                upval = delta
                downval = 0.
            else:
                upval = 0.
                downval = -delta
            up = (up * (period - 1) + upval) / period
            down = (down * (period - 1) + downval) / period
            rs = up / max(down, 1e-9)
            rsi[i] = 100. - 100. / (1. + rs)
        return float(rsi[-1])

    def compute_continuation_score(self, symbol, current_price, klines, btc_klines=None, position_data=None):
        """
        Calculates a Continuation Score from 0 to 100 indicating momentum health.
        """
        if not klines or len(klines) < 5:
            return 50  # Neutral default score

        closes = [float(k['close']) for k in klines]
        volumes = [float(k['volume']) for k in klines]
        
        score = 50  # Start at base neutral score

        # 1. Price vs EMA9 & EMA20 (Up to +20 / -20 pts)
        ema9 = self.calculate_ema(closes, 9)
        ema20 = self.calculate_ema(closes, min(20, len(closes)))
        if current_price > ema9:
            score += 12
        else:
            score -= 10
            
        if ema9 > ema20:
            score += 8
        else:
            score -= 8

        # 2. Price vs VWAP (Up to +15 / -15 pts)
        vwap = self.calculate_vwap(klines[-20:])
        if vwap and vwap > 0:
            if current_price > vwap:
                score += 15
            else:
                score -= 15

        # 3. Higher Lows Structure (Up to +15 / -15 pts)
        if len(klines) >= 3:
            recent_lows = [float(k.get('low', k.get('close'))) for k in klines[-3:]]
            if recent_lows[-1] > recent_lows[-2] > recent_lows[-3]:
                score += 15
            elif recent_lows[-1] < recent_lows[-2] < recent_lows[-3]:
                score -= 15

        # 4. Volume Trend (Up to +10 / -10 pts)
        if len(volumes) >= 5:
            avg_vol = np.mean(volumes[-5:])
            last_vol = volumes[-1]
            last_candle_green = closes[-1] >= float(klines[-1].get('open', closes[-1]))
            if last_vol > avg_vol:
                if last_candle_green:
                    score += 10
                else:
                    score -= 10

        # 5. RSI Momentum (Up to +15 / -15 pts)
        rsi = self.calculate_rsi(closes, min(14, len(closes)-1))
        if 50.0 <= rsi <= 70.0:
            score += 15
        elif rsi > 70.0:
            score += 5  # Overbought zone
        elif 35.0 <= rsi < 50.0:
            score -= 5
        else:
            score -= 15  # Weak RSI (<35)

        # 6. BTC Context Alignment (Up to +15 / -15 pts)
        if btc_klines and len(btc_klines) >= 3 and symbol != 'BTC/USD':
            btc_closes = [float(k['close']) for k in btc_klines]
            btc_change = ((btc_closes[-1] - btc_closes[-3]) / btc_closes[-3]) * 100
            if btc_change > 0.1:
                score += 15
            elif btc_change < -0.1:
                score -= 15

        # Clamp final score between 0 and 100
        final_score = max(0, min(100, int(score)))
        return final_score

    def _fuse_ml_exit_decision(self, rule_decision, rule_reason, ml_exit):
        if not ml_exit or not ml_exit.get('ml_exit_available'):
            return rule_decision, rule_reason

        ml_decision = ml_exit.get('decision', 'HOLD')
        rule_rank = EXIT_DECISION_RANK.get(rule_decision, 0)
        ml_rank = EXIT_DECISION_RANK.get(ml_decision, 0)

        if ml_rank > rule_rank:
            return ml_decision, f"{ml_exit.get('reason', 'ml_exit')}+rules:{rule_reason}"
        if ml_rank < rule_rank:
            return rule_decision, f"{rule_reason}+ml:{ml_exit.get('reason', 'ml_exit')}"
        return rule_decision, f"{rule_reason}+{ml_exit.get('reason', 'ml_exit')}"

    def evaluate_position(self, symbol, current_price, position_data, klines, btc_klines=None, ml_exit=None):
        """
        Evaluates position state and returns recommendation dictionary.
        
        Decisions:
          - HOLD: Strong momentum & health
          - PROTECT_BREAKEVEN: Lock breakeven as score softens
          - TIGHTEN_STOP: Net profit in fragile zone (0 to +0.40%) & weak score
          - TAKE_PROFIT: Clear rejection near resistance with profit > +0.25%
          - FORCE_EXIT: Time limit reached with low score, or strong score breakdown
        """
        buy_price = float(position_data.get('buy_price', current_price))
        fee_rate = float(position_data.get('fee_rate', float(os.getenv('TRADING_FEE_PERCENT', '0.1')) / 100))
        
        # Calculate net PnL percentage
        breakeven_price = buy_price * (1 + fee_rate) / max(0.000001, (1 - fee_rate))
        gross_pnl_pct = ((current_price - buy_price) / buy_price) * 100
        net_pnl_pct = ((current_price - breakeven_price) / buy_price) * 100

        # Calculate Continuation Score
        score = self.compute_continuation_score(symbol, current_price, klines, btc_klines, position_data)
        
        # Compute trade duration in minutes
        created_at_str = position_data.get('created_at') or position_data.get('buy_time')
        duration_minutes = 0
        if created_at_str:
            try:
                if 'T' in created_at_str:
                    created_dt = datetime.fromisoformat(created_at_str.replace('Z', ''))
                else:
                    created_dt = datetime.strptime(created_at_str, '%Y-%m-%d %H:%M:%S')
                duration_minutes = (datetime.now() - created_dt).total_seconds() / 60.0
            except Exception:
                duration_minutes = 0

        resistance_price = position_data.get('resistance_price')
        
        # Decision Logic Evaluation
        decision = "HOLD"
        reason = "momentum_healthy"
        
        # 1. Check Resistance Rejection
        if resistance_price and float(resistance_price) > buy_price:
            dist_to_res_pct = ((float(resistance_price) - current_price) / current_price) * 100
            if dist_to_res_pct < 0.2 and net_pnl_pct >= 0.20 and score < 60:
                decision = "TAKE_PROFIT"
                reason = "resistance_rejection_near_target"

        # 2. Check Fragile Profit Zone (0.0% <= net_pnl <= fragile_max_net_pct)
        if decision == "HOLD" and 0.0 <= net_pnl_pct <= self.fragile_max_net_pct:
            if score < 45:
                decision = "TIGHTEN_STOP"
                reason = "fragile_profit_weak_score"
            elif score < 60:
                decision = "PROTECT_BREAKEVEN"
                reason = "fragile_profit_moderate_score"

        # 3. Check Time Stop (Stagnation)
        if duration_minutes >= self.time_stop_minutes:
            if net_pnl_pct <= 0.15 and score < 60:
                decision = "FORCE_EXIT" if net_pnl_pct <= 0.0 else "TIGHTEN_STOP"
                reason = f"time_stop_stagnation_{int(duration_minutes)}m"

        # 4. Severe Score Breakdown
        if score < 30 and net_pnl_pct < 0:
            decision = "FORCE_EXIT"
            reason = "severe_score_breakdown"

        # Higher Score Overrides
        if score >= 75 and decision in ["TIGHTEN_STOP", "PROTECT_BREAKEVEN"]:
            decision = "HOLD"
            reason = "strong_continuation_override"

        rule_decision = decision
        rule_reason = reason
        decision, reason = self._fuse_ml_exit_decision(rule_decision, rule_reason, ml_exit)

        result = {
            "symbol": symbol,
            "decision": decision,
            "rule_decision": rule_decision,
            "continuation_score": score,
            "net_pnl_pct": round(net_pnl_pct, 4),
            "gross_pnl_pct": round(gross_pnl_pct, 4),
            "duration_minutes": round(duration_minutes, 1),
            "reason": reason,
            "ml_exit": ml_exit or {},
            "timestamp": datetime.now().isoformat()
        }
        return result
