"""F-1: the assistant's figures (NOTEBOOK_DESIGN §13, agents/figures.py): which shape a message asks for, the checks
and labels per shape, and the text forms. Pure, no LLM."""

import pytest

from agents import figures as F

EVIDENCE = [
    {"t": 540.0, "end": 550.0, "text": "when it is actually true and you fail to reject null hypothesis, when it is not true."},
    {"t": 550.0, "end": 560.0, "text": "these are the two things which you typically call the type one error and type two error"},
    {"t": 600.0, "end": 610.0, "text": "So we say reject H0 when H0 is true."},
    {"t": 610.0, "end": 620.0, "text": "Type 2"},
    {"t": 620.0, "end": 630.0, "text": "fail to reject H naught when false."},
    {"t": 1150.0, "end": 1160.0, "text": "compute z equal to S minus mu divided by sigma and compare it with 1.96"},
]


def fig(shape, **body):
    return {"figure": {"shape": shape, "title": "T", **body}}


@pytest.mark.parametrize("msg, shape", [
    ("draw a flowchart of the hypothesis test", "flowchart"),
    ("make a mind map of this lecture", "concept_map"),
    ("show a diagram of how the errors relate", "concept_map"),
    ("give me a timeline of the lecture", "timeline"),
    ("compare type 1 and type 2 errors in a table", "table"),
    ("how do I solve this question step by step", "steps"),
    ("walk me through the z test", "steps"),
    ("what is a null hypothesis?", None),
    ("my timetable for tomorrow", None),
    # real use 29 Oct: components are structure (a concept map), a process is a flowchart
    ("create a flow chart / mind map of different components in programming", "concept_map"),
    ("create a figure of different components in programming", "concept_map"),
    ("visualise the hypothesis testing process", "flowchart"),
    ("flowchart or diagram of how to decide", "flowchart"),
    ("what does a map function do?", None),
    ("help me figure out the formula", None),
    ("what is the big picture here", None),
])
def test_the_shape_is_decided_by_code(msg, shape):
    assert F.detect(msg) == shape


def test_said_matches_numbers_in_any_form_and_short_items_in_full():
    assert F.said("Type II", "Type 2 fail to reject H naught when false.")
    assert F.said("Type I", "which you typically call the type one error")
    assert not F.said("one cycle", "it chose one number")
    assert not F.said("α", "the level of significance is 0.05")                 # a symbol never spoken: added


def test_worked_steps_are_labelled_and_need_the_switch_when_they_go_beyond_the_lecture():
    reply = fig("steps", steps=[
        {"text": "Compute z as S minus mu divided by sigma", "quote": "compute z equal to S minus mu"},
        {"text": "Compare z with 1.96", "quote": "compare it with 1.96"},
        {"text": "Report the p-value with three decimals", "quote": None, "code": "print(round(p, 3))"}])
    figure, flags, note = F.check("steps", reply, EVIDENCE, outside=True)
    assert [s["added"] for s in figure["steps"]] == [False, False, True] and figure["steps"][0]["t"] == 1150.0
    assert "figure_items_added" in flags and note is None
    figure, flags, note = F.check("steps", reply, EVIDENCE, outside=False)
    assert figure is None and "steps_needs_general_knowledge" in flags and "Switch on" in note


def test_a_flowchart_keeps_its_structure_sound():
    nodes = [{"id": "s", "label": "Start", "kind": "start"},
             {"id": "z", "label": "Compute z from S, mu and sigma", "kind": "step", "quote": "compute z equal to S minus mu"},
             {"id": "d", "label": "Compare z with 1.96", "kind": "decision", "quote": "compare it with 1.96"},
             {"id": "r", "label": "Reject H0", "kind": "end", "quote": "So we say reject H0 when H0 is true"},
             {"id": "f", "label": "Fail to reject H0", "kind": "end", "quote": "fail to reject H naught when false"},
             {"id": "lonely", "label": "Unconnected box", "kind": "step"},
             {"id": "z", "label": "duplicate id", "kind": "step"}]
    edges = [{"from": "s", "to": "z"}, {"from": "z", "to": "d"}, {"from": "d", "to": "r", "label": "yes"},
             {"from": "d", "to": "f", "label": "no"}, {"from": "d", "to": "ghost"}]
    figure, flags, _ = F.check("flowchart", fig("flowchart", nodes=nodes, edges=edges), EVIDENCE, outside=False)
    assert [n["id"] for n in figure["nodes"]] == ["s", "z", "d", "r", "f"] and len(figure["edges"]) == 4
    assert {"node_dropped_invalid", "edge_dropped_invalid", "isolated_nodes_dropped"} <= set(flags)
    assert not any(n["added"] for n in figure["nodes"])                           # "Start" is not a claim


def test_a_flowchart_without_decisions_stays_a_flowchart():
    """Real use 29 Oct: a chain of programming components was turned into a "step-by-step solution"."""
    nodes = [{"id": "a", "label": "Compute z from S, mu and sigma", "quote": "compute z equal to S minus mu"},
             {"id": "b", "label": "Compare z with 1.96", "quote": "compare it with 1.96"}]
    figure, flags, _ = F.check("flowchart", fig("flowchart", nodes=nodes, edges=[{"from": "a", "to": "b"}]), EVIDENCE,
                               outside=False)
    assert figure["shape"] == "flowchart" and [n["id"] for n in figure["nodes"]] == ["a", "b"]


def test_a_concept_map_drops_ideas_the_lecture_never_mentioned_unless_the_switch_is_on():
    nodes = [{"id": "h", "label": "Null hypothesis"}, {"id": "a", "label": "Type I error"},
             {"id": "b", "label": "Type II error"}, {"id": "p", "label": "Statistical power"}]
    edges = [{"from": "h", "to": "a", "relation": "wrongly rejected"}, {"from": "h", "to": "b", "relation": "wrongly kept"},
             {"from": "b", "to": "p", "relation": "complement of"}]
    figure, _, _ = F.check("concept_map", fig("concept_map", nodes=nodes, edges=edges), EVIDENCE, outside=True)
    assert [n["added"] for n in figure["nodes"]] == [False, False, False, True]
    figure, flags, _ = F.check("concept_map", fig("concept_map", nodes=nodes, edges=edges), EVIDENCE, outside=False)
    assert [n["id"] for n in figure["nodes"]] == ["h", "a", "b"] and "concepts_dropped_lecture_only" in flags


def test_a_timeline_keeps_lecture_events_only_without_the_switch():
    events = [{"when": "09:00", "label": "Type I and type II error named", "quote": "type one error and type two error"},
              {"when": "10:00", "label": "Reject H0 when H0 is true", "quote": "So we say reject H0 when H0 is true"},
              {"when": "1933", "label": "Neyman and Pearson publish their lemma", "quote": None}]
    figure, _, _ = F.check("timeline", fig("timeline", events=events), EVIDENCE, outside=False)
    assert [e["when"] for e in figure["events"]] == ["09:00", "10:00"]
    figure, _, _ = F.check("timeline", fig("timeline", events=events), EVIDENCE, outside=True)
    assert [e["added"] for e in figure["events"]] == [False, False, True]


def test_broken_or_missing_figures_are_not_shown():
    assert F.check("table", {"lecture": []}, EVIDENCE, True)[0] is None
    assert F.check("flowchart", fig("flowchart", nodes=[{"id": "a", "label": "Only box"}], edges=[]), EVIDENCE, True)[0] is None
    assert F.check("steps", fig("steps", steps=["One step only"]), EVIDENCE, True)[0] is None


def test_text_forms_for_memory_and_markdown():
    figure, _, _ = F.check("flowchart", fig("flowchart", nodes=[
        {"id": "d", "label": 'Is z > "1.96"?', "kind": "decision"}, {"id": "r", "label": "Reject H0", "kind": "end"}],
        edges=[{"from": "d", "to": "r", "label": "yes"}]), EVIDENCE, outside=True)
    assert F.as_text(figure).startswith("Flowchart T: Is z > \"1.96\"? -> Reject H0 (yes)")
    mm = F.mermaid(figure)
    assert mm.startswith("flowchart TD") and 'd{"Is z > #quot;1.96#quot;?"}' in mm and 'd -->|"yes"| r' in mm


@pytest.mark.parametrize("name, dropped", [("Time", True), ("Lecture quote", True), ("Transcript excerpt", True),
                                           ("Evidence", True), ("Goal", False), ("When it happens", False)])
def test_columns_that_only_repeat_the_transcript_are_dropped(name, dropped):
    """Live check 29 Oct: a "quote"-like column of transcript sentences slipped past the exact-name match."""
    assert bool(F.META_COLUMN.search(name)) is dropped


def test_a_figure_that_lecture_only_mode_empties_is_explained_not_dropped_silently():
    """Live check 29 Oct: a lecture-only timeline lost its events and the student saw nothing at all."""
    events = [{"when": "1933", "label": "Neyman and Pearson publish their lemma", "quote": None},
              {"when": "1950", "label": "Wald extends decision theory", "quote": None}]
    figure, flags, note = F.check("timeline", fig("timeline", events=events), EVIDENCE, outside=False)
    assert figure is None and note.startswith("Too little of this timeline was said in the lecture") and "Switch on" in note
