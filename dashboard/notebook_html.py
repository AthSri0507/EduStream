"""The notebook as HTML (docs/NOTEBOOK_DESIGN.md §6, §11.6): study-guide elements, topic bodies, the live box, the rail.

Pure functions from the dicts of agents/study_notes.py to HTML strings; dashboard/app.py places them with st.html
inside Streamlit expanders. EVERY text from the notes is escaped (it is model-written): a "<script>" in a note is
shown as text (tests/test_notebook_page.py). No type labels: prose with run-in leads; only examples, "Remember" and
code are set off. The time of each element sits in the margin, the words said there on hover.
"""

from __future__ import annotations

import base64
import html
import re

from agents.figures import NAME
from agents.text import mmss
from dashboard import figure_draw

NBSP = " "
UNITS = r"(%|‰|°[CF]?|k?Hz|dB|[kmμµn]?[gmsVAW]|min|h|MB|GB|KB|kB)(?![\w])"
TOGETHER = [(re.compile(r"(\d)[  ]+" + UNITS), r"\1" + NBSP + r"\2"),           # 95 %, 454 g, 30 s
            (re.compile(r"(\d)[  ]+±[  ]+(?=[\d.])"), r"\1" + NBSP + "±" + NBSP),   # 4.54 ± 0.2
            (re.compile(r"±[  ]+(?=[\d.])"), "±"),                               # ± 1.96 -> ±1.96
            (re.compile(r"\b([Tt]ype)[  ]+(III|II|I|[123])\b"), r"\1" + NBSP + r"\2")]   # Type I, type 2


def keep_together(text: str) -> str:
    """No line break inside "95 %", "454 g", "±1.96" or "Type II" (docs/UI_DESIGN.md §2): the browser may break at
    an ordinary space, and the notes often put one there. Both fonts have U+00A0."""
    for pattern, repl in TOGETHER:
        text = pattern.sub(repl, text)
    return text


CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")   # e.g. "\bar" in a model's JSON became backspace + "ar"


def e(text) -> str:
    """Escape model-written text for HTML, keeping numbers with their units; control characters (drawn as boxes)
    are dropped."""
    return html.escape(keep_together(CONTROL.sub("", str(text))))

# Tokens: docs/UI_DESIGN.md §2 (Warm paper / Midnight ink). The values come from dashboard/theme.py (--es-*) for the
# active theme; the fallbacks are Warm paper, for HTML shown without the dashboard (bench/replay_notebook.py).
# Literata = what the lecturer said; Fira Sans = the interface around it (times, labels, the student's own additions).
CSS = """
.nb{--text:var(--es-ink,#1F2430);--muted:var(--es-secondary,#55596A);--border:var(--es-border,#DAD5C8);
--panel:var(--es-panel,#EFECE3);--tint:var(--es-tint,#E6EAFB);--accent:var(--es-accent,#2F4BD8);
--live:var(--es-live,#0B6B49);--fault:var(--es-fault,#B42318);--mark:var(--es-mark,#FFF0A8);
--livecard:var(--es-livecard,#FFFCF7);--liveborder:var(--es-liveborder,#E5C779);--caution:var(--es-caution,#8A5300);
--said:Literata,Georgia,serif;--ui:'Fira Sans',system-ui,sans-serif;
color:var(--text);font-family:var(--said);font-size:18px;line-height:1.65}
.nb .doc{max-width:72ch}
.nb .el{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:16px;margin:0 0 16px}
.nb .el p{margin:0}
.nb .ts{align-self:start;margin-top:3px;padding:1px 7px;border-radius:999px;background:var(--tint);color:var(--text);
font:500 13px/1.5 var(--ui);font-variant-numeric:tabular-nums;cursor:help;white-space:nowrap}
.nb .lead{font-weight:650}
.nb .example{border-left:3px solid var(--muted);background:var(--panel);padding:10px 16px;border-radius:0 6px 6px 0}
.nb .exh{font:600 15px/1.4 var(--ui);margin-bottom:4px}
.nb ol{margin:6px 0 0;padding-left:24px}.nb li{margin:3px 0}
.nb pre{margin:8px 0 0;background:var(--panel);color:var(--text);padding:8px 10px;border-radius:6px;overflow-x:auto;
font-size:14px;line-height:1.45;white-space:pre}
.nb .remember{border-left:3px solid var(--text);padding:4px 14px}
.nb .cap{font:600 15px/1.4 var(--ui);margin-bottom:4px}
.nb table{border-collapse:collapse;font-size:16px}
.nb th,.nb td{border:1px solid var(--border);padding:4px 10px;text-align:left;vertical-align:top}
.nb th{font:600 15px/1.4 var(--ui)}
.nb .bg{margin:6px 0 0;color:var(--muted);font:15px/1.5 var(--ui)}
.nb .check{margin:8px 0 4px;padding:10px 14px;background:var(--tint);border-left:3px solid var(--accent);border-radius:0 6px 6px 0}
.nb .check b{font-family:var(--ui);font-weight:600}
.nb .check summary{cursor:pointer;color:var(--accent);font:15px/1.6 var(--ui)}
.nb mark.fresh{background:var(--mark);color:inherit;padding:1px 2px;border-radius:3px;
-webkit-box-decoration-break:clone;box-decoration-break:clone}
.nb .live{background:var(--livecard);border:1px solid var(--liveborder);border-left-width:4px;border-radius:8px;
padding:14px 18px;margin:14px 0}
.nb .lh{font:600 15px/1.4 var(--ui);margin-bottom:12px;color:var(--caution)}
.nb .lh span{font-weight:400;color:var(--muted)}
.nb .pending{color:var(--muted);font-family:var(--ui)}
.nb .status{margin-top:6px;color:var(--muted);font:15px/1.5 var(--ui)}
.nb .now{margin-top:8px;color:var(--muted);font-size:16px}
.nb .now b{font:600 15px/1.5 var(--ui)}
.nb .head{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin:0 0 10px;font-family:var(--ui)}
.nb .state{font-weight:600;font-size:15px;display:inline-flex;align-items:center;gap:7px}
.nb .state.on{color:var(--live)}
.nb .dot{width:9px;height:9px;border-radius:50%;background:var(--live);display:inline-block}
.nb .sub{color:var(--muted);font-size:15px}
.nb .toc{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.3fr);gap:28px;font-family:var(--ui);font-size:15px}
.nb .toc h4{font:600 15px/1.4 var(--ui);margin:0 0 8px}
.nb .toc ol{margin:0;padding-left:22px;line-height:1.5}.nb .toc li{margin:0 0 4px}
.nb .rl{color:var(--muted)}
.nb .terms details{border-radius:6px;padding:4px 10px;margin:0 0 2px;border-left:3px solid transparent}
.nb .terms details[open]{background:var(--tint);border-left-color:var(--accent)}
.nb .terms summary{cursor:pointer;font:600 16px/1.5 var(--said)}
.nb .terms details p{margin:4px 0 6px;font:16px/1.55 var(--said)}
.nb .terms .none{color:var(--muted)}
.nb .info{margin-top:12px;color:var(--muted)}.nb .info ul{margin:4px 0 0;padding-left:18px}
.nb .addn{border:1px solid var(--border);border-radius:6px;padding:10px 14px 8px;margin:2px 0 16px;font-family:var(--ui)}
.nb .addh{font:600 15px/1.4 var(--ui);color:var(--muted);margin-bottom:6px}
.nb .addn img{max-width:100%;height:auto;border-radius:6px}
.nb .addq{color:var(--muted);font-size:15px;margin-top:4px}
.nb .gt{border-bottom:2px dotted var(--accent);cursor:help;position:relative;outline:none}
.nb .gt .gd{display:none;position:absolute;left:0;top:1.55em;z-index:20;width:min(380px,70vw);
background:var(--es-card,#FFFEFB);border:1px solid var(--border);border-left:3px solid var(--accent);border-radius:6px;
padding:8px 12px;font:400 15px/1.5 var(--ui);color:var(--text);white-space:normal}
.nb .gt .gd b{font:600 15px/1.5 var(--said)}
.nb .gt:hover .gd,.nb .gt:focus .gd{display:block}
.nb .gt:focus{background:var(--tint);border-radius:3px}
.nb .live.board{font-size:21px;line-height:1.6}.nb .live.board .el{margin-bottom:18px}
.nb .away{background:var(--tint);border-left:4px solid var(--accent);border-radius:0 8px 8px 0;padding:12px 18px;
margin:0 0 14px}
.nb .away h4{font:600 16px/1.4 var(--ui);margin:0 0 8px}.nb .away .more{color:var(--muted);font:15px/1.5 var(--ui)}
.nb .earlier h3{font:600 19px/1.4 var(--said);margin:18px 0 8px}
.nb .earlier h3 span{font:400 14px var(--ui);color:var(--muted)}
.nb .gl dt{font:600 17px/1.4 var(--said);margin-top:10px}.nb .gl dd{margin:2px 0 0;font:17px/1.6 var(--said)}
@media (max-width:900px){.nb .el{grid-template-columns:minmax(0,1fr);gap:2px}.nb .ts{justify-self:start;order:-1}
.nb .toc{grid-template-columns:minmax(0,1fr)}}
"""


def wrap(body: str, theme: str) -> str:
    return f'<style>{CSS}</style><div class="nb" data-theme="{"dark" if theme == "dark" else "light"}">{body}</div>'


def _keep_case(word: str) -> bool:
    """Acronyms (IQ, ANOVA), Roman numerals (II), single-letter prefixes (Z-score), digits, camelCase and symbols
    (H₀, σ) keep their case in sentence_case; hyphens, including the non-breaking one, are not symbols."""
    core = word.strip("()[],:;.!?\"'“”").replace("‑", "-")
    return (not core or bool(re.fullmatch(r"[IVX]+|[A-Z](-\w+)?|[A-Z]{2,}s?", core))
            or bool(re.search(r"\d|[a-z][A-Z]|[^\x00-\x7f]", core)))


def sentence_case(title: str) -> str:
    """Model titles often come in Title Case ("Hypothesis Statements and Decision Rule"); the UI uses sentence case.
    Only a title where most longer words are capitalised is changed; acronyms (IQ), Roman numerals (Type II), single
    letters (Z-score), words with digits or symbols (H\u2080) keep their case. Proper names are lowercased too: the
    price of a heuristic."""
    words = title.split(" ")
    longer = [w for w in words if len(w) > 3 and w[:1].isalpha()]
    if not longer or sum(w[:1].isupper() for w in longer) < 0.6 * len(longer):
        return title
    return " ".join([words[0]] + [w if _keep_case(w) else w.lower() for w in words[1:]])


def _link_terms(h: str, gloss: list | None, seen: set | None) -> str:
    """The first mention of each glossary term in a topic opens its definition on hover or tap (focus): HTML and CSS
    only. Only text outside tags is searched; a term already shown in this topic, or defined in this very element, is
    skipped."""
    if not gloss or seen is None:
        return h
    for term, definition in sorted(gloss, key=lambda g: -len(g[0])):     # "null hypothesis" before "hypothesis"
        if term.lower() in seen:
            continue
        pat = re.compile(r"(?<![\w\u2011-])(" + re.escape(e(term)) + r")(?![\w\u2011-])", re.I)
        parts, inside = re.split(r"(<[^>]+>)", h), 0
        for i, part in enumerate(parts):
            if part.startswith("<"):                      # never match inside a term already linked (or its box)
                if inside or part.startswith('<span class="gt"'):
                    inside += -1 if part.startswith("</span") else (1 if part.startswith("<span") else 0)
                continue
            m = None if inside else pat.search(part)
            if m:
                tip = (f'<span class="gt" tabindex="0">{m.group(1)}<span class="gd" role="tooltip">'
                       f'<b>{e(term)}</b>: {e(definition)}</span></span>')
                parts[i] = part[:m.start()] + tip + part[m.end():]
                seen.add(term.lower())
                h = "".join(parts)
                break
    return h


def glossary_pairs(nb: dict) -> list[tuple[str, str]]:
    return [(g["term"], g["definition"]) for g in nb.get("glossary") or []]


def _sentences(el: dict, fresh: int | None, gloss=None, seen=None) -> str:
    """Sentences with the first occurrence of each glossary term bold; this update's new sentences highlighted;
    other glossary terms open their definition (first mention per topic)."""
    pending = [t["term"] for t in el.get("terms", [])]
    if seen is not None:
        seen.update(t.lower() for t in pending)           # defined right here: no pop-up needed
    ks = el.get("sentence_k") or []
    out = []
    for i, s in enumerate(el.get("sentences", [])):
        h = e(s)
        for term in list(pending):
            m = re.search(re.escape(e(term)), h, re.I)
            if m:
                h = h[:m.start()] + f"<strong>{m.group(0)}</strong>" + h[m.end():]
                pending.remove(term)
        h = _link_terms(h, gloss, seen)
        out.append(f'<mark class="fresh">{h}</mark>' if fresh is not None and i < len(ks) and ks[i] == fresh else h)
    return " ".join(out)


def element_html(el: dict, fresh: int | None = None, gloss=None, seen=None) -> str:
    k = el["kind"]
    if k == "para":
        lead = f'<span class="lead">{e(el["lead"])}.</span> ' if el.get("lead") else ""
        body = f"<p>{lead}{_sentences(el, fresh, gloss, seen)}</p>"
        if el.get("background"):
            body += f'<div class="bg">Background (not from the lecture): {e(el["background"])}</div>'
    elif k == "example":
        body = (f'<div class="example"><div class="exh">Example{": " + e(el["title"]) if el.get("title") else ""}</div>'
                + (f"<p>{_sentences(el, fresh, gloss, seen)}</p>" if el.get("sentences") else "")
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


FALLBACK_NOTE = "Draft notes as written during the class (this part was not tidied up)."


def addition_html(addition: dict, theme: str = "light") -> str:
    """A student's addition (NOTEBOOK_DESIGN §13.7), set apart from the lecture's notes: drawings as an image, tables,
    steps and timelines as HTML (dashboard/figure_draw.py); every model-written text escaped."""
    figure = addition["figure"]
    if figure_draw.is_drawing(figure):
        png = base64.b64encode(figure_draw.draw_png(figure, theme)).decode("ascii")
        inner = (f'<img alt="{e(figure.get("title") or NAME[figure["shape"]])}" src="data:image/png;base64,{png}">'
                 f'<div class="addq">{e(figure_draw.caption(figure))}</div>')
    else:
        inner = figure_draw.figure_html(figure)
    span = addition.get("span")
    when = f" · {mmss(span[0])}–{mmss(span[1])}" if span else ""
    asked = f'<div class="addq">You asked: “{e(addition["question"])}”{when}</div>' if addition.get("question") else ""
    return (f'<div class="addn"><div class="addh">Your addition ({e(NAME[figure["shape"]].lower())})'
            f'{": " + e(figure["title"]) if figure.get("title") else ""}</div>{inner}{asked}</div>')


def topic_html(topic: dict, theme: str = "light", gloss=None) -> str:
    placed = topic.get("additions") or []
    seen: set = set()
    body = ""
    for i, x in enumerate(topic["elements"]):
        body += element_html(x, None, gloss, seen) + "".join(addition_html(a, theme) for a in placed if a["after"] == i)
    body += "".join(addition_html(a, theme) for a in placed if a["after"] is None
                    or not 0 <= a["after"] < len(topic["elements"]))
    if topic.get("generator") == "fallback":
        body = f'<p class="bg">{FALLBACK_NOTE}</p>' + body
    if topic.get("question"):
        body += (f'<div class="check"><b>Check yourself:</b> {e(topic["question"])}'
                 f'<details><summary>Show answer</summary>{e(topic.get("answer") or "")}</details></div>')
    return f'<div class="doc">{body}</div>'


def topic_label(topic: dict) -> str:
    """Expander label (Streamlit markdown): plain title and range."""
    title = re.sub(r"([\\`*_{}\[\]<>#|~$])", r"\\\1", sentence_case(topic["title"]))
    return f"{topic['n']}. {title}  ({mmss(topic['start'])}–{mmss(topic['end'])})"


def beyond_html(nb: dict, theme: str = "light") -> str:
    """Additions about nothing the lecture covered (§13.6), at the end of the notes."""
    return '<div class="doc">' + "".join(addition_html(a, theme) for a in nb.get("beyond") or []) + "</div>"


def live_html(nb: dict, theme: str = "light", board: bool = False) -> str:
    """The one live notes card. board=True: In class, where it comes first and its lines are larger (up to 22 px)."""
    gloss, seen = glossary_pairs(nb), set()
    drafts = "".join(element_html(d, nb["latest_k"], gloss, seen) for d in nb["drafts"]) \
        or '<p class="pending">The next notes will appear here.</p>'
    drafts += "".join(addition_html(a, theme) for a in nb.get("live_additions") or [])
    now = f'<div class="now"><b>Just said:</b> “…{e(nb["now_text"][-260:])}”</div>' if nb.get("now_text") else ""
    return (f'<div class="live{" board" if board else ""}"><div class="lh">Draft notes since {mmss(nb["since"])} <span>About 1–2 minutes '
            f'behind the class; they become a topic every few minutes.</span></div><div class="doc">{drafts}</div>'
            f'<div class="status">{e(nb["status"])}</div>{now}</div>')


def duration(seconds: float) -> str:
    """16 min 30 s, 1 h 07 min."""
    s = int(seconds or 0)
    return f"{s // 3600} h {s % 3600 // 60:02d} min" if s >= 3600 else f"{s // 60} min {s % 60:02d} s"


def head_html(nb: dict) -> str:
    """One status line (docs/UI_DESIGN.md §3): listening and how far into the class, or finished."""
    if nb["finished"]:
        state, sub = '<span class="state">Class finished</span>', f"{duration(nb['said_until'])} recorded"
    else:
        state = '<span class="state on"><span class="dot"></span>Listening</span>'
        sub = (f"{duration(nb['said_until'])} into the class" if nb["reach"]
               else "The first notes appear about 2 minutes after the class starts.")
    return f'<div class="head">{state}<span class="sub">{e(sub)}</span></div>'


def rail_html(nb: dict) -> str:
    items = [f'<li>{e(sentence_case(t["title"]))}</li>' for t in nb["topics"]]
    if not nb["finished"] and (nb["drafts"] or nb["reach"]):
        items.append(f'<li>Draft since {mmss(nb["since"])} <span class="rl">(being written)</span></li>')
    out = ["<h4>Contents</h4>", "<ol>" + "".join(items) + "</ol>" if items else '<p class="pending">No topics yet.</p>']
    if nb["glossary"]:
        out.append(f'<details open><summary>Glossary ({len(nb["glossary"])})</summary><dl>'
                   + "".join(f'<dt>{e(g["term"])}</dt><dd>{e(g["definition"])}</dd>' for g in nb["glossary"])
                   + "</dl></details>")
    if nb["info"]:
        out.append(f'<details><summary>Course info ({len(nb["info"])})</summary><ul>'
                   + "".join(f'<li>{e(i["text"])}</li>' for i in nb["info"]) + "</ul></details>")
    return '<div class="rail">' + "".join(out) + "</div>"


def toc_html(nb: dict) -> str:
    """Contents and glossary as one compact block above the notes (docs/UI_DESIGN.md §5): the topics on the left, the
    terms on the right as tap-to-open entries (the open one on the accent tint). Native <details>: no JavaScript."""
    items = [f'<li>{e(sentence_case(t["title"]))}</li>' for t in nb["topics"]]
    if not nb["finished"] and (nb["drafts"] or nb["reach"]):
        items.append(f'<li>Draft since {mmss(nb["since"])} <span class="rl">(being written)</span></li>')
    contents = "<ol>" + "".join(items) + "</ol>" if items else '<p class="pending">No topics yet.</p>'
    terms = "".join(f'<details><summary>{e(g["term"])}</summary><p>{e(g["definition"])}</p></details>'
                    for g in nb["glossary"]) or '<p class="none">No terms yet.</p>'
    info = (f'<div class="info"><b>Course info</b><ul>' + "".join(f'<li>{e(i["text"])}</li>' for i in nb["info"])
            + "</ul></div>") if nb["info"] else ""
    return (f'<div class="toc"><div><h4>Contents</h4>{contents}{info}</div>'
            f'<div class="terms"><h4>Glossary ({len(nb["glossary"])})</h4>{terms}</div></div>')


def glossary_end_html(nb: dict) -> str:
    """The glossary as a section at the end of the notes, for reading straight through (Revise)."""
    return ('<div class="doc gl"><dl>' + "".join(f'<dt>{e(g["term"])}</dt><dd>{e(g["definition"])}</dd>'
                                              for g in nb["glossary"]) + "</dl></div>")


def earlier_html(topics: list[dict], gloss=None) -> str:
    """In class: every finished topic except the latest, in order, at reading size (one fold, no page switch)."""
    return '<div class="earlier">' + "".join(
        f'<h3>{t["n"]}. {e(sentence_case(t["title"]))} <span>{mmss(t["start"])}\u2013{mmss(t["end"])}</span></h3>'
        + topic_html(t, gloss=gloss) for t in topics) + "</div>"


def away_html(elements: list[dict], start: float, end: float, limit: int = 6) -> str:
    """While you were away: what the notes gained between leaving the tab and coming back (lecture time)."""
    shown = elements[:limit]
    more = len(elements) - len(shown)
    body = "".join(element_html(x) for x in shown) or ('<p class="pending">The notes for this part are still being written; they appear here within a minute or '
                   'two.</p>')
    tail = f'<p class="more">And {more} more in the notes below.</p>' if more > 0 else ""
    return (f'<div class="away"><h4>While you were away ({mmss(start)}\u2013{mmss(end)})</h4>'
            f'<div class="doc">{body}</div>{tail}</div>')
