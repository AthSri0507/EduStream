"""Hybrid retrieval for the Lecture Assistant (docs/ARCHITECTURE.md §8.5, A18).

Two rankings of the moments in a lecture, fused with Reciprocal Rank Fusion (score = sum of 1 / (60 + rank)):
  * keywords: BM25 over the transcript and the notebook (SQLite FTS5)  - best for exact terms, names, numbers
  * meaning:  cosine similarity between the question and the indexer's 30 s passage vectors (vectors.db) -
              best for paraphrases ("why does it get slower?" vs "complexity")
Brute force over one lecture's vectors (a few hundred) takes milliseconds, so no vector database is needed.
If vectors.db or the embedding model is missing, this is plain keyword search.
"""

from __future__ import annotations

import sqlite3

import numpy as np

from agents import embeddings
from agents import lecture_tools as tools

RRF_K = 60
MIN_SIMILARITY = 0.55        # below this a passage is not considered related (tuned on the R-1 set, M6e)
TOP_EACH = 20


def vector_moments(vconn: sqlite3.Connection | None, embedder, video_id: str, query: str,
                   until: float | None = None) -> list[float]:
    """Start times of the passages most similar in meaning to the query, best first."""
    if vconn is None or embedder is None or not query.strip():
        return []
    until = 1e9 if until is None else until
    try:
        rows = vconn.execute("SELECT start_time, vector FROM passages WHERE video_id = ? AND start_time <= ?",
                             (video_id, until)).fetchall()
    except sqlite3.Error:
        return []
    if not rows:
        return []
    matrix = embeddings.from_blobs([r[1] for r in rows])
    scores = matrix @ embeddings_query(embedder, query)
    order = np.argsort(-scores)[:TOP_EACH]
    return [float(rows[i][0]) for i in order if scores[i] >= MIN_SIMILARITY]


def embeddings_query(embedder, query: str) -> np.ndarray:
    return embedder.query(query)


def fuse(*rankings: list[float]) -> list[float]:
    """Reciprocal Rank Fusion of ranked moment lists (moments on the 10 s chunk grid are the same key)."""
    score: dict[float, float] = {}
    for ranking in rankings:
        for rank, t in enumerate(dict.fromkeys(round(x, 1) for x in ranking)):
            score[t] = score.get(t, 0.0) + 1.0 / (RRF_K + rank + 1)
    return sorted(score, key=lambda t: (-score[t], t))


def search(conn: sqlite3.Connection, video_id: str, query: str, limit: int = 5, until: float | None = None,
           vconn: sqlite3.Connection | None = None, embedder=None, mode: str = "hybrid") -> list[dict]:
    """Passages [{t, end, lines, rank}] best first. mode: "hybrid", "bm25" or "vector" (for the R-1 comparison)."""
    keyword = tools.bm25_moments(conn, video_id, query, until) if mode in ("hybrid", "bm25") else []
    meaning = vector_moments(vconn, embedder, video_id, query, until) if mode in ("hybrid", "vector") else []
    return tools.passages_around(conn, video_id, fuse(keyword, meaning), limit, until)
