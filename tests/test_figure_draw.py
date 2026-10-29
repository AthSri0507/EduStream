"""F-2: showing figures (dashboard/figure_draw.py): drawings are PNGs in both themes, the HTML shapes escape model
text and mark what is not from the lecture."""

import pytest

from dashboard import figure_draw as D

EVIL = '<script>alert("x")</script>'
FLOW = {"shape": "flowchart", "title": "Decide", "nodes": [
    {"id": "s", "label": "Start", "kind": "start", "added": False, "t": None},
    {"id": "d", "label": "Is z > 1.96?", "kind": "decision", "added": False, "t": 1150.0},
    {"id": "r", "label": "Reject H0", "kind": "end", "added": False, "t": 600.0},
    {"id": "f", "label": EVIL, "kind": "end", "added": True, "t": None}],
    "edges": [{"from": "s", "to": "d", "label": ""}, {"from": "d", "to": "r", "label": "yes"},
              {"from": "d", "to": "f", "label": "no"}, {"from": "f", "to": "s", "label": "again"}]}   # a cycle


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_drawings_are_pngs_in_both_themes_even_with_a_cycle(theme):
    png = D.draw_png(FLOW, theme)
    assert png.startswith(b"\x89PNG") and len(png) > 5_000
    assert D.is_drawing(FLOW) and D.caption(FLOW) == "† 1 of 4 boxes are general knowledge, not from the lecture."


def test_layers_go_top_down_and_ignore_back_edges():
    layer = D._layers(FLOW["nodes"], FLOW["edges"])
    assert layer == {"s": 0, "d": 1, "r": 2, "f": 2}


def test_html_shapes_escape_and_mark():
    table = {"shape": "table", "title": EVIL, "columns": ["Type", "Probability"],
             "rows": [{"cells": ["Type I", "α"], "added": [False, True], "t": 600.0}]}
    steps = {"shape": "steps", "title": "", "steps": [
        {"text": EVIL, "code": "x < 1", "result": "2 > 1", "added": True, "t": None},
        {"text": "Compare z with 1.96", "code": None, "result": None, "added": False, "t": 1150.0}]}
    timeline = {"shape": "timeline", "title": "", "events": [
        {"when": "09:00", "label": "Errors named", "added": False, "t": 540.0},
        {"when": "1933", "label": EVIL, "added": True, "t": None}]}
    for figure in (table, steps, timeline):
        page = D.figure_html(figure)
        assert "<script>" not in page and "&lt;script&gt;" in page and "overflow-x:auto" in page
    assert '<td class="add">α †</td><td class="src">10:00</td>' in D.figure_html(table)
    page = D.figure_html(steps)
    assert "<pre>x &lt; 1</pre>" in page and "→ 2 &gt; 1" in page and "Worked by the assistant" in page
    assert '<tr class="add"><td>1933</td>' in D.figure_html(timeline)
    with pytest.raises(ValueError):
        D.figure_html(FLOW)
    with pytest.raises(ValueError):
        D.draw_png(table)
