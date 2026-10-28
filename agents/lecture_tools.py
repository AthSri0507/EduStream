"""Deterministic, read-only tools over SQLite for the Lecture Assistant (docs/ARCHITECTURE.md §8.2, §8.5).

"The code makes the tool calls; the LLM writes the language": every fact the assistant shows comes
from one of these functions. All take an open read-only connection (storage.db.connect_readonly).
A "line" is one transcribed chunk: {t, end, text}; evidence is always a list of lines in time order.
"""

from __future__ import annotations

import re
import sqlite3

from agents.text import STOP, content_words, norm

MAX_LINES = 60          # about 10 minutes of transcript: more is summarised from the notebook instead


def lecture_info(conn: sqlite3.Connection, video_id: str) -> dict | None:
    row = conn.execute(
        "SELECT l.video_id, COALESCE(l.title, l.video_id), l.session_start, l.flushed_ts, COALESCE(l.speedup, 1),"
        " (SELECT MAX(end_time) FROM chunks c WHERE c.video_id = l.video_id)"
        " FROM lectures l WHERE l.video_id = ?", (video_id,)).fetchone()
    if row is None:
        return None
    return {"video_id": row[0], "title": row[1], "session_start": row[2], "finished": row[3] is not None,
            "speedup": row[4], "covered_s": row[5] or 0.0}


def transcript(conn: sqlite3.Connection, video_id: str, start: float, end: float, before: int = 1) -> list[dict]:
    """Chunks overlapping [start, end], plus `before` chunk(s) of context (chunks cut words at their edges)."""
    rows = conn.execute(
        "SELECT start_time, end_time, text FROM chunks WHERE video_id = ? AND end_time > ? AND start_time < ?"
        " ORDER BY start_time", (video_id, start - before * 10.0, end)).fetchall()
    return [{"t": r[0], "end": r[1], "text": r[2]} for r in rows if (r[2] or "").strip()]


def outline(conn: sqlite3.Connection, video_id: str) -> list[dict]:
    return [{"id": r[0], "title": r[1], "t": r[2]} for r in conn.execute(
        "SELECT section_id, COALESCE(final_title, title), media_start FROM sections WHERE video_id = ?"
        " ORDER BY section_id", (video_id,))]


def notebook_points(conn: sqlite3.Connection, video_id: str, start: float = 0.0, end: float = 1e9) -> list[dict]:
    return [{"t": r[0], "text": r[1], "kind": r[2]} for r in conn.execute(
        "SELECT t, text, kind FROM points WHERE video_id = ? AND t >= ? AND t <= ? ORDER BY t", (video_id, start, end))]


def glossary(conn: sqlite3.Connection, video_id: str, term: str) -> list[dict]:
    """Exact (case-insensitive) match first, then terms containing the word."""
    rows = conn.execute("SELECT term, definition, source, t FROM terms WHERE video_id = ? AND term = ?",
                        (video_id, term)).fetchall()
    if not rows:
        rows = conn.execute("SELECT term, definition, source, t FROM terms WHERE video_id = ? AND term LIKE ?",
                            (video_id, f"%{term}%")).fetchall()
    return [{"term": r[0], "definition": r[1], "source": r[2], "t": r[3]} for r in rows]


def _fts_query(text: str) -> str | None:
    words = [w for w in norm(text).split() if w not in STOP and len(w) > 1]
    words = list(dict.fromkeys(words))[:12]
    return " OR ".join(f'"{w}"' for w in words) or None


def bm25_moments(conn: sqlite3.Connection, video_id: str, query: str, until: float | None = None) -> list[float]:
    """Keyword (BM25) ranking over the transcript and the notebook: the start times of the hits, best first."""
    q = _fts_query(query)
    if q is None:
        return []
    until = 1e9 if until is None else until
    hits: list[tuple[float, float]] = []          # (start_time, rank)
    try:
        hits += [(r[0], r[1]) for r in conn.execute(
            "SELECT start_time, bm25(transcript_fts) FROM transcript_fts WHERE transcript_fts MATCH ? AND video_id = ?"
            " ORDER BY bm25(transcript_fts) LIMIT 20", (q, video_id))]
        hits += [(r[0], r[1]) for r in conn.execute(
            "SELECT t, bm25(notebook_fts) FROM notebook_fts WHERE notebook_fts MATCH ? AND video_id = ?"
            " ORDER BY bm25(notebook_fts) LIMIT 10", (q, video_id))]
    except sqlite3.OperationalError:
        return []
    return [float(s) for s, _ in sorted(hits, key=lambda h: h[1]) if float(s) <= until]   # bm25: lower is better


def passages_around(conn: sqlite3.Connection, video_id: str, moments: list[float], limit: int = 5,
                    until: float | None = None) -> list[dict]:
    """Ranked moments -> passages of -10..+20 s, overlapping or adjacent ones merged (the same moment)."""
    until = 1e9 if until is None else until
    passages: list[dict] = []
    for rank, start in enumerate(moments):
        lo, hi = start - 10, start + 20
        for p in passages:
            if lo <= p["end"] and hi >= p["t"]:
                p["t"], p["end"] = min(p["t"], lo), max(p["end"], hi)
                break
        else:
            passages.append({"t": lo, "end": hi, "rank": rank})
    out = []
    for p in passages[:limit]:
        lines = transcript(conn, video_id, max(0.0, p["t"]), min(p["end"], until), before=0)
        if lines:
            out.append({"t": lines[0]["t"], "end": lines[-1]["end"], "lines": lines, "rank": p["rank"]})
    return out


def search(conn: sqlite3.Connection, video_id: str, query: str, limit: int = 5, until: float | None = None) -> list[dict]:
    """Keyword-only search (BM25): passages [{t, end, lines, rank}] best first; `until` hides anything later.
    agents/retrieval.py adds the vector half and fuses both (§8.5)."""
    return passages_around(conn, video_id, bm25_moments(conn, video_id, query, until), limit, until)


def speaking_stats(conn: sqlite3.Connection, video_id: str, start: float, end: float) -> dict:
    row = conn.execute(
        "SELECT COUNT(*), SUM(word_count), SUM(covered_s), AVG(score_avg) FROM window_latest"
        " WHERE video_id = ? AND media_end > ? AND media_start < ?", (video_id, start, end)).fetchone()
    words, covered = row[1] or 0, row[2] or 0.0
    alerts = conn.execute("SELECT type, COUNT(*) FROM alerts WHERE video_id = ? GROUP BY type",
                          (video_id,)).fetchall()
    return {"windows": row[0], "words": words, "covered_s": covered,
            "words_per_min": round(60 * words / covered, 1) if covered else None,
            "score_avg": round(row[3], 3) if row[3] is not None else None, "alerts": dict(alerts)}


def lines_text(lines: list[dict]) -> list[str]:
    return [ln["text"] for ln in lines]


def term_mentions(conn: sqlite3.Connection, video_id: str, term: str, until: float | None = None,
                  limit: int = 3) -> list[dict]:
    """Passages where a term is said, earliest first (a definition is usually given on first use)."""
    words = [w for w in content_words(term)]
    if not words:
        return []
    passages = search(conn, video_id, term, limit=8, until=until)
    pattern = re.compile(re.escape(norm(term)))
    said = [p for p in passages if any(pattern.search(norm(ln["text"])) for ln in p["lines"])]
    return sorted(said, key=lambda p: p["t"])[:limit]
