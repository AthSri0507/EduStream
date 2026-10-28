"""Dashboard smoke test: renders headlessly (Streamlit AppTest) against a database built by the real sink logic."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from storage.db import connect_writer
from storage.db_sink import apply_batch
from tests.test_db_sink import WINDOW_MS, notebook_records, run_records

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
    assert [t.label for t in at.tabs] == ["Notebook", "Data", "Window stats", "Alerts", "Pipeline health"]
    assert at.selectbox(key="notes_lecture").value == "python_l1"
    assert not at.metric                                # pipeline numbers are not in the student view (decision 5)
    at = AppTest.from_file(APP, default_timeout=60)
    at.query_params["tab"] = "Pipeline health"
    at.run()
    assert not at.exception, at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Lectures"] == "1"
    assert metrics["Chunks transcribed"] == "3"
    assert metrics["Windows closed"] == "1"
    assert metrics["Notebook updates"] == "1"          # falls back to the notes.v1 count (runs before M6a)
    assert metrics["Consolidations"] == "0"
    assert metrics["Alerts"] == "1"
    assert metrics["LATE_DROP"] == "0"


def test_dashboard_waits_politely_without_a_database(tmp_path, monkeypatch):
    monkeypatch.setenv("EDU_DB", str(tmp_path / "missing.db"))
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert any("Waiting for the database" in i.value for i in at.info)


def html_of(at) -> str:
    return " ".join(h.proto.body for h in at.get("html"))


def test_the_notebook_tab_renders_topics_elements_and_glossary(tmp_path, monkeypatch):
    path = tmp_path / "edustream.db"
    conn = connect_writer(path)
    apply_batch(conn, run_records() + notebook_records(), now=1_792_051_300_000, window_ms=WINDOW_MS)
    conn.close()
    monkeypatch.setenv("EDU_DB", str(path))
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception, at.exception
    labels = [x.label for x in at.expander]
    assert any(label.startswith("3. Being a machine: following a recipe") for label in labels)
    page = html_of(at)
    assert "Check yourself:" in page and "<ol>" in page and "<pre>import random" in page and "Remember:" in page
    assert "<dt>Imperative knowledge</dt>" in page                                    # glossary in the rail
    assert "Finished" in page and "LIVE NOTES" not in page                            # the last pass was final


def test_the_assistant_answers_from_the_evidence_when_the_llm_is_off(tmp_path, monkeypatch):
    import time
    path = tmp_path / "edustream.db"
    conn = connect_writer(path)
    apply_batch(conn, run_records() + notebook_records(), now=1_792_051_300_000, window_ms=WINDOW_MS)
    conn.close()
    monkeypatch.setenv("EDU_DB", str(path))
    monkeypatch.setenv("LLM_ENABLED", "false")
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception, at.exception
    assert not at.button                                  # a plain chat: no buttons (decision 15 Oct)
    assert at.toggle(key="a_outside").value is False      # answers from the lecture only unless switched on
    at.chat_input(key="a_input").set_value("I didn't get the last 10 seconds").run()
    for _ in range(20):                                    # the turn runs in a background thread
        time.sleep(0.25)
        at.run()
        if any("What was said" in c.value for c in at.caption):
            break
    assert not at.exception, at.exception
    captions = " ".join(c.value for c in at.caption)
    assert "Explaining" in captions and "What was said:" in captions


def test_the_data_tab_runs_a_read_only_query(tmp_path, monkeypatch):
    path = tmp_path / "edustream.db"
    conn = connect_writer(path)
    apply_batch(conn, run_records() + notebook_records(), now=1_792_051_300_000, window_ms=WINDOW_MS)
    conn.close()
    monkeypatch.setenv("EDU_DB", str(path))
    at = AppTest.from_file(APP, default_timeout=60)
    at.query_params["tab"] = "Data"
    at.run()
    assert not at.exception, at.exception
    at.button(key="data_run").click().run()
    assert not at.exception, at.exception
    assert len(at.dataframe) == 1 and len(at.dataframe[0].value) == 1          # one lecture
    at.text_area[0].set_value("DELETE FROM chunks").run()
    at.button(key="data_run").click().run()
    assert at.error and "Query refused" in at.error[0].value


def test_the_notebook_offers_the_three_downloads(tmp_path, monkeypatch):
    path = tmp_path / "edustream.db"
    conn = connect_writer(path)
    apply_batch(conn, run_records() + notebook_records(), now=1_792_051_300_000, window_ms=WINDOW_MS)
    conn.close()
    monkeypatch.setenv("EDU_DB", str(path))
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception, at.exception
    labels = [b.proto.label for b in at.get("download_button")]
    assert labels == ["Markdown", "Word", "PDF"]
