"""The Data tab's read-only SQL box (docs/ARCHITECTURE.md §8.3, A19): storage the user can query, safely.

Defence in depth on top of mode=ro:
  * one statement only (sqlite3 refuses a second one);
  * a SQLite authorizer allows only SELECT, reading the listed tables/views (and FTS shadow tables), and
    plain functions; ATTACH, PRAGMA, writes, temp objects and load_extension are refused;
  * a progress handler stops a query after TIME_LIMIT_S; at most MAX_ROWS rows are returned.
No SQL is ever written by the LLM: the assistant's "data" intent uses fixed queries.
"""

from __future__ import annotations

import sqlite3
import time

import pandas as pd

ALLOWED = {"lectures", "chunks", "window_stats", "window_latest", "notes", "notes_latest", "alerts", "dlq", "lag",
           "live_updates", "drafts", "course_info", "passes", "topics", "elements", "glossary", "additions",
           "notebook_fts",
           "transcript_fts", "notes_fts",
           "sqlite_master", "sqlite_schema"}
FTS = ("notebook_fts", "transcript_fts", "notes_fts")
TIME_LIMIT_S = 2.0
MAX_ROWS = 1000

READY_MADE = {
    "Lectures and their status":
        "SELECT video_id, title, src_partition AS partition, last_chunk_id, flushed_ts IS NOT NULL AS finished"
        " FROM lectures ORDER BY src_partition",
    "Speaking rate and quality per window":
        "SELECT video_id, window_index, ROUND(media_start/60.0, 1) AS minute, word_count, words_per_min,"
        " ROUND(score_avg, 3) AS score_avg, ROUND(score_min, 3) AS score_min, ROUND(score_max, 3) AS score_max"
        " FROM window_latest ORDER BY video_id, window_start",
    "Notebook: live updates and consolidation passes per lecture":
        "SELECT u.video_id, COUNT(*) AS live_updates, SUM(u.generator = 'llm') AS live_by_llm,"
        " (SELECT COUNT(*) FROM passes p WHERE p.video_id = u.video_id) AS passes,"
        " (SELECT SUM(p.generator = 'llm') FROM passes p WHERE p.video_id = u.video_id) AS passes_by_llm,"
        " (SELECT COUNT(*) FROM topics t WHERE t.video_id = u.video_id) AS topics"
        " FROM live_updates u GROUP BY u.video_id",
    "Notebook: topics with their check-yourself questions":
        "SELECT video_id, topic_n, title, ROUND(media_start/60.0, 1) AS from_min, ROUND(media_end/60.0, 1) AS to_min,"
        " question, answer, generator FROM topics ORDER BY video_id, topic_n",
    "Transcript search (edit the word in quotes)":
        "SELECT video_id, chunk_id, start_time, body FROM transcript_fts WHERE transcript_fts MATCH 'computation'"
        " ORDER BY bm25(transcript_fts) LIMIT 20",
    "Alerts":
        "SELECT type, severity, video_id, value, threshold, created_ts FROM alerts ORDER BY created_ts DESC",
    "Consumer lag":
        "SELECT group_id, topic, partition, lag, ROUND(lag_seconds, 1) AS lag_seconds, owner FROM lag"
        " ORDER BY group_id, partition",
    "Dead-letter queue":
        "SELECT stage, source_topic, src_partition, src_offset, error FROM dlq ORDER BY failed_ts DESC",
}


class QueryRefused(Exception):
    """The query was not allowed, or was stopped."""


def _allowed(table: str) -> bool:
    return table in ALLOWED or any(table.startswith(f + "_") for f in FTS)


def make_authorizer(forbidden: set[str]):
    """forbidden: names of real tables/views that are not allowed (a WITH query's own names are fine)."""
    def authorizer(action, arg1, arg2, db_name, trigger):
        if action == sqlite3.SQLITE_READ:
            return sqlite3.SQLITE_DENY if (arg1 or "").lower() in forbidden else sqlite3.SQLITE_OK
        return _authorizer(action, arg1, arg2, db_name, trigger)
    return authorizer


def _authorizer(action, arg1, arg2, db_name, trigger):
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ:
        return sqlite3.SQLITE_OK if _allowed((arg1 or "").lower()) else sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION:
        return sqlite3.SQLITE_DENY if (arg2 or "").lower() in {"load_extension", "readfile", "writefile"} \
            else sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_RECURSIVE:                       # WITH RECURSIVE (bounded by the time limit)
        return sqlite3.SQLITE_OK
    # FTS5's own set-up statements (traced in M6e): a read-only pragma and a schema-table check. The
    # connection is mode=ro, so neither can change anything.
    if action == sqlite3.SQLITE_PRAGMA and (arg1 or "").lower() == "data_version" and arg2 is None:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_UPDATE and (arg1 or "").lower() == "sqlite_master":
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY          # ATTACH, PRAGMA, INSERT, UPDATE, DELETE, CREATE, DROP, transactions ...


def _allow_all(*_):
    return sqlite3.SQLITE_OK


def run_query(conn: sqlite3.Connection, sql: str) -> tuple[pd.DataFrame, bool]:
    """(rows, truncated). Raises QueryRefused with a readable reason."""
    names = {r[0].lower() for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}
    forbidden = {n for n in names | {"sqlite_sequence", "sqlite_stat1", "sqlite_temp_master"} if not _allowed(n)}
    deadline = time.monotonic() + TIME_LIMIT_S
    conn.set_authorizer(make_authorizer(forbidden))
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    try:
        cur = conn.execute(sql)
        columns = [d[0] for d in cur.description or []]
        rows = cur.fetchmany(MAX_ROWS + 1)
    except sqlite3.DatabaseError as exc:
        message = str(exc)
        if "interrupted" in message:
            message = f"stopped after {TIME_LIMIT_S:g} s"
        elif "not authorized" in message or "prohibited" in message:
            message = "only reading (SELECT) the EduStream tables is allowed"
        raise QueryRefused(message) from None
    except (sqlite3.Warning, sqlite3.ProgrammingError) as exc:
        raise QueryRefused(str(exc)) from None
    finally:
        conn.set_authorizer(_allow_all)       # Python 3.10 cannot clear an authorizer with None (3.11+ can)
        conn.set_progress_handler(None, 0)
    return pd.DataFrame(rows[:MAX_ROWS], columns=columns), len(rows) > MAX_ROWS
