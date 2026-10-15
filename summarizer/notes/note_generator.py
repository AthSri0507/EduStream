"""INTERIM note generator (PLAN M3): window_summaries -> extractive notes -> final_notes.

Keeps the pipeline working until the Note Agent (M6) replaces it. Hardened per
docs/ARCHITECTURE.md §6.3 / §10: raw bytes + read_committed, explicit offset
commits, invalid input to the DLQ, keyed notes.v1 output, exit on produce failure.

Input: either the legacy Streams payload {video_id, window_start, window_end (seconds),
transcript} from the interim Streams app, or window.v1 once the M4 app lands.

    .venv\\Scripts\\python -m summarizer.notes.note_generator
"""

from __future__ import annotations

import json
import re
import sys
import time

from common import schemas
from common.config import GROUP_NOTES, TOPIC_NOTES, TOPIC_WINDOWS, load
from common.kafka_utils import (EXIT_PRODUCE_FAILED, ProduceFailed, commit_record, make_consumer, make_producer,
                                poll_one, send_and_wait, send_to_dlq)
from common.log import JsonLog

GROUP = GROUP_NOTES


# --------------------------------------------------
# Simple extractive summarizer (unchanged rule; also the M9 baseline)
# --------------------------------------------------

def generate_notes(transcript):

    # Split transcript into sentences
    sentences = re.split(
        r'(?<=[.!?])\s+',
        transcript
    )

    # Remove empty sentences
    sentences = [
        sentence.strip()
        for sentence in sentences
        if sentence.strip()
    ]

    notes = []

    for sentence in sentences:

        # Ignore extremely short sentences
        if len(sentence.split()) >= 5:
            notes.append(sentence)

    # Keep maximum 5 sentences
    return notes[:5]


def parse_window(raw: bytes) -> dict:
    """Return {video_id, window_start_ms, window_end_ms, revision, transcript, media_*}; raises ContractError."""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise schemas.ContractError(f"window: not UTF-8 JSON ({exc})") from None
    if isinstance(payload, dict) and payload.get("schema") == "window.v1":
        payload = schemas.validate("window.v1", payload)
        return {"video_id": payload["video_id"], "window_start": payload["window_start"],
                "window_end": payload["window_end"], "revision": payload["revision"],
                "transcript": payload["transcript"], "media_start": payload.get("media_start"),
                "media_end": payload.get("media_end")}
    required = ("video_id", "window_start", "window_end", "transcript")
    if not isinstance(payload, dict) or any(k not in payload for k in required):
        raise schemas.ContractError(f"legacy window payload needs {required}")
    # Legacy Streams app: window bounds in SECONDS since the epoch.
    return {"video_id": str(payload["video_id"]), "window_start": int(payload["window_start"]) * 1000,
            "window_end": int(payload["window_end"]) * 1000, "revision": 1,
            "transcript": str(payload["transcript"]), "media_start": None, "media_end": None}


def build_notes(window: dict) -> dict:
    started = time.perf_counter()
    notes = generate_notes(window["transcript"])
    payload = {
        "schema": "notes.v1", "video_id": window["video_id"], "window_start": window["window_start"],
        "window_end": window["window_end"], "revision": window["revision"],
        "summary": notes[0] if notes else "", "key_points": notes, "terms": [], "questions": [],
        "notes": notes, "generator": "extractive", "quality_flag": "interim", "model": None,
        "agent_ms": round((time.perf_counter() - started) * 1000, 2), "created_ts": int(time.time() * 1000),
    }
    for key in ("media_start", "media_end"):
        if window.get(key) is not None:
            payload[key] = window[key]
    return payload


def main() -> int:
    settings = load()
    log = JsonLog("note-generator")
    consumer = make_consumer(settings, GROUP, [TOPIC_WINDOWS], client_id="note-generator")
    producer = make_producer(settings, client_id="note-generator")
    log.info("started", group=GROUP)
    try:
        while True:
            record = poll_one(consumer)
            if record is None:
                continue
            try:
                window = parse_window(record.value)
            except schemas.ContractError as exc:
                send_to_dlq(producer, "note-agent", record, str(exc), log=log)
            else:
                notes = build_notes(window)
                send_and_wait(producer, TOPIC_NOTES, schemas.encode("notes.v1", notes), key=window["video_id"])
                log.info("notes", video_id=window["video_id"], window_start=window["window_start"],
                         key_points=len(notes["key_points"]))
            if not commit_record(consumer, record):
                log.warn("commit_failed_revoked", partition=record.partition, offset=record.offset)
    except ProduceFailed as exc:
        log.error("produce_failed_exiting", error=str(exc))
        producer.close(timeout=0)
        return EXIT_PRODUCE_FAILED
    except KeyboardInterrupt:
        return 0
    finally:
        consumer.close()


if __name__ == "__main__":
    sys.exit(main())
