"""Model pricing table and cost estimation from local token data."""

from __future__ import annotations

# Per-million-token pricing (USD), from platform.claude.com/docs/en/about-claude/pricing
# as of July 2026. Anthropic quotes list prices exclusive of tax.
#
# Each entry: (input, output, cache_read, cache_write_5m, cache_write_1h)
#
# The two cache-write rates are separate products, not a single "cache creation"
# price: a 5-minute-TTL write costs 1.25x input, a 1-hour-TTL write costs 2x.
# Claude Code uses both, so the JSONL breakdown decides which applies.
# cache_read is 0.1x input for every model.
#
# Every family is enumerated rather than relying on a short catch-all prefix:
# a bare "opus-4" key would silently hand a future claude-opus-4-9 the legacy
# $15/$75 tier. Unrecognised models resolve to None so estimate_daily_cost can
# fail closed instead of reporting a wrong number.
_PRICING: dict[str, tuple[float, float, float, float, float]] = {
    # Fable / Mythos
    "fable-5":    (10.00, 50.00, 1.00, 12.50, 20.00),
    "mythos-5":   (10.00, 50.00, 1.00, 12.50, 20.00),
    # Current Opus tier
    "opus-5":     ( 5.00, 25.00, 0.50,  6.25, 10.00),
    "opus-4-8":   ( 5.00, 25.00, 0.50,  6.25, 10.00),
    "opus-4-7":   ( 5.00, 25.00, 0.50,  6.25, 10.00),
    "opus-4-6":   ( 5.00, 25.00, 0.50,  6.25, 10.00),
    "opus-4-5":   ( 5.00, 25.00, 0.50,  6.25, 10.00),
    # Legacy Opus, priced before the 4.5 drop
    "opus-4-1":   (15.00, 75.00, 1.50, 18.75, 30.00),
    "opus-4-0":   (15.00, 75.00, 1.50, 18.75, 30.00),
    "opus-4":     (15.00, 75.00, 1.50, 18.75, 30.00),
    # Sonnet. Sonnet 5 runs introductory pricing ($2/$10) through 2026-08-31;
    # the standard rate is used here rather than adding expiring date logic.
    "sonnet-5":   ( 3.00, 15.00, 0.30,  3.75,  6.00),
    "sonnet-4-6": ( 3.00, 15.00, 0.30,  3.75,  6.00),
    "sonnet-4-5": ( 3.00, 15.00, 0.30,  3.75,  6.00),
    "sonnet-4":   ( 3.00, 15.00, 0.30,  3.75,  6.00),
    # Haiku
    "haiku-4-5":  ( 1.00,  5.00, 0.10,  1.25,  2.00),
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


def _match_pricing(model: str) -> tuple[float, float, float, float, float] | None:
    """Match a full model name to a pricing entry, or None when unknown."""
    name = _normalize(model)
    for prefix in _PRICING_KEYS:
        if name.startswith(prefix):
            return _PRICING[prefix]
    return None


def estimate_daily_cost(
    model_tokens: dict[str, tuple[int, int, int, int, int]],
) -> float | None:
    """Estimate USD cost for a day's usage across models.

    model_tokens maps model name -> (input, output, cache_read,
    cache_write_5m, cache_write_1h) token counts.  Returns None when the
    mapping is empty or when any model that actually consumed tokens is
    unpriced: a partial total understates the day's real spend, so we show no
    estimate rather than a confidently wrong one.
    """
    if not model_tokens:
        return None
    total = 0.0
    for model, tokens in model_tokens.items():
        # Pseudo-models such as "<synthetic>" and the "unknown" fallback appear
        # with no tokens at all. They cannot move the total, so they must not
        # be able to veto the whole day's estimate.
        if not any(tokens):
            continue
        rates = _match_pricing(model)
        if rates is None:
            return None
        total += sum(count * rate / 1_000_000 for count, rate in zip(tokens, rates, strict=True))
    return total
