"""db-sink: the only SQLite writer (docs/ARCHITECTURE.md §9, A10).

Consumes transcriptions, window_summaries, final_notes, alerts and dlq (group db-sink,
read_committed, raw bytes). For each poll batch:
  1. BEGIN; apply every record (first writer wins; see storage/schema.sql); COMMIT
  2. commit Kafka offsets explicitly: offset + 1 of the last record per partition
So a crash between 1 and 2 replays the batch, and the replay changes nothing (test D-1).

A record that fails its JSON Schema here goes straight to the SQLite dlq table with
stage='sink' (DLQ path 2); the sink never produces to Kafka dlq, so no loop is possible.
The same process runs the lag thread (storage/lag_monitor.py), which raises CONSUMER_LAG.

    .venv\\Scripts\\python -m storage.db_sink
"""

from __future__ import annotations

import json
import sqlite3
import sys
import threading
import time

from kafka import TopicPartition
from kafka.errors import CommitFailedError
from kafka.structs import OffsetAndMetadata

from common import schemas
from common.config import (TOPIC_ALERTS, TOPIC_DLQ, TOPIC_NOTES, TOPIC_TRANSCRIPTS, TOPIC_WINDOWS, load)
from common.kafka_utils import EXIT_PRODUCE_FAILED, make_consumer, raw_preview
from common.log import JsonLog
from storage.db import connect_writer

GROUP = "db-sink"
TOPICS = [TOPIC_TRANSCRIPTS, TOPIC_WINDOWS, TOPIC_NOTES, TOPIC_ALERTS, TOPIC_DLQ]
SCHEMA_OF = {TOPIC_TRANSCRIPTS: "transcript.v1", TOPIC_WINDOWS: "window.v1", TOPIC_NOTES: "notes.v1",
             TOPIC_ALERTS: "alert.v1", TOPIC_DLQ: "dlq.v1"}
SQLITE_RETRIES = 5
EXIT_SQLITE_FAILED = 4


# --------------------------------------------------
# Applying one record (pure: a connection, a record; no Kafka). Tested by tests/test_db_sink.py
# --------------------------------------------------

def _window_index(conn: sqlite3.Connection, video_id: str, window_start: int, window_ms: int,
                  session_start: int | None) -> int | None:
    if session_start is None:
        row = conn.execute("SELECT session_start FROM lectures WHERE video_id = ?", (video_id,)).fetchone()
        session_start = row[0] if row else None
    return None if session_start is None else (window_start - session_start) // window_ms


def _notes_body(n: dict) -> str:
    terms = [f"{t['term']}: {t['definition']}" for t in n.get("terms", [])]
    return "\n".join([n["summary"], *n["key_points"], *terms, *n.get("questions", [])]).strip()


def apply_record(conn: sqlite3.Connection, topic: str, value: bytes | None, partition: int, offset: int,
                 key: bytes | None, now: int, window_ms: int) -> str:
    """Store one record. Returns what happened: 'stored', 'duplicate' or 'invalid'."""
    try:
        p = schemas.decode(value, SCHEMA_OF[topic])
    except schemas.ContractError as exc:
        cur = conn.execute(
            "INSERT INTO dlq(stage, source_topic, src_partition, src_offset, key, error, raw_value, failed_ts, sink_ts)"
            " VALUES ('sink', ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            (topic, partition, offset, key.decode("utf-8", "replace") if key else None, str(exc)[:1000],
             raw_preview(value), now, now))
        return "invalid" if cur.rowcount == 1 else "duplicate"

    if topic == TOPIC_TRANSCRIPTS:
        if p["type"] == "flush":
            conn.execute(
                "INSERT INTO lectures(video_id, session_start, last_chunk_id, flushed_ts) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(video_id) DO UPDATE SET"
                "  session_start = COALESCE(lectures.session_start, excluded.session_start),"
                "  last_chunk_id = COALESCE(lectures.last_chunk_id, excluded.last_chunk_id),"
                "  flushed_ts = COALESCE(lectures.flushed_ts, excluded.flushed_ts)",
                (p["video_id"], p["session_start"], p["last_chunk_id"], p["event_ts"]))
            return "stored"
        conn.execute(
            "INSERT INTO lectures(video_id, title, src_partition, session_start, first_event_ts, last_seen_ts)"
            " VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(video_id) DO UPDATE SET"
            "  title = COALESCE(lectures.title, excluded.title),"
            "  src_partition = COALESCE(lectures.src_partition, excluded.src_partition),"
            "  session_start = COALESCE(lectures.session_start, excluded.session_start),"
            "  first_event_ts = MIN(COALESCE(lectures.first_event_ts, excluded.first_event_ts), excluded.first_event_ts),"
            "  last_seen_ts = MAX(COALESCE(lectures.last_seen_ts, excluded.last_seen_ts), excluded.last_seen_ts)",
            (p["video_id"], p.get("title"), p["src_partition"], p["session_start"], p["event_ts"], p["event_ts"]))
        cur = conn.execute(
            "INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
            (p["video_id"], p["chunk_id"], p["model"], p["start_time"], p["end_time"], p["text"], p["asr_score"],
             p.get("avg_logprob"), p.get("no_speech_prob"), p.get("compression_ratio"),
             int(bool(p.get("retried", False))), p.get("worker_id"), p["src_partition"], p["src_offset"],
             p["event_ts"], p.get("transcribed_ts"), p.get("proc_ms"), now))
        return "stored" if cur.rowcount == 1 else "duplicate"

    if topic == TOPIC_WINDOWS:
        s = p["stats"]
        cur = conn.execute(
            "INSERT INTO window_stats VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
            (p["video_id"], p["window_start"], p["revision"],
             _window_index(conn, p["video_id"], p["window_start"], window_ms, p.get("session_start")),
             p["window_end"], p.get("media_start"), p.get("media_end"), s["chunk_count"], s["covered_s"],
             s["word_count"], s["words_per_min"], s.get("score_avg"), s.get("score_min"), s.get("score_max"),
             s.get("no_speech_avg"), s.get("compression_ratio_max"), json.dumps(s.get("top_terms", [])),
             json.dumps(p["chunk_ids"]), p["transcript"], p.get("emitted_ts"), now))
        return "stored" if cur.rowcount == 1 else "duplicate"

    if topic == TOPIC_NOTES:
        cur = conn.execute(
            "INSERT INTO notes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
            (p["video_id"], p["window_start"], p["revision"],
             _window_index(conn, p["video_id"], p["window_start"], window_ms, None), p["window_end"],
             p.get("media_start"), p.get("media_end"), p["summary"], json.dumps(p["key_points"]),
             json.dumps(p.get("terms", [])), json.dumps(p.get("questions", [])), p["generator"],
             p.get("quality_flag"), p.get("model"), p.get("agent_ms"), p.get("created_ts"), now))
        if cur.rowcount != 1:
            return "duplicate"
        latest = conn.execute("SELECT MAX(revision) FROM notes WHERE video_id = ? AND window_start = ?",
                              (p["video_id"], p["window_start"])).fetchone()[0]
        if p["revision"] == latest:   # an older revision arriving late never touches the index
            conn.execute("DELETE FROM notes_fts WHERE video_id = ? AND window_start = ?",
                         (p["video_id"], p["window_start"]))
            conn.execute("INSERT INTO notes_fts(video_id, window_start, revision, body) VALUES (?, ?, ?, ?)",
                         (p["video_id"], p["window_start"], p["revision"], _notes_body(p)))
        return "stored"

    if topic == TOPIC_ALERTS:
        cur = conn.execute(
            "INSERT INTO alerts VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(alert_id) DO UPDATE SET"
            "  value = CASE WHEN excluded.value IS NULL THEN alerts.value WHEN alerts.value IS NULL THEN excluded.value"
            "               ELSE MAX(alerts.value, excluded.value) END",
            (p["alert_id"], p["type"], p["severity"], p.get("video_id"), p.get("window_start"), p.get("revision"),
             p.get("value"), p.get("threshold"), json.dumps(p.get("details", {})), p.get("source"),
             p["created_ts"], now))
        return "stored"

    # TOPIC_DLQ: poison found by another stage (DLQ path 1)
    cur = conn.execute(
        "INSERT INTO dlq(stage, source_topic, src_partition, src_offset, key, error, raw_value, failed_ts, sink_ts)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
        (p["stage"], p["source_topic"], p["src_partition"], p["src_offset"], p.get("key"), p["error"],
         p.get("raw_value", ""), p["failed_ts"], now))
    return "stored" if cur.rowcount == 1 else "duplicate"


def apply_batch(conn: sqlite3.Connection, records, now: int, window_ms: int) -> dict:
    """Apply records in ONE transaction; returns counts per outcome. Raises on SQLite errors (rolled back)."""
    outcomes: dict[str, int] = {}
    conn.execute("BEGIN IMMEDIATE")
    try:
        for r in records:
            outcome = apply_record(conn, r.topic, r.value, r.partition, r.offset, r.key, now, window_ms)
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return outcomes


# --------------------------------------------------
# Main loop
# --------------------------------------------------

def main() -> int:
    from storage.lag_monitor import LagMonitorThread

    settings = load()
    log = JsonLog("db-sink")
    window_ms = settings.window_seconds * 1000
    conn = connect_writer()
    consumer = make_consumer(settings, GROUP, TOPICS, client_id="db-sink", max_poll_records=500)
    stop = threading.Event()
    lag_thread = LagMonitorThread(settings, stop, log)
    lag_thread.start()
    log.info("started", group=GROUP, topics=TOPICS)
    try:
        while not stop.is_set():
            batches = consumer.poll(timeout_ms=1000)
            records = [r for batch in batches.values() for r in batch]
            if not records:
                continue
            for attempt in range(1, SQLITE_RETRIES + 1):
                try:
                    outcomes = apply_batch(conn, records, int(time.time() * 1000), window_ms)
                    break
                except sqlite3.OperationalError as exc:      # e.g. database is locked: transient
                    log.warn("sqlite_retry", attempt=attempt, error=str(exc))
                    time.sleep(attempt)
            else:
                log.error("sqlite_failed_exiting", records=len(records))
                return EXIT_SQLITE_FAILED                      # offsets not committed: the batch replays
            offsets = {TopicPartition(tp.topic, tp.partition): OffsetAndMetadata(batch[-1].offset + 1, None, -1)
                       for tp, batch in batches.items() if batch}
            try:
                consumer.commit(offsets)
            except CommitFailedError:
                log.warn("commit_failed_revoked", partitions=len(offsets))   # replay is harmless (first writer wins)
            log.info("batch", records=len(records), **outcomes)
        log.error("lag_thread_failed_exiting")
        return EXIT_PRODUCE_FAILED
    except KeyboardInterrupt:
        return 0
    finally:
        stop.set()
        consumer.close()
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
