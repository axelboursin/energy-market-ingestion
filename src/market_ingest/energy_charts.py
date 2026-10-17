"""Client for the Energy-Charts public API (Fraunhofer ISE), day-ahead prices.

Data: day-ahead auction results (SDAC) per bidding zone, EUR/MWh, licensed
CC BY 4.0. The API is rate limited: 429 responses are retried, honoring
Retry-After.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)

API_URL = "https://api.energy-charts.info/price"
SOURCE = "energy-charts.info"
EXPECTED_UNIT = "EUR / MWh"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class PricePoint:
    bidding_zone: str
    delivery_start: datetime  # UTC
    delivery_end: datetime  # UTC
    price_eur_mwh: float | None

    @property
    def resolution_minutes(self) -> int:
        return int((self.delivery_end - self.delivery_start).total_seconds() // 60)


class SourceError(RuntimeError):
    pass


def build_url(bidding_zone: str, delivery_date: date) -> str:
    # start/end are inclusive *local* delivery days for the zone.
    query = {"bzn": bidding_zone, "start": delivery_date.isoformat(), "end": delivery_date.isoformat()}
    return f"{API_URL}?{urlencode(query)}"


def fetch_json(url: str, retries: int = 5, backoff_s: float = 5.0, timeout_s: float = 30.0) -> dict:
    if not url.startswith("https://"):
        raise ValueError("only https URLs are allowed")
    headers = {"Accept": "application/json", "User-Agent": "energy-market-ingestion/0.1"}
    request = Request(url, headers=headers)  # noqa: S310 - scheme checked above
    for attempt in range(1, retries + 1):
        try:
            with urlopen(request, timeout=timeout_s) as response:  # noqa: S310 (fixed https host)
                return json.load(response)
        except HTTPError as exc:
            if exc.code not in RETRYABLE_STATUS or attempt == retries:
                raise SourceError(f"HTTP {exc.code} for {url}") from exc
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            wait = float(retry_after) if retry_after and retry_after.isdigit() else backoff_s * 2 ** (attempt - 1)
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            if attempt == retries:
                raise SourceError(f"{type(exc).__name__} for {url}: {exc}") from exc
            wait = backoff_s * 2 ** (attempt - 1)
        log.warning("attempt %d/%d failed for %s, retrying in %.0fs", attempt, retries, url, wait)
        time.sleep(wait)
    raise AssertionError("unreachable")


def parse(payload: dict, bidding_zone: str) -> list[PricePoint]:
    """Turn the API's parallel arrays into price points.

    The interval length is inferred from consecutive timestamps (60 min before
    the SDAC switch to 15-minute products on 2025-10-01, 15 min after).
    """
    if payload.get("unit") != EXPECTED_UNIT:
        raise SourceError(f"unexpected unit {payload.get('unit')!r}")
    seconds = payload.get("unix_seconds") or []
    prices = payload.get("price") or []
    if len(seconds) != len(prices):
        raise SourceError(f"{len(seconds)} timestamps but {len(prices)} prices")
    if not seconds:
        return []

    steps = {b - a for a, b in zip(seconds, seconds[1:], strict=False)}
    if len(seconds) > 1 and len(steps) != 1:
        raise SourceError(f"irregular interval lengths: {sorted(steps)}")
    step = timedelta(seconds=steps.pop() if steps else 3600)

    points = []
    for ts, price in zip(seconds, prices, strict=True):
        start = datetime.fromtimestamp(ts, UTC)
        points.append(PricePoint(bidding_zone, start, start + step, None if price is None else float(price)))
    return points


def fetch_day(bidding_zone: str, delivery_date: date) -> list[PricePoint]:
    return parse(fetch_json(build_url(bidding_zone, delivery_date)), bidding_zone)
