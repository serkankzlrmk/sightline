"""Tests for scripts/load_test.py pure helpers."""


def test_percentile():
    from scripts.load_test import percentile

    values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert percentile(values, 50) == 5
    assert percentile(values, 95) == 10
    assert percentile([], 95) == 0.0
