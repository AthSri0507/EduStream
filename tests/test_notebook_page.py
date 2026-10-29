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


def test_additions_are_placed_by_the_query_and_shown_on_the_page(tmp_path):
    from agents import additions as AD
    from common.config import TOPIC_USER_NOTES
    conn = connect_writer(tmp_path / "a.db")
    passed = fixture("consolidation/valid-llm.json")                    # topics 2 (continued, absent) and 3
    first = {**fixture("consolidation/valid-fallback.json"), "media_end": 520.0}
    apply_batch(conn, run_records() + [rec("final_notes", first, 1), rec("final_notes", passed, 2)], now=1,
                window_ms=WINDOW_MS)
    flow = {"shape": "flowchart", "title": "Being a machine <b>", "nodes": [
        {"id": "a", "label": "Pick a random number", "kind": "step", "added": False, "t": 530.0},
        {"id": "b", "label": "Is it on the sheet?", "kind": "decision", "added": True, "t": None},
        {"id": "c", "label": "Call that student", "kind": "end", "added": False, "t": None}],
        "edges": [{"from": "a", "to": "b", "label": ""}, {"from": "b", "to": "c", "label": "yes"}]}
    table = {"shape": "table", "title": "Power", "columns": ["Term", "Meaning"],
             "rows": [{"cells": ["Power", "1 - beta"], "added": [True, True], "t": None}]}
    in_topic = AD.payload_add("python_l1", flow, [525.0, 640.0], "a flowchart of the recipe", True, "m", now_ms=5)
    beyond = AD.payload_add("python_l1", table, None, "what is power?", True, "m", now_ms=6)
    removed = AD.payload_add("python_l1", table, [525.0, 640.0], "gone", True, "m", now_ms=7)
    records = [rec(TOPIC_USER_NOTES, p, i) for i, p in enumerate((in_topic, beyond, removed))]
    records.append(rec(TOPIC_USER_NOTES, AD.payload_remove("python_l1", removed["addition_id"], now_ms=8), 3))
    apply_batch(conn, records, now=2, window_ms=WINDOW_MS)
    nb = queries.notebook(conn, "python_l1")
    topic3 = next(t for t in nb["topics"] if t["n"] == 3)
    assert [a["addition_id"] for a in topic3["additions"]] == [in_topic["addition_id"]]
    assert topic3["additions"][0]["after"] == 0                          # after "The recipe the students gave"
    assert [a["question"] for a in nb["beyond"]] == ["what is power?"]   # the removed one is gone
    page = nbh.topic_html(topic3, "dark")
    assert "YOUR ADDITION · FLOWCHART · Being a machine &lt;b&gt;" in page and 'src="data:image/png;base64,' in page
    assert page.index("The recipe the students gave") < page.index("YOUR ADDITION") < page.index("Picking the number")
    assert "You asked: “a flowchart of the recipe”" in page and "† 1 of 3 boxes" in page
    assert "<td class=\"add\">1 - beta †</td>" in nbh.beyond_html(nb)
