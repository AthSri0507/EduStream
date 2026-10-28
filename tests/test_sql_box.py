"""Q-1: the Data tab's read-only SQL box (ARCHITECTURE §8.3, A19)."""

import pytest

from dashboard.sql_box import MAX_ROWS, READY_MADE, QueryRefused, run_query
from storage.db import connect_readonly, connect_writer
from storage.db_sink import apply_batch
from tests.test_db_sink import WINDOW_MS, notebook_records, run_records


@pytest.fixture
def ro(tmp_path):
    path = tmp_path / "edustream.db"
    w = connect_writer(path)
    apply_batch(w, run_records() + notebook_records(), now=1, window_ms=WINDOW_MS)
    w.close()
    (tmp_path / "other.db").write_bytes(b"")
    conn = connect_readonly(path)
    yield conn, tmp_path
    conn.close()


def test_select_on_listed_tables_works(ro):
    conn, _ = ro
    df, truncated = run_query(conn, "SELECT video_id, chunk_id FROM chunks ORDER BY chunk_id")
    assert list(df.columns) == ["video_id", "chunk_id"] and len(df) == 3 and not truncated


def test_every_ready_made_query_runs(ro):
    conn, _ = ro
    for name, sql in READY_MADE.items():
        run_query(conn, sql)                                   # must not raise


@pytest.mark.parametrize("sql", [
    "INSERT INTO alerts(alert_id) VALUES ('x')",
    "DELETE FROM chunks",
    "UPDATE lectures SET title = 'x'",
    "DROP TABLE chunks",
    "CREATE TABLE t(x)",
    "PRAGMA journal_mode = DELETE",
    "SELECT load_extension('evil')",
    "SELECT 1; DELETE FROM chunks",
])
def test_anything_but_reading_is_refused(ro, sql):
    conn, _ = ro
    with pytest.raises(QueryRefused):
        run_query(conn, sql)
    assert run_query(conn, "SELECT COUNT(*) AS n FROM chunks")[0]["n"][0] == 3     # nothing changed


def test_other_files_cannot_be_attached(ro):
    conn, tmp = ro
    with pytest.raises(QueryRefused):
        run_query(conn, f"ATTACH DATABASE '{(tmp / 'other.db').as_posix()}' AS other")


def test_slow_queries_stop_and_rows_are_capped(ro):
    conn, _ = ro
    with pytest.raises(QueryRefused, match="stopped"):
        run_query(conn, "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT COUNT(*) FROM r")
    df, truncated = run_query(conn, "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE n < 5000)"
                                    " SELECT n FROM r")
    assert len(df) == MAX_ROWS and truncated


def test_tables_outside_the_list_are_refused(ro, tmp_path):
    from dashboard import sql_box
    conn, _ = ro
    original = sql_box.ALLOWED
    sql_box.ALLOWED = original - {"dlq"}                       # pretend dlq were private
    try:
        with pytest.raises(QueryRefused):
            run_query(conn, "SELECT * FROM dlq")
    finally:
        sql_box.ALLOWED = original
