from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC
from typing import Protocol


def format_cost(usd: float) -> str:
    return f"${usd:.2f}"


# Currencies we render with a symbol instead of an ISO code. Deliberately
# limited to unambiguous ones: CAD, AUD, SGD and friends also spend "$", and a
# bare "$1,000" would misstate the amount. Anything missing keeps its code.
_CURRENCY_SYMBOLS = {
    "USD": "$",
    "EUR": "\u20ac",
    "GBP": "\u00a3",
    "JPY": "\u00a5",
    "INR": "\u20b9",
    "KRW": "\u20a9",
    "BRL": "R$",
}


def format_credits(cents: int | None, currency: str | None = "USD") -> str:
    """Format minor-unit credit amounts (e.g. USD cents) as a display string.

    Drops fractional cents on round values (e.g. $1,000 not $1,000.00).
    Known currencies get a prefixed symbol, matching how the dashboard renders
    them; the rest fall back to a trailing ISO code ("1,234.56 CHF").
    Zero-decimal currencies (JPY, etc.) aren't special-cased here — callers
    rescale to hundredths before this point.
    """
    if cents is None:
        return ""
    amount = cents / 100
    code = (currency or "USD").upper()
    text = f"{int(amount):,}" if amount == int(amount) else f"{amount:,.2f}"
    symbol = _CURRENCY_SYMBOLS.get(code)
    return f"{symbol}{text}" if symbol else f"{text} {code}"


def format_credits_range(
    used: int | None, limit: int | None, currency: str | None = "USD"
) -> str:
    """Format a used/limit pair, naming the currency only as often as needed.

    Symbol currencies repeat it ("$5.72 / $60") the way the dashboard does.
    ISO-code fallbacks carry the code on the limit alone ("15 / 60 CHF"), since
    "15 CHF / 60 CHF" reads as two separate figures.
    """
    used_text = format_credits(used, currency)
    cap_text = format_credits(limit, currency)
    code = (currency or "USD").upper()
    if code not in _CURRENCY_SYMBOLS:
        used_text = used_text.removesuffix(f" {code}")
    return f"{used_text} / {cap_text}"


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
    breakdown_available: bool = True
    cost_usd: float | None = None

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
    # Keyed by ISO date, so any period inside the fetched window can be
    # totalled without fetching again (see models_since / projects_since).
    models_by_day: dict[str, list[ModelTokens]] = field(default_factory=dict)
    projects_by_day: dict[str, list[ProjectUsage]] = field(default_factory=dict)
    limits: list[RateLimitInfo] = field(default_factory=list)
    error: str | None = None


def models_since(data: UsageData, start: str) -> list[ModelTokens]:
    """Per-model totals from start (ISO date) onwards, largest first.

    A model's cost is None when any of its days is unpriced, for the same
    reason a partial period total is withheld.
    """
    totals: dict[str, ModelTokens] = {}
    for day, models in data.models_by_day.items():
        if day < start:
            continue
        for m in models:
            t = totals.get(m.model)
            if t is None:
                t = totals[m.model] = ModelTokens(model=m.model, cost_usd=0.0)
            t.input_tokens += m.input_tokens
            t.output_tokens += m.output_tokens
            t.cache_read_tokens += m.cache_read_tokens
            t.cache_creation_tokens += m.cache_creation_tokens
            t.breakdown_available &= m.breakdown_available
            if t.cost_usd is not None and m.cost_usd is not None:
                t.cost_usd += m.cost_usd
            else:
                t.cost_usd = None
    return sorted((m for m in totals.values() if m.total > 0), key=lambda m: m.total, reverse=True)


def projects_since(data: UsageData, start: str) -> list[ProjectUsage]:
    totals: dict[str, ProjectUsage] = {}
    for day, projects in data.projects_by_day.items():
        if day < start:
            continue
        for p in projects:
            t = totals.get(p.path)
            if t is None:
                t = totals[p.path] = ProjectUsage(name=p.name, path=p.path)
            t.total_tokens += p.total_tokens
            t.message_count += p.message_count
    return sorted(totals.values(), key=lambda p: p.total_tokens, reverse=True)


class UsageProvider(Protocol):
    def fetch(self, days: int) -> UsageData: ...


def format_reset(resets_at: str | None) -> str:
    from datetime import datetime

    if not resets_at:
        return ""
    try:
        reset_time = datetime.fromisoformat(resets_at)
        if reset_time.tzinfo is None:
            reset_time = reset_time.replace(tzinfo=UTC)
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
        from ..dates import short_date, weekday_time

        local_time = reset_time.astimezone()
        # Within the next week, weekday+time is unambiguous ("Fri 02:00").
        # Beyond that, show the date so a month-away reset doesn't look
        # like one that's a few days out.
        if hours < 24 * 7:
            return f"Resets {weekday_time(local_time)}"
        return f"Resets {short_date(local_time.date())}"
    except (ValueError, TypeError):
        return ""
