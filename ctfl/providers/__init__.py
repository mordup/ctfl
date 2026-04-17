from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC
from typing import Protocol


def format_cost(usd: float) -> str:
    return f"${usd:.2f}"


def format_credits(cents: int | None, currency: str | None = "USD") -> str:
    """Format minor-unit credit amounts (e.g. USD cents) as a display string.
    Drops fractional cents on round-dollar values (e.g. $1,000 not $1,000.00).
    """
    if cents is None:
        return ""
    amount = cents / 100
    symbol = "$" if (currency or "USD").upper() == "USD" else ""
    if amount == int(amount):
        return f"{symbol}{int(amount):,}"
    return f"{symbol}{amount:,.2f}"


def format_tokens(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 10_000:
        return f"{n / 1_000:.1f}K"
    return f"{n:,}"


@dataclass
class ModelTokens:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_tokens + self.cache_creation_tokens


@dataclass
class DailyUsage:
    date: str
    message_count: int = 0
    session_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float | None = None
    breakdown_available: bool = True

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_tokens + self.cache_creation_tokens


@dataclass
class RateLimitInfo:
    name: str            # "Session", "Weekly", "Weekly (Sonnet)", etc.
    utilization: float   # 0-100 percentage
    resets_at: str | None  # ISO 8601 timestamp or None
    window_key: str = ""  # "five_hour", "seven_day", "monthly_spend", etc.
    # Spend-limit extras (Enterprise plans only). All three are either set
    # together or left None. Amounts are in minor units (e.g. USD cents).
    used_credits: int | None = None
    monthly_limit: int | None = None
    currency: str | None = None


@dataclass
class ProjectUsage:
    name: str
    path: str
    total_tokens: int = 0
    message_count: int = 0


@dataclass
class UsageData:
    daily: list[DailyUsage] = field(default_factory=list)
    by_model: list[ModelTokens] = field(default_factory=list)
    by_project: list[ProjectUsage] = field(default_factory=list)
    limits: list[RateLimitInfo] = field(default_factory=list)
    # Sum of token cost from assistant messages where the input context
    # (input + cache_read + cache_creation) was at or above LONG_CONTEXT_THRESHOLD.
    # Used as the numerator of "% of tokens spent at long context".
    long_context_tokens: int = 0
    # Total token cost summed over the same scan window as long_context_tokens.
    # Denominator for the ratio; kept separate from the sum of `daily` because
    # stats-cache-era days don't contribute per-message context size.
    long_context_total_tokens: int = 0
    error: str | None = None


class UsageProvider(Protocol):
    def fetch(self, days: int) -> UsageData: ...


def format_reset(resets_at: str | None) -> str:
    from datetime import datetime

    if not resets_at:
        return ""
    try:
        reset_time = datetime.fromisoformat(resets_at)
        now = datetime.now(UTC)
        delta = reset_time - now
        total_seconds = int(delta.total_seconds())
        if total_seconds <= 0:
            return "Resets soon"
        if total_seconds < 60:
            return "Resets in <1m"
        if total_seconds < 3600:
            return f"Resets in {total_seconds // 60}m"
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        if hours < 24:
            return f"Resets in {hours}h{minutes:02d}m"
        local_time = reset_time.astimezone()
        # Within the next week, weekday+time is unambiguous ("Fri 02:00").
        # Beyond that, show the date so a month-away reset doesn't look
        # like one that's a few days out.
        if hours < 24 * 7:
            from ..constants import DATETIME_FMT_WEEKDAY
            return f"Resets {local_time.strftime(DATETIME_FMT_WEEKDAY)}"
        return f"Resets {local_time.strftime('%-d %b')}"
    except (ValueError, TypeError):
        return ""
