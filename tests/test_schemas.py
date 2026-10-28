"""C-1 (Python side): every golden fixture validates exactly as its file name says."""

import json
from pathlib import Path

import pytest

from common import schemas

EXAMPLES = Path(__file__).resolve().parents[1] / "schemas" / "examples"
SCHEMA_OF_FOLDER = {"audio_chunk": "audio_chunk.v1", "transcript": "transcript.v1", "window": "window.v1",
                    "notes": "notes.v1", "notes_v2": "notes.v2", "lecture_notes": "lecture_notes.v1", "alert": "alert.v1", "dlq": "dlq.v1"}
FIXTURES = sorted(EXAMPLES.glob("*/*.json"))


def test_every_schema_has_valid_and_invalid_fixtures():
    for folder in SCHEMA_OF_FOLDER:
        names = [p.name for p in (EXAMPLES / folder).glob("*.json")]
        assert any(n.startswith("valid") for n in names), folder
        assert any(n.startswith("invalid") for n in names), folder


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_fixture(path):
    name = SCHEMA_OF_FOLDER[path.parent.name]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if path.stem.startswith("valid"):
        schemas.validate(name, payload)
        assert schemas.decode(schemas.encode(name, payload), name) == payload   # bytes round trip
    else:
        with pytest.raises(schemas.ContractError):
            schemas.validate(name, payload)


def test_decode_rejects_non_json_and_non_objects():
    for raw in (b"not json {", b"\xff\xfe", b"[1, 2]", None):
        with pytest.raises(schemas.ContractError):
            schemas.decode(raw, "audio_chunk.v1")
