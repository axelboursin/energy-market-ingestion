import io
from datetime import UTC, date, datetime

import pyarrow.parquet as pq

from market_ingest.storage import SCHEMA, object_key, to_parquet


def test_object_key_is_deterministic_and_partitioned():
    assert object_key("day_ahead_prices", "DE-LU", date(2026, 10, 15)) == (
        "day_ahead_prices/bidding_zone=DE-LU/delivery_date=2026-10-15/prices.parquet"
    )


def test_parquet_roundtrip(points):
    day = points("FR", "2026-10-15")
    ingested = datetime(2026, 10, 14, 13, 0, tzinfo=UTC)
    table = pq.read_table(io.BytesIO(to_parquet(day, ingested)))
    assert table.schema.equals(SCHEMA, check_metadata=False)
    assert table.num_rows == 96
    assert table.column("price_eur_mwh").to_pylist()[0] == day[0].price_eur_mwh
    assert table.column("delivery_start").to_pylist()[0] == day[0].delivery_start
    assert set(table.column("resolution_minutes").to_pylist()) == {15}
    assert table.schema.metadata[b"unit"] == b"EUR/MWh"
