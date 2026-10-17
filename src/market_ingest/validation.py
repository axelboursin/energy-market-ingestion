"""Business validation of one delivery day for one bidding zone.

A day is accepted only if it is complete and plausible. Partial data is never
written: the next scheduled run (or a retry) will pick the day up once the
auction results are fully published.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from market_ingest.energy_charts import PricePoint

# All SDAC bidding zones of interest are on Central European Time.
MARKET_TZ = ZoneInfo("Europe/Brussels")

# SDAC harmonised clearing price limits (EUR/MWh). The maximum is raised
# automatically after extreme events, so the upper bound is configurable.
MIN_PRICE = -500.0
DEFAULT_MAX_PRICE = 4000.0


@dataclass(frozen=True)
class ValidationResult:
    status: str  # "ok" | "not_published" | "invalid"
    issues: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def local_day_bounds(delivery_date: date) -> tuple[datetime, datetime]:
    """UTC bounds of a local delivery day: 23, 24 or 25 hours long.

    Converted to UTC on purpose: subtracting two datetimes that share the same
    tzinfo gives the *wall-clock* difference (always 24 h), not the real one.
    """
    start = datetime.combine(delivery_date, time(0), MARKET_TZ).astimezone(UTC)
    end = datetime.combine(delivery_date + timedelta(days=1), time(0), MARKET_TZ).astimezone(UTC)
    return start, end


def expected_intervals(delivery_date: date, resolution_minutes: int) -> int:
    start, end = local_day_bounds(delivery_date)
    return int((end - start).total_seconds() // 60 // resolution_minutes)


def validate_day(
    points: list[PricePoint], delivery_date: date, max_price: float = DEFAULT_MAX_PRICE
) -> ValidationResult:
    if not points:
        return ValidationResult("not_published", ("no data returned yet",))

    issues: list[str] = []
    resolutions = {p.resolution_minutes for p in points}
    if resolutions - {15, 30, 60} or len(resolutions) != 1:
        return ValidationResult("invalid", (f"unexpected resolutions {sorted(resolutions)}",))
    resolution = resolutions.pop()

    day_start, day_end = local_day_bounds(delivery_date)
    starts = [p.delivery_start for p in points]
    if starts != sorted(starts) or len(set(starts)) != len(starts):
        issues.append("timestamps are not strictly increasing")
    outside = [s for s in starts if not day_start <= s < day_end]
    if outside:
        issues.append(f"{len(outside)} intervals outside the local delivery day")

    expected = expected_intervals(delivery_date, resolution)
    if len(points) != expected:
        issues.append(f"expected {expected} intervals of {resolution} min, got {len(points)}")

    missing = sum(p.price_eur_mwh is None for p in points)
    if missing:
        issues.append(f"{missing} intervals without a price")

    out_of_bounds = [
        p.price_eur_mwh for p in points if p.price_eur_mwh is not None and not MIN_PRICE <= p.price_eur_mwh <= max_price
    ]
    if out_of_bounds:
        issues.append(f"{len(out_of_bounds)} prices outside [{MIN_PRICE}, {max_price}]")

    if issues and missing == len(points):
        return ValidationResult("not_published", tuple(issues))
    return ValidationResult("invalid" if issues else "ok", tuple(issues))
