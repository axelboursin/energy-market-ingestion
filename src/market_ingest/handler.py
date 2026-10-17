"""AWS Lambda entry point.

Events:
  {}                                          scheduled run: tomorrow's auction (D+1, market time)
  {"delivery_date": "2026-10-15"}             one day
  {"start": "2026-10-01", "end": "2026-10-07"} backfill, inclusive, max MAX_BACKFILL_DAYS
  optional "bidding_zones": ["FR", "DE-LU"]   overrides the BIDDING_ZONES env var

Each (zone, day) is fetched, validated and written independently. The run
fails (so Lambda retries, then routes the event to the DLQ) only if at least
one pair is invalid or errored; "not published yet" is reported but not an error
for the scheduled D+1 run, which runs again later the same afternoon.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from market_ingest import energy_charts, storage
from market_ingest.validation import MARKET_TZ, validate_day

log = logging.getLogger()
log.setLevel(os.getenv("LOG_LEVEL", "INFO"))

MAX_BACKFILL_DAYS = 31
METRIC_NAMESPACE = "EnergyMarketIngestion"


class IngestionError(RuntimeError):
    pass


@dataclass
class Settings:
    bucket: str
    prefix: str
    bidding_zones: list[str]
    max_price: float
    pause_between_calls_s: float

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            bucket=os.environ["DATA_BUCKET"],
            prefix=os.getenv("DATA_PREFIX", "day_ahead_prices"),
            bidding_zones=[z.strip() for z in os.getenv("BIDDING_ZONES", "FR").split(",") if z.strip()],
            max_price=float(os.getenv("MAX_PRICE_EUR_MWH", "4000")),
            pause_between_calls_s=float(os.getenv("PAUSE_BETWEEN_CALLS_S", "2")),
        )


def delivery_dates(event: dict[str, Any], now: datetime) -> list[date]:
    if "delivery_date" in event:
        return [date.fromisoformat(event["delivery_date"])]
    if "start" in event or "end" in event:
        start, end = date.fromisoformat(event["start"]), date.fromisoformat(event["end"])
        days = (end - start).days + 1
        if not 1 <= days <= MAX_BACKFILL_DAYS:
            raise ValueError(f"backfill must cover 1..{MAX_BACKFILL_DAYS} days, got {days}")
        return [start + timedelta(days=i) for i in range(days)]
    return [now.astimezone(MARKET_TZ).date() + timedelta(days=1)]


def emit_metrics(zone: str, status: str, points: int, avg_price: float | None) -> None:
    """CloudWatch Embedded Metric Format: metrics from a log line, no API call."""
    metrics = [{"Name": "IntervalsIngested", "Unit": "Count"}]
    record: dict[str, Any] = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [{"Namespace": METRIC_NAMESPACE, "Dimensions": [["BiddingZone"]], "Metrics": metrics}],
        },
        "BiddingZone": zone,
        "Status": status,
        "IntervalsIngested": points,
    }
    if avg_price is not None:
        metrics.append({"Name": "AveragePriceEurMwh", "Unit": "None"})
        record["AveragePriceEurMwh"] = round(avg_price, 2)
    print(json.dumps(record))  # noqa: T201 - EMF must go to stdout


def ingest(
    settings: Settings,
    dates: list[date],
    zones: list[str],
    s3_client: Any,
    fetch: Callable[[str, date], list[energy_charts.PricePoint]] | None = None,
) -> list[dict[str, Any]]:
    # Resolved at call time (not as a default argument) so it can be patched.
    fetch = fetch or energy_charts.fetch_day
    results = []
    for zone in zones:
        for day in dates:
            outcome: dict[str, Any] = {"bidding_zone": zone, "delivery_date": day.isoformat()}
            try:
                points = fetch(zone, day)
                check = validate_day(points, day, settings.max_price)
                outcome.update(status=check.status, issues=list(check.issues))
                if check.ok:
                    key, size = storage.write_day(s3_client, settings.bucket, settings.prefix, points, day)
                    prices = [p.price_eur_mwh for p in points if p.price_eur_mwh is not None]
                    outcome.update(key=key, bytes=size, intervals=len(points))
                    emit_metrics(zone, "ok", len(points), sum(prices) / len(prices))
                else:
                    emit_metrics(zone, check.status, 0, None)
            except energy_charts.SourceError as exc:
                outcome.update(status="error", issues=[str(exc)])
                emit_metrics(zone, "error", 0, None)
            results.append(outcome)
            log.info(json.dumps(outcome))
            time.sleep(settings.pause_between_calls_s)  # stay under the API rate limit
    return results


def lambda_handler(event: dict[str, Any] | None, context: Any) -> dict[str, Any]:
    import boto3  # provided by the Lambda runtime; imported lazily for tests

    event = event or {}
    settings = Settings.from_env()
    zones = event.get("bidding_zones") or settings.bidding_zones
    dates = delivery_dates(event, datetime.now(MARKET_TZ))

    results = ingest(settings, dates, zones, boto3.client("s3"))
    failed = [r for r in results if r["status"] in {"invalid", "error"}]
    summary = {
        "ok": sum(r["status"] == "ok" for r in results),
        "not_published": sum(r["status"] == "not_published" for r in results),
        "failed": len(failed),
        "results": results,
    }
    if failed:
        raise IngestionError(json.dumps({"failed": failed}))
    return summary
