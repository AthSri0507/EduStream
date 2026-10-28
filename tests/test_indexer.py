"""The retrieval indexer (ARCHITECTURE §8.5): sliding 30 s passages, one writer, first writer wins, replay = rebuild."""

import hashlib
import json

import numpy as np

from storage import indexer
from storage.indexer import apply_chunks, chunk_of


class FakeEmbedder:
    """Deterministic bag-of-words vectors: similar words -> similar vectors. No model needed."""

    def _vec(self, text):
        v = np.zeros(384, dtype=np.float32)
        for w in text.lower().split():
            v[int(hashlib.md5(w.strip(".,?!").encode()).hexdigest(), 16) % 384] += 1
        n = np.linalg.norm(v)
        return v / n if n else v

    def passages(self, texts):
        return np.array([self._vec(t) for t in texts], dtype=np.float32).reshape(len(texts), 384)

    def query(self, text):
        return self._vec(text)


def chunk(i, text=None, video="python_l1"):
    return {"video_id": video, "chunk_id": i, "start_time": 10.0 * i, "end_time": 10.0 * i + 10,
            "text": text or f"chunk number {i} text"}


def dump(conn):
    return {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2").fetchall() for t in ("chunks", "passages")}


def test_passages_slide_one_chunk_at_a_time():
    conn = indexer.connect_writer(":memory:")
    apply_chunks(conn, [chunk(i) for i in range(5)], FakeEmbedder())
    rows = conn.execute("SELECT first_chunk_id, last_chunk_id, start_time, end_time FROM passages ORDER BY 2").fetchall()
    assert rows == [(0, 0, 0.0, 10.0), (0, 1, 0.0, 20.0), (0, 2, 0.0, 30.0), (1, 3, 10.0, 40.0), (2, 4, 20.0, 50.0)]
    text = conn.execute("SELECT text FROM passages WHERE last_chunk_id = 3").fetchone()[0]
    assert text == "chunk number 1 text chunk number 2 text chunk number 3 text"


def test_a_late_chunk_completes_the_passages_it_belongs_to():
    conn = indexer.connect_writer(":memory:")
    apply_chunks(conn, [chunk(0), chunk(2), chunk(3)], FakeEmbedder())       # chunk 1 is late
    apply_chunks(conn, [chunk(1)], FakeEmbedder())
    rows = conn.execute("SELECT first_chunk_id, last_chunk_id, text FROM passages ORDER BY 2").fetchall()
    assert [(f, l) for f, l, _ in rows] == [(0, 0), (0, 1), (0, 2), (1, 3)]
    assert "chunk number 1 text" in rows[2][2]                                 # passage 0-2 now includes it


def test_duplicates_change_nothing_and_a_replay_rebuilds_identically():
    a, b = indexer.connect_writer(":memory:"), indexer.connect_writer(":memory:")
    chunks = [chunk(i) for i in range(6)]
    apply_chunks(a, chunks, FakeEmbedder())
    before = dump(a)
    counts = apply_chunks(a, chunks, FakeEmbedder())                            # redelivered batch
    assert dump(a) == before and counts["duplicates"] == 6 and counts["passages"] == 0
    for i in range(0, 6, 2):                                                    # rebuild in different batches
        apply_chunks(b, chunks[i:i + 2], FakeEmbedder())
    assert dump(b) == before


def test_only_transcribed_chunks_with_text_are_indexed():
    valid = json.dumps({"schema": "transcript.v1", "type": "chunk", "video_id": "python_l1", "session_start": 1,
                        "chunk_id": 3, "start_time": 30.0, "end_time": 40.0, "event_ts": 30_001, "text": "hello there",
                        "asr_score": 0.8, "model": "base.en", "src_partition": 0, "src_offset": 3}).encode()
    assert chunk_of(valid)["chunk_id"] == 3
    assert chunk_of(b"not json") is None
    silent = json.loads(valid)
    silent["text"] = "  "
    assert chunk_of(json.dumps(silent).encode()) is None
