"""R-1 (ARCHITECTURE §8.5, §10): does hybrid retrieval beat keywords alone? Recall@5, MRR and latency.

30 hand-written questions about two full lectures (real M2 Whisper transcripts), each with the moment(s) where
the lecture answers it. 17 use the lecture's own words, 13 are paraphrases (different words, same meaning).
For every question, BM25, vectors and hybrid (RRF) each return their top 5 passages; a question is answered if
any returned passage overlaps a gold span. No LLM involved. Real embedding model (models/fastembed).

    .venv\\Scripts\\python bench\\retrieval_eval.py

Writes bench/results/retrieval_eval.json and .md.
"""

from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents import embeddings, retrieval  # noqa: E402
from storage import indexer  # noqa: E402
from storage.db import connect_readonly, connect_writer  # noqa: E402
from storage.db_sink import apply_batch  # noqa: E402

LECTURES = {"python_l1": "ocw6001_l01", "algorithms_ku_l1": "ocw6006_l01"}
S0 = 1_792_051_200_000
T = lambda m, s: m * 60 + s  # noqa: E731

# (lecture, question, kind, gold spans [start_s, end_s])
QUESTIONS = [
    ("python_l1", "What is the definition of declarative knowledge?", "words", [(T(8, 40), T(9, 0)), (T(12, 40), T(13, 0))]),
    ("python_l1", "What is imperative knowledge?", "words", [(T(9, 30), T(10, 0))]),
    ("python_l1", "How do you find the square root of a number starting from a guess?", "words", [(T(13, 10), T(14, 20))]),
    ("python_l1", "How is the new guess computed in the square root algorithm?", "words", [(T(13, 40), T(14, 0))]),
    ("python_l1", "What are the three parts of a recipe?", "words", [(T(14, 20), T(15, 10))]),
    ("python_l1", "How does the recipe know when to stop?", "paraphrase", [(T(14, 50), T(15, 20))]),
    ("python_l1", "Why can't a calculator be used to send email?", "paraphrase", [(T(16, 0), T(16, 40))]),
    ("python_l1", "What changed with stored program computers?", "words", [(T(16, 40), T(17, 10))]),
    ("python_l1", "What does the ALU do?", "words", [(T(17, 30), T(17, 50)), (T(18, 0), T(18, 40))]),
    ("python_l1", "What does the program counter do?", "words", [(T(18, 0), T(18, 50))]),
    ("python_l1", "Who showed that six primitives are enough to compute anything?", "words", [(T(20, 30), T(21, 0))]),
    ("python_l1", "If something can be programmed in Python, can it be done in other languages?", "paraphrase",
     [(T(21, 10), T(21, 40))]),
    ("python_l1", "What is an example of bad syntax in English?", "words", [(T(22, 40), T(23, 10))]),
    ("python_l1", "What does static semantics mean?", "words", [(T(23, 30), T(24, 40))]),
    ("python_l1", "Can a sentence have more than one meaning?", "words", [(T(24, 40), T(25, 10))]),
    ("python_l1", "How did she choose the person who wins the prize?", "paraphrase", [(T(10, 30), T(11, 50))]),
    ("python_l1", "Could I damage my laptop by experimenting with commands?", "paraphrase", [(T(3, 10), T(3, 40))]),
    ("python_l1", "Why should other people be able to understand my code?", "paraphrase", [(T(5, 20), T(6, 10))]),
    ("python_l1", "What happens inside the machine while it runs a program step by step?", "paraphrase",
     [(T(17, 0), T(19, 50))]),
    ("python_l1", "Why don't we write programs using only Turing's handful of commands?", "paraphrase",
     [(T(20, 50), T(21, 10))]),
    ("algorithms_ku_l1", "Formally, what is a computational problem?", "words", [(T(3, 30), T(5, 10))]),
    ("algorithms_ku_l1", "Can one input have several correct answers?", "paraphrase", [(T(4, 20), T(4, 50))]),
    ("algorithms_ku_l1", "How do we describe a problem without listing the answer for every input?", "paraphrase",
     [(T(5, 10), T(6, 0))]),
    ("algorithms_ku_l1", "Why must two students share a birthday if there are more than 365 of them?", "words",
     [(T(6, 10), T(6, 30))]),
    ("algorithms_ku_l1", "Why should an algorithm work for a class of any size?", "paraphrase", [(T(8, 0), T(9, 0))]),
    ("algorithms_ku_l1", "What is an algorithm?", "words", [(T(9, 0), T(10, 40)), (T(14, 40), T(15, 10))]),
    ("algorithms_ku_l1", "How does the birthday algorithm work?", "words", [(T(11, 0), T(13, 20))]),
    ("algorithms_ku_l1", "Does an algorithm have to give exactly one output for each input?", "paraphrase",
     [(T(13, 50), T(14, 40))]),
    ("algorithms_ku_l1", "How can we show the algorithm is right for any number of students?", "paraphrase",
     [(T(15, 10), T(17, 30))]),
    ("algorithms_ku_l1", "What do we need for an inductive proof?", "words", [(T(17, 30), T(18, 10))]),
]


def build(tmp: Path, embedder) -> None:
    w = connect_writer(tmp / "edustream.db")
    v = indexer.connect_writer(tmp / "vectors.db")
    for video, item in LECTURES.items():
        rows = [json.loads(x) for x in (ROOT / "bench" / "results" / f"chunks_base.en-reppen_{item}_10s.jsonl")
                .read_text(encoding="utf-8").splitlines()]
        apply_batch(w, [SimpleNamespace(topic="transcriptions", partition=0, offset=r["chunk_id"], key=video.encode(),
                                        value=json.dumps({
                                            "schema": "transcript.v1", "type": "chunk", "video_id": video,
                                            "session_start": S0, "chunk_id": r["chunk_id"],
                                            "start_time": r["start_time"], "end_time": r["end_time"],
                                            "event_ts": S0 + r["chunk_id"] * 10_000, "text": r["text"],
                                            "asr_score": r["asr_score"], "model": "base.en", "src_partition": 0,
                                            "src_offset": r["chunk_id"]}).encode()) for r in rows],
                    now=1, window_ms=30_000)
        indexer.apply_chunks(v, [{"video_id": video, "chunk_id": r["chunk_id"], "start_time": r["start_time"],
                                  "end_time": r["end_time"], "text": r["text"]} for r in rows if r["text"].strip()],
                             embedder)
    w.close()
    v.close()


def main() -> None:
    embedder = embeddings.get()
    if embedder is None:
        sys.exit("embedding model missing: run scripts\\setup.ps1")
    tmp = Path(tempfile.mkdtemp(prefix="r1_"))
    t0 = time.perf_counter()
    build(tmp, embedder)
    print(f"indexed both lectures in {time.perf_counter() - t0:.0f} s")
    conn, vconn = connect_readonly(tmp / "edustream.db"), indexer.connect_readonly(tmp / "vectors.db")
    results = {m: [] for m in ("bm25", "vector", "hybrid")}
    for video, q, kind, gold in QUESTIONS:
        for mode in results:
            started = time.perf_counter()
            ps = retrieval.search(conn, video, q, limit=5, vconn=vconn, embedder=embedder, mode=mode)
            ms = (time.perf_counter() - started) * 1000
            rank = next((i + 1 for i, p in enumerate(ps) if any(p["t"] < b and p["end"] > a for a, b in gold)), None)
            results[mode].append({"question": q, "kind": kind, "rank": rank, "ms": round(ms, 1)})
    summary = {}
    for mode, rows in results.items():
        def recall(kind=None):
            sel = [r for r in rows if kind in (None, r["kind"])]
            return round(sum(r["rank"] is not None for r in sel) / len(sel), 3)
        summary[mode] = {"recall@5": recall(), "recall@5_words": recall("words"),
                         "recall@5_paraphrase": recall("paraphrase"),
                         "mrr": round(statistics.mean(1 / r["rank"] if r["rank"] else 0 for r in rows), 3),
                         "median_ms": round(statistics.median(r["ms"] for r in rows), 1)}
    out = {"questions": len(QUESTIONS), "words": sum(k == "words" for *_, k, _ in [(a, b, c, d) for a, b, c, d in QUESTIONS]),
           "min_similarity": retrieval.MIN_SIMILARITY, "summary": summary, "per_question": results}
    (ROOT / "bench" / "results" / "retrieval_eval.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    lines = ["# R-1: retrieval on 30 questions (2 full lectures, real Whisper transcripts)\n",
             "| Method | Recall@5 | Own words (17) | Paraphrases (13) | MRR | Median latency |", "|---|---|---|---|---|---|"]
    for mode, s in summary.items():
        lines.append(f"| {mode} | {s['recall@5']:.2f} | {s['recall@5_words']:.2f} | {s['recall@5_paraphrase']:.2f} | "
                     f"{s['mrr']:.2f} | {s['median_ms']} ms |")
    lines += ["", "| Question | Kind | BM25 | Vector | Hybrid |", "|---|---|---|---|---|"]
    for i, (_, q, kind, _) in enumerate(QUESTIONS):
        cell = lambda m: str(results[m][i]["rank"] or "–")  # noqa: E731
        lines.append(f"| {q} | {kind} | {cell('bm25')} | {cell('vector')} | {cell('hybrid')} |")
    (ROOT / "bench" / "results" / "retrieval_eval.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
