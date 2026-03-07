from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import RateLimitInfo, UsageData

CREDENTIALS_FILE = Path.home() / ".claude" / ".credentials.json"
_OAUTH_URL = "https://api.anthropic.com/api/oauth/usage"
_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
_CLAUDE_BASE = "https://claude.ai/api"
_CACHE_DIR = Path.home() / ".cache" / "ctfl"
_CACHE_FILE = _CACHE_DIR / "oauth_limits.json"
_ORG_CACHE_FILE = _CACHE_DIR / "org_id.txt"
_TOKEN_EXPIRY_BUFFER = 300  # refresh 5 min before expiry

_KEY_LABELS = {
    "five_hour": "Current session",
    "seven_day": "Weekly",
    "seven_day_opus": "Weekly — Opus",
    "seven_day_sonnet": "Weekly — Sonnet",
}


_PLAN_LABELS = {
    "pro": "Pro",
    "max": "Max 5x",
    "max_20x": "Max 20x",
}


def read_plan_name() -> str | None:
    """Read the short plan name from Claude credentials."""
    if not CREDENTIALS_FILE.exists():
        return None
    try:
        with open(CREDENTIALS_FILE) as f:
            data = json.load(f)
        oauth = data.get("claudeAiOauth", {})
        tier = oauth.get("rateLimitTier", "")
        if "max_20x" in tier:
            return _PLAN_LABELS["max_20x"]
        sub_type = oauth.get("subscriptionType", "")
        return _PLAN_LABELS.get(sub_type)
    except (json.JSONDecodeError, OSError):
        return None


def _is_expired(expires_at_ms: int) -> bool:
    now_ms = int(time.time() * 1000)
    return now_ms >= expires_at_ms - _TOKEN_EXPIRY_BUFFER * 1000


def _save_limits_cache(limits: list[RateLimitInfo]) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        data = [{"name": li.name, "utilization": li.utilization,
                 "resets_at": li.resets_at, "window_key": li.window_key}
                for li in limits]
        _CACHE_FILE.write_text(json.dumps(data))
    except OSError:
        pass


def _load_limits_cache() -> list[RateLimitInfo]:
    try:
        data = json.loads(_CACHE_FILE.read_text())
        return [RateLimitInfo(**entry) for entry in data]
    except (OSError, json.JSONDecodeError, TypeError):
        return []


def _parse_limits(data: dict) -> list[RateLimitInfo]:
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
            utilization=utilization * 100,
            resets_at=entry.get("resets_at"),
            window_key=key,
        ))
    return limits


def _save_org_id(org_id: str) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _ORG_CACHE_FILE.write_text(org_id)
    except OSError:
        pass


def _load_org_id() -> str | None:
    try:
        return _ORG_CACHE_FILE.read_text().strip() or None
    except OSError:
        return None


class OAuthUsageProvider:
    def __init__(
        self,
        get_session_key: Callable[[], str | None] = lambda: None,
        get_cf_clearance: Callable[[], str | None] = lambda: None,
    ) -> None:
        self._get_session_key = get_session_key
        self._get_cf_clearance = get_cf_clearance

    def fetch(self, days: int = 0) -> UsageData:
        # Try session key first (claude.ai browser cookie)
        session_key = self._get_session_key()
        if session_key:
            try:
                cf_clearance = self._get_cf_clearance()
                result = self._fetch_via_session(session_key, cf_clearance)
                if result.limits:
                    _save_limits_cache(result.limits)
                return result
            except (HTTPError, URLError, OSError):
                pass  # fall through to OAuth

        # Fall back to OAuth token
        try:
            token = self._read_oauth_token()
            if not token:
                cached = _load_limits_cache()
                if cached:
                    return UsageData(limits=cached)
                return UsageData()
            result = self._fetch_via_oauth(token)
            if result.limits:
                _save_limits_cache(result.limits)
            return result
        except HTTPError as e:
            if e.code in (401, 403):
                return UsageData(error="Session expired, re-login to claude.ai")
            cached = _load_limits_cache()
            if cached:
                return UsageData(limits=cached)
            return UsageData(error=f"OAuth: HTTP {e.code}")
        except (URLError, OSError):
            cached = _load_limits_cache()
            if cached:
                return UsageData(limits=cached)
            return UsageData(error="Network error")
        except Exception as e:
            return UsageData(error=f"OAuth: {e}")

    def _read_oauth_token(self) -> str | None:
        if not CREDENTIALS_FILE.exists():
            return None
        try:
            with open(CREDENTIALS_FILE) as f:
                data = json.load(f)
            oauth = data.get("claudeAiOauth", {})
            token = oauth.get("accessToken")
            if not token:
                return None
            expires_at = oauth.get("expiresAt")
            if expires_at and _is_expired(expires_at):
                refreshed = self._refresh_token(data, oauth)
                if refreshed:
                    return refreshed
            return token
        except (json.JSONDecodeError, OSError):
            return None

    def _refresh_token(self, creds_data: dict, oauth: dict) -> str | None:
        refresh_token = oauth.get("refreshToken")
        if not refresh_token:
            return None
        try:
            body = urlencode({
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": _CLIENT_ID,
            }).encode()
            req = Request(_TOKEN_URL, data=body, headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "anthropic-beta": "oauth-2025-04-20",
                "User-Agent": "claude-cli/ctfl",
            })
            with urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read())
            new_token = result.get("access_token")
            if not new_token:
                return None
            oauth["accessToken"] = new_token
            if result.get("refresh_token"):
                oauth["refreshToken"] = result["refresh_token"]
            expires_in = result.get("expires_in")
            if expires_in:
                oauth["expiresAt"] = int(time.time() * 1000) + expires_in * 1000
            org_info = result.get("organization")
            if org_info and org_info.get("uuid"):
                _save_org_id(org_info["uuid"])
            creds_data["claudeAiOauth"] = oauth
            tmp = CREDENTIALS_FILE.with_suffix(".tmp")
            fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                os.write(fd, json.dumps(creds_data, indent=2).encode())
            finally:
                os.close(fd)
            tmp.rename(CREDENTIALS_FILE)
            return new_token
        except (HTTPError, URLError, OSError, json.JSONDecodeError, KeyError):
            return None

    def _fetch_via_session(self, session_key: str, cf_clearance: str | None) -> UsageData:
        org_id = self._get_org_id(session_key, cf_clearance)
        headers = self._session_headers(session_key, cf_clearance)
        req = Request(f"{_CLAUDE_BASE}/organizations/{org_id}/usage", headers=headers)
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        return UsageData(limits=_parse_limits(data))

    def _get_org_id(self, session_key: str, cf_clearance: str | None) -> str:
        cached = _load_org_id()
        if cached:
            return cached
        headers = self._session_headers(session_key, cf_clearance)
        req = Request(f"{_CLAUDE_BASE}/organizations", headers=headers)
        with urlopen(req, timeout=15) as resp:
            orgs = json.loads(resp.read())
        if not orgs:
            raise ValueError("No organizations found")
        org_id = orgs[0]["uuid"]
        _save_org_id(org_id)
        return org_id

    @staticmethod
    def _session_headers(session_key: str, cf_clearance: str | None) -> dict:
        cookie = f"sessionKey={session_key}"
        if cf_clearance:
            cookie += f"; cf_clearance={cf_clearance}"
        return {
            "Cookie": cookie,
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:148.0) Gecko/20100101 Firefox/148.0",
        }

    def _fetch_via_oauth(self, token: str) -> UsageData:
        req = Request(_OAUTH_URL, headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
        })
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        return UsageData(limits=_parse_limits(data))
