"""Model pricing table and cost estimation from local token data."""

from __future__ import annotations

import json
import math
import os
import re
from http.client import HTTPException
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

_Rates = tuple[float, float, float, float, float]

# Per-million-token pricing (USD), from platform.claude.com/docs/en/about-claude/pricing
# as of September 2026. Anthropic quotes list prices exclusive of tax.
#
# Each entry: (input, output, cache_read, cache_write_5m, cache_write_1h)
#
# The two cache-write rates are separate products, not a single "cache creation"
# price: a 5-minute-TTL write costs 1.25x input, a 1-hour-TTL write costs 2x.
# Claude Code uses both, so the JSONL breakdown decides which applies.
# cache_read is 0.1x input for every model except Fable/Mythos 5.1 (0.025x)
# and Opus 5.5 (0.05x).
#
# Every id is enumerated and matched exactly after normalisation — not by
# prefix. Prefix matching would hand a future claude-opus-4-9 the legacy
# $15/$75 tier via the bare "opus-4" entry, which is the opposite of failing
# closed. An id that is not listed resolves to None so estimate_daily_cost
# suppresses the day rather than reporting a wrong number, which also makes a
# missing entry visible instead of silently mispriced.
#
# Models released after this build are priced by the pricing.json feed at the
# repo root (see fetch_feed). Add every new model there too: installs already
# in the field only learn about it from the feed.
_PRICING: dict[str, _Rates] = {
    # Fable / Mythos
    "fable-5-1":  (10.00, 50.00, 0.25, 12.50, 20.00),
    "mythos-5-1": (10.00, 50.00, 0.25, 12.50, 20.00),
    "fable-5":    (10.00, 50.00, 1.00, 12.50, 20.00),
    "mythos-5":   (10.00, 50.00, 1.00, 12.50, 20.00),
    # Current Opus tier
    "opus-5-5":   ( 4.00, 20.00, 0.20,  5.00,  8.00),
    "opus-5":     ( 5.00, 25.00, 0.50,  6.25, 10.00),
    "opus-4-8":   ( 5.00, 25.00, 0.50,  6.25, 10.00),
    "opus-4-7":   ( 5.00, 25.00, 0.50,  6.25, 10.00),
    "opus-4-6":   ( 5.00, 25.00, 0.50,  6.25, 10.00),
    "opus-4-5":   ( 5.00, 25.00, 0.50,  6.25, 10.00),
    # Legacy Opus, priced before the 4.5 drop
    "opus-4-1":   (15.00, 75.00, 1.50, 18.75, 30.00),
    "opus-4-0":   (15.00, 75.00, 1.50, 18.75, 30.00),
    "opus-4":     (15.00, 75.00, 1.50, 18.75, 30.00),
    # Sonnet. Sonnet 5's $2/$10 launch rate was made permanent in September 2026.
    "sonnet-5-5": ( 2.00, 10.00, 0.20,  2.50,  4.00),
    "sonnet-5":   ( 2.00, 10.00, 0.20,  2.50,  4.00),
    "sonnet-4-6": ( 3.00, 15.00, 0.30,  3.75,  6.00),
    "sonnet-4-5": ( 3.00, 15.00, 0.30,  3.75,  6.00),
    "sonnet-4":   ( 3.00, 15.00, 0.30,  3.75,  6.00),
    # Haiku
    "haiku-4-5":  ( 1.00,  5.00, 0.10,  1.25,  2.00),
}

# Fast mode (research preview) bills Opus 5.5, Opus 5 and Opus 4.8 at 2x across the
# whole context window; caching multipliers stack on top of it. Opus 4.7 rejects
# speed="fast" outright and Opus 4.6 silently runs at standard rates, so any
# other model asking for fast mode falls back to its standard entry.
_FAST_PRICING: dict[str, _Rates] = {
    "opus-5-5": ( 8.00, 40.00, 0.40, 10.00, 16.00),
    "opus-5":   (10.00, 50.00, 1.00, 12.50, 20.00),
    "opus-4-8": (10.00, 50.00, 1.00, 12.50, 20.00),
}

# Time-limited launch pricing: family key -> (last date inclusive, rates).
# Usage on or before the cutoff bills at the promotional rate; after it, the
# standard _PRICING entry applies. Dates are ISO, so string comparison is safe.
_INTRO_PRICING: dict[str, tuple[str, _Rates]] = {}

_FEED_URL = "https://raw.githubusercontent.com/mordup/ctfl/main/pricing.json"
_FEED_CACHE = Path.home() / ".cache" / "ctfl" / "pricing.json"
_FEED_SCHEMA = 1
_MAX_FEED_BYTES = 64 * 1024
_FEED_FIELDS = {"schema", "updated", "models", "fast", "ignore"}
_RATE_FIELDS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")
_FEED_KEY_RE = re.compile(r"[a-z0-9-]{1,40}")
_MAX_RATE = 1000.0

# (standard, fast) rates from the feed, layered over the bundled tables.
# Replaced as a whole, never mutated, so a fetch worker reading it mid-swap
# sees either the old or the new feed.
_feed: tuple[dict[str, _Rates], dict[str, _Rates]] = ({}, {})


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


def _match_key(model: str) -> str | None:
    """Return the pricing key for a model id, or None when it is not listed.

    Matching is exact on the normalised id. A point release we have not priced
    yet (claude-opus-4-9, claude-sonnet-5-1) therefore returns None and fails
    closed, rather than inheriting a sibling's rates.
    """
    name = _normalize(model)
    return name if name in _PRICING or name in _feed[0] else None


def _match_pricing(
    model: str, speed: str = "standard", date: str | None = None
) -> tuple[float, float, float, float, float] | None:
    """Resolve the rates for a model, or None when the model is unknown.

    speed is the request's service speed as recorded in the JSONL ("standard"
    or "fast").  date is the ISO usage date, used to pick promotional pricing
    that has since expired; when it is None the standard rate applies, which is
    the safer assumption for undated callers.
    """
    key = _match_key(model)
    if key is None:
        return None
    feed_standard, feed_fast = _feed
    if speed == "fast":
        fast = feed_fast.get(key) or _FAST_PRICING.get(key)
        if fast is not None:
            return fast
    intro = _INTRO_PRICING.get(key)
    if intro is not None and date is not None and date <= intro[0]:
        return intro[1]
    return feed_standard.get(key) or _PRICING[key]


def estimate_daily_cost(
    model_tokens: dict[tuple[str, str], tuple[int, int, int, int, int]],
    date: str | None = None,
) -> float | None:
    """Estimate USD cost for a day's usage.

    model_tokens maps (model name, speed) -> (input, output, cache_read,
    cache_write_5m, cache_write_1h) token counts.  Speed is part of the key
    because fast mode is billed at a different rate for the same model.  date
    is the ISO day these tokens belong to, so promotional pricing is applied
    only within its window.

    Returns None when the mapping is empty or when any model that actually
    consumed tokens is unpriced: a partial total understates the day's real
    spend, so we show no estimate rather than a confidently wrong one.
    """
    if not model_tokens:
        return None
    total = 0.0
    for (model, speed), tokens in model_tokens.items():
        # Pseudo-models such as "<synthetic>" and the "unknown" fallback appear
        # with no tokens at all. They cannot move the total, so they must not
        # be able to veto the whole day's estimate.
        if not any(tokens):
            continue
        rates = _match_pricing(model, speed=speed, date=date)
        if rates is None:
            return None
        total += sum(count * rate / 1_000_000 for count, rate in zip(tokens, rates, strict=True))
    return total


def _parse_rates(section: object) -> dict[str, _Rates] | None:
    if not isinstance(section, dict):
        return None
    table: dict[str, _Rates] = {}
    for key, entry in section.items():
        if not _FEED_KEY_RE.fullmatch(key):
            return None
        if not isinstance(entry, dict) or set(entry) != set(_RATE_FIELDS):
            return None
        values = [entry[f] for f in _RATE_FIELDS]
        for v in values:
            if isinstance(v, bool) or not isinstance(v, int | float):
                return None
            if not math.isfinite(v) or not 0 <= v <= _MAX_RATE:
                return None
        table[key] = tuple(float(v) for v in values)
    return table


def parse_feed(raw: bytes) -> tuple[dict[str, _Rates], dict[str, _Rates]] | None:
    """Validate a pricing.json payload into (standard, fast) rate tables.

    Any deviation from the schema rejects the whole file: a partially applied
    feed could price one model from it and its fast mode from somewhere else.
    """
    if len(raw) > _MAX_FEED_BYTES:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    if not isinstance(data, dict) or not set(data) <= _FEED_FIELDS:
        return None
    if data.get("schema") != _FEED_SCHEMA or "models" not in data:
        return None
    ignore = data.get("ignore", [])
    if not isinstance(ignore, list) or not all(
        isinstance(k, str) and _FEED_KEY_RE.fullmatch(k) for k in ignore
    ):
        return None
    standard = _parse_rates(data["models"])
    fast = _parse_rates(data.get("fast", {}))
    if standard is None or fast is None:
        return None
    return standard, fast


def apply_feed(feed: tuple[dict[str, _Rates], dict[str, _Rates]]) -> bool:
    """Layer a parsed feed over the bundled tables; True if the rates changed."""
    global _feed
    if feed == _feed:
        return False
    _feed = feed
    return True


def load_cached_feed() -> None:
    try:
        with open(_FEED_CACHE, "rb") as f:
            raw = f.read(_MAX_FEED_BYTES + 1)
    except OSError:
        return
    feed = parse_feed(raw)
    if feed is not None:
        apply_feed(feed)


def fetch_feed() -> tuple[dict[str, _Rates], dict[str, _Rates]] | None:
    """Download and validate the pricing feed, caching it for offline starts.

    Returns None on any network or validation failure; callers keep whatever
    feed they already have.
    """
    req = Request(_FEED_URL, headers={"User-Agent": "ctfl-pricing"})
    try:
        with urlopen(req, timeout=10) as resp:
            raw = resp.read(_MAX_FEED_BYTES + 1)
    except (URLError, OSError, ValueError, HTTPException):
        return None
    feed = parse_feed(raw)
    if feed is None:
        return None
    try:
        _FEED_CACHE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = _FEED_CACHE.with_suffix(".tmp")
        tmp.write_bytes(raw)
        os.replace(tmp, _FEED_CACHE)
    except OSError:
        pass
    return feed
