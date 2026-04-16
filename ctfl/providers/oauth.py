from __future__ import annotations

import fcntl
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import RateLimitInfo, UsageData
from .instance import resolve_profile

if TYPE_CHECKING:
    from ..config import Config

_OAUTH_URL = "https://api.anthropic.com/api/oauth/usage"
_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
_CLAUDE_BASE = "https://claude.ai/api"
_CACHE_DIR = Path.home() / ".cache" / "ctfl"
_TOKEN_EXPIRY_BUFFER = 300  # refresh 5 min before expiry


def _profile_cache_suffix(credentials_file: Path) -> str:
    """Short stable suffix derived from the credentials path so per-profile
    caches (rate limits, org id) don't leak between accounts.
    """
    import hashlib

    # Non-cryptographic use: just a stable short suffix that differs between
    # profiles. Flagged as usedforsecurity=False to silence Bandit/Ruff S324.
    digest = hashlib.sha1(
        str(credentials_file.parent).encode(), usedforsecurity=False
    ).hexdigest()[:8]
    return digest


def _limits_cache_file(credentials_file: Path) -> Path:
    return _CACHE_DIR / f"oauth_limits_{_profile_cache_suffix(credentials_file)}.json"


def _org_cache_file(credentials_file: Path) -> Path:
    return _CACHE_DIR / f"org_id_{_profile_cache_suffix(credentials_file)}.txt"

_KEY_LABELS = {
    "five_hour": "Session",
    "seven_day": "Weekly",
    "seven_day_opus": "Weekly (Opus)",
    "seven_day_sonnet": "Weekly (Sonnet)",
}


_PLAN_LABELS = {
    "pro": "Pro",
    "max": "Max 5x",
    "max_20x": "Max 20x",
}


def _resolve_credentials_file(config: Config | None) -> Path:
    return resolve_profile(config).credentials_file


def read_plan_name(config: Config | None = None) -> str | None:
    """Read the short plan name from Claude credentials."""
    credentials_file = _resolve_credentials_file(config)
    if not credentials_file.exists():
        return None
    try:
        with open(credentials_file) as f:
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


def _save_limits_cache(credentials_file: Path, limits: list[RateLimitInfo]) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        data = [{"name": li.name, "utilization": li.utilization,
                 "resets_at": li.resets_at, "window_key": li.window_key}
                for li in limits]
        cache_file = _limits_cache_file(credentials_file)
        tmp = cache_file.with_suffix(".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, json.dumps(data).encode())
        finally:
            os.close(fd)
        tmp.rename(cache_file)
    except OSError:
        pass


def _load_limits_cache(credentials_file: Path) -> list[RateLimitInfo]:
    try:
        data = json.loads(_limits_cache_file(credentials_file).read_text())
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
        utilization = max(0.0, min(100.0, float(utilization)))
        limits.append(RateLimitInfo(
            name=label,
            utilization=utilization,
            resets_at=entry.get("resets_at"),
            window_key=key,
        ))
    return limits


def _save_org_id(credentials_file: Path, org_id: str) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        cache_file = _org_cache_file(credentials_file)
        fd = os.open(str(cache_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, org_id.encode())
        finally:
            os.close(fd)
    except OSError:
        pass


def _load_org_id(credentials_file: Path) -> str | None:
    try:
        return _org_cache_file(credentials_file).read_text().strip() or None
    except OSError:
        return None


class OAuthUsageProvider:
    def __init__(
        self,
        get_session_key: Callable[[], str | None] = lambda: None,
        get_cf_clearance: Callable[[], str | None] = lambda: None,
        config: Config | None = None,
    ) -> None:
        self._get_session_key = get_session_key
        self._get_cf_clearance = get_cf_clearance
        self._config = config

    def _credentials_file(self) -> Path:
        return _resolve_credentials_file(self._config)

    def fetch(self, days: int = 0) -> UsageData:
        credentials_file = self._credentials_file()
        # Try session key first (claude.ai browser cookie)
        session_key = self._get_session_key()
        if session_key:
            try:
                cf_clearance = self._get_cf_clearance()
                result = self._fetch_via_session(credentials_file, session_key, cf_clearance)
                if result.limits:
                    _save_limits_cache(credentials_file, result.limits)
                return result
            except (HTTPError, URLError, OSError):
                pass  # fall through to OAuth

        # Fall back to OAuth token
        try:
            token = self._read_oauth_token(credentials_file)
            if not token:
                cached = _load_limits_cache(credentials_file)
                if cached:
                    return UsageData(limits=cached)
                return UsageData()
            result = self._fetch_via_oauth(token)
            if result.limits:
                _save_limits_cache(credentials_file, result.limits)
            return result
        except HTTPError as e:
            if e.code in (401, 403):
                return UsageData(error="Session expired, re-login to claude.ai")
            cached = _load_limits_cache(credentials_file)
            if cached:
                return UsageData(limits=cached)
            return UsageData(error=f"OAuth: HTTP {e.code}")
        except (URLError, OSError):
            cached = _load_limits_cache(credentials_file)
            if cached:
                return UsageData(limits=cached)
            return UsageData(error="Network error")
        except Exception as e:
            return UsageData(error=f"OAuth: {e}")

    def _read_oauth_token(self, credentials_file: Path | None = None) -> str | None:
        if credentials_file is None:
            credentials_file = self._credentials_file()
        if not credentials_file.exists():
            return None
        try:
            with open(credentials_file) as f:
                data = json.load(f)
            oauth = data.get("claudeAiOauth", {})
            token = oauth.get("accessToken")
            if not token:
                return None
            expires_at = oauth.get("expiresAt")
            if expires_at and _is_expired(expires_at):
                refreshed = self._refresh_token(credentials_file, data, oauth)
                if refreshed:
                    return refreshed
            return token
        except (json.JSONDecodeError, OSError):
            return None

    def _refresh_token(self, credentials_file: Path, creds_data: dict, oauth: dict) -> str | None:
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
                _save_org_id(credentials_file, org_info["uuid"])
            lock_fd = os.open(str(credentials_file), os.O_RDONLY)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                # Re-read credentials under lock in case Claude CLI modified them
                with open(credentials_file) as f:
                    creds_data = json.load(f)
                creds_data["claudeAiOauth"] = oauth
                tmp = credentials_file.with_suffix(".tmp")
                fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                try:
                    os.write(fd, json.dumps(creds_data, indent=2).encode())
                finally:
                    os.close(fd)
                tmp.rename(credentials_file)
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)
            return new_token
        except (HTTPError, URLError, OSError, json.JSONDecodeError, KeyError):
            return None

    def _fetch_via_session(
        self, credentials_file: Path, session_key: str, cf_clearance: str | None
    ) -> UsageData:
        org_id = self._get_org_id(credentials_file, session_key, cf_clearance)
        headers = self._session_headers(session_key, cf_clearance)
        req = Request(f"{_CLAUDE_BASE}/organizations/{org_id}/usage", headers=headers)
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        return UsageData(limits=_parse_limits(data))

    def _get_org_id(
        self, credentials_file: Path, session_key: str, cf_clearance: str | None
    ) -> str:
        cached = _load_org_id(credentials_file)
        if cached:
            return cached
        headers = self._session_headers(session_key, cf_clearance)
        req = Request(f"{_CLAUDE_BASE}/organizations", headers=headers)
        with urlopen(req, timeout=15) as resp:
            orgs = json.loads(resp.read())
        if not orgs:
            raise ValueError("No organizations found")
        org_id = orgs[0]["uuid"]
        _save_org_id(credentials_file, org_id)
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
