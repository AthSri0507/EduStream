"""indexer: the retrieval index, as its own Kafka consumer group (docs/ARCHITECTURE.md §8.5, A18).

Reads `transcriptions` (group `indexer`, raw bytes, read_committed) and maintains data/vectors.db, of which it is
the ONLY writer (the db-sink owns edustream.db; one writer per file):
  * chunks    every transcribed chunk's text (so a restarted indexer can rebuild passages on its own)
  * passages  30 s passages: chunk k with the two chunks before it, sliding by one chunk, so a word cut at a
              chunk boundary is whole in some passage; embedded with bge-small-en-v1.5 (agents/embeddings.py)
For each poll batch: embed, one SQLite transaction (first writer wins), THEN commit the Kafka offsets.
Kafka gives this for free: a third, independent consumer group on the same topic (fan-out), its own lag in the
lag monitor, and rebuilding = deleting vectors.db and replaying the topic from the start.

    .venv\\Scripts\\python -m storage.indexer
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path

from kafka import TopicPartition
from kafka.errors import CommitFailedError
from kafka.structs import OffsetAndMetadata

from agents import embeddings
from common import schemas
from common.config import ROOT, TOPIC_TRANSCRIPTS, load
from common.kafka_utils import make_consumer
from common.log import JsonLog

GROUP = "indexer"
PASSAGE_CHUNKS = 3                  # 3 x 10 s = 30 s
EXIT_NO_MODEL = 5

SCHEMA = """
PRAGMA journal_mode = WAL;
CREATE TABLE IF NOT EXISTS chunks (
  video_id TEXT, chunk_id INTEGER, start_time REAL, end_time REAL, text TEXT,
  PRIMARY KEY (video_id, chunk_id)
);
CREATE TABLE IF NOT EXISTS passages (
  video_id TEXT, last_chunk_id INTEGER, first_chunk_id INTEGER, start_time REAL, end_time REAL, text TEXT,
  vector BLOB, PRIMARY KEY (video_id, last_chunk_id)
);
"""


def vectors_path() -> Path:
    return Path(os.environ.get("EDU_VECTORS_DB", str(ROOT / "data" / "vectors.db")))


def connect_writer(path=None) -> sqlite3.Connection:
    target = str(path if path is not None else vectors_path())
    if target != ":memory:":
        Path(target).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=5, isolation_level=None)
    conn.executescript(SCHEMA)
    return conn


def connect_readonly(path=None) -> sqlite3.Connection | None:
    target = Path(path if path is not None else vectors_path())
    if not target.exists():
        return None
    return sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True, timeout=2)


# ------------------------------------------------------------------------------------------- pure part (tested)
def apply_chunks(conn: sqlite3.Connection, chunks: list[dict], embedder) -> dict:
    """Store new chunks and the passages they complete; one transaction; returns counts."""
    counts = {"chunks": 0, "passages": 0, "duplicates": 0}
    conn.execute("BEGIN IMMEDIATE")
    try:
        new = []
        for c in chunks:
            cur = conn.execute("INSERT INTO chunks VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING",
                               (c["video_id"], c["chunk_id"], c["start_time"], c["end_time"], c["text"]))
            if cur.rowcount == 1:
                counts["chunks"] += 1
                new.append(c)
            else:
                counts["duplicates"] += 1
        todo = []
        for c in new:                                  # passages ending at a new chunk, and at the 2 after it
            for last in range(c["chunk_id"], c["chunk_id"] + PASSAGE_CHUNKS):
                todo.append((c["video_id"], last))
        rows = []
        for video_id, last in dict.fromkeys(todo):
            got = conn.execute("SELECT chunk_id, start_time, end_time, text FROM chunks WHERE video_id = ?"
                               " AND chunk_id BETWEEN ? AND ? ORDER BY chunk_id",
                               (video_id, last - PASSAGE_CHUNKS + 1, last)).fetchall()
            if not got or got[-1][0] != last:
                continue                               # the chunk this passage ends at isn't here yet
            text = " ".join(t for *_, t in got if t.strip())
            old = conn.execute("SELECT text FROM passages WHERE video_id = ? AND last_chunk_id = ?",
                               (video_id, last)).fetchone()
            if text.strip() and (old is None or old[0] != text):
                rows.append((video_id, last, got[0][0], got[0][1], got[-1][2], text))
        vectors = embedder.passages([r[5] for r in rows]) if rows else []
        for r, v in zip(rows, vectors):
            # A passage stored before a late chunk arrived is rebuilt from all its chunks: the final state depends
            # only on which chunks exist, so any replay order gives the same table.
            conn.execute("INSERT INTO passages VALUES (?,?,?,?,?,?,?) ON CONFLICT(video_id, last_chunk_id) DO UPDATE"
                         " SET first_chunk_id = excluded.first_chunk_id, start_time = excluded.start_time,"
                         " text = excluded.text, vector = excluded.vector", (*r, embeddings.to_blob(v)))
            counts["passages"] += 1
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return counts


def chunk_of(value: bytes | None) -> dict | None:
    """A transcript chunk with text, or None (flushes, empty chunks, invalid records: the sink DLQs those)."""
    try:
        p = schemas.decode(value, "transcript.v1")
    except schemas.ContractError:
        return None
    if p["type"] != "chunk" or not p["text"].strip():
        return None
    return {"video_id": p["video_id"], "chunk_id": p["chunk_id"], "start_time": p["start_time"],
            "end_time": p["end_time"], "text": p["text"]}


# ------------------------------------------------------------------------------------------- main loop
def main() -> int:
    settings = load()
    log = JsonLog("indexer")
    embedder = embeddings.get()
    if embedder is None:
        log.error("embedding_model_unavailable", hint="run scripts\\setup.ps1 (downloads it into models\\fastembed)")
        return EXIT_NO_MODEL
    conn = connect_writer()
    consumer = make_consumer(settings, GROUP, [TOPIC_TRANSCRIPTS], client_id="indexer", max_poll_records=50)
    log.info("started", group=GROUP, db=str(vectors_path()))
    try:
        while True:
            batches = consumer.poll(timeout_ms=1000)
            records = [r for batch in batches.values() for r in batch]
            if not records:
                continue
            chunks = [c for c in (chunk_of(r.value) for r in records) if c is not None]
            started = time.perf_counter()
            counts = apply_chunks(conn, chunks, embedder) if chunks else {}
            offsets = {TopicPartition(tp.topic, tp.partition): OffsetAndMetadata(batch[-1].offset + 1, None, -1)
                       for tp, batch in batches.items() if batch}
            try:
                consumer.commit(offsets)
            except CommitFailedError:
                log.warn("commit_failed_revoked")      # the replay is harmless: first writer wins
            log.info("batch", records=len(records), ms=round((time.perf_counter() - started) * 1000), **counts)
    except KeyboardInterrupt:
        return 0
    finally:
        consumer.close()
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
