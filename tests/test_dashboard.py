"""Dashboard smoke test: renders headlessly (Streamlit AppTest) against a database built by the real sink logic."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from storage.db import connect_writer
from storage.db_sink import apply_batch
from tests.test_db_sink import WINDOW_MS, run_records

APP = str(Path(__file__).resolve().parents[1] / "dashboard" / "app.py")


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "edustream.db"
    conn = connect_writer(path)
    apply_batch(conn, run_records(), now=1_792_051_300_000, window_ms=WINDOW_MS)
    conn.close()
    monkeypatch.setenv("EDU_DB", str(path))
    return path


def test_dashboard_renders_all_tabs_without_errors(db):
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception, at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Lectures"] == "1"
    assert metrics["Chunks transcribed"] == "3"
    assert metrics["Windows closed"] == "1"
    assert metrics["Notes"] == "1"
    assert metrics["Alerts"] == "1"
    assert metrics["LATE_DROP"] == "0"
    assert [t.label for t in at.tabs] == ["Live notes", "Window stats", "Alerts", "Pipeline health"]
    assert at.selectbox(key="notes_lecture").value == "python_l1"


def test_dashboard_waits_politely_without_a_database(tmp_path, monkeypatch):
    monkeypatch.setenv("EDU_DB", str(tmp_path / "missing.db"))
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert any("Waiting for the database" in i.value for i in at.info)
