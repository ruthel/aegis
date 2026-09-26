import os
import re

DEFAULT_QUOTE_CURRENCY = "USD"


def get_quote_currency() -> str:
    """Return Aegis' configured quote currency, defaulting safely to USD."""
    value = str(os.getenv("AEGIS_QUOTE_CURRENCY", DEFAULT_QUOTE_CURRENCY) or DEFAULT_QUOTE_CURRENCY).strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{3,10}", value):
        return DEFAULT_QUOTE_CURRENCY
    return value


def split_symbol(symbol: str) -> tuple[str, str]:
    text = str(symbol or "").strip().upper()
    if "/" in text:
        base, quote = text.split("/", 1)
        return base, quote
    quote = get_quote_currency()
    if text.endswith(quote) and len(text) > len(quote):
        return text[:-len(quote)], quote
    for candidate in ("USDT", "USDC", "USD", "CAD", "EUR", "GBP", "AUD", "JPY"):
        if text.endswith(candidate) and len(text) > len(candidate):
            return text[:-len(candidate)], candidate
    return text, quote


def make_symbol(base: str, quote: str | None = None) -> str:
    return f"{str(base or '').strip().upper()}/{str(quote or get_quote_currency()).strip().upper()}"


def normalize_symbol(symbol: str, quote: str | None = None) -> str:
    base, detected_quote = split_symbol(symbol)
    return make_symbol(base, detected_quote or quote or get_quote_currency())


def quote_asset_for_symbol(symbol: str) -> str:
    return split_symbol(symbol)[1]


def account_id(mode: str, exchange: str, quote: str | None = None) -> str:
    return f"{str(mode or 'paper').lower()}:{str(exchange or 'kraken').lower()}:{str(quote or get_quote_currency()).upper()}"


def quote_asset_candidates(quote: str | None = None) -> tuple[str, ...]:
    q = str(quote or get_quote_currency()).upper()
    if q == "USD":
        return ("USD", "USDT", "USDC")
    return (q,)


def get_quote_balance(balance: dict, quote: str | None = None) -> dict:
    if not isinstance(balance, dict):
        return {}
    for asset in quote_asset_candidates(quote):
        data = balance.get(asset)
        if data:
            return data
    return {}


def is_quote_asset(asset: str, quote: str | None = None) -> bool:
    return str(asset or "").upper() in quote_asset_candidates(quote)


def get_trading_pairs(raw: str | None = None) -> list[str]:
    """Return configured trading pairs.

    Backward compatibility: legacy compact pairs ending in USD (BTCUSD, ETHUSD, ...)
    are treated as base-asset declarations and remapped to AEGIS_QUOTE_CURRENCY.
    Explicit slash pairs (BTC/USD) keep their explicit quote.
    """
    configured = str(raw if raw is not None else os.getenv("TRADING_PAIRS", "") or "").strip()
    if not configured:
        return [make_symbol(base) for base in ("BTC", "ETH", "SOL", "ADA")]
    quote = get_quote_currency()
    pairs = []
    for item in configured.split(","):
        token = str(item or "").strip().upper().replace("-", "/")
        if not token:
            continue
        if "/" not in token and token.endswith("USD") and quote != "USD":
            pairs.append(make_symbol(token[:-3], quote))
        else:
            pairs.append(normalize_symbol(token))
    return list(dict.fromkeys(pairs))
