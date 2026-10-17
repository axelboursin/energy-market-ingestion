import json
from datetime import date
from pathlib import Path

import pytest

from market_ingest.energy_charts import parse

FIXTURES = Path(__file__).parent / "fixtures"


def load_payload(zone: str, day: str) -> dict:
    """Real API responses captured from api.energy-charts.info (CC BY 4.0)."""
    return json.loads((FIXTURES / f"energy_charts_{zone}_{day}.json").read_text())


@pytest.fixture
def payload():
    return load_payload


@pytest.fixture
def points():
    def build(zone: str, day: str):
        return parse(load_payload(zone, day), zone)

    return build


@pytest.fixture
def fixture_fetch():
    """Drop-in replacement for energy_charts.fetch_day backed by the fixtures."""

    def fetch(zone: str, day: date):
        path = FIXTURES / f"energy_charts_{zone}_{day.isoformat()}.json"
        payload = (
            json.loads(path.read_text()) if path.exists() else {"unit": "EUR / MWh", "unix_seconds": [], "price": []}
        )
        return parse(payload, zone)

    return fetch
