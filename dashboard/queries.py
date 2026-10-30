"""Read-only queries for the dashboard. Readers only use the *_latest views (ARCHITECTURE §9)."""

from __future__ import annotations

import json
import sqlite3

import pandas as pd

from agents import additions as adds
from agents.study_notes import fold_draft

LECTURES_SQL = """
SELECT l.video_id, COALESCE(l.title, l.video_id) AS title, l.src_partition AS partition, l.session_start,
       l.last_seen_ts, l.last_chunk_id, l.flushed_ts,
       (SELECT COUNT(DISTINCT c.chunk_id) FROM chunks c WHERE c.video_id = l.video_id) AS chunks_stored,
       (SELECT MAX(c.chunk_id) FROM chunks c WHERE c.video_id = l.video_id) AS max_chunk_id,
       (SELECT COUNT(*) FROM window_latest w WHERE w.video_id = l.video_id) AS windows,
       (SELECT COUNT(*) FROM notes_latest n WHERE n.video_id = l.video_id) AS notes,
       (SELECT COUNT(*) FROM live_updates u WHERE u.video_id = l.video_id) AS updates,
       (SELECT COUNT(*) FROM passes p WHERE p.video_id = l.video_id) AS passes
FROM lectures l ORDER BY l.src_partition, l.video_id
"""


def lectures(conn: sqlite3.Connection) -> pd.DataFrame:
    df = pd.read_sql_query(LECTURES_SQL, conn)
    if df.empty:
        return df
    expected = df["last_chunk_id"].where(df["last_chunk_id"].notna(), df["max_chunk_id"]).fillna(-1) + 1
    df["expected_chunks"] = expected.astype(int)
    df["completeness_pct"] = (100 * df["chunks_stored"] / expected.where(expected > 0)).round(1)
    df["status"] = df["flushed_ts"].map(lambda v: "finished" if pd.notna(v) else "live")
    return df


def kpis(conn: sqlite3.Connection) -> dict:
    one = lambda sql: conn.execute(sql).fetchone()[0]   # noqa: E731
    return {
        "lectures": one("SELECT COUNT(*) FROM lectures"),
        "chunks": one("SELECT COUNT(*) FROM chunks"),
        "windows": one("SELECT COUNT(*) FROM window_latest"),
        "notes": one("SELECT COUNT(*) FROM notes_latest"),
        "updates": one("SELECT COUNT(*) FROM live_updates"),
        "passes": one("SELECT COUNT(*) FROM passes"),
        "alerts": one("SELECT COUNT(*) FROM alerts WHERE type <> 'LATE_DROP'"),
        "late_drop": one("SELECT COUNT(*) FROM alerts WHERE type = 'LATE_DROP'"),
        "dlq": one("SELECT COUNT(*) FROM dlq"),
        "last_sink_ts": one("SELECT MAX(ts) FROM (SELECT MAX(sink_ts) ts FROM chunks UNION ALL "
                            "SELECT MAX(sink_ts) FROM window_stats UNION ALL SELECT MAX(sink_ts) FROM notes UNION ALL "
                            "SELECT MAX(sink_ts) FROM live_updates UNION ALL SELECT MAX(sink_ts) FROM passes)"),
    }


def notes(conn: sqlite3.Connection, video_id: str) -> pd.DataFrame:
    df = pd.read_sql_query(
        "SELECT n.window_start, n.window_index, n.revision, n.media_start, n.media_end, n.summary, n.key_points,"
        "       n.terms, n.questions, n.generator, n.quality_flag, n.model, w.transcript, w.words_per_min, w.score_avg"
        " FROM notes_latest n LEFT JOIN window_latest w"
        "   ON w.video_id = n.video_id AND w.window_start = n.window_start"
        " WHERE n.video_id = ? ORDER BY n.window_start DESC", conn, params=(video_id,))
    for column in ("key_points", "terms", "questions"):
        df[column] = df[column].map(lambda v: json.loads(v) if v else [])
    return df


def notebook(conn: sqlite3.Connection, video_id: str, update_s: float = 90.0) -> dict:
    """One lecture's notebook (NOTEBOOK_DESIGN §6, §11): finished topics with their elements, the live drafts after
    the last consolidation (folded exactly as the Note Agent folds them), glossary, course info and the live state."""
    topics = [{"n": r[0], "title": r[1], "start": r[2], "end": r[3], "question": r[4], "answer": r[5],
               "generator": r[6], "elements": []} for r in conn.execute(
        "SELECT topic_n, title, media_start, media_end, question, answer, generator FROM topics WHERE video_id = ?"
        " ORDER BY topic_n", (video_id,))]
    by_n = {t["n"]: t for t in topics}
    for topic_n, body in conn.execute("SELECT topic_n, body FROM elements WHERE video_id = ? ORDER BY pass_index, seq",
                                      (video_id,)):
        if topic_n in by_n:
            by_n[topic_n]["elements"].append(json.loads(body))
    since, final = conn.execute("SELECT COALESCE(MAX(media_end), 0), COALESCE(MAX(final), 0) FROM passes"
                                " WHERE video_id = ?", (video_id,)).fetchone()
    drafts: list[dict] = []
    for k, body in conn.execute("SELECT update_index, body FROM drafts WHERE video_id = ? ORDER BY update_index, seq",
                                (video_id,)):
        fold_draft(drafts, json.loads(body), k)
    drafts = sorted((d for d in drafts if d["t"] >= since), key=lambda d: d["t"])   # spoken order (live run 1)
    reach, updates, latest = conn.execute("SELECT COALESCE(MAX(media_end), 0), COUNT(*), MAX(update_index)"
                                          " FROM live_updates WHERE video_id = ?", (video_id,)).fetchone()
    said_until, flushed = conn.execute(
        "SELECT (SELECT COALESCE(MAX(end_time), 0) FROM chunks WHERE video_id = ?),"
        " (SELECT flushed_ts IS NOT NULL FROM lectures WHERE video_id = ?)", (video_id, video_id)).fetchone()
    tail = [r[0] for r in conn.execute("SELECT text FROM chunks WHERE video_id = ? AND TRIM(text) <> ''"
                                       " ORDER BY chunk_id DESC LIMIT 2", (video_id,))][::-1]
    glossary = [{"term": r[0], "definition": r[1], "t": r[2]} for r in conn.execute(
        "SELECT term, definition, t FROM glossary WHERE video_id = ? ORDER BY term COLLATE NOCASE", (video_id,))]
    info = [{"text": r[0], "t": r[1]} for r in conn.execute(
        "SELECT text, t FROM course_info WHERE video_id = ? ORDER BY t", (video_id,))]
    finished = bool(final) or (bool(flushed) and updates > 0 and not drafts and reach <= since)
    if flushed:
        status = "Finishing the notes…"
    elif said_until - reach >= update_s:
        status = f"Writing the notes for {_mmss(reach)}–{_mmss(reach + update_s)}…"
    else:
        status = f"Next notes after {_mmss(reach + update_s)}."
    live_additions, beyond = place_additions(conn, video_id, topics, since, finished)
    return {"topics": topics, "drafts": drafts, "latest_k": latest, "since": since, "reach": reach,
            "said_until": said_until, "now_text": " ".join(tail), "glossary": glossary, "info": info,
            "updates": updates, "finished": finished, "status": status, "live_additions": live_additions,
            "beyond": beyond}


def place_additions(conn: sqlite3.Connection, video_id: str, topics: list[dict], since: float,
                    finished: bool) -> tuple[list[dict], list[dict]]:
    """The student's additions (NOTEBOOK_DESIGN §13.6), placed now: into topic["additions"] (each with "after", the
    element it follows, or None for the end of the topic), under the live notes, or "Beyond the lecture"."""
    for t in topics:
        t["additions"] = []
    try:
        rows = conn.execute("SELECT addition_id, figure, span_start, span_end, question, topic_override, outside,"
                            " created_ts FROM additions WHERE video_id = ? AND removed = 0 ORDER BY created_ts",
                            (video_id,)).fetchall()
    except sqlite3.OperationalError:                       # a database from before §13
        return [], []
    live, beyond = [], []
    by_n = {t["n"]: t for t in topics}
    for r in rows:
        item = {"addition_id": r[0], "figure": json.loads(r[1]), "span": [r[2], r[3]] if r[2] is not None else None,
                "question": r[4] or "", "topic_override": r[5], "outside": bool(r[6]), "created_ts": r[7]}
        placement = adds.place(item, topics, since, finished)
        if placement["where"] == "topic":
            by_n[placement["topic_n"]]["additions"].append({**item, "after": placement["after"]})
        else:
            (live if placement["where"] == "live" else beyond).append(item)
    return live, beyond


def _mmss(seconds: float) -> str:
    return f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}"


def window_stats(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT w.video_id, COALESCE(l.title, w.video_id) AS title, l.src_partition AS partition, w.window_start,"
        "       w.media_start, w.media_end, w.chunk_count, w.covered_s, w.word_count, w.words_per_min,"
        "       w.score_avg, w.score_min, w.score_max, w.compression_ratio_max, w.top_terms"
        " FROM window_latest w LEFT JOIN lectures l ON l.video_id = w.video_id"
        " ORDER BY l.src_partition, w.window_start", conn)


def alerts(conn: sqlite3.Connection, limit: int = 200) -> pd.DataFrame:
    df = pd.read_sql_query(
        "SELECT a.created_ts, a.type, a.severity, COALESCE(l.title, a.video_id) AS lecture, a.window_start,"
        "       a.value, a.threshold, a.details, a.alert_id, l.session_start"
        " FROM alerts a LEFT JOIN lectures l ON l.video_id = a.video_id"
        " ORDER BY a.created_ts DESC LIMIT ?", conn, params=(limit,))
    df["reason"] = df["details"].map(lambda d: (json.loads(d) if d else {}).get("reason", ""))
    return df


def lag(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT g.group_id, g.topic, g.partition, g.owner, g.committed, g.end_offset, g.lag, g.lag_seconds,"
        "       g.sampled_ts, (SELECT COALESCE(l.title, l.video_id) FROM lectures l WHERE l.src_partition = g.partition"
        "                      ORDER BY l.last_seen_ts DESC LIMIT 1) AS lecture"
        " FROM lag g ORDER BY g.group_id, g.partition", conn)


def partition_map(conn: sqlite3.Connection) -> pd.DataFrame:
    """Partition -> lecture -> worker that owns it now (consumer group) and worker of the latest chunk."""
    return pd.read_sql_query(
        "SELECT l.src_partition AS partition, COALESCE(l.title, l.video_id) AS lecture, l.video_id,"
        "       (SELECT g.owner FROM lag g WHERE g.group_id = 'transcription-workers' AND g.partition = l.src_partition)"
        "         AS owner_now,"
        "       (SELECT c.worker_id FROM chunks c WHERE c.video_id = l.video_id ORDER BY c.chunk_id DESC LIMIT 1)"
        "         AS latest_chunk_by,"
        "       (SELECT COUNT(DISTINCT c.worker_id) FROM chunks c WHERE c.video_id = l.video_id) AS workers_used"
        " FROM lectures l ORDER BY l.src_partition", conn)


def dlq(conn: sqlite3.Connection, limit: int = 50) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT failed_ts, stage, source_topic, src_partition, src_offset, key, error FROM dlq"
        " ORDER BY failed_ts DESC LIMIT ?", conn, params=(limit,))
