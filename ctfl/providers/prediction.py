"""Burn rate prediction for rate limit exhaustion."""

from __future__ import annotations

from datetime import datetime, timezone

from . import RateLimitInfo

# Known window durations in hours
_WINDOW_HOURS: dict[str, float] = {
    "five_hour": 5,
    "seven_day": 168,
    "seven_day_opus": 168,
}


def predict_exhaustion(info: RateLimitInfo, window_key: str) -> str | None:
    """Predict time until rate limit exhaustion at current pace.

    Returns a formatted string like '~1h 30m left' or None if the user
    is on track to stay within the limit (or if prediction isn't possible).
    """
    window_hours = _WINDOW_HOURS.get(window_key)
    if window_hours is None or info.utilization <= 0 or not info.resets_at:
        return None

    try:
        reset_time = datetime.fromisoformat(info.resets_at)
        now = datetime.now(timezone.utc)
        hours_until_reset = (reset_time - now).total_seconds() / 3600
    except (ValueError, TypeError):
        return None

    if hours_until_reset <= 0:
        return None

    elapsed = window_hours - hours_until_reset
    if elapsed <= 0:
        return None

    burn_rate = info.utilization / elapsed  # % per hour
    remaining_pct = 100 - info.utilization
    if remaining_pct <= 0:
        return "limit reached"

    time_to_100 = remaining_pct / burn_rate  # hours

    if time_to_100 > hours_until_reset:
        return None  # on track, won't hit limit

    # Format as ~Xh Ym
    total_min = int(time_to_100 * 60)
    if total_min < 1:
        return "~<1m left"
    hours = total_min // 60
    minutes = total_min % 60
    if hours > 0:
        return f"~{hours}h {minutes:02d}m left"
    return f"~{minutes}m left"
