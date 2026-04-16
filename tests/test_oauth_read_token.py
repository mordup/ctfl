import json
from pathlib import Path

from ctfl.providers.instance import Instance
from ctfl.providers.oauth import OAuthUsageProvider, read_plan_name


def _pin_profile(monkeypatch, instance_path: Path) -> None:
    instance = Instance(name="test", path=instance_path)
    monkeypatch.setattr(
        "ctfl.providers.oauth.resolve_profile",
        lambda config=None: instance,
    )
    monkeypatch.setattr(
        "ctfl.providers.instance.resolve_profile",
        lambda config=None: instance,
    )


def test_read_oauth_token_valid(tmp_path, monkeypatch):
    creds = tmp_path / ".credentials.json"
    creds.write_text(json.dumps({
        "claudeAiOauth": {"accessToken": "test-token-123"}
    }))
    _pin_profile(monkeypatch, tmp_path)
    provider = OAuthUsageProvider()
    assert provider._read_oauth_token() == "test-token-123"


def test_read_oauth_token_missing_file(tmp_path, monkeypatch):
    _pin_profile(monkeypatch, tmp_path)
    provider = OAuthUsageProvider()
    assert provider._read_oauth_token() is None


def test_read_oauth_token_no_oauth_key(tmp_path, monkeypatch):
    creds = tmp_path / ".credentials.json"
    creds.write_text(json.dumps({"other": "data"}))
    _pin_profile(monkeypatch, tmp_path)
    provider = OAuthUsageProvider()
    assert provider._read_oauth_token() is None


def test_read_oauth_token_corrupt_json(tmp_path, monkeypatch):
    creds = tmp_path / ".credentials.json"
    creds.write_text("not valid json{{{")
    _pin_profile(monkeypatch, tmp_path)
    provider = OAuthUsageProvider()
    assert provider._read_oauth_token() is None


def test_read_plan_name_max_20x(tmp_path, monkeypatch):
    creds = tmp_path / ".credentials.json"
    creds.write_text(json.dumps({
        "claudeAiOauth": {"rateLimitTier": "max_20x", "subscriptionType": "max"}
    }))
    _pin_profile(monkeypatch, tmp_path)
    assert read_plan_name() == "Max 20x"
