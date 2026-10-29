"""F-3: the student's additions (NOTEBOOK_DESIGN §13.3-13.6, agents/additions.py): the reply to the offer is read by
code, the record validates, and placement follows the notes as they are now. Pure."""

import pytest

from agents import additions as AD
from common import schemas

FIGURE = {"shape": "table", "title": "Type I and Type II errors", "columns": ["Type", "Meaning"],
          "rows": [{"cells": ["Type I", "Rejecting a true null hypothesis"], "added": [False, False], "t": 600.0}]}
TOPICS = [
    {"n": 1, "title": "Hypothesis forms", "start": 360.0, "end": 540.0, "elements": [
        {"kind": "para", "t": 410.0, "lead": "Null and alternate", "sentences": ["H0 has the equality sign."], "terms": []}]},
    {"n": 2, "title": "Type I and II errors", "start": 540.0, "end": 800.0, "elements": [
        {"kind": "para", "t": 545.0, "lead": "Judgement outcomes", "sentences": ["A judgement can be right or wrong."],
         "terms": []},
        {"kind": "example", "t": 600.0, "title": "Reject a true null hypothesis", "sentences": [
            "Rejecting a true null hypothesis is a type I error."], "steps": [], "code": None},
        {"kind": "para", "t": 760.0, "lead": "Level of significance", "sentences": ["Alpha is the risk accepted."],
         "terms": []}]},
]


@pytest.mark.parametrize("msg, expected", [
    ("yes", ("yes", None)), ("Sure, add it", ("yes", None)), ("ok", ("yes", None)),
    ("yes, under topic 2", ("yes", 2)), ("put it in section 1", ("yes", 1)),
    ("no", ("no", None)), ("nope, skip it", ("no", None)), ("don't", ("no", None)),
    ("yes but what is a p-value?", None), ("what is a type I error", None),
    ("yes " + "really " * 20, None),                                             # too long to be a reply
])
def test_the_reply_to_the_offer_is_read_by_code(msg, expected):
    assert AD.read_reply(msg) == expected


def test_records_validate_and_carry_what_placement_needs():
    add = AD.payload_add("hypothesis_testing_0208", FIGURE, [540.0, 650.0], "a table please", True, "m", 2, now_ms=1)
    assert schemas.validate("addition.v1", add) and len(add["addition_id"]) == 32 and add["topic_override"] == 2
    remove = AD.payload_remove("hypothesis_testing_0208", add["addition_id"], now_ms=2)
    assert schemas.validate("addition.v1", remove) and remove["action"] == "remove"
    assert AD.span_of(None, [{"t": 600.0, "end": 610.0}, {"t": 540.0, "end": 550.0}]) == [540.0, 610.0]
    assert AD.span_of([1, 2], []) == [1.0, 2.0] and AD.span_of(None, []) is None


def test_it_goes_under_the_topic_it_overlaps_most_right_after_the_element_it_matches():
    add = {"figure": FIGURE, "span": [580.0, 640.0], "question": "type 1 error as a table", "topic_override": None}
    placement = AD.place(add, TOPICS, since=800.0, finished=False)
    assert placement == {"where": "topic", "topic_n": 2, "after": 1}            # after the example at 10:00
    assert AD.describe(placement, TOPICS) == "under 2. Type I and II errors, after the example “Reject a true null hypothesis”"
    assert AD.offer_text(FIGURE, placement, TOPICS).startswith("Add this table to your notes under 2. Type I and II")


def test_an_override_a_live_part_and_beyond_the_lecture():
    add = {"figure": FIGURE, "span": [580.0, 640.0], "question": "", "topic_override": 1}
    assert AD.place(add, TOPICS, 800.0, False) == {"where": "topic", "topic_n": 1, "after": None}
    live = {"figure": FIGURE, "span": [820.0, 870.0], "question": "", "topic_override": None}
    assert AD.place(live, TOPICS, 800.0, False) == {"where": "live"}
    assert "live notes" in AD.describe({"where": "live"}, TOPICS)
    assert AD.place({**live, "span": None}, TOPICS, 800.0, True) == {"where": "beyond"}
    assert AD.place(live, TOPICS, 800.0, True) == {"where": "beyond"}           # finished, after every topic
