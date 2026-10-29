"""Figures from the Lecture Assistant (docs/NOTEBOOK_DESIGN.md §13): tables, worked steps, flowcharts, concept maps and
timelines. Pure: which shape a message asks for (decided by code), the instructions per shape, and the check that
labels every item as said in the lecture or added. Drawing is dashboard/figure_draw.py (matplotlib: no tokens).

  * The model never writes drawing code: it returns a structure ("figure"); code checks and draws it.
  * Label, don't reject (§13.2): an item is "from the lecture" if it was said around its quote (anywhere in the part
    asked about when it has no real quote); otherwise it is marked added (†). With the switch off (lecture only),
    added items are dropped where that keeps the figure meaningful (table cells and columns, concept-map nodes,
    timeline events); a worked solution or flowchart with an added step is not shown at all (a procedure with a
    step removed would be wrong) and the student is pointed to the switch.
  * Structure is checked: an arrow to a missing box is removed, boxes with no arrow are dropped, and a flowchart
    without any decision is shown as worked steps (a straight line of boxes reads worse than a numbered list).

Tested by tests/test_figures.py.
"""

from __future__ import annotations

import re

from agents.study_notes import evidence_words, grounded, words_of
from agents.text import find_quote

SHAPES = ("table", "steps", "flowchart", "concept_map", "timeline")
NAME = {"table": "table", "steps": "step-by-step solution", "flowchart": "flowchart", "concept_map": "concept map",
        "timeline": "timeline"}
DETECT = (                                  # first match wins: the more specific words first
    ("flowchart", re.compile(r"\b(flow ?charts?|flow diagrams?)\b", re.I)),
    ("concept_map", re.compile(r"\b(concept maps?|mind ?maps?|diagrams?|how (do|does|are) .{1,60} relate"
                               r"|relationships? between)\b", re.I)),
    ("timeline", re.compile(r"\b(timelines?|time ?line|chronolog\w*)\b", re.I)),
    ("table", re.compile(r"\b(table|tabular|tabulate|tabulated)\b", re.I)),
    ("steps", re.compile(r"\b(step[- ]by[- ]step|steps to|walk me through|how (do|can|would|should) (i|we|you) "
                         r"(solve|do|compute|calculate|find|work out|derive|prove)|solve (this|it|that)|worked "
                         r"(example|solution)|procedure for)\b", re.I)),
)
SUPPORT_MIN = 0.5                # an item of three words or more: half of its content words said
NEAR_LINES = 3                   # an item with a real quote is checked against ±3 lines (~30 s) around it
CODE_MIN = 0.30
MAX_ROWS, MAX_COLUMNS, MAX_STEPS, MAX_NODES, MAX_EVENTS = 8, 5, 12, 12, 10
META_COLUMN = re.compile(r"^\s*(time|timestamp|when|said|sources?|mm:ss|\[mm:ss\])\s*$|quote|transcript|evidence|excerpt|citation|lecture says|what was said", re.I)
NUMBER_WORDS = {w: str(i) for i, w in enumerate("zero one two three four five six seven eight nine ten".split())}
NUMBER_WORDS.update({w: str(i) for i, w in enumerate("_ i ii iii iv v vi vii viii ix x".split()) if i})


def detect(msg: str) -> str | None:
    """The figure a message asks for, by its words (the model does not decide), or None."""
    return next((shape for shape, pattern in DETECT if pattern.search(msg or "")), None)


# ----------------------------------------------------------------------------------------------- instructions
QUOTE_RULE = ('Give each item "quote": 3-15 words copied EXACTLY from the line where it is discussed, or null. '
              "Write every item yourself in a few words; never copy transcript sentences and never add time, quote "
              "or source fields (they are added for you).")
SHAPE_RULE = {
    "table": ("a table that answers the question itself, e.g. a comparison: one row per thing compared, one column "
              "per property (2-5 columns, at most 8 rows)."),
    "steps": ("numbered steps that solve or explain it, in order (at most 12); a step may carry \"code\" or "
              "\"result\" (a value it produces)."),
    "flowchart": ("a flowchart: boxes (\"kind\": start, step, decision or end; at most 12) and arrows; a decision has "
                  "two arrows labelled e.g. yes/no. Labels of at most 8 words."),
    "concept_map": ("a concept map: the key ideas as boxes (at most 12, labels of 1-5 words) and arrows labelled with "
                    "how they relate (e.g. \"is a\", \"uses\", \"causes\")."),
    "timeline": "a timeline: events in order (at most 10), each with \"when\" (a time, date or stage) and a label.",
}
KNOWLEDGE_RULE = {
    False: "Use only what the lecture text says; leave something out rather than adding anything else.",
    True: ("Add what the lecture did not say where it helps (other names, symbols, examples, missing steps); each item "
           "is checked and marked when it is not from the lecture. Keep \"background\" to at most one sentence."),
}
FIGURE_SCHEMA = {
    "table": '{"shape": "table", "title": "...", "columns": ["...", "..."], "rows": [{"cells": ["...", "..."], "quote": null}]}',
    "steps": '{"shape": "steps", "title": "...", "steps": [{"text": "...", "code": null, "result": null, "quote": null}]}',
    "flowchart": ('{"shape": "flowchart", "title": "...", "nodes": [{"id": "n1", "label": "...", "kind": "start", '
                  '"quote": null}], "edges": [{"from": "n1", "to": "n2", "label": ""}]}'),
    "concept_map": ('{"shape": "concept_map", "title": "...", "nodes": [{"id": "n1", "label": "...", "quote": null}], '
                    '"edges": [{"from": "n1", "to": "n2", "relation": "..."}]}'),
    "timeline": '{"shape": "timeline", "title": "...", "events": [{"when": "...", "label": "...", "quote": null}]}',
}


def rule(shape: str, outside: bool) -> str:
    # Live check 29 Oct: with the figure rule after the summary rule, gpt-oss-20b returned a plain summary and no
    # figure. The rule now comes first and says the figure is required.
    return (f'The student asked for a {NAME[shape]}. The answer MUST contain "figure": {SHAPE_RULE[shape]} '
            f'{QUOTE_RULE} {KNOWLEDGE_RULE[outside]} "lecture" may hold one or two sentences around it, or be empty.')


def missing_note(shape: str) -> str:
    return f"I couldn't build the {NAME[shape]} this time. Please ask again."


def schema(shape: str) -> str:
    return ('{"lecture": [{"text": "...", "quote": "...", "t": "mm:ss"}], "background": "", "figure": '
            + FIGURE_SCHEMA[shape] + "}")


# ----------------------------------------------------------------------------------------------- said or added
# Speech says the name of a symbol, the model writes the symbol (real check 29 Oct: "Reject H0" was marked as not
# from the lecture, which says "reject the null hypothesis" / "H naught"). Both sides are rewritten to the words.
SPOKEN = [(re.compile(p, re.I), w) for p, w in (
    (r"\bh\s*(?:0|₀|naught|nought|not|zero)\b", " null hypothesis "),
    (r"\bh\s*(?:1|₁|a)\b(?!\w)", " alternative hypothesis "),
    (r"\balternate hypothesis\b", " alternative hypothesis "),
    (r"α", " alpha "), (r"β", " beta "), (r"γ", " gamma "), (r"δ", " delta "), (r"θ", " theta "),
    (r"λ", " lambda "), (r"μ", " mu "), (r"π", " pi "), (r"σ", " sigma "), (r"χ\s*²?", " chi squared "),
    (r"\bchi[- ]?square\b", " chi squared "), (r"≤", " less than or equal "), (r"≥", " greater than or equal "),
)]


def _numbers(text: str) -> str:
    """"Type II", "type two" and "Type 2" are the same words to the check (Whisper writes numbers either way), and so
    are a symbol and its spoken name (SPOKEN)."""
    for pattern, words in SPOKEN:
        text = pattern.sub(words, text)
    return re.sub(r"\b[A-Za-z]+\b", lambda m: NUMBER_WORDS.get(m.group(0).lower(), m.group(0)), text)


def said(item: str, near: str) -> bool:
    """A short item (1-2 content words) must be said in full ("one cycle" passed at 50 % on "one"); a longer one at
    SUPPORT_MIN. An item without words (a symbol such as α) is not counted as said."""
    item, near = _numbers(item), _numbers(near)
    words = words_of(item)
    if not words:
        return False
    return words <= evidence_words(near) if len(words) <= 2 else grounded(item, near) >= SUPPORT_MIN


class _Evidence:
    def __init__(self, evidence: list[dict]) -> None:
        self.lines = evidence
        self.texts = [e["text"] for e in evidence]
        self.whole = " ".join(self.texts)

    def place(self, quote) -> tuple[str, float | None]:
        """The text an item is checked against, and its time: around its quote when the quote is real."""
        span = find_quote(str(quote or ""), self.texts) if quote else None
        if span is None:
            return self.whole, None
        near = " ".join(self.texts[max(0, span[0] - NEAR_LINES): span[1] + NEAR_LINES + 1])
        return near, self.lines[span[0]]["t"]


def _text(raw, n: int) -> str:
    text = str(raw or "").strip()[:n]
    return text if re.search(r"\w", text) else ""                # "-", "n/a" style blanks say nothing


def _list(raw, key: str) -> list:
    value = raw.get(key) if isinstance(raw, dict) else None
    return value if isinstance(value, list) else []


SWITCH = "Switch on “Use general knowledge” to get it with the parts the lecture didn't give, marked."


# ----------------------------------------------------------------------------------------------- the check
def check(shape: str, reply: dict, evidence: list[dict], outside: bool) -> tuple[dict | None, list, str | None]:
    """(figure or None, flags, a note for the student or None)."""
    raw = reply.get("figure") if isinstance(reply.get("figure"), dict) else None
    if raw is None and shape == "table" and isinstance(reply.get("table"), dict):
        raw = reply["table"]                                     # an older reply format
    if raw is None:
        return None, ["figure_missing"], None
    ev = _Evidence(evidence)
    title = _text(raw.get("title") or raw.get("caption"), 120)
    checker = {"table": _table, "steps": _steps, "flowchart": _flowchart, "concept_map": _concept_map,
               "timeline": _timeline}[shape]
    figure, flags, note = checker(raw, ev, outside)
    if figure is None:
        # Never silently: live check 29 Oct, a lecture-only timeline lost its events and the student saw nothing.
        if note is None and not outside and any(f.endswith("_lecture_only") for f in flags):
            note = f"Too little of this {NAME[shape]} was said in the lecture to show it. " + SWITCH
        return None, flags, note
    figure = {"shape": figure.pop("shape", shape), "title": title, **figure}
    added = count_added(figure)
    if added:
        flags.append("figure_items_added")
    return figure, flags, note


def count_added(figure: dict) -> int:
    shape = figure["shape"]
    if shape == "table":
        return sum(sum(r["added"]) for r in figure["rows"])
    items = {"steps": "steps", "flowchart": "nodes", "concept_map": "nodes", "timeline": "events"}[shape]
    return sum(1 for x in figure[items] if x["added"])


def _table(raw: dict, ev: _Evidence, outside: bool):
    flags: list[str] = []
    names = [str(c).strip()[:40] for c in _list(raw, "columns")]
    keep = [i for i, n in enumerate(names) if n and not META_COLUMN.search(n)][:MAX_COLUMNS]
    if len(keep) < len([n for n in names if n]):
        flags.append("table_meta_columns_dropped")
    if len(keep) < 2:
        return None, flags + ["table_without_columns"], None
    rows = []
    for r in _list(raw, "rows")[:MAX_ROWS * 2]:
        cells = r.get("cells") if isinstance(r, dict) else r
        if not isinstance(cells, list):
            continue
        cells = [_text(cells[i], 140) if i < len(cells) else "" for i in keep]
        if not any(cells):
            continue
        near, t = ev.place(r.get("quote") if isinstance(r, dict) else None)
        # The row's name (first column) is a subject, not a claim: discussed anywhere in the part asked about is
        # enough (real check 29 Oct: "Null hypothesis" was marked although the lecture discusses it, 40 s away).
        added = [bool(c) and not said(c, ev.whole if j == 0 else near) for j, c in enumerate(cells)]
        rows.append({"cells": cells, "added": added, "t": t})
    columns = [names[i] for i in keep]
    if not outside:
        lecture_cols = [j for j in range(len(columns)) if j == 0 or any(not r["added"][j] and r["cells"][j] for r in rows)]
        if len(lecture_cols) < len(columns):
            flags.append("table_columns_dropped_lecture_only")
        columns = [columns[j] for j in lecture_cols]
        kept = []
        for r in rows:
            cells = [r["cells"][j] if not r["added"][j] else "" for j in lecture_cols]
            if not any(cells[1:]):
                flags.append("table_row_dropped_lecture_only")
                continue
            if any(r["added"][j] and r["cells"][j] for j in lecture_cols):
                flags.append("table_cells_blanked_lecture_only")
            kept.append({"cells": [c or "—" for c in cells], "added": [False] * len(cells), "t": r["t"]})
        rows = kept
        if len(columns) < 2:
            return None, flags + ["table_empty"], None
    rows = rows[:MAX_ROWS]
    if not rows:
        return None, flags + ["table_empty"], None
    return {"columns": columns, "rows": rows}, flags, None


def _code_said(code: str, near: str) -> bool:
    words = words_of(code)
    return bool(words) and len(words & evidence_words(near)) / len(words) >= CODE_MIN


def _steps(raw: dict, ev: _Evidence, outside: bool):
    steps = []
    for s in _list(raw, "steps")[:MAX_STEPS]:
        if isinstance(s, str):
            s = {"text": s}
        if not isinstance(s, dict):
            continue
        text = _text(s.get("text"), 300)
        if not text:
            continue
        near, t = ev.place(s.get("quote"))
        code = str(s.get("code") or "").strip()[:500] or None
        result = _text(s.get("result"), 120) or None
        added = not said(text, near) or (code is not None and not _code_said(code, near))
        steps.append({"text": text, "code": code, "result": result, "added": added, "t": t})
    return _procedure({"steps": steps}, [s["added"] for s in steps], outside, "steps")


def _procedure(figure: dict, added: list[bool], outside: bool, kind: str):
    if len(added) < 2:
        return None, [f"{kind}_too_short"], None
    if not outside and any(added):                               # a procedure with a step removed would be wrong
        return None, [f"{kind}_needs_general_knowledge"], (
            f"The lecture doesn't give every step of this {'flowchart' if kind == 'flowchart' else 'solution'}. "
            + SWITCH)
    return figure, [], None


def _graph(raw: dict, ev: _Evidence, label_key: str, kinds: bool):
    """Nodes (unique ids, labels) and arrows between existing nodes; boxes with no arrow are dropped."""
    flags: list[str] = []
    nodes, ids = [], set()
    for n in _list(raw, "nodes")[:MAX_NODES]:
        if not isinstance(n, dict):
            continue
        nid, label = str(n.get("id") or "").strip()[:20], _text(n.get("label"), 80)
        if not nid or not label or nid in ids:
            flags.append("node_dropped_invalid")
            continue
        kind = str(n.get("kind") or "step").lower() if kinds else None
        if kinds and kind not in ("start", "step", "decision", "end"):
            kind = "step"
        near, t = ev.place(n.get("quote"))
        terminal = kinds and kind in ("start", "end") and len(words_of(label)) <= 2     # "Start", "End": not claims
        nodes.append({"id": nid, "label": label, "kind": kind, "added": not terminal and not said(label, near), "t": t})
        ids.add(nid)
    edges = []
    for e in _list(raw, "edges")[:MAX_NODES * 3]:
        if not isinstance(e, dict):
            continue
        a, b = str(e.get("from") or "").strip(), str(e.get("to") or "").strip()
        if a not in ids or b not in ids or a == b:
            flags.append("edge_dropped_invalid")
            continue
        edges.append({"from": a, "to": b, "label": _text(e.get(label_key), 40)})
    linked = {x for e in edges for x in (e["from"], e["to"])}
    if len(linked) < len(nodes):
        flags.append("isolated_nodes_dropped")
    nodes = [n for n in nodes if n["id"] in linked]
    return nodes, edges, flags


def _flowchart(raw: dict, ev: _Evidence, outside: bool):
    nodes, edges, flags = _graph(raw, ev, "label", kinds=True)
    if len(nodes) < 2:
        return None, flags + ["flowchart_too_small"], None
    if not any(n["kind"] == "decision" for n in nodes):         # a straight line reads better as a numbered list
        order = _topological(nodes, edges)
        steps = [{"text": n["label"], "code": None, "result": None, "added": n["added"], "t": n["t"]}
                 for n in order if not (n["kind"] in ("start", "end") and len(words_of(n["label"])) <= 2)]
        figure, more, note = _procedure({"steps": steps, "shape": "steps"}, [s["added"] for s in steps], outside,
                                        "flowchart")
        return figure, flags + ["flowchart_without_decisions_as_steps"] + more, note
    figure, more, note = _procedure({"nodes": nodes, "edges": edges}, [n["added"] for n in nodes], outside, "flowchart")
    return figure, flags + more, note


def _topological(nodes: list[dict], edges: list[dict]) -> list[dict]:
    by_id = {n["id"]: n for n in nodes}
    indegree = {n["id"]: 0 for n in nodes}
    for e in edges:
        indegree[e["to"]] += 1
    order, ready, seen = [], [n["id"] for n in nodes if indegree[n["id"]] == 0], set()
    while ready:
        nid = ready.pop(0)
        if nid in seen:
            continue
        seen.add(nid)
        order.append(by_id[nid])
        for e in edges:
            if e["from"] == nid:
                indegree[e["to"]] -= 1
                if indegree[e["to"]] <= 0:
                    ready.append(e["to"])
    return order + [n for n in nodes if n["id"] not in seen]   # cycles: the rest in the model's order


def _concept_map(raw: dict, ev: _Evidence, outside: bool):
    nodes, edges, flags = _graph(raw, ev, "relation", kinds=False)
    for n in nodes:                                              # a concept's name: discussed anywhere is enough
        n["added"] = not said(n["label"], ev.whole)
    if not outside:
        lecture = {n["id"] for n in nodes if not n["added"]}
        if len(lecture) < len(nodes):
            flags.append("concepts_dropped_lecture_only")
        edges = [e for e in edges if e["from"] in lecture and e["to"] in lecture]
        linked = {x for e in edges for x in (e["from"], e["to"])}
        nodes = [n for n in nodes if n["id"] in linked]
    if len(nodes) < 2 or not edges:
        return None, flags + ["concept_map_too_small"], None
    return {"nodes": nodes, "edges": edges}, flags, None


def _timeline(raw: dict, ev: _Evidence, outside: bool):
    flags: list[str] = []
    events = []
    for x in _list(raw, "events")[:MAX_EVENTS]:
        if not isinstance(x, dict):
            continue
        label = _text(x.get("label"), 140)
        if not label:
            continue
        near, t = ev.place(x.get("quote"))
        events.append({"when": _text(x.get("when"), 40), "label": label, "added": not said(label, near), "t": t})
    if not outside:
        if any(e["added"] for e in events):
            flags.append("events_dropped_lecture_only")
        events = [e for e in events if not e["added"]]
    if len(events) < 2:
        return None, flags + ["timeline_too_short"], None
    return {"events": events}, flags, None


# ----------------------------------------------------------------------------------------------- text forms
def as_text(figure: dict) -> str:
    """Plain text of a figure: the conversation memory, search and the notes' plain text."""
    shape, title = figure["shape"], figure.get("title") or NAME[figure["shape"]]
    if shape == "table":
        body = "; ".join(" | ".join(r["cells"]) for r in figure["rows"])
    elif shape == "steps":
        body = " ".join(f"{i}. {s['text']}" for i, s in enumerate(figure["steps"], 1))
    elif shape == "timeline":
        body = "; ".join(f"{e['when']}: {e['label']}" for e in figure["events"])
    else:
        label = {n["id"]: n["label"] for n in figure["nodes"]}
        body = "; ".join(f"{label[e['from']]} -> {label[e['to']]}" + (f" ({e['label']})" if e["label"] else "")
                         for e in figure["edges"])
    return f"{NAME[shape].capitalize()} {title}: {body}"


def mermaid(figure: dict) -> str | None:
    """Mermaid text for a flowchart or concept map (Markdown downloads: Obsidian and GitHub draw it themselves)."""
    if figure["shape"] not in ("flowchart", "concept_map"):
        return None

    def esc(text: str) -> str:
        return text.replace('"', "#quot;").replace("\n", " ")

    lines = ["flowchart TD"]
    for n in figure["nodes"]:
        label = esc(n["label"] + (" †" if n["added"] else ""))
        lines.append(f'    {n["id"]}{{"{label}"}}' if n.get("kind") == "decision"
                     else f'    {n["id"]}(["{label}"])' if n.get("kind") in ("start", "end")
                     else f'    {n["id"]}["{label}"]')
    for e in figure["edges"]:
        lines.append(f'    {e["from"]} -->|"{esc(e["label"])}"| {e["to"]}' if e["label"] else f'    {e["from"]} --> {e["to"]}')
    return "\n".join(lines)
