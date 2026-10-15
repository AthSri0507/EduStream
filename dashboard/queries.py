"""Read-only queries for the dashboard. Readers only use the *_latest views (ARCHITECTURE §9)."""

from __future__ import annotations

import json
import sqlite3

import pandas as pd

LECTURES_SQL = """
SELECT l.video_id, COALESCE(l.title, l.video_id) AS title, l.src_partition AS partition, l.session_start,
       l.last_seen_ts, l.last_chunk_id, l.flushed_ts,
       (SELECT COUNT(DISTINCT c.chunk_id) FROM chunks c WHERE c.video_id = l.video_id) AS chunks_stored,
       (SELECT MAX(c.chunk_id) FROM chunks c WHERE c.video_id = l.video_id) AS max_chunk_id,
       (SELECT COUNT(*) FROM window_latest w WHERE w.video_id = l.video_id) AS windows,
       (SELECT COUNT(*) FROM notes_latest n WHERE n.video_id = l.video_id) AS notes
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
        "alerts": one("SELECT COUNT(*) FROM alerts WHERE type <> 'LATE_DROP'"),
        "late_drop": one("SELECT COUNT(*) FROM alerts WHERE type = 'LATE_DROP'"),
        "dlq": one("SELECT COUNT(*) FROM dlq"),
        "last_sink_ts": one("SELECT MAX(ts) FROM (SELECT MAX(sink_ts) ts FROM chunks UNION ALL "
                            "SELECT MAX(sink_ts) FROM window_stats UNION ALL SELECT MAX(sink_ts) FROM notes)"),
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
