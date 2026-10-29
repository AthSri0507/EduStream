"""The student's additions to the notes (docs/NOTEBOOK_DESIGN.md §13.3-13.6): a figure from the Lecture Assistant that
the student said yes to. Pure: no Kafka, no Streamlit.

  * offer / reply   after a figure the assistant asks "Add this to your notes under …?"; the reply is read by CODE:
                    yes / sure / add it, no / skip, "yes, under topic 2" (a topic number overrides the placement).
                    Only a short reply counts; anything else leaves the offer open and is an ordinary question.
  * payload         an addition.v1 record (topic user_notes): add, or remove (removal is an event too).
  * place           where an addition goes, worked out each time the notes are shown (the notes change: live drafts
                    become topics minutes later): the topic overlapping its time span most, right after the element
                    that best matches it (the lecturer's example with the question), else the end of the topic; while
                    its part is still live, under the live notes; nothing the lecture covered: "Beyond the lecture".

Tested by tests/test_additions.py.
"""

from __future__ import annotations

import re
import time
import uuid

from agents import figures
from agents.study_notes import text_of
from agents.text import mmss, similar

YES = re.compile(r"^\s*(yes|yeah|yep|yup|sure|ok(ay)?|please|add( it| this)?|save( it| this)?|do it|go ahead|y)\b", re.I)
NO = re.compile(r"^\s*(no|nope|nah|don'?t|do not|skip|not now|n)\b", re.I)
TOPIC = re.compile(r"\b(?:under|in|to|into)\s+(?:topic|section|part)\s+(\d{1,2})\b", re.I)
MAX_REPLY_CHARS = 60             # "yes, under topic 2" counts; "yes but what is a p-value?" is a new question
MATCH_MIN = 0.12                 # how well an element must match to place the addition right after it


def read_reply(msg: str) -> tuple[str, int | None] | None:
    """("yes", topic or None), ("no", None), or None when the message is not an answer to the offer."""
    msg = (msg or "").strip()
    if not msg or len(msg) > MAX_REPLY_CHARS or "?" in msg:
        return None
    topic = TOPIC.search(msg)
    if NO.match(msg):
        return "no", None
    if YES.match(msg) or topic:
        return "yes", int(topic.group(1)) if topic else None
    return None


def span_of(plan_span, evidence: list[dict]) -> list[float] | None:
    """The part of the lecture an addition is about: the plan's span, else the evidence it was built from."""
    if plan_span:
        return [float(plan_span[0]), float(plan_span[1])]
    if evidence:
        return [float(min(e["t"] for e in evidence)), float(max(e.get("end", e["t"]) for e in evidence))]
    return None


def payload_add(video_id: str, figure: dict, span, question: str, outside: bool, model: str | None,
                topic_override: int | None = None, now_ms: int | None = None) -> dict:
    return {"schema": "addition.v1", "video_id": video_id, "addition_id": uuid.uuid4().hex, "action": "add",
            "figure": figure, "span": span, "question": question[:300], "outside": bool(outside), "model": model,
            "topic_override": topic_override,
            "created_ts": now_ms if now_ms is not None else int(time.time() * 1000)}


def payload_remove(video_id: str, addition_id: str, now_ms: int | None = None) -> dict:
    return {"schema": "addition.v1", "video_id": video_id, "addition_id": addition_id, "action": "remove",
            "created_ts": now_ms if now_ms is not None else int(time.time() * 1000)}


# ----------------------------------------------------------------------------------------------- placement
def place(addition: dict, topics: list[dict], since: float, finished: bool) -> dict:
    """{"where": "topic", "topic_n", "after"} | {"where": "live"} | {"where": "beyond"}. `topics` as in
    dashboard/queries.notebook (n, title, start, end, elements); `since`: where the live drafts begin."""
    by_n = {t["n"]: t for t in topics}
    override = addition.get("topic_override")
    if override in by_n:
        return {"where": "topic", "topic_n": override, "after": None}
    span = addition.get("span")
    if not span:
        return {"where": "beyond"}
    a, b = float(span[0]), max(float(span[1]), float(span[0]))
    if not finished and a >= since:
        return {"where": "live"}
    overlap = [(min(b, t["end"]) - max(a, t["start"]), t) for t in topics]
    best = max(overlap, key=lambda x: x[0], default=(0.0, None))
    if best[1] is None or (best[0] <= 0 and not (best[1]["start"] <= a < best[1]["end"])):
        return {"where": "live"} if not finished and b > since else {"where": "beyond"}
    topic = best[1]
    return {"where": "topic", "topic_n": topic["n"], "after": _after(addition, topic, a, b)}


def _after(addition: dict, topic: dict, a: float, b: float) -> int | None:
    """Index of the element the addition belongs right after (an example, the step it solves), or None (the end)."""
    about = f"{addition.get('question') or ''} {figures.as_text(addition['figure'])}"
    best, at = MATCH_MIN, None
    for i, el in enumerate(topic["elements"]):
        score = similar(text_of(el), about) + (0.15 if a - 30 <= el["t"] <= b + 30 else 0.0) \
            + (0.05 if el["kind"] == "example" else 0.0)
        if score > best:
            best, at = score, i
    return at


def describe(placement: dict, topics: list[dict]) -> str:
    """The offer's words: "under 3. Being a machine, after the example 'Picking a random responder'"."""
    if placement["where"] == "live":
        return "under the live notes; it moves into its topic when that topic is written"
    if placement["where"] == "beyond":
        return "in “Beyond the lecture” at the end of the notes"
    topic = next(t for t in topics if t["n"] == placement["topic_n"])
    where = f"under {topic['n']}. {topic['title']}"
    if placement["after"] is None:
        return where
    el = topic["elements"][placement["after"]]
    what = {"example": "the example", "steps": "the steps", "table": "the table", "code": "the code"}.get(
        el["kind"], "the paragraph")
    name = el.get("title") or el.get("lead") or el.get("caption") or ""
    return f"{where}, after {what}" + (f" “{name}”" if name else f" at {mmss(el['t'])}")


def offer_text(figure: dict, placement: dict, topics: list[dict]) -> str:
    return (f"Add this {figures.NAME[figure['shape']]} to your notes {describe(placement, topics)}? "
            "Reply “yes”, “no”, or e.g. “yes, under topic 2”.")
