"""Backfill a date range by invoking the deployed Lambda in 31-day chunks.

uv run python scripts/backfill.py --function market-ingest-prod --start 2025-01-01 --end 2025-12-31
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta

import boto3

CHUNK_DAYS = 31


def chunks(start: date, end: date, size: int = CHUNK_DAYS):
    while start <= end:
        stop = min(start + timedelta(days=size - 1), end)
        yield start, stop
        start = stop + timedelta(days=1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--function", required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--zones", help="comma-separated, defaults to the function's BIDDING_ZONES")
    args = parser.parse_args()

    client = boto3.client("lambda")
    for start, stop in chunks(args.start, args.end):
        event = {"start": start.isoformat(), "end": stop.isoformat()}
        if args.zones:
            event["bidding_zones"] = args.zones.split(",")
        response = client.invoke(FunctionName=args.function, Payload=json.dumps(event).encode())
        payload = json.loads(response["Payload"].read())
        status = "FAILED" if "FunctionError" in response else "ok"
        print(f"{start}..{stop}: {status} {json.dumps(payload)[:300]}")  # noqa: T201


if __name__ == "__main__":
    main()
