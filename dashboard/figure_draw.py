"""Showing the assistant's figures (docs/NOTEBOOK_DESIGN.md §13): flowcharts and concept maps drawn with matplotlib
(PNG, no tokens: the model only returned their structure), tables / worked steps / timelines as escaped HTML. Used by
the chat, and (later) by the notebook page and the downloads, so a figure looks the same everywhere.

An item that is not from the lecture is marked "†" (dashed outline in a drawing, dimmed in HTML), with a caption that
counts them. Tested by tests/test_figure_draw.py.
"""

from __future__ import annotations

import html
import io
import json
import textwrap
from functools import lru_cache

from agents.figures import NAME, count_added
from agents.text import mmss

e = html.escape
PALETTE = {
    "light": {"bg": "#ffffff", "text": "#1d2433", "box": "#eef2fb", "edge": "#3159c9", "decision": "#fdf3e1",
              "terminal": "#e8f5ee", "line": "#5b6475", "added": "#8a93a6"},
    "dark": {"bg": "#0e1117", "text": "#e6e9ef", "box": "#1b2433", "edge": "#7aa2ff", "decision": "#33291a",
             "terminal": "#173225", "line": "#9aa3b2", "added": "#7d8596"},
}


def caption(figure: dict) -> str:
    added = count_added(figure)
    if figure["shape"] == "steps" and added:
        return (f"† {added} step{'s' if added > 1 else ''} added from general knowledge, not from the lecture. "
                "Worked by the assistant, not checked by the lecturer.")
    if not added:
        return "Everything in this figure is from the lecture."
    unit = {"table": "cells", "flowchart": "boxes", "concept_map": "ideas", "timeline": "events"}[figure["shape"]]
    total = (sum(len(r["cells"]) for r in figure["rows"]) if figure["shape"] == "table"
             else len(figure["nodes"] if figure["shape"] in ("flowchart", "concept_map") else figure["events"]))
    return f"† {added} of {total} {unit} are general knowledge, not from the lecture."


# ----------------------------------------------------------------------------------------------- HTML shapes
CSS = ("<style>.afig{overflow-x:auto;margin:4px 0 8px}.afig table{border-collapse:collapse;font-size:14px;"
       "min-width:100%}.afig th,.afig td{border:1px solid rgba(128,128,128,.35);padding:5px 9px;text-align:left;"
       "vertical-align:top}.afig th{font-weight:600}.afig .src{white-space:nowrap;font-family:monospace;"
       "font-size:12.5px;opacity:.8}.afig .add{opacity:.72}.afig .cap{font-weight:600;margin-bottom:4px}"
       ".afig .note{font-style:italic;font-size:13px;opacity:.8;margin-top:4px}.afig ol{margin:4px 0;padding-left:22px}"
       ".afig li{margin:4px 0}.afig pre{margin:4px 0;padding:6px 8px;border-radius:6px;background:rgba(128,128,128,.12);"
       "font-size:13px;overflow-x:auto}.afig .res{opacity:.85}</style>")


def _when(t) -> str:
    return mmss(t) if t is not None else "—"


def figure_html(figure: dict) -> str:
    """Tables, worked steps and timelines (drawings are PNGs: draw_png)."""
    shape = figure["shape"]
    title = f'<div class="cap">{e(figure["title"])}</div>' if figure.get("title") else ""
    if shape == "table":
        head = "".join(f"<th>{e(c)}</th>" for c in figure["columns"]) + "<th>Source</th>"
        body = "".join(
            "<tr>" + "".join(f'<td class="add">{e(c)} †</td>' if added and c else f"<td>{e(c)}</td>"
                             for c, added in zip(r["cells"], r["added"]))
            + f'<td class="src">{_when(r["t"])}</td></tr>' for r in figure["rows"])
        inner = f"<table><tr>{head}</tr>{body}</table>"
    elif shape == "steps":
        items = []
        for s in figure["steps"]:
            mark = ' class="add"' if s["added"] else ""
            body = e(s["text"]) + (" †" if s["added"] else "")
            if s.get("code"):
                body += f"<pre>{e(s['code'])}</pre>"
            if s.get("result"):
                body += f'<div class="res">→ {e(s["result"])}</div>'
            when = f' <span class="src">{_when(s["t"])}</span>' if s.get("t") is not None else ""
            items.append(f"<li{mark}>{body}{when}</li>")
        inner = "<ol>" + "".join(items) + "</ol>"
    elif shape == "timeline":
        rows = ""
        for x in figure["events"]:
            mark, dagger = (' class="add"', " †") if x["added"] else ("", "")
            rows += (f'<tr{mark}><td>{e(x["when"])}</td><td>{e(x["label"])}{dagger}</td>'
                     f'<td class="src">{_when(x["t"])}</td></tr>')
        inner = f"<table><tr><th>When</th><th>What</th><th>Source</th></tr>{rows}</table>"
    else:
        raise ValueError(f"{shape} is drawn, not written: use draw_png")
    return f'{CSS}<div class="afig">{title}{inner}<div class="note">{e(caption(figure))}</div></div>'


# ----------------------------------------------------------------------------------------------- drawings
def _layers(nodes: list[dict], edges: list[dict]) -> dict[str, int]:
    """Top-down layer of each node: the longest path from a node without incoming arrows (back edges ignored)."""
    ids = [n["id"] for n in nodes]
    out: dict[str, list[str]] = {i: [] for i in ids}
    indeg = {i: 0 for i in ids}
    for ed in edges:
        out[ed["from"]].append(ed["to"])
        indeg[ed["to"]] += 1
    roots = [i for i in ids if indeg[i] == 0] or ids[:1]
    layer = {i: 0 for i in roots}
    order, stack, on_path, done = [], [], set(), set()

    def visit(i: str) -> None:                               # DFS: a topological order without the back edges
        on_path.add(i)
        for j in out[i]:
            if j not in done and j not in on_path:
                visit(j)
        on_path.discard(i)
        done.add(i)
        order.append(i)

    for r in roots + ids:
        if r not in done:
            visit(r)
    position = {i: k for k, i in enumerate(reversed(order))}
    for i in reversed(order):
        for j in out[i]:
            if position[j] > position[i]:                    # forward edge only
                layer[j] = max(layer.get(j, 0), layer.get(i, 0) + 1)
    for i in ids:
        layer.setdefault(i, 0)
    return layer


def draw_png(figure: dict, theme: str = "light") -> bytes:
    """A flowchart or concept map as a PNG: boxes in top-down layers, arrows with their labels.

    Cached by the figure's content: a drawing takes 0.25-0.8 s, and the notebook (every 2 s) and the chat (every 1 s)
    show the same saved figures again and again (backup recording 29 Oct: the page stayed greyed out re-rendering)."""
    return _draw_png(json.dumps(figure, sort_keys=True, ensure_ascii=False), theme)


@lru_cache(maxsize=64)
def _draw_png(key: str, theme: str) -> bytes:
    figure = json.loads(key)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon

    if figure["shape"] not in ("flowchart", "concept_map"):
        raise ValueError(f"{figure['shape']} is written, not drawn: use figure_html")
    c = PALETTE["dark" if theme == "dark" else "light"]
    nodes, edges = figure["nodes"], figure["edges"]
    layer = _layers(nodes, edges)
    rows: dict[int, list[dict]] = {}
    for n in nodes:
        rows.setdefault(layer[n["id"]], []).append(n)
    width = max(len(r) for r in rows.values())
    box_w, box_h, gap_x = 2.6, 0.9, 0.5
    gap_y = 1.45 if figure["shape"] == "concept_map" else 0.75     # room for relation labels between the rows
    fig_w = max(5.0, width * (box_w + gap_x) + gap_x)
    fig_h = len(rows) * (box_h + gap_y) + gap_y + 0.2
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=110)
    fig.patch.set_facecolor(c["bg"])
    ax.set_facecolor(c["bg"])
    ax.set_xlim(0, fig_w)
    ax.set_ylim(0, fig_h)
    ax.axis("off")
    centre: dict[str, tuple[float, float]] = {}
    parents: dict[str, list[str]] = {}
    for ed in edges:
        parents.setdefault(ed["to"], []).append(ed["from"])
    for k in sorted(rows):
        row = rows[k]
        if k:                                                # under their parents: fewer crossing arrows
            row.sort(key=lambda n: sum(centre[p][0] for p in parents.get(n["id"], []) if p in centre)
                     / max(1, sum(1 for p in parents.get(n["id"], []) if p in centre)) if any(
                p in centre for p in parents.get(n["id"], [])) else fig_w / 2)
        span = len(row) * box_w + (len(row) - 1) * gap_x
        x0 = (fig_w - span) / 2
        y = fig_h - gap_y - k * (box_h + gap_y) - box_h / 2
        for i, n in enumerate(row):
            centre[n["id"]] = (x0 + i * (box_w + gap_x) + box_w / 2, y)
    diagonal = 0
    for ed in edges:
        (x1, y1), (x2, y2) = centre[ed["from"]], centre[ed["to"]]
        tip = {n["id"]: 0.12 if n.get("kind") == "decision" else 0.0 for n in nodes}      # a diamond's points stick out
        down = y2 < y1
        start = (x1, y1 - box_h / 2 - tip[ed["from"]]) if down else (x1 + (box_w / 2 if x2 >= x1 else -box_w / 2), y1)
        end = (x2, y2 + box_h / 2 + tip[ed["to"]]) if down else (x2 + (box_w / 2 if x1 >= x2 else -box_w / 2), y2)
        ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=12, color=c["line"], lw=1.2,
                                     connectionstyle="arc3,rad=0.0" if down else "arc3,rad=0.35", zorder=1))
        if ed["label"]:
            # A straight arrow: label beside its middle. Diagonal arrows cross (a 2 x 2 concept map): their labels
            # alternate between a third and two thirds of the way, so they never sit on top of each other.
            if abs(end[0] - start[0]) < 0.01:
                f = 0.5
            else:
                f, diagonal = (0.3 if diagonal % 2 == 0 else 0.68), diagonal + 1
            ax.text(start[0] + f * (end[0] - start[0]) + 0.08, start[1] + f * (end[1] - start[1]),
                    "\n".join(textwrap.wrap(ed["label"], 18)),
                    fontsize=8, color=c["edge"], ha="left", va="center", zorder=3,
                    bbox={"boxstyle": "round,pad=0.15", "fc": c["bg"], "ec": "none"})
    for n in nodes:
        x, y = centre[n["id"]]
        kind = n.get("kind") or "step"
        style = {"ls": "--" if n["added"] else "-", "lw": 1.3,
                 "ec": c["added"] if n["added"] else c["edge"], "zorder": 2}
        if kind == "decision":
            ax.add_patch(Polygon([(x, y + box_h / 2 + 0.12), (x + box_w / 2, y), (x, y - box_h / 2 - 0.12),
                                  (x - box_w / 2, y)], closed=True, fc=c["decision"], **style))
        else:
            ax.add_patch(FancyBboxPatch((x - box_w / 2, y - box_h / 2), box_w, box_h,
                                        boxstyle=f"round,pad=0.02,rounding_size={0.4 if kind in ('start', 'end') else 0.12}",
                                        fc=c["terminal"] if kind in ("start", "end") else c["box"], **style))
        label = n["label"] + (" †" if n["added"] else "")
        ax.text(x, y, "\n".join(textwrap.wrap(label, 22 if kind != "decision" else 18)[:3]), ha="center",
                va="center", fontsize=9, color=c["added"] if n["added"] else c["text"], zorder=4)
    if figure.get("title"):
        ax.text(0.15, fig_h - 0.18, figure["title"], fontsize=10, fontweight="bold", color=c["text"], va="top")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=c["bg"], bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    return buf.getvalue()


def is_drawing(figure: dict) -> bool:
    return figure["shape"] in ("flowchart", "concept_map")


def label(figure: dict) -> str:
    return NAME[figure["shape"]]
