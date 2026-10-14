import json
from pathlib import Path

import pytest

from common import schemas
from summarizer.notes.note_generator import build_notes, generate_notes, parse_window

FIXTURE = Path(__file__).resolve().parents[1] / "schemas" / "examples" / "window" / "valid.json"


def test_extractive_rule_unchanged():
    text = "Hi. This sentence has more than five words. Short one. Another long sentence is right here."
    assert generate_notes(text) == ["This sentence has more than five words.", "Another long sentence is right here."]


def test_legacy_payload_seconds_become_ms():
    raw = json.dumps({"video_id": "python_l1", "window_start": 1792051260, "window_end": 1792051290,
                      "transcript": "This sentence has more than five words."}).encode()
    window = parse_window(raw)
    assert window["window_start"] == 1_792_051_260_000 and window["revision"] == 1
    schemas.validate("notes.v1", build_notes(window))


def test_window_v1_payload_is_accepted():
    window = parse_window(FIXTURE.read_bytes())
    notes = build_notes(window)
    schemas.validate("notes.v1", notes)
    assert notes["media_start"] == 60.0 and notes["generator"] == "extractive"


def test_bad_payloads_raise_contract_error():
    for raw in (b"nope", json.dumps({"video_id": "x"}).encode(), None):
        with pytest.raises(schemas.ContractError):
            parse_window(raw)
