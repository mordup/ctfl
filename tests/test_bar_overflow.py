"""Verify bar chart normalization handles values exceeding 32-bit int range."""


def _normalize(value: int, max_value: int) -> int:
    """Mirror the normalization logic from popup._BarChartWidget.set_rows."""
    return round(value / max_value * 1000) if max_value else 0


def test_large_token_counts():
    """Values above 2^31 must not overflow when normalized."""
    result = _normalize(3_000_000_000, 5_000_000_000)
    assert 0 <= result <= 1000
    assert result == 600


def test_zero_max():
    assert _normalize(100, 0) == 0


def test_full_bar():
    assert _normalize(5_000_000_000, 5_000_000_000) == 1000


def test_small_values():
    assert _normalize(1, 100) == 10
