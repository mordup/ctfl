"""Model pricing table and cost estimation from local token data."""

from __future__ import annotations

# Per-million-token pricing (USD) as of July 2026.
# Each entry: (input, output, cache_read, cache_create)
#
# cache_read is 0.1x input; cache_create is 1.25x input — the 5-minute-TTL
# write rate, which is the default.
#
# Every family is enumerated rather than relying on a short catch-all prefix:
# a bare "opus-4" key would silently hand a future claude-opus-4-9 the legacy
# $15/$75 tier. Unrecognised models resolve to None so estimate_daily_cost can
# fail closed instead of reporting a wrong number.
_PRICING: dict[str, tuple[float, float, float, float]] = {
    # Fable / Mythos
    "fable-5":    (10.00, 50.00, 1.00, 12.50),
    "mythos-5":   (10.00, 50.00, 1.00, 12.50),
    # Current Opus tier
    "opus-5":     ( 5.00, 25.00, 0.50,  6.25),
    "opus-4-8":   ( 5.00, 25.00, 0.50,  6.25),
    "opus-4-7":   ( 5.00, 25.00, 0.50,  6.25),
    "opus-4-6":   ( 5.00, 25.00, 0.50,  6.25),
    "opus-4-5":   ( 5.00, 25.00, 0.50,  6.25),
    # Legacy Opus, priced before the 4.5 drop
    "opus-4-1":   (15.00, 75.00, 1.50, 18.75),
    "opus-4-0":   (15.00, 75.00, 1.50, 18.75),
    "opus-4":     (15.00, 75.00, 1.50, 18.75),
    # Sonnet. Sonnet 5 runs introductory pricing ($2/$10) through 2026-08-31;
    # the standard rate is used here rather than adding expiring date logic.
    "sonnet-5":   ( 3.00, 15.00, 0.30,  3.75),
    "sonnet-4-6": ( 3.00, 15.00, 0.30,  3.75),
    "sonnet-4-5": ( 3.00, 15.00, 0.30,  3.75),
    "sonnet-4":   ( 3.00, 15.00, 0.30,  3.75),
    # Haiku
    "haiku-4-5":  ( 1.00,  5.00, 0.10,  1.25),
}

# Longest key first, so "opus-4-1" is matched before "opus-4". Ties are safe:
# two distinct keys of equal length cannot prefix one another.
_PRICING_KEYS = sorted(_PRICING, key=len, reverse=True)


def _normalize(model: str) -> str:
    """Reduce a full model name to its pricing family key.

    Strips the 'claude-' prefix, any bracketed variant suffix, and 8-digit date
    segments, e.g. 'claude-opus-4-5-20251101' -> 'opus-4-5' and
    'claude-opus-5[1m]' -> 'opus-5'.
    """
    name = model.lower().removeprefix("claude-")
    name = name.split("[", 1)[0]
    parts = name.split("-")
    cleaned = [p for p in parts if not (len(p) == 8 and p.isdigit())]
    return "-".join(cleaned)


def _match_pricing(model: str) -> tuple[float, float, float, float] | None:
    """Match a full model name to a pricing entry, or None when unknown."""
    name = _normalize(model)
    for prefix in _PRICING_KEYS:
        if name.startswith(prefix):
            return _PRICING[prefix]
    return None


def estimate_daily_cost(
    model_tokens: dict[str, tuple[int, int, int, int]],
) -> float | None:
    """Estimate USD cost for a day's usage across models.

    model_tokens maps model name -> (input, output, cache_read, cache_create)
    token counts.  Returns None when the mapping is empty or when any model is
    unpriced: a partial total understates the day's real spend, so we show no
    estimate rather than a confidently wrong one.
    """
    if not model_tokens:
        return None
    total = 0.0
    for model, (inp, out, cache_r, cache_c) in model_tokens.items():
        rates = _match_pricing(model)
        if rates is None:
            return None
        r_in, r_out, r_cache_r, r_cache_c = rates
        total += (
            inp * r_in / 1_000_000
            + out * r_out / 1_000_000
            + cache_r * r_cache_r / 1_000_000
            + cache_c * r_cache_c / 1_000_000
        )
    return total
