"""Pure market-structure detectors shared by live and historical training.

These functions intentionally contain no exchange/network access. The live bot fetches
the requested timeframes, while training passes timestamp-bounded historical slices.
That guarantees falling-knife and reversal features have identical semantics.
"""
from typing import Dict, List


def calculate_ema(prices, period):
    values = [float(v) for v in (prices or [])]
    if not values:
        return 0.0
    if len(values) < period:
        return values[-1]
    multiplier = 2.0 / (float(period) + 1.0)
    ema = values[0]
    for value in values[1:]:
        ema = (value * multiplier) + (ema * (1.0 - multiplier))
    return float(ema)


def momentum_pct(klines: List[Dict], periods: int) -> float:
    rows = list(klines or [])
    if len(rows) <= periods:
        return 0.0
    old_price = float(rows[-periods].get("close") or 0.0)
    new_price = float(rows[-1].get("close") or 0.0)
    if old_price <= 0:
        return 0.0
    return ((new_price - old_price) / old_price) * 100.0


def detect_falling_knife(daily: List[Dict], h4: List[Dict]) -> Dict:
    daily = list(daily or [])
    h4 = list(h4 or [])
    if len(daily) < 50 or len(h4) < 30:
        return {
            "is_falling": False,
            "reason": "insufficient_data",
            "daily_momentum_7d": 0.0,
            "h4_momentum_24h": 0.0,
        }

    daily_closes = [float(k.get("close") or 0.0) for k in daily]
    h4_closes = [float(k.get("close") or 0.0) for k in h4]
    daily_ema20 = calculate_ema(daily_closes, 20)
    daily_ema50 = calculate_ema(daily_closes, 50)
    h4_ema20 = calculate_ema(h4_closes, 20)
    h4_ema50 = calculate_ema(h4_closes, 50)
    current_daily = daily_closes[-1]
    current_h4 = h4_closes[-1]

    daily_momentum_7d = momentum_pct(daily, 7)
    h4_momentum_24h = momentum_pct(h4, 6)
    recent_lows = [float(k.get("low") or 0.0) for k in daily[-8:]]
    lower_low = min(recent_lows[-3:]) < min(recent_lows[:5])

    ema_downtrend = (
        current_daily < daily_ema20 < daily_ema50
        and current_h4 < h4_ema20 < h4_ema50
    )
    momentum_down = daily_momentum_7d <= -3.0 or h4_momentum_24h <= -2.0
    is_falling = bool(ema_downtrend and (momentum_down or lower_low))

    reasons = []
    if ema_downtrend:
        reasons.append("ema_downtrend_1d_4h")
    if momentum_down:
        reasons.append("negative_momentum")
    if lower_low:
        reasons.append("lower_lows")

    return {
        "is_falling": is_falling,
        "reason": ",".join(reasons) if reasons else "not_falling",
        "daily_momentum_7d": float(daily_momentum_7d),
        "h4_momentum_24h": float(h4_momentum_24h),
        "daily_ema20": float(daily_ema20),
        "daily_ema50": float(daily_ema50),
        "h4_ema20": float(h4_ema20),
        "h4_ema50": float(h4_ema50),
    }


def detect_reversal_confirmation(h1: List[Dict]) -> Dict:
    h1 = list(h1 or [])
    if len(h1) < 21:
        return {"confirmed": False, "reason": "insufficient_data"}

    closes = [float(k.get("close") or 0.0) for k in h1]
    lows = [float(k.get("low") or 0.0) for k in h1]
    volumes = [float(k.get("volume") or 0.0) for k in h1]
    ema9 = calculate_ema(closes, 9)
    ema21 = calculate_ema(closes, 21)
    recent_momentum = momentum_pct(h1, 3)
    higher_low = min(lows[-3:]) > min(lows[-8:-3])
    avg_volume = sum(volumes[-12:-1]) / max(1, len(volumes[-12:-1]))
    volume_ok = volumes[-1] >= avg_volume * 1.05 if avg_volume > 0 else False
    price_above_fast_ema = closes[-1] > ema9
    ema_reclaim = ema9 >= ema21 * 0.998

    confirmed = bool(
        price_above_fast_ema
        and recent_momentum > 0
        and (higher_low or volume_ok or ema_reclaim)
    )

    reasons = []
    if price_above_fast_ema:
        reasons.append("price_above_ema9")
    if recent_momentum > 0:
        reasons.append("positive_1h_momentum")
    if higher_low:
        reasons.append("higher_low")
    if volume_ok:
        reasons.append("volume_confirmed")
    if ema_reclaim:
        reasons.append("ema9_reclaim")

    return {
        "confirmed": confirmed,
        "reason": ",".join(reasons) if reasons else "no_reversal_confirmation",
        "momentum_3h": float(recent_momentum),
        "ema9": float(ema9),
        "ema21": float(ema21),
        "higher_low": bool(higher_low),
        "volume_ok": bool(volume_ok),
    }
