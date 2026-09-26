"""Canonical position-truth helpers.

Aegis must not treat residual exchange dust as an open/tradable position.
This module contains the single threshold rule used by live position reconciliation.
"""

from __future__ import annotations


def classify_position_tradeability(
    amount,
    price,
    min_amount=0.0,
    min_cost=0.0,
    *,
    epsilon=1e-12,
):
    """Classify whether a holding is economically tradable.

    If price is unavailable, fail safe: do not classify a non-trivial amount as
    dust solely because valuation could not be computed.
    """
    try:
        amount = max(0.0, float(amount or 0.0))
    except Exception:
        amount = 0.0
    try:
        price = float(price or 0.0)
    except Exception:
        price = 0.0
    try:
        min_amount = max(0.0, float(min_amount or 0.0))
    except Exception:
        min_amount = 0.0
    try:
        min_cost = max(0.0, float(min_cost or 0.0))
    except Exception:
        min_cost = 0.0

    value = amount * price if price > 0 else None

    if amount <= epsilon:
        return {
            "tradeable": False,
            "reason": "no_holding",
            "amount": amount,
            "value": value,
            "min_amount": min_amount,
            "min_cost": min_cost,
        }

    if min_amount > 0 and amount < min_amount:
        return {
            "tradeable": False,
            "reason": "below_min_amount",
            "amount": amount,
            "value": value,
            "min_amount": min_amount,
            "min_cost": min_cost,
        }

    if price <= 0:
        return {
            "tradeable": True,
            "reason": "price_unavailable_assume_tradeable",
            "amount": amount,
            "value": None,
            "min_amount": min_amount,
            "min_cost": min_cost,
        }

    if min_cost > 0 and value < min_cost:
        return {
            "tradeable": False,
            "reason": "below_min_cost",
            "amount": amount,
            "value": value,
            "min_amount": min_amount,
            "min_cost": min_cost,
        }

    return {
        "tradeable": True,
        "reason": "tradeable",
        "amount": amount,
        "value": value,
        "min_amount": min_amount,
        "min_cost": min_cost,
    }
