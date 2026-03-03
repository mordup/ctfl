from ctfl.popup import _short_model


def test_strips_claude_prefix():
    assert _short_model("claude-opus-4-6") == "Opus-4-6"


def test_strips_date_suffix():
    assert _short_model("claude-opus-4-5-20251101") == "Opus-4-5"


def test_no_prefix():
    assert _short_model("opus-4-6") == "Opus-4-6"


def test_haiku():
    assert _short_model("claude-haiku-4-5-20251001") == "Haiku-4-5"


def test_sonnet():
    assert _short_model("claude-sonnet-4-6") == "Sonnet-4-6"
