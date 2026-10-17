import io
from datetime import UTC, date, datetime
from email.message import Message
from urllib.error import HTTPError

import pytest

from market_ingest import energy_charts
from market_ingest.energy_charts import SourceError, build_url, parse


def test_url_uses_inclusive_local_day():
    assert build_url("DE-LU", date(2026, 10, 15)) == (
        "https://api.energy-charts.info/price?bzn=DE-LU&start=2026-10-15&end=2026-10-15"
    )


def test_parse_quarter_hour_day(points):
    day = points("FR", "2026-10-15")
    assert len(day) == 96
    assert day[0].delivery_start == datetime(2026, 10, 14, 22, 0, tzinfo=UTC)  # 00:00 Paris (CEST)
    assert day[0].resolution_minutes == 15
    assert all(p.bidding_zone == "FR" for p in day)


def test_parse_hourly_day_before_15min_products(points):
    day = points("FR", "2025-06-15")
    assert len(day) == 24
    assert {p.resolution_minutes for p in day} == {60}
    assert min(p.price_eur_mwh for p in day) < 0  # negative prices are real and valid


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"unit": "EUR / kWh", "unix_seconds": [], "price": []}, "unexpected unit"),
        ({"unit": "EUR / MWh", "unix_seconds": [0, 900], "price": [1.0]}, "2 timestamps but 1 prices"),
        ({"unit": "EUR / MWh", "unix_seconds": [0, 900, 3600], "price": [1.0, 2.0, 3.0]}, "irregular"),
    ],
)
def test_parse_rejects_malformed_payloads(payload, message):
    with pytest.raises(SourceError, match=message):
        parse(payload, "FR")


def test_parse_empty_day_returns_nothing():
    assert parse({"unit": "EUR / MWh", "unix_seconds": [], "price": []}, "FR") == []


def http_error(code, retry_after=None):
    headers = Message()
    if retry_after:
        headers["Retry-After"] = retry_after
    return HTTPError("https://api.energy-charts.info/price", code, "error", headers, io.BytesIO())


def test_rate_limit_is_retried_with_retry_after(monkeypatch):
    calls, sleeps = [], []

    def fake_urlopen(request, timeout):
        calls.append(1)
        if len(calls) == 1:
            raise http_error(429, retry_after="7")
        return io.BytesIO(b'{"ok": true}')

    monkeypatch.setattr(energy_charts, "urlopen", fake_urlopen)
    monkeypatch.setattr(energy_charts.time, "sleep", sleeps.append)
    assert energy_charts.fetch_json("https://x") == {"ok": True}
    assert sleeps == [7.0]


def test_client_errors_are_not_retried(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(1)
        raise http_error(404)

    monkeypatch.setattr(energy_charts, "urlopen", fake_urlopen)
    with pytest.raises(SourceError, match="HTTP 404"):
        energy_charts.fetch_json("https://x")
    assert len(calls) == 1


def test_gives_up_after_retries(monkeypatch):
    monkeypatch.setattr(energy_charts, "urlopen", lambda request, timeout: (_ for _ in ()).throw(http_error(503)))
    monkeypatch.setattr(energy_charts.time, "sleep", lambda s: None)
    with pytest.raises(SourceError, match="HTTP 503"):
        energy_charts.fetch_json("https://x", retries=3)
