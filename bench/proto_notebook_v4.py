"""Prototype for docs/NOTEBOOK_DESIGN.md §11: study-guide notes (prose by default, structure only where the
content has that shape). Same two stages, same triggers and the same real transcript as proto_notebook_v3.py
(Python · Lecture 1, 28 Oct live run), so the two can be compared screenshot by screenshot.

    .venv\\Scripts\\python bench\\proto_notebook_v4.py

Writes bench/results/proto_v4/: report.md (every reply and every validation decision), metrics.json and
view_<moment>.html. Replies are cached (LLM_CACHE=on), so a rerun costs nothing. Keys are never printed.
"""

from __future__ import annotations

import copy
import json
import time
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench import proto_notebook_v3 as v3  # noqa: E402  (loads .env, enables the cached LLM client)
from agents import llm  # noqa: E402
from agents.text import mmss, norm, parse_t, similar  # noqa: E402

e = v3.e
OUT = ROOT / "bench" / "results" / "proto_v4"
KINDS = ("para", "example", "steps", "table", "code", "remember")
LIVE_MAX_ELEMENTS = 2
PARA_MAX_SENTENCES, LIVE_PARA_MAX = 4, 6
SENTENCE_MIN = 0.40              # distinct content words of a sentence said within ±90 s of its anchor (§11.2)
KEEP_MIN = 0.5                   # a paragraph that loses more than half of its sentences is dropped
CODE_MIN = 0.30
TERM_MIN = 0.30
WINDOW = 9                       # chunks either side of the anchor
LIVE_CONTEXT_WORDS = 250
FILLER = re.compile(r"\b(in this (section|lecture|topic|part|segment)|(the )?(lecturer|professor|instructor|speaker)\b"
                    r"|\b(she|he) (says|said|explains|explained|mentions|mentioned|notes|stresses|emphasi[sz]es"
                    r"|suggests|recommends|encourages|argues|demonstrates|shows|wants)"
                    r"|we (will|'ll|are going to) (now )?(explore|discuss|look at|cover|learn about)"
                    r"|this (section|part|topic) (covers|explains|introduces|discusses|describes)"
                    r"|let'?s (explore|look at|dive)|transcript)\b", re.I)
BACKREF = re.compile(r"^(this|that|these|those|it|its|they|such|so|thus|therefore|hence|here)\b", re.I)
LOGISTICS = re.compile(r"\b(record(ed|ing)|ocw|opencourseware|creative commons|camera|licen[cs]e|office hours"
                       r"|piazza|syllabus|grading|deadline)\b", re.I)
DEFINES = r"\W+(is|are|means|refers to|consists of|is called|are called)\b(?!\s+(\w+ed|taught|built|made|given|done|shown|known)\b)"
EMPHASIS = re.compile(r"\b(important|i want to stress|want you to (remember|know|understand)|keep in mind"
                      r"|don'?t forget|key ?(word|thing|point|idea|takeaway)|the (main|big) (thing|point|takeaway)"
                      r"|crucial|on the (exam|quiz|test)|come back to this|pay attention|make sure (you|that))\b", re.I)


# ============================================================================================== prompts
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

LIVE_SYSTEM = f"""You write the running notes of a live university lecture, the way a good student writes them up.
Every 90 seconds you receive the next part of the transcript (speech recognition, so it can contain errors) and the
notes written since the last organised topic.

Continue the notes with at most 2 elements for this part. A paragraph may continue the last paragraph of the notes
so far: give "continue": true and no "lead". Start a new paragraph when the idea changes. Never repeat what is
already in the notes. Returning no elements is fine. Course logistics go in "info" (one short line), not in the notes.

{ELEMENTS_DOC}

{STYLE}

Return ONLY a JSON object: {{"elements": [ ... ], "info": null or {{"text": "...", "quote": "..."}}}}"""

CONSOLIDATE_SYSTEM = f"""You write the final study notes for one stretch of a university lecture, like a section of a
good textbook. You receive the topics finished earlier in the lecture and the glossary so far, the transcript of the
stretch (speech recognition, so it can contain errors), and the rough live notes written during it.

- Split the stretch into 1-3 topics where the subject actually changes, each with a clear, specific title.
  Course logistics (recording, slides, problem-set dates) are never a topic and never a question.
- Write each topic mostly as paragraphs (2-4 sentences each; about 2-4 paragraphs per 6 minutes) that explain the
  ideas and how they connect. Use steps, table or code only where the lecturer really listed, compared or wrote
  something. Put each example right after the paragraph it illustrates.
- Use the live notes as a draft: keep what is right, merge repeats, fix what is wrong, drop what is trivial.
- Do not define again a term already in the glossary unless the lecturer adds something new.
- One check-yourself question per topic that tests understanding, with a short answer from the lecture.
OPEN_RULE
{ELEMENTS_DOC}

{STYLE}

Return ONLY a JSON object with flat lists. Number the new topics from NEXT_N; elements and questions name their topic
by that number.
{{"topics": [{{"n": NEXT_N, "title": "...", "starts_at": "mm:ss"}}],
 "elements": [{{"topic": NEXT_N, "kind": "para", "lead": "...", "text": "...", "terms": [], "quote": "..."}}],
 "questions": [{{"topic": NEXT_N, "q": "...", "answer": "..."}}]OPEN_FIELD}}"""


# ============================================================================================== state
class State:
    def __init__(self) -> None:
        self.drafts: list[dict] = []        # live elements not organised yet
        self.topics: list[dict] = []
        self.glossary: dict[str, dict] = {}
        self.info: list[dict] = []
        self.S = 0.0
        self.reach = 0.0
        self.last_k = -1
        self.organised: set[int] = set()

    def index(self) -> str:
        done = "; ".join(f"{t['n']}. {t['title']} ({mmss(t['start'])}-{mmss(t['end'])})" for t in self.topics)
        terms = ", ".join(g["term"] for g in self.glossary.values())
        return f"Finished topics: {done or '(none yet)'}\nGlossary so far: {terms or '(none yet)'}"

    def sentences(self) -> list[str]:
        return [s["text"] for el in self.drafts + [x for t in self.topics for x in t["elements"]]
                for s in el.get("sentences", [])]


# ============================================================================================== validation (§11.2)
def pace(res) -> None:
    """Offline replay compresses a lecture into minutes; a live lecture spaces calls 90 s apart. Wait in proportion
    to the tokens just used so Groq's 8,000 tokens/minute is not exceeded (unseen-lecture run 1: HTTP 429s)."""
    if res.ok and not res.cached and res.tokens:
        time.sleep(min(60.0, res.tokens / 6000 * 60))


def split_sentences(text) -> list[str]:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(\[])", text) if s.strip()]


def evidence_words(evidence: str) -> set[str]:
    """Words said nearby, plus neighbouring words joined: speech recognition writes "rand int" for randint."""
    words = v3.words_of(evidence)
    toks = re.findall(r"[a-z0-9]+", evidence.lower())
    return words | {a + b for a, b in zip(toks, toks[1:])}


def grounded(text: str, evidence: str) -> float:
    mine = v3.words_of(text)
    return len(mine & evidence_words(evidence)) / len(mine) if mine else 0.0


def clean_items(raw, evidence: str, flags: list) -> list[str]:
    out = []
    for it in (raw if isinstance(raw, list) else [])[:8]:
        text = str((it.get("text") if isinstance(it, dict) else it) or "").strip()[:220]
        if not text:
            continue
        score = grounded(text, evidence)
        if score < SENTENCE_MIN:
            flags.append(f"item_unsupported({score:.2f}): {text[:60]!r}")
        elif not any(similar(text, x) >= v3.DUPLICATE_MIN for x in out):
            out.append(text)
    return out


def check_sentences(raw, evidence: str, flags: list, stats: Counter, limit: int, known: list[str]) -> list[str] | None:
    sents = split_sentences(raw)
    if len(sents) > limit:
        flags.append(f"too_many_sentences({len(sents)})")
        sents = sents[:limit]
    stats["sentences_proposed"] += len(sents)
    kept, checked, prev_dropped = [], 0, False
    for s in sents:
        if FILLER.search(s):
            flags.append(f"filler: {s[:60]!r}")
            stats["sentences_filler"] += 1
            prev_dropped = True
            continue
        if any(similar(s, k) >= v3.DUPLICATE_MIN for k in known + kept):
            flags.append(f"repeat: {s[:60]!r}")
            stats["sentences_repeat"] += 1
            prev_dropped = True
            continue
        checked += 1
        if prev_dropped and BACKREF.match(s):
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
    words = v3.words_of(code)
    if not words:
        return None
    score = len(words & evidence_words(evidence)) / len(words)
    if score < CODE_MIN:
        flags.append(f"code_unsupported({score:.2f})")
        return None
    return code


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


def validate(raw: dict, texts: list[str], chunks: list[dict], flags: list, stats: Counter, known: list[str],
             live: bool) -> dict | None:
    kind = raw.get("kind")
    if kind not in KINDS:
        flags.append(f"kind_fixed:{kind!r}")
        kind = "para"
    stats[f"proposed_{kind}"] += 1
    claim = raw_text(raw)
    if not claim.strip():
        flags.append("empty_element")
        return None
    span = v3.ground(raw.get("quote"), claim, texts, flags, 3)
    if span is None:
        stats["elements_not_grounded"] += 1
        return None
    ev = v3.around(texts, span, WINDOW)
    base = {"kind": kind, "t": chunks[span[0]]["start_time"], "said": v3.said(texts, span)}
    if kind == "remember":
        text = str(raw.get("text") or "").strip()[:240]
        if EMPHASIS.search(v3.around(texts, span, 2)) and grounded(text, ev) >= SENTENCE_MIN:
            stats["remember_verified"] += 1
            return {**base, "text": text}
        flags.append(f"remember_demoted: {text[:60]!r}")       # the content stays, the claim of emphasis goes
        stats["remember_demoted"] += 1
        kind, raw = "para", {"text": text}
        base["kind"] = "para"
    if kind == "para":
        if LOGISTICS.search(f"{raw.get('lead') or ''} {raw.get('text') or ''}"):
            flags.append(f"logistics_paragraph: {str(raw.get('text'))[:50]!r}")      # run 4: the OCW recording note
            stats["logistics_dropped"] += 1
            return None
        sents = check_sentences(raw.get("text"), ev, flags, stats, LIVE_PARA_MAX if live else PARA_MAX_SENTENCES, known)
        if sents is None:
            return None
        lead = lead_of(raw.get("lead"))
        if lead and norm(sents[0]).startswith(norm(lead)):
            lead = ""                              # "Declarative knowledge. Declarative knowledge consists ..."
        # Run 3: model-written definitions were textbook ones the lecturer never gave. The glossary entry is the
        # checked sentence of these notes that explains the term, so it is grounded by construction.
        terms = []
        for tm in (raw.get("terms") or [])[:3]:
            term = str((tm.get("term") if isinstance(tm, dict) else tm) or "").strip()[:60]
            said = any(v3.in_transcript(term, x) for x in texts) if term else False
            defining = next((x for x in sents if term and re.match(r"(the |a |an )?" + re.escape(term) + DEFINES, x, re.I)),
                            None)                  # the sentence must open with "<term> is/consists of ..." (not "is taught")
            if said and defining:
                terms.append({"term": term, "definition": defining})
            else:
                flags.append(f"term_dropped:{term!r}")
        return {**base, "lead": lead, "sentences": [{"text": s} for s in sents], "terms": terms,
                "background": v3.background_of(raw.get("background"), " ".join(sents), flags),
                "continue": bool(raw.get("continue"))}
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
            flags.append("example_text_repeats_steps")        # run 5: "Step 1: ... Step 2: ..." and the same list
            sents = []
        if not (sents or code or len(steps) >= 2):
            flags.append("example_empty")
            return None
        return {**base, "title": str(raw.get("title") or "").strip()[:80], "sentences": [{"text": s} for s in sents or []],
                "steps": steps, "code": code}
    if kind == "steps":
        items = clean_items(raw.get("items"), ev, flags)
        if len(items) < 2:
            flags.append("steps_too_short")
            return None
        return {**base, "lead": lead_of(raw.get("lead")), "items": items}
    if kind == "table":
        cols = [str(c).strip()[:40] for c in (raw.get("columns") or [])[:3] if str(c).strip()]
        rows = []
        for r in (raw.get("rows") or [])[:6]:
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
        return {**base, "caption": str(raw.get("caption") or "").strip()[:120], "columns": cols, "rows": rows}
    code = code_ok(raw.get("code"), ev, flags)
    if code is None:
        return None
    return {**base, "caption": str(raw.get("caption") or "").strip()[:120], "code": code}


def text_of(el: dict) -> str:
    """Plain text of an element: for the live prompt, the consolidation prompt and repeat checks."""
    k = el["kind"]
    body = " ".join(s["text"] for s in el.get("sentences", []))
    if k == "para":
        return f"{el['lead']}. {body}".strip(". ") if el["lead"] else body
    if k == "example":
        steps = "; ".join(el["steps"])
        return (f"Example ({el['title']}): {body}" + (f" Steps: {steps}." if steps else "")
                + (f" Code: {el['code']}" if el["code"] else ""))
    if k == "steps":
        return f"{el['lead']}: " + "; ".join(f"{i + 1}) {x}" for i, x in enumerate(el["items"]))
    if k == "table":
        return f"{el['caption']}: " + "; ".join(" | ".join(r) for r in el["rows"])
    if k == "code":
        return f"{el['caption']}: {el['code']}"
    return f"Remember: {el['text']}"


# ============================================================================================== stage 1: live (§11.4)
def live_user(state: State, chunks: list[dict]) -> str:
    words = "\n".join(text_of(el) for el in state.drafts).split()
    so_far = ("… " if len(words) > LIVE_CONTEXT_WORDS else "") + " ".join(words[-LIVE_CONTEXT_WORDS:])
    transcript = "\n".join(f"[{mmss(c['start_time'])}] {c['text']}" for c in chunks)
    return (f"{state.index()}\n\nNotes so far (since {mmss(state.S)}):\n{so_far or '(none yet)'}\n\n"
            f"Transcript, {mmss(chunks[0]['start_time'])}-{mmss(chunks[-1]['end_time'])}:\n{transcript}")


def apply_live(state: State, reply: dict, chunks: list[dict], k: int) -> tuple[list, Counter]:
    flags, stats = [], Counter()
    texts = [c["text"] for c in chunks]
    info = reply.get("info") if isinstance(reply.get("info"), dict) else None
    if info and str(info.get("text") or "").strip():
        span = v3.ground(info.get("quote"), str(info["text"]), texts, flags)
        if span:
            state.info.append({"text": str(info["text"]).strip()[:200], "t": chunks[span[0]]["start_time"]})
            stats["info"] += 1
    elements = [x for x in (reply.get("elements") or []) if isinstance(x, dict)]
    if len(elements) > LIVE_MAX_ELEMENTS:
        flags.append(f"too_many_elements({len(elements)})")
        elements = elements[:LIVE_MAX_ELEMENTS]
    for raw in elements:
        el = validate(raw, texts, chunks, flags, stats, state.sentences(), live=True)
        if el is None:
            continue
        el["k"] = k
        for s in el.get("sentences", []):
            s["k"] = k
        cont = el.pop("continue", False)
        paras = [d for d in state.drafts if d["kind"] == "para"]
        if cont and paras and len(paras[-1]["sentences"]) + len(el["sentences"]) <= LIVE_PARA_MAX:
            paras[-1]["sentences"] += el["sentences"]
            paras[-1]["terms"] += el["terms"]
            stats["continued"] += 1
        else:
            if cont:
                flags.append("continue_as_new_paragraph")
            state.drafts.append(el)
        stats[f"kept_{el['kind']}"] += 1
    state.reach = max(state.reach, chunks[-1]["end_time"])
    state.last_k = k
    return flags, stats


def extractive_live(state: State, chunks: list[dict], k: int) -> None:
    from agents.extractive import top_sentences
    picks = top_sentences(chunks)
    if picks:
        state.drafts.append({"kind": "para", "t": picks[0]["t"], "said": picks[0]["text"], "lead": "", "k": k,
                             "sentences": [{"text": p["text"], "k": k} for p in picks], "terms": [],
                             "background": None})
    state.reach = max(state.reach, chunks[-1]["end_time"])
    state.last_k = k


# ============================================================================================== stage 2: consolidation (§11.5)
def in_spoken_order(elements: list[dict]) -> list[dict]:
    """Run 2: the model ordered paragraphs by importance (03:40, 05:00, 02:30, 02:50), so the margin times jumped.
    Units (an idea plus the examples/code right after it) are put in spoken order."""
    units: list[list[dict]] = []
    for el in elements:
        if el["kind"] in ("example", "code") and units:
            units[-1].append(el)
        else:
            units.append([el])
    units.sort(key=lambda u: u[0]["t"])
    return [x for u in units for x in u]


def merge_short(topics: list[dict], state: State, flags: list) -> tuple[list[dict], set[int]]:
    """As in v3: a topic shorter than 2 minutes joins its neighbour; repeats are left out."""
    kept, appended, carry = [], set(), None
    for t in topics:
        if carry is not None:
            t["start"], t["elements"] = carry["start"], carry["elements"] + t["elements"]
            t["question"] = t["question"] or carry["question"]
            carry = None
        if t["end"] - t["start"] >= v3.MIN_TOPIC_S:
            kept.append(t)
            continue
        prev = kept[-1] if kept else (state.topics[-1] if state.topics and state.topics[-1]["end"] == t["start"]
                                      else None)
        if prev is None:
            carry = t
            continue
        have = [text_of(x) for x in prev["elements"]]
        extra = [x for x in t["elements"] if not any(similar(text_of(x), h) >= 0.5 for h in have)]
        flags.append(f"short_topic_merged:{t['title']!r} -> {prev['title']!r} ({len(extra)} kept, "
                     f"{len(t['elements']) - len(extra)} repeated)")
        prev["elements"] += extra
        prev["end"] = t["end"]
        prev["question"] = prev["question"] or t["question"]
        if not kept:
            appended.add(prev["n"])
    if carry is not None:
        kept.append(carry)
    return kept, appended


def consolidate(state: State, client, chunks_all: list[dict], end: float, mode: str, report: list) -> dict:
    S = state.S
    chunks = [c for c in chunks_all if S <= c["start_time"] < end]
    texts = [c["text"] for c in chunks]
    whole = " ".join(texts)
    drafts = [d for d in state.drafts if d["t"] < end]
    system = CONSOLIDATE_SYSTEM.replace("OPEN_RULE", v3.OPEN_RULE + "\n" if mode == "open" else "").replace(
        "OPEN_FIELD", ',\n "in_progress_from": null' if mode == "open" else "").replace(
        "NEXT_N", str(len(state.topics) + 1))
    transcript = "\n".join(f"[{mmss(c['start_time'])}] {c['text']}" for c in chunks)
    user = (f"{state.index()}\n\nTranscript, {mmss(chunks[0]['start_time'])}-{mmss(chunks[-1]['end_time'])}:\n"
            f"{transcript}\n\nRough live notes of this stretch:\n" + ("\n".join(text_of(d) for d in drafts) or "(none)"))
    res = v3.strong_call(client, system, user)
    pace(res)
    flags, stats = [], Counter()
    cut, new_topics = end, []
    if res.ok:
        reply = res.data
        if mode == "open":
            ipf = parse_t(reply.get("in_progress_from"))
            if ipf is not None:
                if S + 60 <= ipf <= end - 30:
                    cut = v3.snap(ipf, chunks)
                    flags.append(f"in_progress_from {mmss(cut)}")
                else:
                    flags.append(f"in_progress_from_ignored:{reply.get('in_progress_from')!r}")
        by_n: dict = {}
        for i, rt in enumerate([t for t in (reply.get("topics") or []) if isinstance(t, dict)][:3]):
            title = str(rt.get("title") or "").strip()[:90] or "Untitled"
            start = S if i == 0 else parse_t(rt.get("starts_at"))
            start = None if start is None else v3.snap(start, chunks)
            if new_topics and (start is None or start <= new_topics[-1]["start"]):
                flags.append(f"topic_start_invalid:{title!r}")
                by_n[rt.get("n")] = new_topics[-1]
            elif start is not None and start >= cut:
                by_n[rt.get("n")] = None
            else:
                new_topics.append({"title": title, "start": start if start is not None else S, "elements": [],
                                   "question": None})
                by_n[rt.get("n")] = new_topics[-1]
        known = [s["text"] for t in state.topics for x in t["elements"] for s in x.get("sentences", [])]
        for raw in [x for x in (reply.get("elements") or []) if isinstance(x, dict)][:30]:
            if not new_topics:
                break
            el = validate(raw, texts, chunks, flags, stats, known, live=False)
            if el is None:
                continue
            el.pop("continue", None)
            if el["t"] >= cut:
                flags.append("element_after_cut")
                continue
            target = [t for t in new_topics if t["start"] <= el["t"]][-1]      # by time; model order kept within
            if raw.get("topic") in by_n and by_n[raw.get("topic")] is not target:
                flags.append("element_topic_by_time")
            if el["kind"] in ("example", "code") and any(
                    similar(text_of(el), text_of(x)) >= 0.5 or (el.get("code") and x.get("code")
                                                                 and norm(el["code"]) in norm(x["code"]))
                    for t in new_topics for x in t["elements"] if x["kind"] in ("example", "code")):
                flags.append("example_repeats_earlier")
                continue
            target["elements"].append(el)
            known += [s["text"] for s in el.get("sentences", [])]
        for q in [q for q in (reply.get("questions") or []) if isinstance(q, dict)]:
            target = by_n.get(q.get("topic"))
            question, answer = str(q.get("q") or "").strip()[:300], str(q.get("answer") or "").strip()[:400]
            if target is None or not question or not answer or target["question"] is not None:
                continue
            if LOGISTICS.search(question):
                flags.append("logistics_question")
                continue
            score = grounded(answer, whole)
            if score >= v3.LOCAL_SUPPORT_MIN:
                target["question"] = {"q": question, "answer": answer}
            else:
                flags.append(f"question_unsupported({score:.2f})")
        new_topics = [t for t in new_topics if t["elements"]]
        if new_topics:
            new_topics[0]["start"] = S                  # an emptied first topic must not leave a gap
    generator = "llm" if new_topics else "fallback"
    if not new_topics:
        flags.append(f"fallback ({res.reason or 'nothing survived'})")
        kept = [d for d in drafts if d["t"] < cut]
        if kept:
            new_topics = [{"title": f"Notes {mmss(S)}–{mmss(cut)}", "start": S, "elements": kept, "question": None}]
    for i, t in enumerate(new_topics):
        t["end"] = new_topics[i + 1]["start"] if i + 1 < len(new_topics) else cut
        t["elements"] = in_spoken_order(t["elements"])
        for x in t["elements"]:
            for tm in x.get("terms", []):
                key = tm["term"].lower()
                state.glossary[key] = {**tm, "t": x["t"], "refined": key in state.glossary}
    new_topics, appended = merge_short(new_topics, state, flags)
    if not new_topics and state.topics and state.topics[-1]["end"] == S:
        state.topics[-1]["end"] = cut
    for t in new_topics:
        t["n"] = len(state.topics) + 1
        t["generator"] = generator
        state.topics.append(t)
    state.organised = {t["n"] for t in new_topics} | appended
    state.drafts = [d for d in state.drafts if d["t"] >= cut]
    state.S = cut

    report.append(f"\n## Consolidation {mmss(S)}-{mmss(end)} ({mode}) -> cut at {mmss(cut)}, {generator}\n")
    if res.ok:
        report.append(f"{res.model}, {res.latency_s} s, {res.prompt_tokens}+{res.completion_tokens} tokens"
                      f"{' (cached)' if res.cached else ''}\n")
        report.append("```json\n" + json.dumps(res.data, indent=1, ensure_ascii=False)[:12000] + "\n```\n")
    if res.attempts:
        report.append(f"Attempts that failed first: {res.attempts}\n")
    report.append("Validation: " + ("; ".join(f"`{f}`" for f in flags) or "all kept") + "\n")
    return {"span": f"{mmss(S)}-{mmss(end)}", "mode": mode, "cut": cut, "generator": generator, "model": res.model,
            "latency_s": res.latency_s, "tokens": res.tokens if res.ok else None,
            "topics": [t["title"] for t in new_topics], "stats": dict(stats), "flags": flags}


# ============================================================================================== page (§11.6)
CSS = v3.CSS + """
.cols{grid-template-columns:210px minmax(0,1fr) 320px}
.doc{max-width:48em}
.topic{background:transparent;border:0;border-top:1px solid var(--border);border-radius:0;margin:0 0 6px}
.topic>summary{padding:14px 0 8px;font-size:19px}
.topic .doc{padding:0 0 10px}
.el{display:grid;grid-template-columns:minmax(0,1fr) 46px;gap:14px;margin:0 0 12px}
.el .ts{justify-self:end;align-self:start;margin-top:3px}
.el p{margin:0;line-height:1.65}
.lead{font-weight:700}
.example{border-left:3px solid var(--ex);background:var(--panel);padding:8px 14px;border-radius:0 6px 6px 0}
.exh{font-size:13px;font-weight:700;color:var(--ex);margin-bottom:4px}
.example ol,.steps ol{margin:6px 0 0;padding-left:22px}
.example pre,.el pre{margin:8px 0 0;background:var(--codebg);padding:8px 10px;border-radius:6px;overflow-x:auto;font-size:13px}
.remember{border-left:3px solid var(--imp);padding:4px 12px}
.cap{font-weight:600;margin-bottom:4px}
.el table{border-collapse:collapse;font-size:14px}
.el th,.el td{border:1px solid var(--border);padding:4px 10px;text-align:left;vertical-align:top}
.el .bg{margin:6px 0 0;color:var(--muted);font-size:13px;font-style:italic}
mark.fresh{background:color-mix(in srgb,var(--new) 22%,transparent);color:inherit;border-radius:3px;padding:0 1px}
.live .el p{opacity:.95}
@media (max-width:1000px){.cols{grid-template-columns:minmax(0,1fr)}.el{grid-template-columns:minmax(0,1fr)}
.el .ts{justify-self:start;order:-1}.topic>summary{font-size:17px}}
"""


def sentences_html(sents: list[dict], terms: list[dict], new_k: int | None) -> str:
    pending = [t["term"] for t in terms]
    out = []
    for s in sents:
        h = e(s["text"])
        for term in list(pending):                 # bold the first occurrence of each defined term (escaped text)
            m = re.search(re.escape(e(term)), h, re.I)
            if m:
                h = h[:m.start()] + f"<strong>{m.group(0)}</strong>" + h[m.end():]
                pending.remove(term)
        out.append(f'<mark class="fresh">{h}</mark>' if new_k is not None and s.get("k") == new_k else h)
    return " ".join(out)


def element_html(el: dict, new_k: int | None = None) -> str:
    k = el["kind"]
    if k == "para":
        lead = f'<span class="lead">{e(el["lead"])}.</span> ' if el["lead"] else ""
        body = f"<p>{lead}{sentences_html(el['sentences'], el['terms'], new_k)}</p>"
        if el.get("background"):
            body += f'<div class="bg">Background: {e(el["background"])}</div>'
    elif k == "example":
        body = (f'<div class="example"><div class="exh">Example{" · " + e(el["title"]) if el["title"] else ""}</div>'
                + (f"<p>{sentences_html(el['sentences'], [], new_k)}</p>" if el["sentences"] else "")
                + ("<ol>" + "".join(f"<li>{e(x)}</li>" for x in el["steps"]) + "</ol>" if el["steps"] else "")
                + (f"<pre>{e(el['code'])}</pre>" if el["code"] else "") + "</div>")
    elif k == "steps":
        body = (f'<div class="steps"><p><span class="lead">{e(el["lead"])}:</span></p><ol>'
                + "".join(f"<li>{e(x)}</li>" for x in el["items"]) + "</ol></div>")
    elif k == "table":
        body = ((f'<div class="cap">{e(el["caption"])}</div>' if el["caption"] else "") + "<table><tr>"
                + "".join(f"<th>{e(c)}</th>" for c in el["columns"]) + "</tr>"
                + "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in r) + "</tr>" for r in el["rows"]) + "</table>")
    elif k == "code":
        body = (f'<div class="cap">{e(el["caption"])}</div>' if el["caption"] else "") + f"<pre>{e(el['code'])}</pre>"
    else:
        body = f'<div class="remember"><span class="lead">Remember:</span> {e(el["text"])}</div>'
    return (f'<div class="el"><div>{body}</div><span class="ts" title="&ldquo;{e(el["said"])}&rdquo;">'
            f'{mmss(el["t"])}</span></div>')


def render(state: State, chunks: list[dict], now: float, status: str, finished: bool) -> str:
    topics = []
    for i, t in enumerate(state.topics):
        is_open = finished or i == len(state.topics) - 1
        chip = ' <span class="chip">✓ organised</span>' if t["n"] in state.organised and not finished else ""
        body = "".join(element_html(x) for x in t["elements"])
        if t["question"]:
            body += (f'<div class="check"><b>Check yourself:</b> {e(t["question"]["q"])}'
                     f'<details><summary>Show answer</summary>{e(t["question"]["answer"])}</details></div>')
        topics.append(f'<details class="topic"{" open" if is_open else ""}><summary>{t["n"]}. {e(t["title"])}'
                      f'<span class="range">{mmss(t["start"])}–{mmss(t["end"])}</span>{chip}</summary>'
                      f'<div class="doc">{body}</div></details>')
    live = ""
    if not finished:
        tail = [c for c in chunks if c["end_time"] <= now][-2:]
        said = " ".join(c["text"] for c in tail)
        live = (f'<section class="live"><div class="lh">LIVE NOTES SINCE {mmss(state.S)} · draft, organised into '
                f'topics every few minutes</div><div class="doc">'
                + ("".join(element_html(d, state.last_k) for d in state.drafts)
                   or '<p class="pending">the next notes will appear here</p>')
                + f'</div><div class="status">{e(status)}</div>'
                + (f'<div class="now">now: “…{e(said[-260:])}”</div>' if said else "") + "</section>")
    rail = ["<h3>Contents</h3><ol>"] + [f'<li>{e(t["title"])} <span class="ok">✓</span></li>' for t in state.topics]
    if not finished:
        rail.append(f'<li>Live notes since {mmss(state.S)} <span class="rl">live</span></li>')
    rail.append("</ol>")
    if state.info:
        rail.append(f"<details><summary>Course info ({len(state.info)})</summary><ul>"
                    + "".join(f"<li>{e(i['text'])}</li>" for i in state.info) + "</ul></details>")
    if state.glossary:
        rail.append(f"<details open><summary>Glossary ({len(state.glossary)})</summary><dl>"
                    + "".join(f"<dt>{e(g['term'])}</dt><dd>{e(g['definition'])}</dd>"
                              for g in sorted(state.glossary.values(), key=lambda g: g["term"].lower())) + "</dl></details>")
    badge = (f'<span class="badge">Finished · {mmss(v3.END_S)}</span>' if finished
             else f'<span class="badge live">● LIVE {mmss(min(now, v3.END_S))}</span>')
    reach = ("" if finished else f'<div class="sub">Notes reach {mmss(state.reach)} (they follow the lecture by about '
                                 f'1–2 min)</div>') if state.reach else \
        '<div class="sub">The first notes appear about 2 minutes into the lecture</div>'
    main = "".join(topics) + live or '<div class="empty">No notes yet.</div>'
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>Notebook prototype</title><style>{CSS}</style></head>'
            f'<body><div class="page"><div class="head"><div><h1>{e(v3.TITLE)}</h1>{reach}</div>{badge}</div>'
            f'<div class="cols"><nav class="rail">{"".join(rail)}</nav><main>{main}</main>'
            f'<aside class="chat"><b>Lecture Assistant</b><br>Chat, unchanged (not part of this prototype).</aside>'
            f'</div></div></body></html>')


# ============================================================================================== main
def main() -> None:
    global OUT
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks", help="another transcript (M2 chunks .jsonl); default: the 28 Oct live run")
    ap.add_argument("--title")
    ap.add_argument("--minutes", type=float)
    ap.add_argument("--out", help="results folder name under bench/results")
    args = ap.parse_args()
    if args.chunks:                       # an unseen lecture: same code and prompts, only the input changes
        v3.CHUNKS, v3.TITLE = Path(args.chunks), args.title or Path(args.chunks).stem
        v3.END_S = int((args.minutes or 12.5) * 60)
        v3.MOMENTS = {"live": round(v3.END_S * 0.6), "finished": v3.END_S + 100}
        OUT = ROOT / "bench" / "results" / (args.out or f"proto_v4_{Path(args.chunks).stem}")
    OUT.mkdir(parents=True, exist_ok=True)
    chunks = [c for c in v3.load_chunks() if c["start_time"] < v3.END_S]
    client = llm.Client("notes")
    if not client.chain:
        sys.exit("No LLM provider configured in .env")
    state, report, live_rows, cons_rows, events = State(), [], [], [], []
    report.append(f"# Prototype §11: study-guide notes, {v3.TITLE}, 00:00-{mmss(v3.END_S)}\n")
    n_updates = -(-v3.END_S // v3.UPDATE_S)
    for k in range(n_updates):
        part = [c for c in chunks if k * v3.UPDATE_S <= c["start_time"] < (k + 1) * v3.UPDATE_S]
        res = client.complete_json(LIVE_SYSTEM, live_user(state, part), max_tokens=1500, wait_s=60)
        pace(res)
        span = f"{mmss(part[0]['start_time'])}-{mmss(part[-1]['end_time'])}"
        report.append(f"\n## Update {k}: {span}\n")
        if res.ok:
            flags, stats = apply_live(state, res.data, part, k)
            report.append(f"{res.model}, {res.latency_s} s, {res.prompt_tokens}+{res.completion_tokens} tokens"
                          f"{' (cached)' if res.cached else ''}\n")
            report.append("```json\n" + json.dumps(res.data, indent=1, ensure_ascii=False)[:6000] + "\n```\n")
        else:
            extractive_live(state, part, k)
            flags, stats = [f"llm_failed:{res.reason} {res.attempts}"], Counter()
        report.append("Validation: " + ("; ".join(f"`{f}`" for f in flags) or "all kept") + "\n")
        live_rows.append({"update": k, "span": span, "ok": res.ok, "model": res.model, "latency_s": res.latency_s,
                          "tokens": res.tokens if res.ok else None, "stats": dict(stats), "flags": flags})
        print(f"update {k} {span}: {'ok' if res.ok else 'FAILED ' + str(res.reason)} {dict(stats)}", flush=True)
        last = k == n_updates - 1
        visible = min((k + 1) * v3.UPDATE_S, v3.END_S) + v3.VISIBLE_DELAY_S + (v3.END_DETECT_S if last else 0)
        state.organised = set()
        events.append({"kind": "update", "visible": visible, "block_start": k * v3.UPDATE_S,
                       "block_end": min((k + 1) * v3.UPDATE_S, v3.END_S), "state": copy.deepcopy(state)})
        block_end = part[-1]["end_time"]
        trigger = (v3.END_S, "closed") if last else (
            (block_end, "open" if block_end - state.S < v3.FORCE_S else "closed")
            if block_end - state.S >= v3.STRETCH_S else None)
        if trigger:
            row = consolidate(state, client, chunks, trigger[0], trigger[1], report)
            cons_rows.append(row)
            print(f"  consolidation {row['span']} {row['mode']}: {row['generator']} topics={row['topics']} "
                  f"{row['stats']}", flush=True)
            events.append({"kind": "consolidation", "visible": visible + (row["latency_s"] or 5),
                           "state": copy.deepcopy(state)})

    for name, now in v3.MOMENTS.items():
        shown = [ev for ev in events if ev["visible"] <= now]
        st = shown[-1]["state"] if shown else State()
        finished = now >= events[-1]["visible"]
        (OUT / f"view_{name}.html").write_text(render(st, chunks, now, v3.status_at(now, events), finished),
                                               encoding="utf-8")

    elements = [x for t in state.topics for x in t["elements"]]
    words = sum(len(text_of(x).split()) for x in elements)
    list_lines = sum(len(x.get("items", [])) + len(x.get("steps", [])) + len(x.get("rows", [])) for x in elements)
    live_total, cons_total = Counter(), Counter()
    for r in live_rows:
        live_total.update(r["stats"])
    for r in cons_rows:
        cons_total.update(r["stats"])
    per6 = v3.END_S / 360
    metrics = {
        "live": {"updates": len(live_rows), "llm_ok": sum(r["ok"] for r in live_rows), **live_total,
                 "tokens_mean": round(sum(r["tokens"] or 0 for r in live_rows) / len(live_rows))},
        "consolidation": {"calls": len(cons_rows), "llm": sum(r["generator"] == "llm" for r in cons_rows),
                          **cons_total, "tokens_mean": round(sum(r["tokens"] or 0 for r in cons_rows) / max(1, len(cons_rows)))},
        "final": {"topics": [f"{t['n']}. {t['title']} ({mmss(t['start'])}-{mmss(t['end'])})" for t in state.topics],
                  "elements": dict(Counter(x["kind"] for x in elements)),
                  "sentences": sum(len(x.get("sentences", [])) for x in elements),
                  "words": words, "words_per_6_min": round(words / per6),
                  "list_lines_per_6_min": round(list_lines / per6, 1),
                  "questions": sum(1 for t in state.topics if t["question"]),
                  "glossary": [g["term"] for g in state.glossary.values()], "info": [i["text"] for i in state.info]},
        "per_update": live_rows, "per_consolidation": cons_rows,
    }
    (OUT / "report.md").write_text("\n".join(report), encoding="utf-8")
    (OUT / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in metrics.items() if not k.startswith("per_")}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
