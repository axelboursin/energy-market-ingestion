"""Replay failed ingestion events from the DLQ once the cause is fixed.

Messages come from two places: Lambda's on-failure destination (the original
event is under "requestPayload") and the scheduler's dead-letter config (the
body is the event itself).

    uv run python scripts/replay_dlq.py --queue-url <dlq_url> --function market-ingest-prod [--dry-run]
"""

from __future__ import annotations

import argparse
import json

import boto3


def original_event(body: str) -> dict:
    message = json.loads(body)
    return message.get("requestPayload", message) if isinstance(message, dict) else {}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue-url", required=True)
    parser.add_argument("--function", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    sqs, lambda_client = boto3.client("sqs"), boto3.client("lambda")
    replayed = 0
    while True:
        batch = sqs.receive_message(QueueUrl=args.queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=2)
        messages = batch.get("Messages", [])
        if not messages:
            break
        for message in messages:
            event = original_event(message["Body"])
            print(f"replay {json.dumps(event)}")  # noqa: T201
            if args.dry_run:
                continue
            response = lambda_client.invoke(FunctionName=args.function, Payload=json.dumps(event).encode())
            if "FunctionError" in response:
                print(f"  still failing: {response['Payload'].read()[:300]!r}")  # noqa: T201
                continue
            sqs.delete_message(QueueUrl=args.queue_url, ReceiptHandle=message["ReceiptHandle"])
            replayed += 1
        if args.dry_run:
            break
    print(f"{replayed} event(s) replayed")  # noqa: T201


if __name__ == "__main__":
    main()
