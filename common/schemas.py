"""The message contract (ARCHITECTURE §5): JSON Schemas in schemas/*.schema.json.

encode() validates before producing (a bug fails fast at the source);
decode() parses raw Kafka bytes and validates on consumption (invalid input
goes to the DLQ). Both raise ContractError, never anything else.
"""

from __future__ import annotations

import json
from functools import lru_cache

from jsonschema import Draft202012Validator

from common.config import ROOT

SCHEMA_DIR = ROOT / "schemas"
NAMES = ("audio_chunk.v1", "transcript.v1", "window.v1", "notes.v1", "notes.v2", "lecture_notes.v1", "notes.v3",
         "consolidation.v1", "addition.v1", "alert.v1", "dlq.v1")


class ContractError(ValueError):
    """A payload is not valid JSON or does not match its schema."""


@lru_cache(maxsize=None)
def validator(name: str) -> Draft202012Validator:
    if name not in NAMES:
        raise KeyError(f"unknown schema {name!r}")
    schema = json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate(name: str, payload: dict) -> dict:
    errors = sorted(validator(name).iter_errors(payload), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        where = "/".join(str(p) for p in first.absolute_path) or "(root)"
        raise ContractError(f"{name} invalid at {where}: {first.message}")
    return payload


def encode(name: str, payload: dict) -> bytes:
    """Validate and serialise to UTF-8 JSON bytes (kafka-python 3.x: send bytes, no serializer callables)."""
    return json.dumps(validate(name, payload), separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def decode(raw: bytes | None, name: str) -> dict:
    if raw is None:
        raise ContractError(f"{name}: empty record value")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{name}: not UTF-8 JSON ({type(exc).__name__}: {exc})") from None
    if not isinstance(payload, dict):
        raise ContractError(f"{name}: top level must be an object")
    return validate(name, payload)
