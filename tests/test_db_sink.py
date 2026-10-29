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
TABLES = ["lectures", "chunks", "window_stats", "notes", "alerts", "dlq", "notes_fts", "transcript_fts"]


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


# --------------------------------------------------------------------------------------------- D-2 (notebook, §11)
NOTEBOOK_TABLES = ["live_updates", "drafts", "course_info", "passes", "topics", "elements", "glossary",
                   "notebook_fts"]


def notebook_dump(conn) -> dict:
    return {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2, 3").fetchall() for t in NOTEBOOK_TABLES}


def notebook_records():
    """Two live updates (the second continues a paragraph of the first), then a pass that consolidates the first."""
    live = fixture("notes_v3/valid-llm.json")
    earlier = {**fixture("notes_v3/valid-extractive.json"), "update_index": 6, "media_start": 540.0,
               "media_end": 630.0}
    earlier["elements"] = [{**earlier["elements"][0], "id": "u6e0", "t": 600.0}]
    first_pass = {**fixture("consolidation/valid-fallback.json"), "media_end": 620.0}
    later_pass = {**fixture("consolidation/valid-llm.json"), "pass_index": 1, "media_start": 640.0}
    return [rec(TOPIC_NOTES, earlier, 10), rec(TOPIC_NOTES, live, 11), rec(TOPIC_NOTES, first_pass, 12),
            rec(TOPIC_NOTES, later_pass, 13),
            rec(TOPIC_NOTES, fixture("notes_v2/valid-llm.json"), 14),        # the retired rev 6 notebook: skipped
            rec(TOPIC_NOTES, fixture("notes/valid-llm.json"), 15)]           # an old notes.v1 record still works


def test_notebook_records_are_stored_once_and_replay_identically(conn):
    first = apply_batch(conn, notebook_records(), now=1_000, window_ms=WINDOW_MS)
    before = notebook_dump(conn)
    second = apply_batch(conn, notebook_records(), now=2_000, window_ms=WINDOW_MS)
    assert first == {"stored": 5, "skipped": 1} and second == {"duplicate": 5, "skipped": 1}
    assert notebook_dump(conn) == before
    assert conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 1        # the notes.v1 record


def test_notebook_tables_hold_what_was_sent(conn):
    apply_batch(conn, notebook_records()[:3], now=1_000, window_ms=WINDOW_MS)
    # drafts before a pass's cut (10:20) leave the search index: u6e0 and its continuation u7e0 are done
    assert {r[0] for r in conn.execute("SELECT ref FROM notebook_fts WHERE kind = 'draft'")} == {"u7e1"}
    apply_batch(conn, notebook_records()[3:], now=1_000, window_ms=WINDOW_MS)
    drafts = conn.execute("SELECT draft_id, extends, root_t FROM drafts ORDER BY update_index, seq").fetchall()
    assert drafts == [("u6e0", None, 600.0), ("u7e0", "u6e0", 600.0), ("u7e1", None, 630.0)]   # root of a continuation
    assert conn.execute("SELECT text FROM course_info").fetchall() == [("Problem set 0 is due on Thursday.",)]
    topics = conn.execute("SELECT topic_n, title, media_start, media_end, question IS NOT NULL FROM topics"
                          " ORDER BY 1").fetchall()
    assert topics == [(1, "Part 1", 0.0, 360.0, 0), (3, "Being a machine: following a recipe", 520.0, 750.0, 1)]
    # topic 2 of the later pass continues a topic that is not stored here: the update touches nothing
    assert conn.execute("SELECT topic_n, kind FROM elements ORDER BY pass_index, seq").fetchall() == [
        (1, "para"), (2, "para"), (2, "table"), (3, "steps"), (3, "code"), (3, "remember")]
    assert conn.execute("SELECT term, topic_n FROM glossary").fetchall() == [("Imperative knowledge", 2)]
    assert conn.execute("SELECT COUNT(*) FROM notebook_fts WHERE kind = 'draft'").fetchone()[0] == 0   # cut 12:30
    assert conn.execute("SELECT COUNT(*) FROM notebook_fts WHERE kind <> 'draft'").fetchone()[0] == 6
    assert conn.execute("SELECT COUNT(*) FROM notebook_fts WHERE notebook_fts MATCH 'recipe'").fetchone()[0] >= 1


def test_a_continued_topic_grows_and_a_later_definition_replaces_the_glossary_entry(conn):
    base = fixture("consolidation/valid-llm.json")
    first = {**base, "pass_index": 0, "media_start": 0.0, "media_end": 520.0, "final": False,
             "topics": [{**base["topics"][0], "new": True, "media_start": 0.0}],
             "elements": base["elements"][:2]}
    later = {**base, "glossary": [{**base["glossary"][0], "definition": "Imperative knowledge is a how-to.",
                                   "t": 600.0}],
             "topics": [{**base["topics"][0], "media_end": 640.0,
                         "question": {"q": "What is imperative knowledge?", "answer": "A recipe."}},
                        base["topics"][1]]}
    apply_batch(conn, [rec(TOPIC_NOTES, first, 0), rec(TOPIC_NOTES, later, 1)], now=1, window_ms=WINDOW_MS)
    assert conn.execute("SELECT topic_n, media_start, media_end, question FROM topics ORDER BY 1").fetchall() == [
        (2, 0.0, 640.0, "What is imperative knowledge?"), (3, 520.0, 750.0, base["topics"][1]["question"]["q"])]
    assert conn.execute("SELECT definition, pass_index FROM glossary").fetchall() == [
        ("Imperative knowledge is a how-to.", 1)]


def test_a_notebook_record_that_breaks_its_contract_goes_to_the_sink_dlq(conn):
    bad = fixture("notes_v3/invalid-model-field-leaks.json")
    worse = fixture("consolidation/invalid-element-without-topic.json")
    assert apply_batch(conn, [rec(TOPIC_NOTES, bad, 20), rec(TOPIC_NOTES, worse, 21)], now=1,
                       window_ms=WINDOW_MS) == {"invalid": 2}
    assert conn.execute("SELECT COUNT(*) FROM live_updates").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM passes").fetchone()[0] == 0


def test_a_long_lecture_digest_is_trimmed_evenly_so_every_topic_is_summarised(conn):
    from agents.lecture_tools import notebook_digest
    base = fixture("consolidation/valid-fallback.json")
    records = []
    for n in (1, 2, 3):                                            # 3 topics of 14 paragraphs each
        els = [{"topic": n, "kind": "para", "t": 1000.0 * n + i, "said": "", "lead": "", "terms": [],
                "background": None, "sentences": [f"Point {i} about topic {n}."]} for i in range(14)]
        records.append(rec(TOPIC_NOTES, {**base, "pass_index": n - 1, "media_start": 1000.0 * (n - 1),
                                         "media_end": 1000.0 * n, "elements": els,
                                         "topics": [{**base["topics"][0], "n": n, "title": f"Topic {n}"}]}, n))
    apply_batch(conn, records, now=1, window_ms=WINDOW_MS)
    lines = notebook_digest(conn, "python_l1", 0, 1e9, limit=24)
    headings = [ln["text"] for ln in lines if ln["text"].startswith("Section ")]
    assert headings == ["Section 1: Topic 1", "Section 2: Topic 2", "Section 3: Topic 3"] and len(lines) <= 24
    per_topic = [sum(1 for ln in lines if f"about topic {n}." in ln["text"]) for n in (1, 2, 3)]
    assert min(per_topic) == max(per_topic) == 7                   # an even share, not the first 21 paragraphs
    assert any(f"Point {i} about topic 1" in ln["text"] for i in (11, 12, 13) for ln in lines)


def test_transcripts_are_indexed_once_for_search(conn):
    apply_batch(conn, run_records(), now=1_000, window_ms=WINDOW_MS)
    apply_batch(conn, run_records(), now=2_000, window_ms=WINDOW_MS)          # replay: no second index row
    rows = conn.execute("SELECT chunk_id FROM transcript_fts ORDER BY chunk_id").fetchall()
    stored = conn.execute("SELECT chunk_id FROM chunks WHERE TRIM(text) <> '' ORDER BY chunk_id").fetchall()
    assert rows == stored and len(rows) >= 1


def test_additions_are_stored_once_and_a_removal_only_marks_them(conn):
    from common.config import TOPIC_USER_NOTES
    add, remove = fixture("addition/valid-add-table.json"), fixture("addition/valid-remove.json")
    beyond = fixture("addition/valid-add-beyond-the-lecture.json")
    beyond["addition_id"] = "1" * 32
    first = apply_batch(conn, [rec(TOPIC_USER_NOTES, add, 0), rec(TOPIC_USER_NOTES, beyond, 1)], now=1, window_ms=WINDOW_MS)
    again = apply_batch(conn, [rec(TOPIC_USER_NOTES, add, 0)], now=2, window_ms=WINDOW_MS)
    assert first == {"stored": 2} and again == {"duplicate": 1}
    rows = conn.execute("SELECT shape, span_start, span_end, topic_override, outside, removed FROM additions"
                        " ORDER BY addition_id").fetchall()
    assert rows == [("table", 540.0, 650.0, None, 1, 0), ("steps", None, None, 2, 1, 0)]
    assert apply_batch(conn, [rec(TOPIC_USER_NOTES, remove, 2)], now=3, window_ms=WINDOW_MS) == {"stored": 1}
    assert apply_batch(conn, [rec(TOPIC_USER_NOTES, remove, 2)], now=4, window_ms=WINDOW_MS) == {"duplicate": 1}
    assert conn.execute("SELECT removed FROM additions WHERE addition_id = ?", (add["addition_id"],)).fetchone() == (1,)
    bad = fixture("addition/invalid-unknown-shape.json")
    assert apply_batch(conn, [rec(TOPIC_USER_NOTES, bad, 3)], now=5, window_ms=WINDOW_MS) == {"invalid": 1}
