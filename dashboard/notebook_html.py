"""The notebook as HTML (docs/NOTEBOOK_DESIGN.md §6, §11.6): study-guide elements, topic bodies, the live box, the rail.

Pure functions from the dicts of agents/study_notes.py to HTML strings; dashboard/app.py places them with st.html
inside Streamlit expanders. EVERY text from the notes is escaped (it is model-written): a "<script>" in a note is
shown as text (tests/test_notebook_page.py). No type labels: prose with run-in leads; only examples, "Remember" and
code are set off. The time of each element sits in the margin, the words said there on hover.
"""

from __future__ import annotations

import html
import re

from agents.text import mmss

e = html.escape

CSS = """
.nb{--text:#1d2433;--muted:#5b6475;--border:#dde1e8;--panel:#f6f7f9;--accent:#3159c9;--live:#c2410c;--ex:#b45309;
--imp:#dc2626;--codebg:#eef1f5;--new:#16a34a;color:var(--text);font-size:15.5px;line-height:1.6}
.nb[data-theme="dark"]{--text:#e6e9ef;--muted:#9aa3b2;--border:#2a3140;--panel:#161b24;--accent:#7aa2ff;--live:#fb923c;
--ex:#fbbf24;--imp:#f87171;--codebg:#1f2633;--new:#4ade80}
.nb .doc{max-width:48em}
.nb .el{display:grid;grid-template-columns:minmax(0,1fr) 46px;gap:14px;margin:0 0 12px}
.nb .el p{margin:0}
.nb .ts{justify-self:end;align-self:start;margin-top:3px;color:var(--muted);font-size:12px;cursor:help;
border-bottom:1px dotted var(--muted);font-variant-numeric:tabular-nums}
.nb .lead{font-weight:700}
.nb .example{border-left:3px solid var(--ex);background:var(--panel);padding:8px 14px;border-radius:0 6px 6px 0}
.nb .exh{font-size:13px;font-weight:700;color:var(--ex);margin-bottom:4px}
.nb ol{margin:6px 0 0;padding-left:22px}.nb li{margin:2px 0}
.nb pre{margin:8px 0 0;background:var(--codebg);color:var(--text);padding:8px 10px;border-radius:6px;overflow-x:auto;
font-size:13px;line-height:1.45;white-space:pre}
.nb .remember{border-left:3px solid var(--imp);padding:4px 12px}
.nb .cap{font-weight:600;margin-bottom:4px}
.nb table{border-collapse:collapse;font-size:14px}
.nb th,.nb td{border:1px solid var(--border);padding:4px 10px;text-align:left;vertical-align:top}
.nb .bg{margin:6px 0 0;color:var(--muted);font-size:13px;font-style:italic}
.nb .check{margin:6px 0 4px;padding:8px 12px;border-left:3px solid var(--accent);background:var(--panel);border-radius:4px}
.nb .check summary{cursor:pointer;color:var(--accent);font-size:13px}
.nb mark.fresh{background:color-mix(in srgb,var(--new) 22%,transparent);color:inherit;border-radius:3px;padding:0 1px}
.nb .live{border:2px dashed var(--live);border-radius:8px;padding:10px 14px;margin:4px 0 12px}
.nb .lh{color:var(--live);font-weight:700;font-size:12.5px;letter-spacing:.04em;margin-bottom:6px}
.nb .pending{color:var(--muted);font-style:italic}
.nb .status{margin-top:6px;color:var(--muted);font-size:13px}
.nb .now{margin-top:6px;font-size:13px;color:var(--muted);border-top:1px solid var(--border);padding-top:6px}
.nb .head{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap;margin:0 0 6px}
.nb .sub{color:var(--muted);font-size:13px}
.nb .badge{font-weight:600;font-size:13px;padding:2px 10px;border-radius:12px;border:1px solid var(--border);white-space:nowrap}
.nb .badge.on{color:var(--live);border-color:var(--live)}
.nb .rail h4{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:0 0 6px}
.nb .rail ol{margin:0 0 14px;padding-left:20px;font-size:14px}
.nb .ok{color:var(--new)}.nb .rl{color:var(--live);font-size:12px}
.nb .rail details{margin:0 0 12px;font-size:14px}.nb .rail summary{cursor:pointer;color:var(--muted);font-weight:600}
.nb .rail dl{margin:6px 0 0}.nb .rail dt{font-weight:600}.nb .rail dd{margin:0 0 8px;color:var(--muted);font-size:13px}
.nb .rail ul{margin:6px 0 0;padding-left:18px;color:var(--muted);font-size:13px}
.nb .range{color:var(--muted);font-size:13px}
@media (max-width:1000px){.nb .el{grid-template-columns:minmax(0,1fr)}.nb .ts{justify-self:start;order:-1}}
"""


def wrap(body: str, theme: str) -> str:
    return f'<style>{CSS}</style><div class="nb" data-theme="{"dark" if theme == "dark" else "light"}">{body}</div>'


def _sentences(el: dict, fresh: int | None) -> str:
    """Sentences with the first occurrence of each glossary term bold; this update's new sentences highlighted."""
    pending = [t["term"] for t in el.get("terms", [])]
    ks = el.get("sentence_k") or []
    out = []
    for i, s in enumerate(el.get("sentences", [])):
        h = e(s)
        for term in list(pending):
            m = re.search(re.escape(e(term)), h, re.I)
            if m:
                h = h[:m.start()] + f"<strong>{m.group(0)}</strong>" + h[m.end():]
                pending.remove(term)
        out.append(f'<mark class="fresh">{h}</mark>' if fresh is not None and i < len(ks) and ks[i] == fresh else h)
    return " ".join(out)


def element_html(el: dict, fresh: int | None = None) -> str:
    k = el["kind"]
    if k == "para":
        lead = f'<span class="lead">{e(el["lead"])}.</span> ' if el.get("lead") else ""
        body = f"<p>{lead}{_sentences(el, fresh)}</p>"
        if el.get("background"):
            body += f'<div class="bg">Background (not from the lecture): {e(el["background"])}</div>'
    elif k == "example":
        body = (f'<div class="example"><div class="exh">Example{" · " + e(el["title"]) if el.get("title") else ""}</div>'
                + (f"<p>{_sentences(el, fresh)}</p>" if el.get("sentences") else "")
                + ("<ol>" + "".join(f"<li>{e(x)}</li>" for x in el["steps"]) + "</ol>" if el.get("steps") else "")
                + (f"<pre>{e(el['code'])}</pre>" if el.get("code") else "") + "</div>")
    elif k == "steps":
        body = (f'<div><p><span class="lead">{e(el["lead"])}:</span></p><ol>'
                + "".join(f"<li>{e(x)}</li>" for x in el["items"]) + "</ol></div>")
    elif k == "table":
        body = ((f'<div class="cap">{e(el["caption"])}</div>' if el.get("caption") else "") + "<table><tr>"
                + "".join(f"<th>{e(c)}</th>" for c in el["columns"]) + "</tr>"
                + "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in r) + "</tr>" for r in el["rows"]) + "</table>")
    elif k == "code":
        body = (f'<div class="cap">{e(el["caption"])}</div>' if el.get("caption") else "") + f"<pre>{e(el['code'])}</pre>"
    else:
        body = f'<div class="remember"><span class="lead">Remember:</span> {e(el["text"])}</div>'
    return (f'<div class="el"><div>{body}</div><span class="ts" title="Said: &ldquo;{e(el.get("said") or "")}&rdquo;">'
            f'{mmss(el["t"])}</span></div>')


def topic_html(topic: dict) -> str:
    body = "".join(element_html(x) for x in topic["elements"])
    if topic.get("question"):
        body += (f'<div class="check"><b>Check yourself:</b> {e(topic["question"])}'
                 f'<details><summary>Show answer</summary>{e(topic.get("answer") or "")}</details></div>')
    return f'<div class="doc">{body}</div>'


def topic_label(topic: dict) -> str:
    """Expander label (Streamlit markdown): plain title and range."""
    title = re.sub(r"([\\`*_{}\[\]<>#|~$])", r"\\\1", topic["title"])
    return f"{topic['n']}. {title}  ·  {mmss(topic['start'])}–{mmss(topic['end'])}"


def live_html(nb: dict) -> str:
    drafts = "".join(element_html(d, nb["latest_k"]) for d in nb["drafts"]) \
        or '<p class="pending">The next notes will appear here.</p>'
    now = f'<div class="now">now: “…{e(nb["now_text"][-260:])}”</div>' if nb.get("now_text") else ""
    return (f'<div class="live"><div class="lh">LIVE NOTES SINCE {mmss(nb["since"])} · draft, organised into a topic '
            f'every few minutes</div><div class="doc">{drafts}</div><div class="status">{e(nb["status"])}</div>'
            f'{now}</div>')


def head_html(nb: dict) -> str:
    if nb["finished"]:
        badge, sub = f'<span class="badge">Finished · {mmss(nb["said_until"])}</span>', ""
    else:
        badge = f'<span class="badge on">● LIVE {mmss(nb["said_until"])}</span>'
        sub = (f"Notes reach {mmss(nb['reach'])} (they follow the lecture by about 1–2 minutes)" if nb["reach"]
               else "The first notes appear about 2 minutes into the lecture")
    return f'<div class="head"><span class="sub">{e(sub)}</span>{badge}</div>'


def rail_html(nb: dict) -> str:
    items = [f'<li>{e(t["title"])} <span class="ok">✓</span></li>' for t in nb["topics"]]
    if not nb["finished"] and (nb["drafts"] or nb["reach"]):
        items.append(f'<li>Live notes since {mmss(nb["since"])} <span class="rl">live</span></li>')
    out = ["<h4>Contents</h4>", "<ol>" + "".join(items) + "</ol>" if items else '<p class="pending">No topics yet.</p>']
    if nb["glossary"]:
        out.append(f'<details open><summary>Glossary ({len(nb["glossary"])})</summary><dl>'
                   + "".join(f'<dt>{e(g["term"])}</dt><dd>{e(g["definition"])}</dd>' for g in nb["glossary"])
                   + "</dl></details>")
    if nb["info"]:
        out.append(f'<details><summary>Course info ({len(nb["info"])})</summary><ul>'
                   + "".join(f'<li>{e(i["text"])}</li>' for i in nb["info"]) + "</ul></details>")
    return '<div class="rail">' + "".join(out) + "</div>"
