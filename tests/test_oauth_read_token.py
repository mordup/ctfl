import json

from ctfl.providers.oauth import OAuthUsageProvider, CREDENTIALS_FILE


def test_read_token_valid(tmp_path, monkeypatch):
    creds = tmp_path / ".credentials.json"
    creds.write_text(json.dumps({
        "claudeAiOauth": {"accessToken": "test-token-123"}
    }))
    monkeypatch.setattr("ctfl.providers.oauth.CREDENTIALS_FILE", creds)
    provider = OAuthUsageProvider()
    assert provider._read_token() == "test-token-123"


def test_read_token_missing_file(tmp_path, monkeypatch):
    creds = tmp_path / ".credentials.json"
    monkeypatch.setattr("ctfl.providers.oauth.CREDENTIALS_FILE", creds)
    provider = OAuthUsageProvider()
    assert provider._read_token() is None


def test_read_token_no_oauth_key(tmp_path, monkeypatch):
    creds = tmp_path / ".credentials.json"
    creds.write_text(json.dumps({"other": "data"}))
    monkeypatch.setattr("ctfl.providers.oauth.CREDENTIALS_FILE", creds)
    provider = OAuthUsageProvider()
    assert provider._read_token() is None


def test_read_token_corrupt_json(tmp_path, monkeypatch):
    creds = tmp_path / ".credentials.json"
    creds.write_text("not valid json{{{")
    monkeypatch.setattr("ctfl.providers.oauth.CREDENTIALS_FILE", creds)
    provider = OAuthUsageProvider()
    assert provider._read_token() is None
