from ctfl.providers import format_cost


def test_basic():
    assert format_cost(0.42) == "$0.42"


def test_large():
    assert format_cost(12.35) == "$12.35"


def test_zero():
    assert format_cost(0) == "$0.00"


def test_rounds():
    assert format_cost(1.999) == "$2.00"
    assert format_cost(0.005) == "$0.01"


def test_small():
    assert format_cost(0.001) == "$0.00"
