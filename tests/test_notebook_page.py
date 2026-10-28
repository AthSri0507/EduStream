"""UI-1: the notebook page's HTML (NOTEBOOK_DESIGN §6.4, §11.6): every model-written text is escaped, the live box
highlights only the newest sentences, and drafts fold on the dashboard exactly as in the Note Agent."""

import json

from dashboard import notebook_html as nbh
from dashboard import queries
from storage.db import connect_writer
from storage.db_sink import apply_batch
from tests.test_db_sink import WINDOW_MS, fixture, rec, run_records

EVIL = '<script>alert("x")</script><img src=x onerror=alert(1)>'


def test_every_text_from_the_notes_is_escaped():
    el = {"kind": "para", "t": 10.0, "said": EVIL, "lead": EVIL, "sentences": [EVIL + " is bad."],
          "terms": [{"term": "<script>", "definition": EVIL}], "background": EVIL}
    topic = {"n": 1, "title": EVIL, "start": 0.0, "end": 60.0, "question": EVIL, "answer": EVIL, "elements": [
        el, {"kind": "example", "t": 1.0, "said": "", "title": EVIL, "sentences": [EVIL], "steps": [EVIL], "code": EVIL},
        {"kind": "table", "t": 2.0, "said": "", "caption": EVIL, "columns": [EVIL, "b"], "rows": [[EVIL, EVIL]]},
        {"kind": "steps", "t": 3.0, "said": "", "lead": EVIL, "items": [EVIL, EVIL]},
        {"kind": "code", "t": 4.0, "said": "", "caption": EVIL, "code": EVIL},
        {"kind": "remember", "t": 5.0, "said": "", "text": EVIL}]}
    nb = {"topics": [topic], "drafts": [dict(el, sentence_k=[3])], "latest_k": 3, "since": 60.0, "reach": 90.0,
          "said_until": 100.0, "now_text": EVIL, "glossary": [{"term": EVIL, "definition": EVIL}],
          "info": [{"text": EVIL}], "finished": False, "status": EVIL}
    page = nbh.topic_html(topic) + nbh.live_html(nb) + nbh.rail_html(nb) + nbh.head_html(nb)
    assert "<script>" not in page and "<img" not in page
    assert "&lt;script&gt;" in page
    assert "\\<script\\>" in nbh.topic_label(topic)              # expander labels are markdown: escaped too


def test_the_live_box_highlights_only_the_newest_update():
    draft = {"kind": "para", "t": 0.0, "said": "", "lead": "Computers", "background": None,
             "terms": [{"term": "memory", "definition": "Memory stores results."}],
             "sentences": ["Old sentence.", "Memory stores results, and memory is fast."], "sentence_k": [4, 5]}
    html = nbh.element_html(draft, fresh=5)
    assert '<mark class="fresh"><strong>Memory</strong> stores results, and memory is fast.</mark>' in html
    assert '<mark class="fresh">Old' not in html                   # only the newest update; a term bold only once


def test_the_dashboard_folds_drafts_and_hides_consolidated_ones(tmp_path):
    live = fixture("notes_v3/valid-llm.json")
    earlier = {**fixture("notes_v3/valid-extractive.json"), "update_index": 6, "media_start": 540.0,
               "media_end": 630.0}
    earlier["elements"] = [{**earlier["elements"][0], "id": "u6e0", "t": 600.0}]
    conn = connect_writer(tmp_path / "e.db")
    apply_batch(conn, run_records() + [rec("final_notes", earlier, 1), rec("final_notes", live, 2)], now=1,
                window_ms=WINDOW_MS)
    nb = queries.notebook(conn, "python_l1")
    assert [len(d["sentences"]) for d in nb["drafts"]] == [3, 1]                 # u7e0 continued u6e0
    assert nb["drafts"][0]["sentence_k"] == [6, 6, 7] and nb["latest_k"] == 7
    assert nb["info"] == [{"text": "Problem set 0 is due on Thursday.", "t": 640.0}]
    one_pass = {**fixture("consolidation/valid-fallback.json"), "media_end": 620.0}
    apply_batch(conn, [rec("final_notes", one_pass, 3)], now=2, window_ms=WINDOW_MS)
    nb = queries.notebook(conn, "python_l1")
    assert [d["id"] for d in nb["drafts"]] == ["u7e1"] and nb["since"] == 620.0
    assert [t["title"] for t in nb["topics"]] == ["Part 1"] and json.dumps(nb)          # serialisable
