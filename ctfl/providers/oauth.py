from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import RateLimitInfo, UsageData

CREDENTIALS_FILE = Path.home() / ".claude" / ".credentials.json"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"

_KEY_LABELS = {
    "five_hour": "Current session",
    "seven_day": "Weekly",
    "seven_day_opus": "Weekly — Opus",
}


class OAuthUsageProvider:
    def fetch(self, days: int = 0) -> UsageData:
        try:
            token = self._read_token()
            if not token:
                return UsageData()
            return self._fetch(token)
        except HTTPError as e:
            if e.code in (401, 403):
                return UsageData(error="OAuth: session expired, re-login to claude.ai")
            return UsageData(error=f"OAuth: HTTP {e.code}")
        except (URLError, OSError):
            return UsageData(error="OAuth: network error")
        except Exception as e:
            return UsageData(error=f"OAuth: {e}")

    def _read_token(self) -> str | None:
        if not CREDENTIALS_FILE.exists():
            return None
        try:
            with open(CREDENTIALS_FILE) as f:
                data = json.load(f)
            return data.get("claudeAiOauth", {}).get("accessToken")
        except (json.JSONDecodeError, OSError):
            return None

    def _fetch(self, token: str) -> UsageData:
        req = Request(USAGE_URL, headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
        })
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        limits: list[RateLimitInfo] = []
        for key, label in _KEY_LABELS.items():
            entry = data.get(key)
            if entry is None:
                continue
            utilization = entry.get("utilization")
            if utilization is None:
                continue
            limits.append(RateLimitInfo(
                name=label,
                utilization=utilization,
                resets_at=entry.get("resets_at"),
            ))

        return UsageData(limits=limits)
