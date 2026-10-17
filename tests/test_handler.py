import json
from datetime import UTC, date, datetime

import boto3
import pytest
from moto import mock_aws

from market_ingest import handler
from market_ingest.handler import IngestionError, Settings, delivery_dates, ingest

BUCKET = "market-data-test"


@pytest.fixture
def settings():
    return Settings(
        bucket=BUCKET, prefix="day_ahead_prices", bidding_zones=["FR"], max_price=4000, pause_between_calls_s=0
    )


@pytest.fixture
def s3():
    with mock_aws():
        client = boto3.client("s3", region_name="eu-west-3")
        client.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "eu-west-3"})
        yield client


def test_default_run_targets_tomorrow_in_market_time():
    # 23:30 UTC on Oct 14 is already Oct 15 in Paris: the next auction is for Oct 16.
    assert delivery_dates({}, datetime(2026, 10, 14, 23, 30, tzinfo=UTC)) == [date(2026, 10, 16)]


def test_backfill_range_is_inclusive_and_bounded():
    assert len(delivery_dates({"start": "2026-10-01", "end": "2026-10-07"}, datetime.now(UTC))) == 7
    with pytest.raises(ValueError):
        delivery_dates({"start": "2026-01-01", "end": "2026-03-01"}, datetime.now(UTC))


def test_ingest_writes_valid_days_and_is_idempotent(settings, s3, fixture_fetch, capsys):
    days = [date(2026, 10, 15)]
    first = ingest(settings, days, ["FR", "DE-LU"], s3, fetch=fixture_fetch)
    second = ingest(settings, days, ["FR", "DE-LU"], s3, fetch=fixture_fetch)

    assert [r["status"] for r in first] == ["ok", "ok"]
    assert first[0]["key"] == second[0]["key"]
    keys = [o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET)["Contents"]]
    assert sorted(keys) == [
        "day_ahead_prices/bidding_zone=DE-LU/delivery_date=2026-10-15/prices.parquet",
        "day_ahead_prices/bidding_zone=FR/delivery_date=2026-10-15/prices.parquet",
    ]

    emf = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith('{"_aws"')]
    assert emf[0]["BiddingZone"] == "FR" and emf[0]["IntervalsIngested"] == 96
    assert emf[0]["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "EnergyMarketIngestion"


def test_unpublished_day_writes_nothing(settings, s3, fixture_fetch):
    [result] = ingest(settings, [date(2030, 1, 1)], ["FR"], s3, fetch=fixture_fetch)
    assert result["status"] == "not_published"
    assert s3.list_objects_v2(Bucket=BUCKET)["KeyCount"] == 0


def test_handler_fails_the_run_on_invalid_data(monkeypatch, s3, points):
    monkeypatch.setenv("DATA_BUCKET", BUCKET)
    monkeypatch.setenv("PAUSE_BETWEEN_CALLS_S", "0")
    truncated = points("FR", "2026-10-15")[:50]
    monkeypatch.setattr(handler.energy_charts, "fetch_day", lambda zone, day: truncated)
    with pytest.raises(IngestionError, match="expected 96 intervals"):
        handler.lambda_handler({"delivery_date": "2026-10-15"}, None)


def test_handler_summary(monkeypatch, s3, fixture_fetch):
    monkeypatch.setenv("DATA_BUCKET", BUCKET)
    monkeypatch.setenv("BIDDING_ZONES", "FR,ES")
    monkeypatch.setenv("PAUSE_BETWEEN_CALLS_S", "0")
    monkeypatch.setattr(handler.energy_charts, "fetch_day", fixture_fetch)
    summary = handler.lambda_handler({"delivery_date": "2026-10-15"}, None)
    assert summary["ok"] == 2 and summary["failed"] == 0
