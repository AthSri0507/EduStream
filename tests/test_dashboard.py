"""Dashboard smoke test: renders headlessly (Streamlit AppTest) against a database built by the real sink logic.

Pages (docs/UI_DESIGN.md): In class (landing with no class running), Revise (any lecture's notes and the assistant)
and System (pipeline health, window stats, alerts, data)."""

import re
import time
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from storage.db import connect_writer
from storage.db_sink import apply_batch
from tests.test_db_sink import WINDOW_MS, notebook_records, run_records

APP = str(Path(__file__).resolve().parents[1] / "dashboard" / "app.py")


@pytest.fixture(autouse=True)
def no_real_recorder(tmp_path, monkeypatch):
    """The pages read the live recorder's state files; tests must not see a class running on this laptop."""
    from dashboard import live_panel
    monkeypatch.setattr(live_panel, "STATE_DIR", tmp_path / "lectures")


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "edustream.db"
    conn = connect_writer(path)
    apply_batch(conn, run_records(), now=1_792_051_300_000, window_ms=WINDOW_MS)
    conn.close()
    monkeypatch.setenv("EDU_DB", str(path))
    return path


@pytest.fixture
def notes_db(tmp_path, monkeypatch):
    path = tmp_path / "edustream.db"
    conn = connect_writer(path)
    apply_batch(conn, run_records() + notebook_records(), now=1_792_051_300_000, window_ms=WINDOW_MS)
    conn.close()
    monkeypatch.setenv("EDU_DB", str(path))
    return path


def revise(at: AppTest) -> AppTest:
    return at.switch_page("app_pages/revise.py").run()


def test_dashboard_renders_all_pages_without_errors(db):
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception, at.exception
    assert not at.tabs and not at.sidebar.button                 # no tab bar, no sidebar (30 Oct)
    assert [s.value for s in at.subheader] == ["Join a live class", "Upload a lecture recording", "Recent lectures"]
    assert [b.label for b in at.button] == ["Start class", "Open in Revise"]   # the form and one lecture
    assert not at.metric                                          # pipeline numbers are not in the student view
    at = revise(at)
    assert not at.exception, at.exception
    assert at.selectbox(key="notes_lecture").value == "python_l1" and at.chat_input(key="a_input")
    at.switch_page("app_pages/system.py").run()
    assert not at.exception, at.exception
    assert [t.label for t in at.tabs] == ["Pipeline health", "Window stats", "Alerts", "Data"]
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Lectures"] == "1"
    assert metrics["Chunks transcribed"] == "3"
    assert metrics["Windows closed"] == "1"
    assert metrics["Notebook updates"] == "1"          # falls back to the notes.v1 count (runs before M6a)
    assert metrics["Consolidations"] == "0"
    assert metrics["Alerts"] == "1"
    assert metrics["LATE_DROP"] == "0"


def test_open_in_revise_opens_that_lecture(db):
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.button(key="open_python_l1").click().run()
    assert not at.exception, at.exception
    assert at.selectbox(key="notes_lecture").value == "python_l1"


def test_dashboard_waits_politely_without_a_database(tmp_path, monkeypatch):
    monkeypatch.setenv("EDU_DB", str(tmp_path / "missing.db"))
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert any("not running on this laptop" in i.value for i in at.info)


def html_of(at) -> str:
    return " ".join(h.proto.body for h in at.get("html"))


def test_revise_renders_topics_elements_and_glossary(notes_db):
    at = revise(AppTest.from_file(APP, default_timeout=60).run())
    assert not at.exception, at.exception
    labels = [x.label for x in at.expander]
    assert any(label.startswith("3. Being a machine: following a recipe") for label in labels)
    page = html_of(at)
    assert "Check yourself:" in page and "<ol>" in page and "<pre>import random" in page and "Remember:" in page
    assert "Draft notes since" not in page                                         # the last pass was final
    assert "<summary>Imperative knowledge</summary>" not in page                      # contents and glossary: off
    at.toggle(key="show_toc").set_value(True).run()
    assert "<summary>Imperative knowledge</summary>" in html_of(at)                   # the glossary, tap to open


def test_layouts_and_an_answer_survives_a_layout_change(notes_db, monkeypatch):
    monkeypatch.setenv("LLM_ENABLED", "false")
    at = revise(AppTest.from_file(APP, default_timeout=60).run())
    assert not at.exception, at.exception
    assert at.segmented_control(key="layout").value == "Notes and assistant"
    assert at.toggle(key="a_outside").value is False      # answers from the lecture only unless switched on
    assert not at.button                                   # no prompt buttons: the student types (owner, 30 Oct)
    at.chat_input(key="a_input").set_value("I didn't get the last 10 seconds").run()
    at.segmented_control(key="layout").set_value("Notes only").run()                  # the assistant is hidden
    assert not at.exception, at.exception
    assert not at.chat_input
    time.sleep(1.5)                                        # the turn runs in a background thread meanwhile
    at.segmented_control(key="layout").set_value("Assistant wide").run()
    for _ in range(20):
        if any(x.label.startswith("What the lecturer said") for x in at.expander):
            break
        time.sleep(0.25)
        at.run()
    assert not at.exception, at.exception
    assert any(x.label.startswith("What the lecturer said") for x in at.expander)    # answered; quotes folded
    assert any("Explaining" in c.value for c in at.caption)


def test_the_data_tab_runs_a_read_only_query(notes_db):
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.query_params["view"] = "Data"
    at.switch_page("app_pages/system.py").run()
    assert not at.exception, at.exception
    at.button(key="data_run").click().run()
    assert not at.exception, at.exception
    assert len(at.dataframe) == 1 and len(at.dataframe[0].value) == 1          # one lecture
    at.text_area[0].set_value("DELETE FROM chunks").run()
    at.button(key="data_run").click().run()
    assert at.error and "Query refused" in at.error[0].value


JARGON = re.compile(r"\b(kafka|whisper|transcripts?|pipeline|partitions?|chunks?|windows?|consumers?|offsets?|dlq"
                    r"|asr_score|llm|models?|tokens?)\b", re.I)


def student_text(at) -> str:
    """What a student reads on a page: messages, captions, labels and our HTML (status row, notes)."""
    parts = [x.value for x in list(at.info) + list(at.warning) + list(at.error) + list(at.caption) + list(at.markdown)
             + list(at.subheader) + list(at.success)]
    parts += [x.label for x in list(at.button) + list(at.expander)] + [html_of(at)]
    return " ".join(parts)


def student_pages(at) -> list[str]:
    texts = [student_text(at)]
    at = revise(at)
    if at.get("toggle"):
        at.toggle(key="show_toc").set_value(True).run()
    texts.append(student_text(at))
    return texts


def test_student_facing_text_never_mentions_the_pipeline(tmp_path, monkeypatch):
    # .claude/skills/edustream-ui/SKILL.md rule 2: no Kafka, Whisper, transcripts or pipeline on In class, Revise or
    # the status row (the System page may).
    monkeypatch.setenv("EDU_DB", str(tmp_path / "missing.db"))
    texts = student_pages(AppTest.from_file(APP, default_timeout=60).run())
    empty = tmp_path / "empty.db"
    connect_writer(empty).close()
    monkeypatch.setenv("EDU_DB", str(empty))
    texts += student_pages(AppTest.from_file(APP, default_timeout=60).run())
    path = tmp_path / "edustream.db"
    conn = connect_writer(path)
    apply_batch(conn, run_records() + notebook_records(), now=1_792_051_300_000, window_ms=WINDOW_MS)
    conn.close()
    monkeypatch.setenv("EDU_DB", str(path))
    texts += student_pages(AppTest.from_file(APP, default_timeout=60).run())
    from dashboard import in_class_page
    from dashboard import notebook_html as nbh
    from dashboard import status
    texts.append(in_class_page.UPLOAD_NOTE)
    for finished, reach in ((False, 0.0), (False, 90.0), (True, 90.0)):    # first 2 minutes, live, finished
        nb = {"topics": [], "drafts": [], "latest_k": None, "since": 0.0, "reach": reach, "said_until": 100.0,
              "now_text": "", "glossary": [], "info": [], "finished": finished, "status": "Next notes after 03:00."}
        texts.append(nbh.head_html(nb) + nbh.live_html(nb) + nbh.toc_html(nb))
    now = 1_000_000_000
    live = {"video_id": "v", "title": "DBMS", "live": True, "said": 990.0, "age": 5.0}
    rec = {"video_id": "v", "status": "active", "updated_ts": now, "last_chunk_sent": 9, "devices": ["Headphones"]}
    for lecture, recorder in ((live, None), ({**live, "age": 120.0}, None), ({**live, "live": False}, None),
                              (live, {**rec, "level_dbfs": -80.0}), (live, {**rec, "level_dbfs": -45.0}),
                              (live, {**rec, "updated_ts": now - 60_000})):
        current = status.compute(now, lecture, recorder)
        texts.append(status.row_html(current) + current["title"])
    found = sorted({m.group(0).lower() for t in texts for m in JARGON.finditer(t)})
    assert not found, found


def test_revise_offers_one_export_menu_with_three_formats(notes_db):
    at = revise(AppTest.from_file(APP, default_timeout=60).run())
    assert not at.exception, at.exception
    labels = [b.proto.label for b in at.get("download_button")]
    assert labels == ["Markdown", "Word", "PDF"]
