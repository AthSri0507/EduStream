"""N-3: consolidation (NOTEBOOK_DESIGN §4, §11.5, §11.10): when a pass runs, how a reply becomes topics, the
fallback, and how the Note Agent paces, defers and finishes. Pure logic plus the agent with fakes; no Kafka, no LLM."""

import json
from types import SimpleNamespace

import pytest

from agents import consolidation as C
from agents import note_agent
from agents.notebook import Held, LectureEnd, Memory, Window, build_update, extractive_live
from common import schemas
from common.config import load

S0 = 1_792_051_200_000
COMPUTERS = ["A computer does two things: it performs calculations and it remembers results.",
             "It performs a billion calculations per second.",
             "The results are stored in computer memory, hundreds of gigabytes."]
KNOWLEDGE = ["Declarative knowledge is statements of fact.",
             "Imperative knowledge is a recipe, a sequence of steps.",
             "The square root of x is y such that y times y is x.",
             "Problem set zero is due on Thursday, so start early."]


def text_at(t: float) -> str:
    pool = COMPUTERS if t < 180 else KNOWLEDGE
    return pool[int(t // 10) % len(pool)]


def chunks(k: int) -> list[dict]:
    return [{"chunk_id": c, "start_time": 10.0 * c, "end_time": 10.0 * c + 10, "text": text_at(10.0 * c)}
            for c in range(9 * k, 9 * k + 9)]


def lecture(updates: int) -> Memory:
    """A memory after `updates` live updates, each written by the extractive fallback."""
    m = Memory("python_l1")
    for k in range(updates):
        held = Held("python_l1", k, [Window("python_l1", S0 + k * 90_000, S0 + k * 90_000 + 30_000, S0, chunks(k), 0, k)])
        m.apply_update(build_update(held, extractive_live(m, chunks(k), k), None, 0.0, now_ms=S0), partition=0)
    return m


def el(text, quote, topic=None, **extra):
    return {"kind": "para", "lead": "", "text": text, "terms": [], "quote": quote,
            **({"topic": topic} if topic else {}), **extra}


REPLY = {
    "topics": [{"n": 1, "title": "What a computer does", "starts_at": "00:00"},
               {"n": 2, "title": "Declarative and imperative knowledge", "starts_at": "03:00"}],
    "elements": [
        el("A computer performs calculations and remembers results. It performs a billion calculations per second.",
           "it performs calculations and it remembers results", 1, lead="What a computer does"),
        el("Declarative knowledge is statements of fact. Imperative knowledge is a recipe, a sequence of steps.",
           "Declarative knowledge is statements of fact", 2, terms=["Declarative knowledge", "Imperative knowledge"]),
        el("The results are stored in computer memory.", "The results are stored in computer memory", 2),
    ],
    "questions": [{"topic": 1, "q": "What two things does a computer do?",
                   "answer": "It performs calculations and remembers the results."},
                  {"topic": 2, "q": "When is problem set zero due?", "answer": "On Thursday."}],
}


# ------------------------------------------------------------------------------------------------ when (§4.1)
def test_a_pass_is_due_every_six_minutes_and_at_the_lecture_end():
    assert C.due(lecture(3), lecture_ended=False) is None                     # 4.5 minutes of drafts
    assert C.due(lecture(4), False) == C.Plan(0.0, 360.0, "open", False)
    assert C.due(lecture(9), False) == C.Plan(0.0, 540.0, "closed", False)    # capped; 13.5 min waiting: closed
    assert C.due(lecture(3), lecture_ended=True) == C.Plan(0.0, 270.0, "closed", True, ending=True)
    m = lecture(4)
    m.finished = True
    assert C.due(m, True) is None


# ------------------------------------------------------------------------------------------------ a reply
def run(memory, reply, plan=None):
    plan = plan or C.due(memory, False)
    fields = C.from_reply(memory, json.loads(json.dumps(reply)), plan, memory.chunks(plan.end))
    payload = C.build_pass(memory, fields, "openai/gpt-oss-120b", 10.0, now_ms=S0)
    assert schemas.decode(schemas.encode("consolidation.v1", payload), "consolidation.v1") == payload
    return payload


def test_a_reply_becomes_topics_in_spoken_order_with_a_grounded_glossary_and_questions():
    p = run(lecture(4), REPLY)
    assert [(t["n"], t["title"], t["media_start"], t["media_end"], t["new"]) for t in p["topics"]] == [
        (1, "What a computer does", 0.0, 180.0, True), (2, "Declarative and imperative knowledge", 180.0, 360.0, True)]
    # elements go to the topic their time falls in, not the one the model named
    assert [(e["topic"], e["t"]) for e in p["elements"]] == [(1, 0.0), (1, 20.0), (2, 200.0)]
    assert any(f == "element_topic_by_time" for f in p["quality_flags"])
    assert [g["term"] for g in p["glossary"]] == ["Declarative knowledge", "Imperative knowledge"]
    assert p["topics"][0]["question"]["q"] == "What two things does a computer do?"
    assert p["topics"][1]["question"] is None and "logistics_question" in p["quality_flags"]
    assert p["generator"] == "llm" and p["pass_index"] == 0 and p["final"] is False


def test_a_topic_still_in_progress_is_handed_over_and_its_drafts_stay_live():
    m = lecture(4)
    p = run(m, {**REPLY, "in_progress_from": "03:00"})
    assert p["media_end"] == 180.0 and [t["n"] for t in p["topics"]] == [1] and "element_after_cut" in p["quality_flags"]
    m.apply_pass(p)
    assert m.consolidated_to == 180.0 and all(d["t"] >= 180.0 for d in m.drafts) and len(m.drafts) == 2
    assert min(c["start_time"] for c in m.transcript.values()) == 180.0
    assert "Finished topics: 1. What a computer does (00:00-03:00)" in m.index()


def test_a_short_topic_joins_its_neighbour_and_a_continuing_one_joins_the_last_finished_topic():
    m = lecture(4)
    short = {**REPLY, "topics": [{"n": 1, "title": "What a computer does", "starts_at": "00:00"},
                                 {"n": 2, "title": "Knowledge", "starts_at": "05:00"}]}
    p = run(m, short)                                            # topic 2 is 60 s long: merged into topic 1
    assert [(t["title"], t["media_end"]) for t in p["topics"]] == [("What a computer does", 360.0)]
    m.apply_pass(p)
    for k in range(4, 8):                                        # 6 more minutes, all about knowledge
        held = Held("python_l1", k, [Window("python_l1", S0, S0 + 1, S0, chunks(k), 0, k)])
        m.apply_update(build_update(held, extractive_live(m, chunks(k), k), None, 0.0, now_ms=S0))
    nxt = {"topics": [{"n": 2, "title": "More on knowledge", "starts_at": "06:00", "continues": True}],
           "elements": [el("The square root of x is y such that y times y is x.",
                           "The square root of x is y such that y times y is x", 2)],
           "questions": [{"topic": 2, "q": "What is a square root?", "answer": "y such that y times y is x."}]}
    plan = C.due(m, False)
    assert "continues" in C.system_prompt(m, plan)
    p2 = run(m, nxt, plan)
    assert [(t["n"], t["new"], t["media_end"]) for t in p2["topics"]] == [(1, False, 720.0)]
    assert [e["topic"] for e in p2["elements"]] == [1] and p2["topics"][0]["question"] is None   # topic 1 had one
    m.apply_pass(p2)
    assert len(m.topics) == 1 and m.topics[0]["end"] == 720.0
    assert len(m.topics[0]["elements"]) == len(p["elements"]) + 1


def test_continues_never_grows_a_topic_past_fifteen_minutes():
    # Run 30 Oct: "continues" on every pass turned the whole Hypothesis lecture into one 61-minute topic.
    last = {"n": 1, "title": "Hypothesis testing fundamentals", "start": 360.0, "end": 1080.0, "elements": [],
            "question": None}
    new = [{"title": "Z-score and two-sided rejection rule", "start": 1080.0, "end": 1440.0, "continues": True,
            "elements": [el("Reject when z is beyond 1.96.", "beyond 1.96", 2)], "question": None}]
    flags: list = []
    kept, ext = C._merge(new, last, flags)
    assert [t["title"] for t in kept] == ["Z-score and two-sided rejection rule"] and ext is None
    assert flags == ["continues_refused:'Z-score and two-sided rejection rule' (18 min)"]
    new[0]["end"] = 1200.0                                       # within 15 minutes: still joins topic 1
    kept, ext = C._merge(new, last, [])
    assert kept == [] and ext["end"] == 1200.0


def test_nothing_surviving_falls_back_to_the_drafts_without_repeats():
    m = lecture(4)
    m.drafts.append(dict(m.drafts[0]))                           # a repeated draft
    p = run(m, {"topics": [{"n": 1, "title": "Rust", "starts_at": "00:00"}],
                "elements": [el("Rust has a borrow checker.", "rust borrow checker", 1)]})
    assert p["generator"] == "fallback" and p["model"] is None and "nothing_survived" in p["quality_flags"]
    assert p["topics"][0]["title"] == "Part 1" and len(p["elements"]) == 2       # 5 drafts, 2 distinct
    assert all("id" not in e and "sentence_k" not in e for e in p["elements"])


# Live run 29 Oct, Hypothesis Testing 36:00-42:00: the live drafts held a worked example; 120b's pass kept one sentence.
def draft(t, kind, k=0, **fields):
    base = {"id": f"u{k}e{int(t)}", "extends": None, "k": k, "kind": kind, "t": float(t), "said": "...",
            "sentence_k": [k] * len(fields.get("sentences", []))}
    if kind == "para":
        base.update(lead="", terms=[], background=None, sentences=[])
    else:
        base.update(title="", sentences=[], steps=[], code=None)
    return {**base, **fields}


QA_DRAFTS = [
    draft(30, "example", title="Potato wafer net-weight study",
          sentences=["The company claims the mean net weight of its potato wafers is 454 g."]),
    draft(100, "para", lead="Quality assurance testing",
          sentences=["The quality assurance team periodically conducts hypothesis tests on the packaging machine."]),
    draft(250, "para", lead="Null and alternative",
          sentences=["The null hypothesis says the mean weight is 454 grams; the alternative says it is not 454 grams."]),
    draft(300, "para", lead="Rejection region",
          sentences=["For a two-tailed test the rejection region is the two extreme tails of the distribution.",
                     "Students are encouraged to copy the diagram.", "He noted that the tails matter."]),
]
ONE_SENTENCE = {"topics": [{"n": 1, "title": "Quality-assurance hypothesis test", "starts_at": "00:00"}],
                "elements": [el("A computer performs calculations and remembers results.",
                                "it performs calculations and it remembers results", 1)]}


def test_a_thin_pass_cannot_lose_what_its_live_drafts_held():
    m = lecture(4)
    m.drafts = [dict(d) for d in QA_DRAFTS]
    p = run(m, ONE_SENTENCE)
    assert p["generator"] == "llm" and [t["title"] for t in p["topics"]] == ["Quality-assurance hypothesis test"]
    got = [(e["kind"], e["t"], e.get("lead") or e.get("title")) for e in p["elements"]]
    assert got == [("para", 0.0, None), ("example", 30.0, "Potato wafer net-weight study"),
                   ("para", 100.0, "Quality assurance testing"), ("para", 250.0, "Null and alternative"),
                   ("para", 300.0, "Rejection region")]
    assert p["elements"][-1]["sentences"] == [QA_DRAFTS[-1]["sentences"][0]]     # not the filler or the logistics
    assert "carried_from_live(4, thin pass)" in p["quality_flags"]
    assert all("id" not in e and "sentence_k" not in e for e in p["elements"])


def test_a_rich_pass_keeps_its_choices_but_never_drops_numbers_or_examples():
    m = lecture(4)
    m.drafts = [dict(d) for d in QA_DRAFTS]
    rich = {"topics": ONE_SENTENCE["topics"], "elements": ONE_SENTENCE["elements"] + [
        el("A computer performs a billion calculations per second. The results are stored in computer memory, hundreds "
           "of gigabytes.", "It performs a billion calculations per second", 1),
        el("Declarative knowledge is statements of fact. Imperative knowledge is a recipe, a sequence of steps.",
           "Declarative knowledge is statements of fact", 1),
        el("The square root of x is y such that y times y is x.", "The square root of x is y such that y times y", 1)]}
    p = run(m, rich)
    carried = [e.get("lead") or e.get("title") for e in p["elements"] if e["t"] in (30.0, 100.0, 250.0, 300.0)]
    assert carried == ["Potato wafer net-weight study", "Null and alternative"]   # the example, the 454 g sentence
    assert "carried_from_live(2)" in p["quality_flags"]


def test_the_pass_prompt_keeps_worked_problems_whole_and_every_live_point():
    prompt = C.system_prompt(lecture(4), C.due(lecture(4), False))
    assert "never dropped or cut to one sentence" in prompt and "every correct point in them must appear" in prompt
    assert "2-4 paragraphs per 6 minutes" not in prompt and C.MAX_TOKENS == 2400


def test_a_fallback_topic_is_named_after_its_drafts_not_part_n():
    m = lecture(4)
    m.drafts = [dict(d) for d in QA_DRAFTS]
    p = run(m, {"topics": [{"n": 1, "title": "Rust", "starts_at": "00:00"}],
                "elements": [el("Rust has a borrow checker.", "rust borrow checker", 1)]})
    assert p["generator"] == "fallback" and p["topics"][0]["title"] == "Rejection region"    # its fullest paragraph
    assert C.fallback_title([], 6) == "Part 6"


# ------------------------------------------------------------------------------------------------ the agent
class FakeProducer:
    def __init__(self):
        self.sent = []

    def send(self, topic, value=None, key=None, partition=None, timestamp_ms=None):
        self.sent.append(json.loads(value))
        return SimpleNamespace(get=lambda timeout=None: None, add_callback=lambda f: None, add_errback=lambda f: None)


class FakeLLM:
    """Replies in order; "fail" = a transient failure (all models busy)."""

    def __init__(self, *replies):
        self.replies, self.calls, self.chain = list(replies), [], [1, 2]

    def complete_json(self, system, user, **kw):
        self.calls.append(kw)
        r = self.replies.pop(0) if self.replies else "off"
        if r in ("fail", "off"):
            return SimpleNamespace(ok=False, reason="all_failed" if r == "fail" else "disabled", model=None,
                                   data=None, attempts=[])
        return SimpleNamespace(ok=True, data=r, model="openai/gpt-oss-120b", attempts=[], reason=None)


def agent_with(memory, client, end=None):
    log = SimpleNamespace(info=lambda *a, **k: None, warn=lambda *a, **k: None, error=lambda *a, **k: None)
    agent = note_agent.NoteAgent(load(), log, client)
    agent.producer = FakeProducer()
    agent.consumer = SimpleNamespace(commit=lambda offsets: None)
    agent.memories[memory.video_id] = memory
    agent._lecture_ends = lambda vids: {v: end for v in vids if end is not None and v == memory.video_id}
    return agent


def test_a_pass_waits_for_the_gap_after_the_last_live_call_and_asks_the_strong_model_first():
    m = lecture(4)
    m.last_live_at = 1000.0
    agent = agent_with(m, FakeLLM(REPLY))
    agent.timers(1000.0 + C.GAP_S - 1)
    assert agent.producer.sent == []
    agent.timers(1000.0 + C.GAP_S)
    (p,) = agent.producer.sent
    assert p["schema"] == "consolidation.v1" and p["generator"] == "llm" and m.passes == 1
    assert agent.client.calls[0]["first_only"] is True and agent.client.calls[0]["max_tokens"] == C.MAX_TOKENS


def test_a_failed_pass_is_deferred_and_retried_and_the_drafts_stay_live():
    m = lecture(4)
    agent = agent_with(m, FakeLLM("fail", "fail", REPLY))
    agent.timers(1000.0)
    assert agent.producer.sent == [] and m.retry_at == 1000.0 + C.RETRY_S and len(m.drafts) == 4
    agent.timers(1000.0 + C.RETRY_S - 1)
    assert len(agent.client.calls) == 2                          # not retried before retry_at
    agent.timers(1000.0 + max(C.RETRY_S, C.PASS_SPACING_S))      # the strong model's minute was used
    assert [p["generator"] for p in agent.producer.sent] == ["llm"]


def test_with_the_llm_off_the_drafts_are_published_at_once():
    m = lecture(4)
    agent = agent_with(m, FakeLLM())
    agent.timers(1000.0)
    (p,) = agent.producer.sent
    assert p["generator"] == "fallback" and p["topics"][0]["title"] == "Part 1" and len(agent.client.calls) == 1


@pytest.mark.parametrize("last_chunk, at, ended", [(26, 1001.0, True), (30, 1029.0, False), (30, 1030.0, True)])
def test_the_lecture_end_finishes_the_notebook_once(last_chunk, at, ended):
    """Ended = flushed, and the notes reach the last chunk (26: 270 s) or 30 s of quiet (chunk 30 never comes)."""
    m = lecture(3)                                               # 4.5 minutes: no pass yet
    agent = agent_with(m, FakeLLM(), LectureEnd(last_chunk_id=last_chunk, flush_seen_at=1000.0))
    agent.timers(at)
    assert [p["final"] for p in agent.producer.sent] == ([True] if ended else [])
    if ended:
        agent.timers(at + 100)
        assert len(agent.producer.sent) == 1 and m.finished and agent.producer.sent[0]["media_end"] == 270.0


def test_a_pass_runs_while_the_next_update_is_collected_but_the_end_waits_for_the_last_update():
    import time
    now = time.time()
    m = lecture(4)
    agent = agent_with(m, FakeLLM())
    agent.grouper(0).add(Window("python_l1", S0, S0 + 30_000, S0, chunks(4)[:3], 0, 99, arrived=now), m.last_sent)
    agent.timers(now)
    assert [p["final"] for p in agent.producer.sent] == [False]  # mid-lecture: no need to wait (live run 28 Oct)
    m = lecture(3)
    agent = agent_with(m, FakeLLM(), LectureEnd(last_chunk_id=50, flush_seen_at=now - 100))
    agent.grouper(0).add(Window("python_l1", S0, S0 + 30_000, S0, chunks(3)[:3], 0, 99, arrived=now), m.last_sent)
    agent.timers(now)
    assert agent.producer.sent == []                             # ended, but its last update is still held


def test_after_the_lecture_end_no_pass_is_deferred_even_one_that_is_not_the_last():
    """Live run 28 Oct: 12.5 minutes unconsolidated at the end = two passes; the first was not final and deferred."""
    m = lecture(9)                                               # 13.5 min of drafts, nothing consolidated
    agent = agent_with(m, FakeLLM("fail", "fail", "fail", "fail"), LectureEnd(last_chunk_id=80, flush_seen_at=1000.0))
    agent.timers(1001.0)
    assert agent.producer.sent == [] and m.retry_at == 1001.0 + C.RETRY_S / 2      # retried for a while first ...
    agent.timers(1001.0 + C.END_GRACE_S)
    agent.timers(1001.0 + C.END_GRACE_S + C.PASS_SPACING_S)        # the next pass a minute later
    assert [(p["media_start"], p["media_end"], p["generator"], p["final"]) for p in agent.producer.sent] == [
        (0.0, 540.0, "fallback", False), (540.0, 810.0, "fallback", True)]          # ... then never deferred
    assert m.finished


def test_a_stale_lock_whose_pid_was_reused_does_not_keep_the_agent_out(tmp_path):
    """Live run 28 Oct: the lock named a pid Windows had reused; every new agent exited with already_running."""
    import os
    import subprocess
    import sys
    lock = tmp_path / "note-agent.lock"
    lock.write_text(str(os.getppid()))                           # alive, but not a Note Agent
    assert note_agent.acquire_lock(lock) and lock.read_text() == str(os.getpid())
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)", "agents.note_agent"])
    try:
        lock.write_text(str(other.pid))                          # a running Note Agent: stay out
        assert not note_agent.acquire_lock(lock)
    finally:
        other.kill()


def test_passes_of_two_lectures_due_together_run_a_minute_apart_most_overdue_first():
    """Dry run 28 Oct: both lectures reached 6 minutes at once; the second one's passes went to the small model."""
    a, b = lecture(5), lecture(4)                                  # a: 7.5 min unconsolidated, b: 6 min
    b.video_id = "hypothesis_testing_0208"
    agent = agent_with(a, FakeLLM(REPLY, REPLY))
    agent.memories[b.video_id] = b
    clock = [1000.0]
    agent.timers(1000.0)
    assert [p["video_id"] for p in agent.producer.sent] == ["python_l1"]          # the most overdue first
    clock[0] = 1000.0 + C.PASS_SPACING_S - 1
    agent.timers(clock[0])
    assert len(agent.producer.sent) == 1                                         # the strong model's minute
    clock[0] = 1000.0 + C.PASS_SPACING_S
    agent.timers(clock[0])
    assert [p["video_id"] for p in agent.producer.sent] == ["python_l1", "hypothesis_testing_0208"]
    assert all(c["first_only"] for c in agent.client.calls)                      # both asked the strong model


def test_three_lectures_ending_while_the_llm_is_blocked_all_finish_none_starves():
    """Rehearsal 28 Oct: the daily limit blocked both models; two lectures got their fallback, Python L1 never got
    a turn (failing lectures retook every turn, and its grace only started at a first attempt)."""
    class Blocked(FakeLLM):
        def complete_json(self, system, user, **kw):
            self.calls.append(kw)
            return SimpleNamespace(ok=False, reason="all_failed", model=None, data=None,
                                   attempts=[("openai/gpt-oss-120b", "provider_blocked")])
    names = ["algorithms_demaine_l2", "algorithms_ku_l1", "python_l1"]
    lectures = []
    for name in names:
        m = lecture(3)
        m.video_id = name
        lectures.append(m)
    agent = agent_with(lectures[0], Blocked(), LectureEnd(last_chunk_id=26, flush_seen_at=1000.0))
    agent._lecture_ends = lambda vids: {v: LectureEnd(last_chunk_id=26, flush_seen_at=1000.0) for v in vids}
    for m in lectures[1:]:
        agent.memories[m.video_id] = m
    for now in range(1001, 1001 + C.END_GRACE_S + 60, 5):              # the 5 s timer
        agent.timers(float(now))
    finals = sorted(p["video_id"] for p in agent.producer.sent if p["final"])
    assert finals == names and all(p["generator"] == "fallback" for p in agent.producer.sent)
    assert agent.strong_free_at == 0.0                                 # blocked locally: no minute was used
