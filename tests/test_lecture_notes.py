"""M6b: the end-of-lecture pass (ARCHITECTURE §8.1.5) - validation, fallback, storage, and when it runs (N-4 logic)."""

import json
from types import SimpleNamespace

from agents import note_agent
from agents.notebook import (Grouper, LectureEnd, Memory, Window, build_lecture_notes, end_user_prompt,
                             lecture_fallback, lecture_from_reply)
from common import schemas
from common.config import load
from storage.db import connect_writer
from storage.db_sink import apply_batch

S0 = 1_792_051_200_000


def update(k, sid, title, is_new, points, terms=()):
    return {"schema": "notes.v2", "video_id": "python_l1", "update_index": k, "media_start": 90.0 * k,
            "media_end": 90.0 * k + 90, "window_starts": [S0 + k * 90_000], "section": {"id": sid, "title": title,
                                                                                      "is_new": is_new},
            "points": [{"section_id": sid, "text": t, "t": 90.0 * k + 10 * i, "kind": "point", "quote": t}
                       for i, t in enumerate(points)],
            "terms": [{"term": a, "definition": b, "t": 90.0 * k, "source": "lecture"} for a, b in terms],
            "generator": "llm", "created_ts": S0}


def lecture() -> tuple[Memory, list[dict]]:
    ups = [update(0, 1, "Introduction", True, ["Practice is the key to learning programming.",
                                               "Download the code before the lecture."]),
           update(1, 1, "Introduction", False, ["The course has three big goals."]),
           update(2, 2, "Computers", True, ["A computer performs calculations and remembers results."],
                  [("computer memory", "Where results are stored.")]),
           update(3, 2, "Computers", False, ["Declarative knowledge is statements of fact."],
                  [("declarative knowledge", "Statements of fact.")])]
    m = Memory("python_l1")
    for u in ups:
        m.apply(u, partition=0)
    return m, ups


def test_memory_knows_point_ids_partition_and_how_far_it_reaches():
    m, _ = lecture()
    assert [p["id"] for p in m.points] == ["u0p0", "u0p1", "u1p0", "u2p0", "u3p0"]
    assert (m.partition, m.media_end, m.lecture_notes_done) == (0, 360.0, False)


def test_the_prompt_is_trimmed_for_long_lectures_but_keeps_every_section():
    m, _ = lecture()
    for k in range(4, 60):                                    # a 90-minute lecture
        m.apply(update(k, 2, "Computers", False, [f"Point {k}: " + "detail " * 30]), partition=0)
    text, kept = end_user_prompt(m, cap_chars=3000)
    assert len(text) <= 3000 and kept < len(m.points)
    assert "Section 1: Introduction" in text and "Section 2: Computers" in text


def test_the_reply_is_validated_against_the_notebook():
    m, _ = lecture()
    reply = {"outline": [
        {"section_id": 1, "title": "How to succeed in 6.0001", "gist": "Practice.", "weak_points": ["u1p0", "u9p9"]},
        {"section_id": 7, "title": "A section that does not exist", "gist": "", "weak_points": []}],
        "glossary": [{"term": "Declarative knowledge", "definition": "Facts."}, {"term": "quantum entanglement",
                                                                                  "definition": "Not in this lecture."}],
        "questions": [{"question": f"Q{i}?", "answer": "A", "section_id": 2} for i in range(7)]}
    f = lecture_from_reply(m, reply)
    assert [(o["section_id"], o["title"], o["weak_points"]) for o in f["outline"]] == [
        (1, "How to succeed in 6.0001", ["u1p0"]), (2, "Computers", [])]                  # missing section kept
    assert [g["term"] for g in f["glossary"]] == ["Declarative knowledge", "computer memory"]   # collected term kept
    assert len(f["questions"]) == 3 and f["questions"][0]["t"] == 180.0     # 6 min lecture: 3; t = section start
    assert "summary" not in f                                                  # the notebook is the summary
    assert {"unknown_section_dropped", "section_missing_kept_live_title", "glossary_term_not_in_notebook",
            "questions_trimmed"} <= set(f["quality_flags"])
    schemas.validate("lecture_notes.v1", build_lecture_notes(m, f, "fake", 1.0, "last_window", 1))


def test_the_fallback_needs_no_llm_and_validates():
    m, _ = lecture()
    f = lecture_fallback(m, ["llm_unavailable:disabled"])
    assert "summary" not in f and [o["title"] for o in f["outline"]] == ["Introduction", "Computers"]
    assert {g["term"] for g in f["glossary"]} == {"computer memory", "declarative knowledge"}
    schemas.validate("lecture_notes.v1", build_lecture_notes(m, f, None, 1.0, "idle", 1))


def rec(topic, payload, offset):
    return SimpleNamespace(topic=topic, value=json.dumps(payload).encode(), partition=0, offset=offset,
                           key=b"python_l1")


def test_storing_sets_final_titles_and_weak_points_once():
    m, ups = lecture()
    notes = build_lecture_notes(m, {**lecture_fallback(m), "outline": [
        {"section_id": 1, "title": "How to succeed", "gist": "", "weak_points": ["u0p1"]},
        {"section_id": 2, "title": "What a computer does", "gist": "", "weak_points": []}],
        "generator": "llm"}, "fake", 1.0, "last_window", 5)
    records = [rec("final_notes", u, i) for i, u in enumerate(ups)] + [rec("lecture_notes", notes, 0)]
    conn = connect_writer(":memory:")
    assert apply_batch(conn, records, now=1, window_ms=30_000)["stored"] == 5
    titles = conn.execute("SELECT section_id, title, final_title FROM sections ORDER BY 1").fetchall()
    assert titles == [(1, "Introduction", "How to succeed"), (2, "Computers", "What a computer does")]
    assert conn.execute("SELECT update_index, seq FROM points WHERE weak = 1").fetchall() == [(0, 1)]
    before = {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2").fetchall()
              for t in ("lecture_notes", "sections", "points")}
    other = {**notes, "outline": [{**o, "title": "Changed later"} for o in notes["outline"]]}
    assert apply_batch(conn, [rec("lecture_notes", other, 1)], now=2, window_ms=30_000) == {"duplicate": 1}
    assert {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2").fetchall() for t in before} == before


# ------------------------------------------------------------------------------- when the agent finishes a lecture
class FakeProducer:
    def __init__(self):
        self.sent = []

    def send(self, topic, value=None, key=None, partition=None, timestamp_ms=None):
        self.sent.append((topic, partition, json.loads(value)))
        return SimpleNamespace(get=lambda timeout=None: None, add_callback=lambda f: None,
                               add_errback=lambda f: None)


class NoLLM:
    def complete_json(self, *a, **k):
        return SimpleNamespace(ok=False, reason="disabled", model=None, data=None)


def agent_with(memory, end):
    log = SimpleNamespace(info=lambda *a, **k: None, warn=lambda *a, **k: None, error=lambda *a, **k: None)
    agent = note_agent.NoteAgent(load(), log, NoLLM())
    agent.producer = FakeProducer()
    agent.consumer = SimpleNamespace(commit=lambda offsets: None)
    agent.memories[memory.video_id] = memory
    agent._lecture_ends = lambda vids: {v: end for v in vids if v == memory.video_id}
    return agent


def test_a_lecture_is_finished_once_the_notebook_reaches_its_last_chunk():
    m, _ = lecture()                                            # notebook reaches 360 s = chunk 35
    agent = agent_with(m, LectureEnd(last_chunk_id=35, flush_seen_at=1000.0))
    agent.timers(1001.0)
    agent.timers(1002.0)
    sent = [s for s in agent.producer.sent if s[0] == "lecture_notes"]
    assert len(sent) == 1 and sent[0][1] == 0 and sent[0][2]["ended_by"] == "last_window"
    assert sent[0][2]["generator"] == "extractive" and m.lecture_notes_done


def test_a_missing_last_window_is_finished_after_30_s_of_quiet():
    m, _ = lecture()
    agent = agent_with(m, LectureEnd(last_chunk_id=40, flush_seen_at=1000.0))   # notebook stops at chunk 35
    agent.timers(1029.0)
    assert agent.producer.sent == []
    agent.timers(1030.0)
    assert [s[2]["ended_by"] for s in agent.producer.sent] == ["idle"]


def test_never_while_an_update_is_still_held_and_only_after_the_last_one():
    import time
    m, _ = lecture()
    now = time.time()
    agent = agent_with(m, LectureEnd(last_chunk_id=50, flush_seen_at=now - 100))   # last chunk never arrives
    window = Window("python_l1", S0, S0 + 30_000, S0, [{"chunk_id": 36, "start_time": 360.0, "end_time": 370.0,
                                                        "text": "Results are stored in memory."}], 0, 99,
                    arrived=now - 5)
    agent.grouper(0).add(window, m.last_sent)
    agent.timers(now)
    assert agent.producer.sent == []                                  # 1. held, lecture not over yet: nothing
    agent.grouper(0).held.windows[0].arrived = now - 40
    agent.timers(now)
    assert [s[0] for s in agent.producer.sent] == ["final_notes"]     # 2. the held update first (idle end) ...
    agent.timers(now + 10)
    assert [s[0] for s in agent.producer.sent] == ["final_notes"]     # ... the end pass waits for quiet ...
    agent.timers(now + 31)
    agent.timers(now + 60)
    assert [s[0] for s in agent.producer.sent] == ["final_notes", "lecture_notes"]   # 3. ... then exactly once


def test_review_questions_grow_with_the_lecture():
    from agents.notebook import end_prompt, questions_wanted
    m, _ = lecture()
    assert questions_wanted(m) == 3
    m.media_end = 2 * 3600.0                                    # a 2-hour lecture
    assert questions_wanted(m) == 8 and "Exactly 8 review questions" in end_prompt(m)


def test_a_long_lecture_is_trimmed_evenly_so_every_section_is_summarised():
    from agents.lecture_tools import notebook_digest
    ups = []
    for k in range(30):                                          # 45 minutes, 3 sections of 10 updates
        sid = k // 10 + 1
        ups.append(update(k, sid, f"Topic {sid}", k % 10 == 0, [f"Point {k}a about topic {sid}.",
                                                               f"Point {k}b about topic {sid}."]))
    conn = connect_writer(":memory:")
    apply_batch(conn, [rec("final_notes", u, i) for i, u in enumerate(ups)], now=1, window_ms=30_000)
    lines = notebook_digest(conn, "python_l1", 0, 1e9, limit=24)
    headings = [ln["text"] for ln in lines if ln["text"].startswith("Section ")]
    assert headings == ["Section 1: Topic 1", "Section 2: Topic 2", "Section 3: Topic 3"] and len(lines) <= 24
    per_section = [sum(1 for ln in lines if f"about topic {s}." in ln["text"]) for s in (1, 2, 3)]
    assert min(per_section) == max(per_section) == 7               # an even share, not the first 21 points
    assert any(f"Point {k}" in ln["text"] for k in (7, 8, 9) for ln in lines)   # reaches the end of section 1
