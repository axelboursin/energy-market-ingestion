import importlib.util
import json
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backfill_chunks_cover_range_without_overlap():
    chunks = list(load("backfill").chunks(date(2026, 1, 1), date(2026, 3, 5)))
    assert chunks[0] == (date(2026, 1, 1), date(2026, 1, 31))
    assert chunks[-1][1] == date(2026, 3, 5)
    assert all(b[0] == a[1].fromordinal(a[1].toordinal() + 1) for a, b in zip(chunks, chunks[1:], strict=False))


def test_replay_extracts_event_from_both_dlq_formats():
    replay = load("replay_dlq")
    lambda_destination = json.dumps({"requestPayload": {"delivery_date": "2026-10-15"}, "responsePayload": {}})
    assert replay.original_event(lambda_destination) == {"delivery_date": "2026-10-15"}
    assert replay.original_event("{}") == {}
