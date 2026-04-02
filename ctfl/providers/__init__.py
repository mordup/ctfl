from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC
from typing import Protocol


def format_cost(usd: float) -> str:
    return f"${usd:.2f}"


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

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_tokens + self.cache_creation_tokens


@dataclass
class RateLimitInfo:
    name: str            # "Session", "Weekly", "Weekly (Sonnet)", etc.
    utilization: float   # 0-100 percentage
    resets_at: str | None  # ISO 8601 timestamp or None
    window_key: str = ""  # "five_hour", "seven_day", etc.


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
        from ..constants import DATETIME_FMT_WEEKDAY
        local_time = reset_time.astimezone()
        return f"Resets {local_time.strftime(DATETIME_FMT_WEEKDAY)}"
    except (ValueError, TypeError):
        return ""
