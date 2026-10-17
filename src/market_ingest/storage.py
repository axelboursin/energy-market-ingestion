"""Parquet serialization and S3 layout.

One object per (bidding zone, delivery day) at a deterministic key: re-running
an ingestion overwrites the same object, so runs are idempotent and late
corrections from the source simply replace the previous file.
"""

from __future__ import annotations

import io
from datetime import UTC, date, datetime
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from market_ingest.energy_charts import SOURCE, PricePoint

SCHEMA = pa.schema(
    [
        pa.field("delivery_start", pa.timestamp("ms", tz="UTC"), nullable=False),
        pa.field("delivery_end", pa.timestamp("ms", tz="UTC"), nullable=False),
        pa.field("resolution_minutes", pa.int16(), nullable=False),
        pa.field("price_eur_mwh", pa.float64(), nullable=False),
        pa.field("source", pa.string(), nullable=False),
        pa.field("ingested_at", pa.timestamp("ms", tz="UTC"), nullable=False),
    ],
    metadata={"license": "CC BY 4.0, Energy-Charts / Bundesnetzagentur | SMARD.de", "unit": "EUR/MWh"},
)


def object_key(prefix: str, bidding_zone: str, delivery_date: date) -> str:
    # Hive-style partitions, matching the Glue table's partition projection.
    return f"{prefix}/bidding_zone={bidding_zone}/delivery_date={delivery_date.isoformat()}/prices.parquet"


def to_parquet(points: list[PricePoint], ingested_at: datetime | None = None) -> bytes:
    ingested_at = ingested_at or datetime.now(UTC)
    table = pa.Table.from_pydict(
        {
            "delivery_start": [p.delivery_start for p in points],
            "delivery_end": [p.delivery_end for p in points],
            "resolution_minutes": [p.resolution_minutes for p in points],
            "price_eur_mwh": [p.price_eur_mwh for p in points],
            "source": [SOURCE] * len(points),
            "ingested_at": [ingested_at] * len(points),
        },
        schema=SCHEMA,
    )
    buffer = io.BytesIO()
    pq.write_table(table, buffer, compression="zstd")
    return buffer.getvalue()


def write_day(
    s3_client: Any, bucket: str, prefix: str, points: list[PricePoint], delivery_date: date
) -> tuple[str, int]:
    key = object_key(prefix, points[0].bidding_zone, delivery_date)
    body = to_parquet(points)
    s3_client.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/vnd.apache.parquet")
    return key, len(body)
