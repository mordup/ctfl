from ctfl.providers import DailyUsage, ModelTokens, ProjectUsage


def test_daily_usage_total_tokens():
    d = DailyUsage(
        date="2026-03-03",
        input_tokens=100,
        output_tokens=200,
        cache_read_tokens=50,
        cache_creation_tokens=25,
    )
    assert d.total_tokens == 375


def test_daily_usage_total_tokens_zero():
    d = DailyUsage(date="2026-03-03")
    assert d.total_tokens == 0


def test_model_tokens_total():
    m = ModelTokens(
        model="claude-opus-4-6",
        input_tokens=1000,
        output_tokens=500,
        cache_read_tokens=200,
        cache_creation_tokens=100,
    )
    assert m.total == 1800


def test_model_tokens_total_zero():
    m = ModelTokens(model="test")
    assert m.total == 0


def test_project_usage_defaults():
    p = ProjectUsage(name="ctfl", path="-home-user-ctfl")
    assert p.total_tokens == 0
    assert p.message_count == 0


def test_project_usage_fields():
    p = ProjectUsage(name="Ctfl", path="-home-user-ctfl", total_tokens=5000, message_count=42)
    assert p.name == "Ctfl"
    assert p.total_tokens == 5000
    assert p.message_count == 42
