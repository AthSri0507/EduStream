"""Study-guide notes (docs/NOTEBOOK_DESIGN.md §11): the element model shared by both stages of the notebook.

  * Elements, by shape not role: para (the default), example, steps, table, code, remember (§11.1).
  * validate() checks one element the model proposed against what was said around it: a near-verbatim quote
    places it, then EVERY sentence must be supported by the transcript within about ±90 s (§11.2).
  * The live stage (agents/notebook.py) and consolidation (agents/consolidation.py) use the same prompts' element
    format, the same validator and the same text_of(); the dashboard renders the same dicts.

Pure: no Kafka, no network, no clock. Ported from bench/proto_notebook_v4.py (validated on three lectures, §11.9-10;
the script was deleted 29 Oct, its results are in bench/results/proto_v4*).
Tested by tests/test_study_notes.py.
"""

from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher

from agents.text import content_words, find_quote, mmss, norm, similar, stem, support

KINDS = ("para", "example", "steps", "table", "code", "remember")
ANCHOR_MIN = 0.80                # share of a quote's words found in order (the model tidies ASR text)
LOCATE_SUPPORT_MIN = 0.50        # no usable quote: code finds where the element was said, stricter bar
SENTENCE_MIN = 0.40              # distinct content words of a sentence said within ±90 s of its anchor (§11.2)
KEEP_MIN = 0.5                   # a paragraph that loses more than half of its sentences is dropped
CODE_MIN = 0.30
DUPLICATE_MIN = 0.60             # Jaccard of content words: a near-repeat
WINDOW = 9                       # chunks either side of the anchor (10 s chunks: about ±90 s)
LIVE_PARA_MAX, PARA_MAX_SENTENCES = 6, 4
MAX_ITEMS, MAX_ROWS, MAX_COLUMNS = 8, 6, 3

FILLER = re.compile(r"\b(in this (section|lecture|topic|part|segment)|(the )?(lecturer|professor|instructor|speaker)\b"
                    r"|\b(she|he) (says|said|explains|explained|mentions|mentioned|notes|stresses|emphasi[sz]es"
                    r"|suggests|recommends|encourages|argues|demonstrates|shows|wants)"
                    r"|we (will|'ll|are going to) (now )?(explore|discuss|look at|cover|learn about)"
                    r"|this (section|part|topic) (covers|explains|introduces|discusses|describes)"
                    r"|let'?s (explore|look at|dive)|transcript)\b", re.I)
BACKREF = re.compile(r"^(this|that|these|those|it|its|they|such|so|thus|therefore|hence|here)\b", re.I)
LOGISTICS = re.compile(r"\b(record(ed|ing)|ocw|opencourseware|creative commons|camera|licen[cs]e|office hours"
                       r"|piazza|syllabus|grading|deadline)\b", re.I)
DEFINES = (r"\W+(is|are|means|refers to|consists of|is called|are called)\b"
           r"(?!\s+(\w+ed|taught|built|made|given|done|shown|known)\b)")
EMPHASIS = re.compile(r"\b(important|i want to stress|want you to (remember|know|understand)|keep in mind"
                      r"|don'?t forget|key ?(word|thing|point|idea|takeaway)|the (main|big) (thing|point|takeaway)"
                      r"|crucial|on the (exam|quiz|test)|come back to this|pay attention|make sure (you|that))\b", re.I)


# ============================================================================================== prompt parts
ELEMENTS_DOC = """Elements (plain text in every field, no markdown):
- {"kind": "para", "lead": "2-6 word run-in heading", "text": "2-4 sentences", "terms": ["..."],
   "background": null, "quote": "..."}
  The default. Explains an idea in connected sentences that keep the reasoning (because, so, which means).
  "terms": names of technical terms this paragraph explains in its own text (never everyday words). The glossary
  uses your sentence that explains the term, so explain it the way the lecturer did.
- {"kind": "example", "title": "...", "text": "1-3 sentences", "steps": ["..."], "code": "...", "quote": "..."}
  A concrete example or demonstration, placed right after the paragraph it illustrates. "steps" and "code" only
  if the lecturer gave them.
- {"kind": "steps", "lead": "...", "items": ["..."], "quote": "..."}
  Only when the lecturer gives a procedure or explicitly lists things ("there are three things ...").
- {"kind": "table", "caption": "...", "columns": ["...", "..."], "rows": [["...", "..."]], "quote": "..."}
  Only for an explicit comparison.
- {"kind": "code", "caption": "...", "code": "...", "quote": "..."}
  Code or a formula the lecturer writes or dictates.
- {"kind": "remember", "text": "one sentence", "quote": "..."}
  Only when the lecturer explicitly stresses something ("I want to stress", "remember this", "important").
Every element has "quote": 5-15 consecutive words copied from the transcript where its content is said."""

STYLE = """Style:
- Write the notes themselves, like a good textbook: clear, specific, connected sentences. Never describe the talk
  ("the lecturer says", "the professor demonstrates", "in this section", "we will explore"), never mention a
  transcript. Write examples directly: "Picking a random responder: random.randint(16, 272) returned 75."
- Every sentence must state something actually said in the lecture. Do not add generic commentary, benefits, uses
  or consequences the lecturer did not mention: sentences that cannot be found in the lecture are deleted, and a
  paragraph that loses half of its sentences is deleted. Fewer, accurate sentences are better than more.
- If an idea needs an explanation the lecturer did not give, put one short sentence in the paragraph's
  "background" (shown separately, labelled); never mix outside knowledge into "text".
- Where speech recognition obviously misheard a word, write the intended word.
- Leave out course logistics (slides, problem sets, deadlines, recording notices)."""


def transcript_block(chunks: list[dict]) -> str:
    return "\n".join(f"[{mmss(c['start_time'])}] {c['text']}" for c in chunks)


# ============================================================================================== where it was said
def anchor(quote: str, texts: list[str]) -> tuple[int, int] | None:
    """Where a quote was said: exact first (find_quote), else near-verbatim: >= 80 % of its words in order within
    a stretch at most twice its length ("It performs calculations" for "It performs these calculations")."""
    exact = find_quote(quote, texts)
    if exact is not None:
        return exact
    q = [w for frag in re.split(r"\.\.\.|…", quote or "") for w in norm(frag).split()]
    if len(q) < 4:
        return None
    words, owner = [], []
    for i, t in enumerate(texts):
        for w in norm(t).split():
            words.append(w)
            owner.append(i)
    qs, best, at = set(q), 0.0, None
    for s0 in range(len(words)):
        if words[s0] not in qs:
            continue
        blocks = [b for b in SequenceMatcher(None, q, words[s0:s0 + 2 * len(q)], autojunk=False).get_matching_blocks()
                  if b.size]
        score = sum(b.size for b in blocks) / len(q)
        if score > best:
            best, at = score, (owner[s0 + blocks[0].b], owner[s0 + blocks[-1].b + blocks[-1].size - 1])
    return at if best >= ANCHOR_MIN else None


def ground(quote, claim: str, texts: list[str], flags: list, r: int = 1) -> tuple[int, int] | None:
    """Location of an element: its quote, or (no usable quote) the line whose neighbourhood supports it best."""
    span = anchor(str(quote or ""), texts)
    if span is not None:
        if find_quote(str(quote or ""), texts) is None:
            flags.append("quote_near_verbatim")
        return span
    best, at, own = 0.0, None, 0.0
    for i in range(len(texts)):
        score = support(claim, " ".join(texts[max(0, i - r): i + r + 1]))
        line = support(claim, texts[i])            # tie-break: the line itself, not the first window that covers it
        if (score, line) > (best, own):
            best, at, own = score, i, line
    if best >= LOCATE_SUPPORT_MIN:
        flags.append("located_by_support")
        return at, at
    flags.append(f"not_grounded({best:.2f}): {claim[:60]!r}")
    return None


def said(texts: list[str], span: tuple[int, int]) -> str:
    return " ".join(texts[span[0]: span[1] + 1])[:400]


def around(texts: list[str], span: tuple[int, int], r: int) -> str:
    return " ".join(texts[max(0, span[0] - r): span[1] + r + 1])


def snap(t: float, chunks: list[dict]) -> float:
    """The start of the chunk a time falls in (topic boundaries sit on chunk starts)."""
    starts = [c["start_time"] for c in chunks if c["start_time"] <= t]
    return max(starts) if starts else chunks[0]["start_time"]


def in_transcript(term: str, whole: str) -> bool:
    n, w = norm(term), norm(whole)
    return bool(n) and (n in w or " ".join(stem(x) for x in n.split()) in " ".join(stem(x) for x in w.split()))


# ============================================================================================== sentence checks (§11.2)
def words_of(text: str) -> set[str]:
    """Distinct content words, stems without a final e ("solve" ~ "solving")."""
    return {w[:-1] if len(w) > 4 and w.endswith("e") else w for w in content_words(text)}


def evidence_words(evidence: str) -> set[str]:
    """Words said nearby, plus neighbouring words joined: speech recognition writes "rand int" for randint."""
    toks = re.findall(r"[a-z0-9]+", evidence.lower())
    return words_of(evidence) | {a + b for a, b in zip(toks, toks[1:])}


def grounded(text: str, evidence: str) -> float:
    """Share of a text's DISTINCT content words said in the evidence (repeats must not lift an invented claim)."""
    mine = words_of(text)
    return len(mine & evidence_words(evidence)) / len(mine) if mine else 0.0


def split_sentences(text) -> list[str]:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(\[])", text) if s.strip()]


def clean_items(raw, evidence: str, flags: list) -> list[str]:
    out: list[str] = []
    for it in (raw if isinstance(raw, list) else [])[:MAX_ITEMS]:
        text = str((it.get("text") if isinstance(it, dict) else it) or "").strip()[:220]
        if not text:
            continue
        score = grounded(text, evidence)
        if score < SENTENCE_MIN:
            flags.append(f"item_unsupported({score:.2f}): {text[:60]!r}")
        elif not any(similar(text, x) >= DUPLICATE_MIN for x in out):
            out.append(text)
    return out


def check_sentences(raw, evidence: str, flags: list, stats: Counter, limit: int, known: list[str]) -> list[str] | None:
    """The sentences that survive (§11.2 rules 2-5), or None when the paragraph has lost its spine."""
    sents = split_sentences(raw)
    if len(sents) > limit:
        flags.append(f"too_many_sentences({len(sents)})")
        sents = sents[:limit]
    stats["sentences_proposed"] += len(sents)
    kept: list[str] = []
    checked, prev_dropped = 0, False
    for s in sents:
        s = s[:400]
        if FILLER.search(s):
            flags.append(f"filler: {s[:60]!r}")
            stats["sentences_filler"] += 1
            prev_dropped = True
            continue
        if any(similar(s, k) >= DUPLICATE_MIN for k in known + kept):
            flags.append(f"repeat: {s[:60]!r}")
            stats["sentences_repeat"] += 1
            prev_dropped = True
            continue
        checked += 1
        if prev_dropped and BACKREF.match(s):          # it would point at a sentence that is gone
            flags.append(f"cascade: {s[:60]!r}")
            stats["sentences_cascade"] += 1
            continue
        score = grounded(s, evidence)
        if score < SENTENCE_MIN:
            flags.append(f"sentence_unsupported({score:.2f}): {s[:70]!r}")
            stats["sentences_unsupported"] += 1
            prev_dropped = True
            continue
        kept.append(s)
        prev_dropped = False
    if not kept or len(kept) < KEEP_MIN * checked:
        if checked:
            flags.append(f"paragraph_dropped({len(kept)}/{checked})")
            stats["paragraphs_dropped"] += 1
        return None
    stats["sentences_kept"] += len(kept)
    return kept


def code_ok(code, evidence: str, flags: list) -> str | None:
    code = str(code or "").strip()[:800]
    words = words_of(code)
    if not words:
        return None
    score = len(words & evidence_words(evidence)) / len(words)
    if score < CODE_MIN:
        flags.append(f"code_unsupported({score:.2f})")
        return None
    return code


def background_of(raw, text: str, flags: list) -> str | None:
    if not isinstance(raw, str) or not raw.strip() or raw.strip().lower() in ("null", "none"):
        return None
    if similar(raw, text) >= DUPLICATE_MIN:
        flags.append("background_repeats_text")
        return None
    return raw.strip()[:300]


def _short(raw, n: int) -> str:
    return str(raw or "").strip()[:n]


def lead_of(raw) -> str:
    return str(raw or "").strip().rstrip(".:;,")[:60]


def raw_text(raw: dict) -> str:
    parts = [raw.get(k) for k in ("lead", "title", "caption", "text", "code")]
    listed = raw.get("items") or raw.get("steps")
    if isinstance(listed, list):
        parts += [str(i) for i in listed]
    for r in raw.get("rows") or []:
        if isinstance(r, list):
            parts += [str(c) for c in r]
    return " ".join(str(p) for p in parts if p)


# ============================================================================================== one element
def validate(raw: dict, chunks: list[dict], flags: list, stats: Counter, known: list[str], live: bool) -> dict | None:
    """One proposed element -> the stored element, or None. `chunks` is the transcript the element may come from;
    `known` are sentences already in the notes (repeats are dropped). A para may carry "continue" (live only)."""
    texts = [c["text"] for c in chunks]
    kind = raw.get("kind")
    if kind not in KINDS:
        flags.append(f"kind_fixed:{str(kind)[:20]!r}")
        kind = "para"
    stats[f"proposed_{kind}"] += 1
    claim = raw_text(raw)
    if not claim.strip():
        flags.append("empty_element")
        return None
    span = ground(raw.get("quote"), claim, texts, flags, 3)
    if span is None:
        stats["elements_not_grounded"] += 1
        return None
    ev = around(texts, span, WINDOW)
    base = {"kind": kind, "t": float(chunks[span[0]]["start_time"]), "said": said(texts, span)}
    if kind == "remember":
        text = _short(raw.get("text"), 240)
        if EMPHASIS.search(around(texts, span, 2)) and grounded(text, ev) >= SENTENCE_MIN:
            stats["remember_verified"] += 1
            return {**base, "text": text}
        flags.append(f"remember_demoted: {text[:60]!r}")     # the content stays, the claim of emphasis goes (§11.3)
        stats["remember_demoted"] += 1
        kind, raw, base["kind"] = "para", {"text": text}, "para"
    if kind == "para":
        if LOGISTICS.search(f"{raw.get('lead') or ''} {raw.get('text') or ''}"):
            flags.append(f"logistics_paragraph: {str(raw.get('text'))[:50]!r}")
            stats["logistics_dropped"] += 1
            return None
        sents = check_sentences(raw.get("text"), ev, flags, stats, LIVE_PARA_MAX if live else PARA_MAX_SENTENCES, known)
        if sents is None:
            return None
        lead = lead_of(raw.get("lead"))
        if lead and norm(sents[0]).startswith(norm(lead)):
            lead = ""                                  # "Declarative knowledge. Declarative knowledge consists ..."
        # The glossary entry is the checked sentence of these notes that explains the term, so it is grounded by
        # construction (prototype run 3: model-written definitions were textbook ones the lecturer never gave).
        terms = []
        for tm in (raw.get("terms") if isinstance(raw.get("terms"), list) else [])[:3]:
            term = _short(tm.get("term") if isinstance(tm, dict) else tm, 60)
            heard = term and any(in_transcript(term, x) for x in texts)
            defining = next((x for x in sents if term and re.match(r"(the |a |an )?" + re.escape(term) + DEFINES, x, re.I)),
                            None)                      # must open with "<term> is/consists of ..." (not "is taught")
            if heard and defining:
                terms.append({"term": term, "definition": defining})
            elif term:
                flags.append(f"term_dropped:{term!r}")
        el = {**base, "lead": lead, "sentences": sents, "terms": terms,
              "background": background_of(raw.get("background"), " ".join(sents), flags)}
        if live:
            el["continue"] = bool(raw.get("continue"))
        return el
    if kind == "example":
        sents = check_sentences(raw.get("text"), ev, flags, stats, 3, known) if raw.get("text") else []
        steps = clean_items(raw.get("steps"), ev, flags)
        code = code_ok(raw.get("code"), ev, flags)
        if code:
            repeated = [x for x in steps if norm(x) and norm(x) in norm(code)]
            if repeated:
                flags.append(f"example_steps_repeat_code({len(repeated)})")
                steps = [x for x in steps if x not in repeated]
        if steps and sents and similar(" ".join(sents), " ".join(steps)) >= 0.4:
            flags.append("example_text_repeats_steps")
            sents = []
        if not (sents or code or len(steps) >= 2):
            flags.append("example_empty")
            return None
        return {**base, "title": _short(raw.get("title"), 80), "sentences": sents or [], "steps": steps, "code": code}
    if kind == "steps":
        items = clean_items(raw.get("items"), ev, flags)
        if len(items) < 2:
            flags.append("steps_too_short")
            return None
        return {**base, "lead": lead_of(raw.get("lead")), "items": items}
    if kind == "table":
        cols = [str(c).strip()[:40] for c in (raw.get("columns") or [])[:MAX_COLUMNS] if str(c).strip()]
        rows = []
        for r in (raw.get("rows") if isinstance(raw.get("rows"), list) else [])[:MAX_ROWS]:
            cells = ([str(c).strip()[:140] for c in r] if isinstance(r, list) else [])[:len(cols)]
            cells += [""] * (len(cols) - len(cells))
            score = grounded(" ".join(cells), ev)
            if score < SENTENCE_MIN:
                flags.append(f"row_unsupported({score:.2f}): {' | '.join(cells)[:60]!r}")
                continue
            rows.append(cells)
        if len(cols) < 2 or not rows:
            flags.append("table_empty")
            return None
        return {**base, "caption": _short(raw.get("caption"), 120), "columns": cols, "rows": rows}
    code = code_ok(raw.get("code"), ev, flags)
    if code is None:
        return None
    return {**base, "caption": _short(raw.get("caption"), 120), "code": code}


def text_of(el: dict) -> str:
    """Plain text of an element: for prompts, repeat checks, search and the assistant."""
    k = el["kind"]
    body = " ".join(el.get("sentences", []))
    if k == "para":
        return f"{el['lead']}. {body}".strip(". ") if el.get("lead") else body
    if k == "example":
        steps = "; ".join(el.get("steps", []))
        return (f"Example ({el.get('title') or 'example'}): {body}" + (f" Steps: {steps}." if steps else "")
                + (f" Code: {el['code']}" if el.get("code") else ""))
    if k == "steps":
        return f"{el['lead']}: " + "; ".join(f"{i + 1}) {x}" for i, x in enumerate(el["items"]))
    if k == "table":
        return f"{el['caption']}: " + "; ".join(" | ".join(r) for r in el["rows"])
    if k == "code":
        return f"{el['caption']}: {el['code']}"
    return f"Remember: {el['text']}"


def sentences_of(el: dict) -> list[str]:
    return list(el.get("sentences", [])) + ([el["text"]] if el["kind"] == "remember" else [])


def in_spoken_order(elements: list[dict]) -> list[dict]:
    """Prototype run 2: the model ordered paragraphs by importance, so the margin times jumped. Units (an idea plus
    the examples/code right after it) are put in spoken order."""
    units: list[list[dict]] = []
    for el in elements:
        if el["kind"] in ("example", "code") and units:
            units[-1].append(el)
        else:
            units.append([el])
    units.sort(key=lambda u: u[0]["t"])
    return [x for u in units for x in u]


# ============================================================================================== live drafts
DRAFT_ONLY = ("id", "extends", "k", "sentence_k")


def fold_draft(drafts: list[dict], el: dict, k: int) -> None:
    """Add one live element (notes.v3) to the drafts: a continuation joins the paragraph it extends (§11.4).
    The same code builds the drafts in the Note Agent's memory and on the dashboard."""
    el = {**el, "k": k, "sentence_k": [k] * len(el.get("sentences", []))}
    target = next((d for d in drafts if el.get("extends") and d.get("id") == el["extends"]), None)
    if target is None:
        drafts.append(el)
        return
    target["sentences"] = target["sentences"] + el.get("sentences", [])
    target["sentence_k"] = target["sentence_k"] + el["sentence_k"]
    target["terms"] = target.get("terms", []) + el.get("terms", [])


def published(el: dict) -> dict:
    """A draft as a finished element (no draft bookkeeping)."""
    return {k: v for k, v in el.items() if k not in DRAFT_ONLY}
