from ctfl.providers import format_tokens


def test_billions():
    assert format_tokens(1_500_000_000) == "1.5B"
    assert format_tokens(1_000_000_000) == "1.0B"


def test_millions():
    assert format_tokens(1_200_000) == "1.2M"
    assert format_tokens(1_000_000) == "1.0M"
    assert format_tokens(999_999_999) == "1000.0M"


def test_thousands():
    assert format_tokens(10_000) == "10.0K"
    assert format_tokens(50_000) == "50.0K"


def test_small_with_commas():
    assert format_tokens(9_999) == "9,999"
    assert format_tokens(1_000) == "1,000"
    assert format_tokens(100) == "100"
    assert format_tokens(0) == "0"
