"""A-1: the Lecture Assistant, scripted (ARCHITECTURE §8.2). Real SQLite built by the real sink from the M2
Whisper transcript of Python · Lecture 1; a fake LLM, so every turn is deterministic. No network."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents import assistant as A
from storage.db import connect_readonly, connect_writer
from storage.db_sink import apply_batch

ROOT = Path(__file__).resolve().parents[1]
WHISPER = ROOT / "bench" / "results" / "chunks_base.en-reppen_ocw6001_l01_10s.jsonl"
S0 = 1_792_051_200_000


class FakeLLM:
    """Answers the understand step with `plan` and the answer step with `answer`; records the prompts."""

    def __init__(self, plan=None, answer=None, ok=True):
        self.plan, self.answer, self.ok, self.calls, self.kwargs = plan, answer, ok, [], []

    def complete_json(self, system, user, max_tokens=0, **kw):
        kind = "understand" if system.startswith("You are the request-understanding") else "answer"
        self.calls.append((kind, user))
        self.kwargs.append((kind, kw))
        data = self.plan if kind == "understand" else self.answer
        if not self.ok or data is None:
            return SimpleNamespace(ok=False, reason="disabled", data=None, model=None)
        return SimpleNamespace(ok=True, data=data, model="fake-20b", reason=None)


def rec(topic, payload, offset):
    return SimpleNamespace(topic=topic, value=json.dumps(payload).encode(), partition=0, offset=offset,
                           key=b"python_l1")


@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    path = tmp_path_factory.mktemp("a1") / "edustream.db"
    rows = [json.loads(line) for line in WHISPER.read_text(encoding="utf-8").splitlines()][:60]   # 10 minutes
    records = []
    for r in rows:
        records.append(rec("transcriptions", {
            "schema": "transcript.v1", "type": "chunk", "video_id": "python_l1", "session_start": S0,
            "chunk_id": r["chunk_id"], "start_time": r["start_time"], "end_time": r["end_time"],
            "event_ts": S0 + r["chunk_id"] * 10_000, "text": r["text"], "asr_score": r["asr_score"],
            "model": "base.en", "src_partition": 0, "src_offset": r["chunk_id"],
            **({"title": "Python · Lecture 1 (Bell)"} if r["chunk_id"] == 0 else {})}, r["chunk_id"]))
    sentence = "Declarative knowledge is statements of fact."
    para = {"kind": "para", "t": 520.0, "said": "The first type of knowledge is declarative knowledge", "lead": "",
            "sentences": [sentence], "terms": [{"term": "declarative knowledge", "definition": sentence}],
            "background": None}
    records.append(rec("final_notes", {
        "schema": "consolidation.v1", "video_id": "python_l1", "pass_index": 0, "media_start": 0.0,
        "media_end": 540.0, "final": False,
        "topics": [{"n": 1, "title": "What does a computer do?", "media_start": 0.0, "media_end": 540.0,
                    "question": None, "new": True}],
        "elements": [{"topic": 1, **para}],
        "glossary": [{"term": "declarative knowledge", "definition": sentence, "t": 520.0, "topic": 1}],
        "generator": "llm", "created_ts": S0}, 0))
    w = connect_writer(path)
    apply_batch(w, records, now=1, window_ms=30_000)
    w.close()
    c = connect_readonly(path)
    yield c
    c.close()


def pos(ref=445.0, live=True):
    return A.Position("python_l1", "Python · Lecture 1 (Bell)", live, ref, 600.0)


# ---------------------------------------------------------------- understand: code fixes what wording makes certain
@pytest.mark.parametrize("msg, llm_plan, check", [
    ("wait what did she mean just now", None,
     lambda p: p.intent == "explain_recent" and p.span == [415.0, 445.0] and p.source == "rules"),
    ("summarise the last 5 minutes", {"intent": "summarise", "refers_to": {"span": [0, 100]}},
     lambda p: p.span == [145.0, 445.0]),
    ("summarise the last two minutes", None, lambda p: p.span == [325.0, 445.0]),
    ("quiz me on what we've covered so far", {"intent": "quiz", "refers_to": {"span": None}},
     lambda p: p.intent == "quiz" and p.span == [0.0, 445.0]),
    ("what does modular mean? short answer please", {"intent": "define", "refers_to": {"term": None}},
     lambda p: p.term == "modular" and p.depth == "brief"),
    ("what happened at 05:10?", {"intent": "ask"}, lambda p: p.span == [295.0, 325.0]),
    ("tell me about computers", {"intent": "chitchat"}, lambda p: p.intent == "ask"),
    ("how does a computer store results", {"intent": "ask", "style": "simpler"}, lambda p: p.style == "same"),
    ("explain everything", {"intent": "summarise", "refers_to": {"span": [0, 9999]}},
     lambda p: p.span == [0.0, 445.0]),                          # clamped to "now" in a live lecture
    ("who won the world cup in 2022?", {"intent": "other"}, lambda p: p.intent == "other"),
])
def test_understand_without_history(conn, msg, llm_plan, check):
    plan = A.understand(FakeLLM(plan=llm_plan) if llm_plan else FakeLLM(ok=False), msg, [], pos(), "ctx")
    assert check(plan), plan


@pytest.mark.parametrize("msg, check", [
    ("ok and in a lot more detail please", lambda p: p.previous_answer and p.depth == "detailed"),
    ("explain that again but simpler", lambda p: p.previous_answer and p.style == "simpler"),
    ("tell me more about the second one", lambda p: p.previous_answer),
])
def test_understand_follow_ups(conn, msg, check):
    turns = [{"role": "user", "text": "what is declarative knowledge?"},
             {"role": "assistant", "text": "Declarative knowledge is statements of fact [08:40]."}]
    plan = A.understand(FakeLLM(plan={"intent": "ask", "refers_to": {"previous_answer": False}}), msg, turns, pos(), "")
    assert check(plan), plan


def test_the_users_chosen_span_is_used_for_didnt_get_that(conn):
    plan = A.understand(FakeLLM(ok=False), "didn't get that", [], pos(), "", span_s=60)
    assert plan.span == [385.0, 445.0]


def test_the_chip_says_what_was_understood():
    plan = A.Plan(intent="explain_recent", span=[415.0, 445.0], style="simpler", previous_answer=True)
    assert plan.chip() == "Explaining **06:55–07:25** · simpler · follow-up"


# ---------------------------------------------------------------- fetch, answer, verify
def test_explain_recent_reads_the_span_plus_one_chunk_before(conn):
    lines, _, _ = A.fetch(conn, A.Plan(intent="explain_recent", span=[420.0, 440.0]), pos())
    assert [ln["t"] for ln in lines] == [410.0, 420.0, 430.0]


def test_a_verified_answer_takes_its_time_from_the_quote(conn):
    llm = FakeLLM(plan={"intent": "explain_recent"}, answer={"lecture": [
        {"text": "A computer does two things: it calculates and it stores the results in memory.",
         "quote": "Store them in computer memory", "t": "01:00"}], "background": ""})
    ans = A.run_turn(conn, llm, "didn't get that", [], pos())
    assert ans.generator == "llm" and ans.items[0]["t"] == 430.0 and "timestamp_corrected" in ans.flags
    assert ans.plan.span == [415.0, 445.0]


def test_an_invented_quote_is_moved_to_background_never_shown_as_the_lecture(conn):
    llm = FakeLLM(plan={"intent": "explain_recent"}, answer={"lecture": [
        {"text": "Computers use transistors.", "quote": "transistors are tiny electronic switches", "t": "07:10"}]})
    ans = A.run_turn(conn, llm, "didn't get that", [], pos(), outside=True)
    assert ans.items == [] and ans.background == ["Computers use transistors."]
    assert "unverified_moved_to_background" in ans.flags
    llm.calls.clear()
    ans = A.run_turn(conn, llm, "didn't get that", [], pos())                  # lecture only: not shown at all
    assert ans.items == [] and ans.background == [] and "unverified_removed_lecture_only" in ans.flags
    assert "Switch on" in ans.note and not ans.outside


def test_answers_are_cut_to_the_budget_at_item_boundaries(conn):
    long = "A computer performs calculations and has to store them in computer memory. " * 5   # 60 said words
    llm = FakeLLM(plan={"intent": "define", "depth": "brief", "refers_to": {"term": "computer memory"}},
                  answer={"lecture": [{"text": long, "quote": "Store them in computer memory"}] * 4})
    ans = A.run_turn(conn, llm, "what is computer memory? briefly", [], pos())
    assert len(ans.items) == 1 and "trimmed_to_budget" in ans.flags


def test_with_the_llm_down_the_user_still_gets_the_plan_and_the_evidence(conn):
    ans = A.run_turn(conn, FakeLLM(ok=False), "didn't get that", [], pos())
    assert ans.generator == "evidence" and ans.evidence and ans.plan.intent == "explain_recent"
    assert any(f.startswith("llm_unavailable") for f in ans.flags)


def test_statistics_are_computed_never_written_by_the_llm(conn):
    llm = FakeLLM(plan={"intent": "data"})
    ans = A.run_turn(conn, llm, "how fast was she speaking in the last minute?", [], pos())
    assert ans.stats is not None and ans.stats["span"] == [385.0, 445.0]
    assert [k for k, _ in llm.calls] == ["understand"]


def test_define_uses_the_glossary_and_where_it_was_said(conn):
    llm = FakeLLM(plan={"intent": "define", "refers_to": {"term": "declarative knowledge"}}, answer={"lecture": []})
    ans = A.run_turn(conn, llm, "what is declarative knowledge?", [], pos(ref=600, live=False))
    assert any(e["text"].startswith("Glossary: declarative knowledge") for e in ans.evidence)
    assert any("declarative knowledge" in e["text"].lower() and not e["text"].startswith("Glossary") for e in ans.evidence)


def test_an_open_question_is_answered_from_keyword_search(conn):
    lines, _, _ = A.fetch(conn, A.Plan(intent="ask", question="why can't computers know anything by themselves?"),
                          pos(ref=600, live=False))
    assert any("only know what you tell them" in ln["text"] for ln in lines)


def test_a_live_lecture_never_shows_what_comes_later(conn):
    lines, _, note = A.fetch(conn, A.Plan(intent="define", term="imperative knowledge",
                                          question="what is imperative knowledge"), pos(ref=445.0))
    assert lines == [] and note == "This hasn't come up in the lecture yet."     # said at 09:30, now is 07:25
    llm = FakeLLM(plan={"intent": "define", "refers_to": {"term": "imperative knowledge"}},
                  answer={"lecture": [{"text": "It is a recipe.", "quote": "a recipe or the how-to", "t": "09:30"}],
                          "background": "In general: knowing how to do something, step by step."})
    ans = A.run_turn(conn, llm, "what is imperative knowledge?", [], pos(ref=445.0), outside=True)
    assert ans.note == "This hasn't come up in the lecture yet." and ans.items == []    # nothing "from the lecture"
    assert ans.background[0].startswith("In general")                                # labelled general knowledge
    assert [k for k, _ in llm.calls] == ["understand", "answer"]
    assert "Lecture text:\n(none)" in llm.calls[-1][1]                                   # the LLM saw no lecture text
    llm.calls.clear()
    ans = A.run_turn(conn, llm, "what is imperative knowledge?", [], pos(ref=445.0))   # lecture only
    assert [k for k, _ in llm.calls] == ["understand"] and ans.background == []        # no answer call at all
    assert ans.note.startswith("“imperative knowledge” hasn't come up in the lecture yet")


def test_off_topic_questions_are_answered_only_with_general_knowledge_on(conn):
    llm = FakeLLM(plan={"intent": "other"}, answer={"lecture": [], "background": "Argentina. Back to the lecture?"})
    ans = A.run_turn(conn, llm, "who won the world cup in 2022?", [], pos(), outside=True)
    assert ans.items == [] and ans.background == ["Argentina. Back to the lecture?"] and ans.outside
    llm.calls.clear()
    ans = A.run_turn(conn, llm, "who won the world cup in 2022?", [], pos())
    assert ans.note == A.LECTURE_ONLY_OTHER and [k for k, _ in llm.calls] == ["understand"]


def test_quiz_questions_point_at_real_moments(conn):
    llm = FakeLLM(plan={"intent": "quiz"}, answer={"questions": [
        {"q": "What two things does a computer do?", "answer": "Calculate and remember.", "t": "07:05"},
        {"q": "Unanchored question?", "answer": "x", "t": "45:00"}]})
    ans = A.run_turn(conn, llm, "quiz me on the last 2 minutes", [], pos())
    assert [q["t"] for q in ans.questions] == [420.0, None]


def test_the_previous_answer_is_given_to_the_answer_step_for_follow_ups(conn):
    turns = [{"role": "user", "text": "what is a computer good at?"},
             {"role": "assistant", "text": "It performs calculations and remembers results [07:00]."}]
    llm = FakeLLM(plan={"intent": "ask", "refers_to": {"previous_answer": True}}, answer={"lecture": []})
    A.run_turn(conn, llm, "explain that again but simpler", turns, pos())
    answer_prompt = [u for k, u in llm.calls if k == "answer"][0]
    assert "previous answer" in answer_prompt and "remembers results" in answer_prompt


def test_a_malformed_answer_falls_back_to_the_evidence(conn):
    llm = FakeLLM(plan={"intent": "explain_recent"}, answer={"lecture": "not a list", "questions": "nope"})
    ans = A.run_turn(conn, llm, "didn't get that", [], pos())
    assert ans.generator == "evidence" and "llm_answer_empty" in ans.flags and ans.evidence


def test_didnt_get_that_is_about_the_lecture_not_the_previous_answer(conn):
    turns = [{"role": "user", "text": "what is a program?"}, {"role": "assistant", "text": "A recipe [09:30]."}]
    plan = A.understand(FakeLLM(plan={"intent": "explain_recent", "refers_to": {"previous_answer": True}}),
                        "didn't get that", turns, pos(), "")
    assert plan.previous_answer is False and plan.span == [415.0, 445.0]


def test_an_answer_with_only_background_also_shows_what_was_said(conn):
    llm = FakeLLM(plan={"intent": "summarise"}, answer={"lecture": [], "background": "Some general remark."})
    ans = A.run_turn(conn, llm, "summarise the last 2 minutes", [], pos(), outside=True)
    assert "no_lecture_items" in ans.flags and ans.evidence


def test_depth_and_style_follow_the_users_words_not_the_models_guess(conn):
    plan = A.understand(FakeLLM(plan={"intent": "summarise", "depth": "brief", "style": "simpler"}),
                        "summarise the last 2 minutes", [], pos(), "")
    assert (plan.depth, plan.style) == ("normal", "same")


def test_what_does_x_do_is_not_a_term_but_what_does_x_mean_is(conn):
    plan = A.understand(FakeLLM(plan={"intent": "define", "refers_to": {"term": None}}), "what does a computer do?",
                        [], pos(), "")
    assert plan.term is None
    plan = A.understand(FakeLLM(plan={"intent": "define", "refers_to": {"term": None}}), "what does modular mean?",
                        [], pos(), "")
    assert plan.term == "modular"


def test_an_unverifiable_claim_about_the_lecturer_is_removed_not_relabelled(conn):
    llm = FakeLLM(plan={"intent": "explain_recent"}, answer={"lecture": [
        {"text": "The lecturer says computers dream of electric sheep.", "quote": "electric sheep dream", "t": "07:10"},
        {"text": "Computers are fast.", "quote": "never said anywhere", "t": "07:10"}]})
    ans = A.run_turn(conn, llm, "didn't get that", [], pos(), outside=True)
    assert ans.background == ["Computers are fast."] and "unverified_removed" in ans.flags


@pytest.mark.parametrize("msg, span", [
    ("summarise 03:00 to 05:00", [180.0, 300.0]),
    ("what happened between 02:10 - 02:40?", [130.0, 160.0]),
    ("explain 05:10", [295.0, 325.0]),
])
def test_times_and_ranges_anywhere_in_the_message(conn, msg, span):
    assert A.understand(FakeLLM(ok=False), msg, [], pos(), "").span == span


def test_saying_youre_a_beginner_simplifies_the_answer(conn):
    plan = A.understand(FakeLLM(ok=False), "I'm new to programming, what is a program?", [], pos(), "")
    assert plan.style == "simpler"


def test_talk_about_transcripts_is_never_shown(conn):
    llm = FakeLLM(plan={"intent": "summarise"}, answer={"lecture": [], "background":
                  "The transcript provided ends at 05:30 and does not include the last lines. Practice matters."})
    ans = A.run_turn(conn, llm, "summarise the last minute", [], pos(), outside=True)
    assert ans.background == ["Practice matters."] and "meta_talk_removed" in ans.flags


def test_a_part_not_said_yet_gets_a_plain_note_without_the_llm(conn):
    p = A.Position("python_l1", "Python · Lecture 1 (Bell)", True, 2.0, 0.0)          # 2 s in, nothing stored
    llm = FakeLLM(plan={"intent": "summarise"})
    ans = A.run_turn(conn, llm, "summarise the last 10 seconds", [], p)
    assert ans.note == "Nothing has been said in that part of the lecture yet."
    assert [k for k, _ in llm.calls] == ["understand"]


# ------------------------------------------------------------------------------ summaries are the assistant's job now
def outline_fixture():
    return [{"id": 1, "title": "Course overview and how to succeed", "t": 30.0},
            {"id": 2, "title": "What does a computer do?", "t": 420.0},
            {"id": 3, "title": "Declarative and imperative knowledge", "t": 520.0}]


@pytest.mark.parametrize("msg, span", [
    ("summarise section 2", [420.0, 520.0]),
    ("summarise this section", [420.0, 520.0]),                  # now = 07:25, inside section 2
    ("summarise the previous section", [30.0, 420.0]),
    ("summarise the part about declarative and imperative knowledge", [520.0, 600.0]),
])
def test_sections_are_resolved_to_their_time_span(msg, span):
    plan = A.resolve_section(A.Plan(intent="summarise", question=msg), msg, outline_fixture(), pos())
    assert plan.span == span


def test_a_summary_grows_with_the_time_it_covers():
    words = lambda minutes, depth="normal": A.budget_for(A.Plan(intent="summarise", span=[0.0, minutes * 60],  # noqa: E731
                                                               depth=depth))
    assert (words(5), words(30), words(120)) == (120, 260, 600)
    assert words(120, "detailed") == 1200                                  # capped: the reply must fit max_tokens
    assert A.budget_for(A.Plan(intent="define")) == 50                     # other intents unchanged


def test_asking_for_the_entire_context_gets_the_detail_and_the_notes_of_that_stretch(conn):
    msg = "give me the entire context between 36:00 to 42:00"           # live run 29 Oct: 3 bullets for 6 min
    recorded = A.Position("python_l1", "Python · Lecture 1 (Bell)", False, 3000.0, 3000.0)
    plan = A.guard(A.Plan(intent="summarise", question=msg), msg, False, recorded)
    assert plan.depth == "detailed" and plan.span == [2160.0, 2520.0] and A.budget_for(plan) == 360
    assert "give each worked example completely" in A.answer_prompt(plan, "university", [])
    for wording in ("what was the full context here", "tell me everything that was said", "all the details please"):
        assert A.guard(A.Plan(intent="ask", question=wording), wording, False, pos()).depth == "detailed"
    normal, _, _ = A.fetch(conn, A.Plan(intent="summarise", span=[420.0, 520.0]), pos())
    detailed, _, _ = A.fetch(conn, A.Plan(intent="summarise", span=[420.0, 520.0], depth="detailed"), pos())
    notes = A.tools.notebook_points(conn, "python_l1", 420.0, 520.0)
    assert notes and len(detailed) == len(normal) + len(notes)             # the transcript, plus the notes
    assert [ln["t"] for ln in detailed] == sorted(ln["t"] for ln in detailed)


def test_a_long_range_keeps_every_section_evenly(conn):
    lines = A.tools.notebook_digest(conn, "python_l1", 0, 1e9, limit=10)
    assert lines[0]["text"].startswith("Section 1:") and len(lines) <= 10


def test_summarise_without_a_range_means_the_whole_lecture_so_far():
    plan = A.understand(FakeLLM(plan={"intent": "summarise", "refers_to": {"span": None}}), "summarise the lecture",
                        [], pos(), "")
    assert plan.span == [0.0, 445.0]


def test_the_two_modes_ask_the_model_differently_and_background_never_pushes_out_the_lecture(conn):
    plan = A.Plan(intent="ask", question="what is a z-score?")
    assert '"background" must be ""' in A.answer_prompt(plan, "unknown", [], False)
    assert "answer it fully in \"background\"" in A.answer_prompt(plan, "unknown", [], True)
    evidence = [{"t": 400.0, "end": 410.0, "text": "Store them in computer memory, so the computer remembers."}]
    reply = {"lecture": [{"text": "The computer stores them in memory.", "quote": "Store them in computer memory",
                          "t": "06:40"}],
             "background": " ".join(f"Sentence number {i} adds some general knowledge here." for i in range(40))}
    items, background, _, flags = A.verify(reply, plan, evidence, outside=True)
    assert len(items) == 1 and "background_trimmed" in flags                     # the lecture item stays
    assert len(background[0].split()) <= A.budget_for(plan)                     # about half the answer
    items, background, _, flags = A.verify(reply, plan, evidence, outside=False)
    assert len(items) == 1 and background == [] and "background_dropped_lecture_only" in flags


def test_lecture_only_checks_the_lecture_before_calling_a_question_off_topic(conn):
    """Dry run 28 Oct: a question the lecture covers was planned as "other" and refused in lecture-only mode."""
    llm = FakeLLM(plan={"intent": "other"}, answer={"lecture": [
        {"text": "A computer stores results in memory.", "quote": "Store them in computer memory", "t": "06:40"}]})
    ans = A.run_turn(conn, llm, "tell me what a computer does with calculations and memory", [], pos())
    assert ans.plan.intent == "ask" and ans.evidence and ans.note is None
    assert [k for k, _ in llm.calls] == ["understand", "answer"] and len(ans.items) == 1


def test_a_real_quote_does_not_carry_a_claim_the_lecturer_did_not_make(conn):
    """Dry run 28 Oct: "F distribution is used in variance ratio tests" cited a line that only listed F."""
    plan = A.Plan(intent="ask", question="what distributions are there?")
    evidence = [{"t": 830.0, "end": 840.0, "text": "it can involve normal distributions, t distributions, F and chi squared"}]
    reply = {"lecture": [
        {"text": "Tests can involve normal, t, F and chi-squared distributions.", "quote": "normal distributions, t distributions"},
        {"text": "The F distribution is used in variance ratio tests.", "quote": "F and chi squared"}]}
    items, background, _, flags = A.verify(reply, plan, evidence, outside=False)
    assert [i["text"] for i in items] == ["Tests can involve normal, t, F and chi-squared distributions."]
    assert background == [] and any(f.startswith("claim_unsupported") for f in flags)
    items, background, _, _ = A.verify(reply, plan, evidence, outside=True)
    assert len(items) == 1 and background == ["The F distribution is used in variance ratio tests."]   # labelled


# ---------------------------------------------------------------- figures (NOTEBOOK_DESIGN §13), end to end
TABLE_REPLY = {"lecture": [], "background": "", "figure": {
    "shape": "table", "title": "Where a computer keeps things", "columns": ["Thing", "What it does", "Time", "Speed"],
    "rows": [{"cells": ["Memory", "stores the results of calculations", "07:10", "slow compared to a register"],
              "quote": "Store them in computer memory"},
             {"cells": ["Registers", "tiny cells inside the processor", "", "one cycle"], "quote": None}]}}


def test_a_table_request_is_decided_by_code_and_every_cell_is_checked(conn):
    llm = FakeLLM(plan={"intent": "ask"}, answer=TABLE_REPLY)
    msg = "make a table of where a computer keeps its results"
    ans = A.run_turn(conn, llm, msg, [], pos(), outside=True)
    assert ans.plan.shape == "table" and ans.figure["columns"] == ["Thing", "What it does", "Speed"]   # no "Time"
    memory, registers = ans.figure["rows"]
    assert memory["t"] == 430.0 and memory["added"] == [False, False, True]                # said / said / not said
    assert registers["t"] is None and registers["added"] == [True, True, True]
    assert "table_meta_columns_dropped" in ans.flags and "figure_items_added" in ans.flags
    ans = A.run_turn(conn, llm, msg, [], pos())                                              # lecture only
    assert ans.figure["columns"] == ["Thing", "What it does"]                                # "Speed": nothing said
    assert [r["cells"] for r in ans.figure["rows"]] == [["Memory", "stores the results of calculations"]]
    assert {"table_columns_dropped_lecture_only", "table_row_dropped_lecture_only"} <= set(ans.flags)


def test_the_figure_rule_is_in_the_prompt_only_when_one_was_asked_for():
    plan = A.Plan(intent="ask", question="x", shape="table")
    assert "leave something out rather than adding anything else" in A.answer_prompt(plan, "unknown", [], False)
    assert "Add what the lecture did not say" in A.answer_prompt(plan, "unknown", [], True)
    assert '"figure": {"shape": "table"' in A.answer_prompt(plan, "unknown", [], True)
    assert '"figure"' not in A.answer_prompt(A.Plan(intent="ask", question="x"), "unknown", [], True)


def test_a_table_with_nothing_from_the_lecture_is_no_table_in_lecture_only_mode(conn):
    only_general = {"lecture": [], "background": "", "figure": {"shape": "table", "columns": ["A", "B"],
                    "rows": [{"cells": ["Registers", "tiny storage inside the processor"], "quote": None}]}}
    ans = A.run_turn(conn, FakeLLM(plan={"intent": "ask"}, answer=only_general),
                     "table of processor storage please", [], pos())
    assert ans.figure is None and "table_empty" in ans.flags and "Switch on" in ans.note


def test_a_worked_solution_asks_the_strong_model_and_needs_the_switch_when_it_goes_beyond_the_lecture(conn):
    steps = {"lecture": [], "background": "", "figure": {"shape": "steps", "title": "Store a result", "steps": [
        {"text": "The computer performs the calculation", "quote": "It performs these calculations"},
        {"text": "It stores the result in computer memory", "quote": "Store them in computer memory"},
        {"text": "A cache line is then flushed to RAM", "quote": None}]}}
    llm = FakeLLM(plan={"intent": "ask"}, answer=steps)
    ans = A.run_turn(conn, llm, "walk me through how a computer keeps a result", [], pos())
    assert ans.plan.shape == "steps" and ans.figure is None and "doesn't give every step" in ans.note
    ans = A.run_turn(conn, llm, "walk me through how a computer keeps a result", [], pos(), outside=True)
    assert [s["added"] for s in ans.figure["steps"]] == [False, False, True]
    assert all(kw.get("prefer") == A.STRONG_MODEL for kind, kw in llm.kwargs if kind == "answer")


def test_a_figure_the_model_did_not_return_is_said_plainly_and_figures_ask_the_strong_model(conn):
    """Live check 29 Oct: a table request came back as a plain summary; nothing told the student."""
    llm = FakeLLM(plan={"intent": "summarise"}, answer={"lecture": [], "background": ""})
    ans = A.run_turn(conn, llm, "make a table of what a computer does", [], pos(), outside=True)
    assert ans.figure is None and ans.note == "I couldn't build the table this time. Please ask again."
    assert [kw.get("prefer") for kind, kw in llm.kwargs if kind == "answer"] == [A.STRONG_MODEL]
    plan = A.Plan(intent="summarise", question="x", shape="timeline")
    prompt = A.answer_prompt(plan, "unknown", [], False)
    assert prompt.index('MUST contain "figure"') < prompt.index("Summarise as short items")
