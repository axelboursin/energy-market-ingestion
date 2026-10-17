import dataclasses
from datetime import date

import pytest

from market_ingest.validation import expected_intervals, validate_day


@pytest.mark.parametrize(
    ("zone", "day", "count"),
    [
        ("FR", "2026-10-15", 96),
        ("DE-LU", "2026-10-15", 96),
        ("ES", "2026-10-15", 96),
        ("FR", "2026-03-29", 92),  # spring DST: 23-hour day
        ("FR", "2025-10-26", 100),  # autumn DST: 25-hour day
        ("FR", "2025-06-15", 24),  # hourly products before 2025-10-01
    ],
)
def test_real_days_are_valid(points, zone, day, count):
    day_points = points(zone, day)
    assert len(day_points) == count
    result = validate_day(day_points, date.fromisoformat(day))
    assert result.ok, result.issues


def test_expected_intervals_follow_dst():
    # Regression: same-tzinfo subtraction used to return 24 h for every day.
    assert expected_intervals(date(2026, 3, 29), 15) == 92
    assert expected_intervals(date(2026, 10, 25), 15) == 100
    assert expected_intervals(date(2026, 10, 15), 60) == 24


def test_empty_day_is_not_published():
    result = validate_day([], date(2026, 10, 16))
    assert result.status == "not_published"


def test_incomplete_day_is_invalid(points):
    result = validate_day(points("FR", "2026-10-15")[:80], date(2026, 10, 15))
    assert result.status == "invalid"
    assert "expected 96 intervals of 15 min, got 80" in result.issues


def test_wrong_delivery_day_is_invalid(points):
    result = validate_day(points("FR", "2026-10-15"), date(2026, 10, 16))
    assert result.status == "invalid"
    assert any("outside the local delivery day" in issue for issue in result.issues)


def test_missing_and_out_of_bounds_prices(points):
    day = points("FR", "2026-10-15")
    day[3] = dataclasses.replace(day[3], price_eur_mwh=None)
    day[4] = dataclasses.replace(day[4], price_eur_mwh=-600.0)
    day[5] = dataclasses.replace(day[5], price_eur_mwh=4500.0)
    result = validate_day(day, date(2026, 10, 15))
    assert result.status == "invalid"
    assert "1 intervals without a price" in result.issues
    assert "2 prices outside [-500.0, 4000.0]" in result.issues
    assert validate_day(day[:3] + day[6:], date(2026, 10, 15), max_price=5000).status == "invalid"


def test_all_prices_missing_means_not_published(points):
    day = [dataclasses.replace(p, price_eur_mwh=None) for p in points("FR", "2026-10-15")]
    assert validate_day(day, date(2026, 10, 15)).status == "not_published"
