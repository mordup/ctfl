"""The session-key path must fall through to the OAuth token on any failure.

A stale cf_clearance makes claude.ai answer with an HTTP 200 Cloudflare
challenge page rather than JSON. That raises JSONDecodeError, which used to
escape the except clause guarding the session path and skip the OAuth fallback
entirely — the user silently lost their rate limits.
"""

import json

from ctfl.providers.instance import Instance
from ctfl.providers.oauth import OAuthUsageProvider

_OAUTH_USAGE = {"five_hour": {"utilization": 42, "resets_at": "2026-12-01T18:00:00+00:00"}}
_SESSION_USAGE = {"seven_day": {"utilization": 7, "resets_at": "2026-12-05T00:00:00+00:00"}}


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _setup(monkeypatch, tmp_path, *, org_response: bytes):
    """Pin profile and cache dir, then route urlopen by URL.

    `org_response` is what claude.ai returns for the organizations lookup —
    the first call the session path makes. api.anthropic.com always serves a
    valid OAuth usage payload, so reaching it proves the fallback ran.
    """
    instance = Instance(name="test", path=tmp_path)
    monkeypatch.setattr(
        "ctfl.providers.oauth.resolve_profile", lambda config=None: instance
    )
    monkeypatch.setattr("ctfl.providers.oauth._CACHE_DIR", tmp_path / "cache")

    (tmp_path / ".credentials.json").write_text(
        json.dumps({"claudeAiOauth": {"accessToken": "oauth-token"}})
    )

    def fake_urlopen(req, timeout=None):
        url = req.full_url
        if "api.anthropic.com" in url:
            return _FakeResponse(json.dumps(_OAUTH_USAGE).encode())
        if url.endswith("/organizations"):
            return _FakeResponse(org_response)
        return _FakeResponse(json.dumps(_SESSION_USAGE).encode())

    monkeypatch.setattr("ctfl.providers.oauth.urlopen", fake_urlopen)


def _provider() -> OAuthUsageProvider:
    return OAuthUsageProvider(get_session_key=lambda: "sk-ant-sid-stale")


def test_cloudflare_html_falls_back_to_oauth(tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path, org_response=b"<html>Just a moment...</html>")
    data = _provider().fetch()
    assert data.error is None
    assert [li.name for li in data.limits] == ["Session"]


def test_empty_org_list_falls_back_to_oauth(tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path, org_response=b"[]")
    data = _provider().fetch()
    assert data.error is None
    assert [li.name for li in data.limits] == ["Session"]


def test_malformed_org_entry_falls_back_to_oauth(tmp_path, monkeypatch):
    # Missing the "uuid" key -> KeyError inside _get_org_id.
    _setup(monkeypatch, tmp_path, org_response=json.dumps([{"id": "x"}]).encode())
    data = _provider().fetch()
    assert data.error is None
    assert [li.name for li in data.limits] == ["Session"]


def test_working_session_path_is_used_without_oauth(tmp_path, monkeypatch):
    # Happy path guard: a healthy session key still serves claude.ai data.
    _setup(monkeypatch, tmp_path, org_response=json.dumps([{"uuid": "org-1"}]).encode())
    data = _provider().fetch()
    assert data.error is None
    assert [li.name for li in data.limits] == ["Weekly"]


def test_no_session_key_uses_oauth(tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path, org_response=b"[]")
    data = OAuthUsageProvider().fetch()
    assert data.error is None
    assert [li.name for li in data.limits] == ["Session"]
