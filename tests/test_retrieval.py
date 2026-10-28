"""Hybrid retrieval (ARCHITECTURE §8.5): fusion, the vector half, live filtering, keyword fallback."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents import embeddings, retrieval
from storage import indexer
from storage.db import connect_readonly, connect_writer
from storage.db_sink import apply_batch
from tests.test_indexer import FakeEmbedder

ROOT = Path(__file__).resolve().parents[1]
WHISPER = ROOT / "bench" / "results" / "chunks_base.en-reppen_ocw6001_l01_10s.jsonl"
S0 = 1_792_051_200_000


@pytest.fixture(scope="module")
def dbs(tmp_path_factory):
    d = tmp_path_factory.mktemp("r")
    rows = [json.loads(line) for line in WHISPER.read_text(encoding="utf-8").splitlines()][:72]   # 12 minutes
    w = connect_writer(d / "edustream.db")
    apply_batch(w, [SimpleNamespace(topic="transcriptions", partition=0, offset=r["chunk_id"], key=b"python_l1",
                                    value=json.dumps({
                                        "schema": "transcript.v1", "type": "chunk", "video_id": "python_l1",
                                        "session_start": S0, "chunk_id": r["chunk_id"], "start_time": r["start_time"],
                                        "end_time": r["end_time"], "event_ts": S0 + r["chunk_id"] * 10_000,
                                        "text": r["text"], "asr_score": r["asr_score"], "model": "base.en",
                                        "src_partition": 0, "src_offset": r["chunk_id"]}).encode()) for r in rows],
                now=1, window_ms=30_000)
    w.close()
    chunks = [{"video_id": "python_l1", "chunk_id": r["chunk_id"], "start_time": r["start_time"],
               "end_time": r["end_time"], "text": r["text"]} for r in rows if r["text"].strip()]
    return d, chunks


def vector_db(d, chunks, embedder, name):
    v = indexer.connect_writer(d / name)
    indexer.apply_chunks(v, chunks, embedder)
    v.close()
    return indexer.connect_readonly(d / name)


def test_rrf_rewards_agreement_and_keeps_single_lists_in_order():
    assert retrieval.fuse([10.0, 20.0, 30.0]) == [10.0, 20.0, 30.0]
    assert retrieval.fuse([10.0, 20.0, 30.0], [30.0, 40.0])[0] == 30.0       # found by both: first
    assert retrieval.fuse([], []) == []


def test_without_vectors_it_is_plain_keyword_search(dbs):
    d, _ = dbs
    conn = connect_readonly(d / "edustream.db")
    q = "why can't computers know anything by themselves?"
    assert retrieval.search(conn, "python_l1", q, vconn=None, embedder=None) == \
        retrieval.tools.search(conn, "python_l1", q)


def test_live_lectures_never_retrieve_what_comes_later(dbs):
    d, chunks = dbs
    conn = connect_readonly(d / "edustream.db")
    vconn = vector_db(d, chunks, FakeEmbedder(), "fake.db")
    for p in retrieval.search(conn, "python_l1", "imperative knowledge recipe", until=300.0, vconn=vconn,
                              embedder=FakeEmbedder()):
        assert p["end"] <= 310.0                                               # nothing after 05:00 (+ the line end)


real = embeddings.get()


@pytest.mark.skipif(real is None, reason="embedding model not downloaded (scripts/setup.ps1)")
def test_meaning_finds_a_paraphrase_that_keywords_miss(dbs):
    d, chunks = dbs
    conn = connect_readonly(d / "edustream.db")
    vconn = vector_db(d, chunks, real, "real.db")
    q = "is there any risk that I damage my laptop by experimenting?"            # said: "afraid ... break your computer"
    said = lambda ps: any("break your computer" in ln["text"] for p in ps[:3] for ln in p["lines"])  # noqa: E731
    assert said(retrieval.search(conn, "python_l1", q, vconn=vconn, embedder=real, mode="vector"))
    assert said(retrieval.search(conn, "python_l1", q, vconn=vconn, embedder=real, mode="hybrid"))
