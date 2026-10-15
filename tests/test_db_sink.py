"""D-1: sink idempotency (ARCHITECTURE §9, §10), on an in-memory SQLite database. No Kafka needed."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from common.config import TOPIC_ALERTS, TOPIC_DLQ, TOPIC_NOTES, TOPIC_TRANSCRIPTS, TOPIC_WINDOWS
from storage.db import connect_writer
from storage.db_sink import apply_batch

EXAMPLES = Path(__file__).resolve().parents[1] / "schemas" / "examples"
WINDOW_MS = 30_000
TABLES = ["lectures", "chunks", "window_stats", "notes", "alerts", "dlq", "notes_fts"]


def fixture(path: str) -> dict:
    return json.loads((EXAMPLES / path).read_text(encoding="utf-8"))


def rec(topic: str, payload, offset: int, partition: int = 0):
    value = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return SimpleNamespace(topic=topic, value=value, partition=partition, offset=offset, key=b"python_l1")


def dump(conn) -> dict:
    return {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2, 3").fetchall() for t in TABLES}


def notes(revision: int, summary: str) -> dict:
    n = copy.deepcopy(fixture("notes/valid-llm.json"))
    n["revision"], n["summary"] = revision, summary
    return n


@pytest.fixture
def conn():
    c = connect_writer(":memory:")
    yield c
    c.close()


def run_records():
    chunk = fixture("transcript/valid-chunk.json")
    chunk_first = {**chunk, "chunk_id": 0, "start_time": 0.0, "end_time": 10.0, "src_offset": 0,
                   "event_ts": chunk["session_start"], "title": "Python · Lecture 1 (Bell)"}
    alert = fixture("alert/valid-low-asr-score.json")
    return [
        rec(TOPIC_TRANSCRIPTS, chunk_first, 0),
        rec(TOPIC_TRANSCRIPTS, chunk, 1),
        rec(TOPIC_TRANSCRIPTS, fixture("transcript/valid-chunk-no-speech.json"), 2),
        rec(TOPIC_TRANSCRIPTS, fixture("transcript/valid-flush.json"), 3),
        rec(TOPIC_WINDOWS, fixture("window/valid.json"), 0),
        rec(TOPIC_NOTES, fixture("notes/valid-llm.json"), 0),
        rec(TOPIC_ALERTS, {**alert, "value": 0.50}, 0),
        rec(TOPIC_ALERTS, {**alert, "value": 0.58}, 1),             # same alert_id: duplicate, larger value
        rec(TOPIC_DLQ, fixture("dlq/valid.json"), 0),
        rec(TOPIC_WINDOWS, b"not json {", 1),                       # fails the contract at the sink
    ]


def test_replaying_everything_twice_gives_identical_tables(conn):
    first = apply_batch(conn, run_records(), now=1_000, window_ms=WINDOW_MS)
    before = dump(conn)
    second = apply_batch(conn, run_records(), now=2_000, window_ms=WINDOW_MS)   # different sink time
    assert dump(conn) == before                                  # nothing rewritten, not even sink_ts
    assert first["invalid"] == 1 and second.get("invalid", 0) == 0
    assert second.get("stored", 0) == 3                           # flush + 2 alerts upserts are no-ops


def test_tables_hold_what_was_sent(conn):
    apply_batch(conn, run_records(), now=1_000, window_ms=WINDOW_MS)
    lecture = conn.execute("SELECT title, src_partition, last_chunk_id, flushed_ts FROM lectures").fetchone()
    assert lecture[0] == "Python · Lecture 1 (Bell)" and lecture[1] == 0 and lecture[2] == 258
    assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 3
    assert conn.execute("SELECT window_index FROM window_stats").fetchone()[0] == 2     # (S+60 s - S) / 30 s
    assert conn.execute("SELECT window_index FROM notes").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*), MAX(value) FROM alerts").fetchone() == (1, 0.58)
    stages = sorted(r[0] for r in conn.execute("SELECT stage FROM dlq"))
    assert stages == ["sink", "worker"]                          # DLQ path 2 (sink) + path 1 (worker)


def test_old_revision_arriving_late_changes_nothing(conn):
    apply_batch(conn, [rec(TOPIC_NOTES, notes(2, "revised summary"), 0),
                       rec(TOPIC_NOTES, notes(1, "first summary"), 1)], now=1_000, window_ms=WINDOW_MS)
    latest = conn.execute("SELECT revision, summary FROM notes_latest").fetchall()
    assert latest == [(2, "revised summary")]
    fts = conn.execute("SELECT revision, body FROM notes_fts").fetchall()
    assert len(fts) == 1 and fts[0][0] == 2 and fts[0][1].startswith("revised summary")


def test_duplicate_of_latest_revision_with_different_text_changes_nothing(conn):
    apply_batch(conn, [rec(TOPIC_NOTES, notes(2, "revised summary"), 0)], now=1_000, window_ms=WINDOW_MS)
    before = dump(conn)
    apply_batch(conn, [rec(TOPIC_NOTES, notes(2, "LLM re-generated different text"), 1)],
                now=2_000, window_ms=WINDOW_MS)
    assert dump(conn) == before


def test_index_holds_only_the_latest_revision(conn):
    apply_batch(conn, [rec(TOPIC_NOTES, notes(1, "first summary"), 0)], now=1_000, window_ms=WINDOW_MS)
    apply_batch(conn, [rec(TOPIC_NOTES, notes(2, "revised summary"), 1)], now=2_000, window_ms=WINDOW_MS)
    assert conn.execute("SELECT revision FROM notes_fts").fetchall() == [(2,)]
    hits = conn.execute("SELECT revision FROM notes_fts WHERE notes_fts MATCH 'revised'").fetchall()
    assert hits == [(2,)]
    assert conn.execute("SELECT COUNT(*) FROM notes_fts WHERE notes_fts MATCH 'first'").fetchone()[0] == 0


def test_a_failing_batch_is_rolled_back_completely(conn):
    good = rec(TOPIC_TRANSCRIPTS, fixture("transcript/valid-chunk.json"), 0)
    bad = SimpleNamespace(topic="unknown_topic", value=b"{}", partition=0, offset=1, key=None)
    with pytest.raises(KeyError):
        apply_batch(conn, [good, bad], now=1_000, window_ms=WINDOW_MS)
    assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0   # offsets would not be committed either


# --------------------------------------------------------------------------------------------- D-2 (rev 6)
NOTEBOOK_TABLES = ["notebook_updates", "sections", "points", "terms", "notebook_fts"]


def notebook_dump(conn) -> dict:
    return {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2, 3").fetchall() for t in NOTEBOOK_TABLES}


def notebook_records():
    llm_update = fixture("notes_v2/valid-llm.json")
    first = {**fixture("notes_v2/valid-extractive.json")}
    other_title = {**llm_update, "update_index": 5, "section": {**llm_update["section"], "title": "Renamed?"},
                   "terms": [{**llm_update["terms"][0], "definition": "A second, different definition."}],
                   "points": [{**llm_update["points"][1], "section_id": 2}]}
    return [rec(TOPIC_NOTES, first, 10), rec(TOPIC_NOTES, llm_update, 11), rec(TOPIC_NOTES, other_title, 12),
            rec(TOPIC_NOTES, fixture("notes/valid-llm.json"), 13)]          # an old notes.v1 record still works


def test_notebook_updates_are_stored_once_and_replay_identically(conn):
    first = apply_batch(conn, notebook_records(), now=1_000, window_ms=WINDOW_MS)
    before = notebook_dump(conn)
    second = apply_batch(conn, notebook_records(), now=2_000, window_ms=WINDOW_MS)
    assert first == {"stored": 4} and second == {"duplicate": 4}
    assert notebook_dump(conn) == before
    assert conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 1        # the notes.v1 record


def test_notebook_tables_hold_what_was_sent(conn):
    apply_batch(conn, notebook_records(), now=1_000, window_ms=WINDOW_MS)
    assert conn.execute("SELECT section_id, title FROM sections ORDER BY 1").fetchall() == [
        (1, "Part 1"), (2, "What does a computer do?")]                          # first title wins
    assert conn.execute("SELECT COUNT(*) FROM points").fetchone()[0] == 4
    assert conn.execute("SELECT section_id FROM points WHERE update_index = 4 ORDER BY seq").fetchall() == [(1,), (2,)]
    assert conn.execute("SELECT definition, source FROM terms").fetchall() == [
        ("Where a computer stores the results of its calculations.", "lecture")]  # first definition wins
    # index: 4 points + 1 term + 2 new sections
    assert conn.execute("SELECT COUNT(*) FROM notebook_fts").fetchone()[0] == 7
    assert conn.execute("SELECT COUNT(*) FROM notebook_fts WHERE notebook_fts MATCH 'calculations'").fetchone()[0] >= 2


def test_a_notebook_update_with_a_broken_point_goes_to_the_sink_dlq(conn):
    bad = fixture("notes_v2/invalid-point-without-quote.json")
    assert apply_batch(conn, [rec(TOPIC_NOTES, bad, 20)], now=1, window_ms=WINDOW_MS) == {"invalid": 1}
    assert conn.execute("SELECT COUNT(*) FROM notebook_updates").fetchone()[0] == 0
