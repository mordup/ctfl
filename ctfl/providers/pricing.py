"""Model pricing table and cost estimation from local token data."""

from __future__ import annotations

# Per-million-token pricing (USD) as of March 2026.
# Each entry: (input, output, cache_read, cache_create)
_PRICING: dict[str, tuple[float, float, float, float]] = {
    "opus-4":   (15.00, 75.00, 1.50, 18.75),
    "sonnet-4": ( 3.00, 15.00, 0.30,  3.75),
    "haiku-4":  ( 1.00,  5.00, 0.10,  1.25),
}


def _match_pricing(model: str) -> tuple[float, float, float, float] | None:
    """Match a full model name to a pricing entry.

    Strips 'claude-' prefix and date suffixes, then checks if any pricing
    key is a prefix of the cleaned name.  e.g. 'claude-sonnet-4-6-20260301'
    -> 'sonnet-4-6' matches 'sonnet-4'.
    """
    name = model.lower().removeprefix("claude-")
    # Strip trailing date suffix (8-digit segment)
    parts = name.split("-")
    cleaned = [p for p in parts if not (len(p) == 8 and p.isdigit())]
    name = "-".join(cleaned)

    for prefix, rates in _PRICING.items():
        if name.startswith(prefix):
            return rates
    return None


def estimate_daily_cost(
    model_tokens: dict[str, tuple[int, int, int, int]],
) -> float | None:
    """Estimate USD cost for a day's usage across models.

    model_tokens maps model name -> (input, output, cache_read, cache_create)
    token counts.  Returns None if no models could be matched.
    """
    total = 0.0
    matched = False
    for model, (inp, out, cache_r, cache_c) in model_tokens.items():
        rates = _match_pricing(model)
        if rates is None:
            continue
        matched = True
        r_in, r_out, r_cache_r, r_cache_c = rates
        total += (
            inp * r_in / 1_000_000
            + out * r_out / 1_000_000
            + cache_r * r_cache_r / 1_000_000
            + cache_c * r_cache_c / 1_000_000
        )
    return total if matched else None
