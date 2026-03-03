from __future__ import annotations

from dataclasses import dataclass, field


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
    name: str            # "Current session", "Weekly — All models", etc.
    utilization: float   # 0-100 percentage
    resets_at: str | None  # ISO 8601 timestamp or None


@dataclass
class UsageData:
    daily: list[DailyUsage] = field(default_factory=list)
    by_model: list[ModelTokens] = field(default_factory=list)
    limits: list[RateLimitInfo] = field(default_factory=list)
    error: str | None = None
