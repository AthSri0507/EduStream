"""Prototype for docs/NOTEBOOK_DESIGN.md rev 2: structured live drafts + consolidation, offline.

Replays the real transcript of the 28 Oct live run (Python · Lecture 1, 00:00-12:30, real Whisper output from
data/edustream.db) through
  stage 1  one structured live call per 90 s (ops: new / extend / topic / info), validated in code (§3.3)
  stage 2  consolidation of each stretch with hindsight (§4), triggered by the §4.1 rules
and renders the proposed notebook page (§6) at the same moments as the 28 Oct screenshots, so the two can be
compared side by side. Nothing in the pipeline changes.

    .venv\\Scripts\\python bench\\proto_notebook_v3.py

Writes bench/results/proto_v3/: report.md (every reply and every validation decision), metrics.json and
view_<moment>.html. Replies are cached (LLM_CACHE=on, data/llm_cache.sqlite), so a rerun costs nothing.
API keys come from .env and are never printed.
"""

from __future__ import annotations

import copy
import html
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from common import config  # noqa: E402,F401  (loads .env)

os.environ.update(LLM_ENABLED="true", LLM_FORCE_FAIL="false", LLM_CACHE="on")

from agents import llm  # noqa: E402
from agents.extractive import top_sentences  # noqa: E402
from agents.text import content_words, find_quote, mmss, norm, parse_t, similar, stem, support  # noqa: E402

OUT = ROOT / "bench" / "results" / "proto_v3"
CHUNKS = ROOT / "bench" / "results" / "chunks_live_python_l1_20261028.jsonl"
VIDEO_ID, TITLE = "python_l1", "Python · Lecture 1 (Bell)"
UPDATE_S, END_S = 90, 750
VISIBLE_DELAY_S = 27              # 28 Oct run: an update reached the screen 24-29 s after its 90 s block
END_DETECT_S = 30                 # the last update waits for the lecture-end signal
MOMENTS = {"02m30s": 157, "05m00s": 301, "08m00s": 481, "12m10s": 731, "finished": 849}

LIVE_TYPES = ("key_idea", "definition", "list", "example", "code", "important")
EXTENDABLE = ("key_idea", "list", "example")
TYPES = LIVE_TYPES + ("comparison",)
LABEL = {"key_idea": "Key idea", "definition": "Definition", "list": "List", "example": "Example",
         "comparison": "Comparison", "code": "Code", "important": "Important"}
MAX_NOTE_OPS = 3
LOCAL_SUPPORT_MIN = 0.30          # as today (option A): the block vs. its quote's neighbourhood
ITEM_SUPPORT_MIN = 0.40           # an item vs. the update (live) or the block's neighbourhood (consolidation)
DUPLICATE_MIN = 0.60
ANCHOR_MIN = 0.80                 # share of a quote's words found in order (run 1: the model tidies ASR text)
LOCATE_SUPPORT_MIN = 0.50         # no usable quote: code finds where the block was said, stricter bar
CUT_MIN_S, STRETCH_S, FORCE_S = 180, 360, 720      # §4.1
MIN_TOPIC_S = 120                 # shorter topics join a neighbour (run 3)
HOUSEKEEPING = re.compile(r"\b(slides?|problem sets?|psets?|office hours|recitations?|piazza|recorded|exams?|quiz(zes)?"
                          r"|grades?|deadlines?|website|textbook|finger exercises|attend\w*)\b", re.I)


# ============================================================================================== prompts
LIVE_SYSTEM = """You are the note-taker for a live university lecture. Every 90 seconds you receive the next part
of the transcript (automatic speech recognition, so it can contain errors) and the notes of the current topic so far.

Write structured notes, as a diligent student would, using blocks:
- key_idea: a main point. "title" states the point in one sentence; optional "items": 1-4 short sub-points.
- definition: a technical term the lecturer introduces and explains (not an everyday word such as "practice").
  "term" is the term, "title" its definition.
- list: an enumeration or a procedure. "title" names it ("Three parts of the course"); "items" are the entries or
  steps in order. If the lecturer announces a list but has not given the entries yet, use "items": [] and add them
  later with "extend".
- example: a worked example. "title" names it; "items" are its steps or facts in order.
- code: code or a formula the lecturer writes or dictates. "title" says what it does; "code" holds it.
- important: something the lecturer stresses as important or warns about. "title" is the statement.

Operations:
- {"op": "new", "type": "...", "title": "...", "term": "... (definition only)", "items": ["..."],
   "code": "... (code only)", "quote": "...", "background": null or "..."}
- {"op": "extend", "block": "<id of a block of the current topic>", "items": ["..."], "quote": "..."}
  Use it when the lecturer continues a list, an example or an idea that is already in the notes: add to that
  block instead of starting a new one.
- {"op": "topic", "title": "short name of the new topic", "starts_at": "mm:ss"}
  Only when the lecturer clearly moves to a different subject in this part. At most one.
- {"op": "info", "text": "...", "quote": "..."}
  Course logistics (slides, problem sets, deadlines, office hours, recording notices) go here, never into blocks.
  At most one.

Rules:
- At most 3 "new"/"extend" operations. Returning no operations is fine when nothing new is worth noting.
- Write the notes themselves, telegraphic and specific; never describe the talk ("the lecturer says ...").
- Only what was said in this part. If a block needs an explanation the lecturer did not give, put it in
  "background" (shown separately, labelled); never mix outside knowledge into "title" or "items".
- Every "new" and "extend" needs "quote": 5-15 consecutive words copied from this part of the transcript, where
  the block (or the added items) is said. No "...".
- "block" in "extend" must be one of the ids listed under "Notes of the current topic"; nothing else exists yet.
  To give a block you are creating now more entries, put them in its "items".
- Topics: the current topic's name is shown above. When what is being said no longer fits it (for example the
  lecturer moves from course organisation to the first subject, or from one concept to the next), use "topic".
  A topic usually lasts 3-10 minutes; an hour-long lecture has about 6-15 of them.
- Never repeat what is already in the notes.
- The transcript has recognition errors: in your own wording write the intended word when it is obvious.

Return ONLY a JSON object: {"ops": [ ... ]}"""

CONSOLIDATE_SYSTEM = """You turn the rough live notes of one stretch of a university lecture into the final,
well-organised notes for that stretch. You receive the topics finished earlier in the lecture and the glossary so
far, the transcript of the stretch (automatic speech recognition, so it can contain errors), and the rough live
notes written during it.

Write the notes a top student would keep for studying:
- Split the stretch into 1-3 topics where the subject actually changes, each with a clear, specific title.
  If a topic continues or revisits a finished topic, set "revisits" to that topic's number.
- Blocks: key_idea (a main point, optional 1-4 sub-points in "items"), definition (a technical term the lecturer
  explains, not an everyday word: "term" + definition in "title"),
  list (entries or steps kept together and complete), example (a worked example, its steps or facts in order),
  comparison (only when the lecturer explicitly contrasts 2-3 things: a small table), code ("code"), important.
- Keep what the live notes got right, merge repeated points, complete lists and examples, drop what is wrong,
  trivial or course logistics. Prefer fewer, richer blocks: about 4-8 per 6 minutes of lecture.
- Do not define again a term already in the glossary unless the lecturer adds something new; then give the
  refined definition.
- One check-yourself question per topic that tests understanding (not trivia), with a short answer from the lecture.
- Only what was said. An explanation the lecturer did not give goes in "background": one short sentence, only where
  the lecture leaves a real gap.
- Write the notes themselves, never "the lecturer says". Correct obvious recognition errors in your wording.
- Every block has its own "quote": 5-15 consecutive words copied from the transcript where its content is said.
OPEN_RULE
Return ONLY a JSON object with three flat lists. Number the new topics from NEXT_N; blocks and questions name their
topic by that number. Do not put "revisits" information into a title.
{"topics": [{"n": NEXT_N, "title": "...", "starts_at": "mm:ss", "revisits": null}],
 "blocks": [{"topic": NEXT_N, "type": "key_idea", "title": "...", "items": ["..."], "quote": "..."}],
 "questions": [{"topic": NEXT_N, "q": "...", "answer": "..."}]OPEN_FIELD}
Extra block fields by type: definition adds "term"; code adds "code"; comparison adds
"table": {"columns": ["...", "..."], "rows": [["...", "..."]]}; any block may add "background"."""

OPEN_RULE = ("- If the last topic is still going on at the end of the stretch (the lecturer is in the middle of it),"
             " do not write it: set \"in_progress_from\" to the mm:ss where it starts; it will be written with the"
             " next stretch. Otherwise \"in_progress_from\": null.")


# ============================================================================================== state
class State:
    def __init__(self) -> None:
        self.drafts: list[dict] = []        # live blocks not consolidated yet
        self.ptopics: list[dict] = []       # provisional topics {id, title, start}
        self.topics: list[dict] = []        # consolidated topics
        self.glossary: dict[str, dict] = {}
        self.info: list[dict] = []
        self.S = 0.0                        # start of the stretch not consolidated yet
        self.seq = 0
        self.reach = 0.0                    # how far the notes reach (media seconds)
        self.last_k = -1                    # newest update applied (for "new" marks)
        self.organised: set[int] = set()    # topics consolidated by the newest event

    @property
    def current(self) -> dict:
        if not self.ptopics:
            self.seq += 1
            self.ptopics.append({"id": self.seq, "title": None, "start": self.S})
        return self.ptopics[-1]

    def index(self) -> str:
        done = "; ".join(f"{t['n']}. {t['title']} ({mmss(t['start'])}-{mmss(t['end'])})" for t in self.topics)
        terms = ", ".join(g["term"] for g in self.glossary.values())
        return f"Finished topics: {done or '(none yet)'}\nGlossary so far: {terms or '(none yet)'}"


def anchor(quote: str, texts: list[str]) -> tuple[int, int] | None:
    """Where a quote was said: exact first (find_quote), else near-verbatim: >= 80 % of its words in order within
    a stretch at most twice its length (run 1: "It performs calculations" for "It performs these calculations")."""
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
    """Location of a block: its quote, or (no usable quote) the line whose neighbourhood supports it best."""
    span = anchor(str(quote or ""), texts)
    if span is not None:
        if find_quote(str(quote or ""), texts) is None:
            flags.append("quote_near_verbatim")
        return span
    best, at = 0.0, None
    for i in range(len(texts)):
        score = support(claim, " ".join(texts[max(0, i - r): i + r + 1]))
        if score > best:
            best, at = score, i
    if best >= LOCATE_SUPPORT_MIN:
        flags.append("located_by_support")
        return at, at
    flags.append(f"not_grounded({best:.2f}): {claim[:60]!r}")
    return None


def said(texts: list[str], span: tuple[int, int]) -> str:
    return " ".join(texts[span[0]: span[1] + 1])[:400]


def snap(t: float, chunks: list[dict]) -> float:
    starts = [c["start_time"] for c in chunks if c["start_time"] <= t]
    return max(starts) if starts else chunks[0]["start_time"]


def around(texts: list[str], span: tuple[int, int], r: int) -> str:
    return " ".join(texts[max(0, span[0] - r): span[1] + r + 1])


def in_transcript(term: str, whole: str) -> bool:
    n, w = norm(term), norm(whole)
    return bool(n) and (n in w or " ".join(stem(x) for x in n.split()) in " ".join(stem(x) for x in w.split()))


def words_of(text: str) -> set[str]:
    """Distinct content words, stems without a final e ("solve" ~ "solving")."""
    out = set()
    for w in content_words(text):
        out.add(w[:-1] if len(w) > 4 and w.endswith("e") else w)
    return out


def item_support(text: str, evidence: str) -> float:
    """Share of an item's DISTINCT content words said nearby. Run 4: counting repeats let an invented
    "random.random() returns a float" pass on "random" twice, while a real "Problem-solving ability" failed."""
    mine = words_of(text)
    return len(mine & words_of(evidence)) / len(mine) if mine else 0.0


def clean_items(raw, evidence: str, flags: list, existing=()) -> list[str]:
    out: list[str] = []
    for it in (raw if isinstance(raw, list) else [])[:8]:
        text = str((it.get("text") if isinstance(it, dict) else it) or "").strip()[:220]
        if not text:
            continue
        score = item_support(text, evidence)
        if score < ITEM_SUPPORT_MIN:
            flags.append(f"item_unsupported({score:.2f}): {text[:60]!r}")
            continue
        if any(similar(text, e) >= DUPLICATE_MIN for e in [*existing, *out]):
            flags.append(f"item_duplicate: {text[:60]!r}")
            continue
        out.append(text)
    return out


def background_of(raw, title: str, flags: list) -> str | None:
    if not isinstance(raw, str) or not raw.strip() or raw.strip().lower() in ("null", "none"):
        return None
    if similar(raw, title) >= DUPLICATE_MIN:
        flags.append("background_repeats_block")
        return None
    return raw.strip()[:300]


# ============================================================================================== stage 1: live
def live_user(state: State, chunks: list[dict]) -> str:
    cur = state.current
    blocks = [b for b in state.drafts if b["ptopic"] == cur["id"]][-8:]
    lines = []
    for b in blocks:
        last = f'; last: "{b["items"][-1]["text"][:80]}"' if b["items"] else ""
        lines.append(f"- {b['id']} [{b['type']}] {b['title'][:120]} ({len(b['items'])} items{last})")
    transcript = "\n".join(f"[{mmss(c['start_time'])}] {c['text']}" for c in chunks)
    return (f"{state.index()}\nCurrent topic: {cur['title'] or '(not named yet)'}\n"
            f"Notes of the current topic:\n" + ("\n".join(lines) or "(none yet)") +
            f"\n\nTranscript, {mmss(chunks[0]['start_time'])}-{mmss(chunks[-1]['end_time'])}:\n{transcript}")


def apply_live(state: State, reply: dict, chunks: list[dict], k: int) -> tuple[list, Counter, float | None]:
    flags: list[str] = []
    stats: Counter = Counter()
    texts = [c["text"] for c in chunks]
    whole = " ".join(texts)
    ops = [o for o in (reply.get("ops") if isinstance(reply.get("ops"), list) else []) if isinstance(o, dict)]
    before = state.current
    current_ids = {b["id"] for b in state.drafts if b["ptopic"] == before["id"]}
    seen_titles = [b["title"] for b in state.drafts] + [b["title"] for t in state.topics for b in t["blocks"]]

    shift = None
    for o in [o for o in ops if o.get("op") == "topic"][:1]:
        stats["topic"] += 1
        title = str(o.get("title") or "").strip()[:80]
        t = parse_t(o.get("starts_at"))
        if not title:
            flags.append("topic_without_title")
            continue
        if t is None or not chunks[0]["start_time"] <= t < chunks[-1]["end_time"]:
            flags.append("topic_start_outside_update")
            t = chunks[0]["start_time"]
        t = snap(t, chunks)
        if not current_ids:                               # nothing written under the current topic yet: name it
            before["title"] = title
            flags.append("topic_names_current")
        elif t - before["start"] < 60:
            flags.append("topic_too_soon_ignored")
        else:
            state.seq += 1
            state.ptopics.append({"id": state.seq, "title": title, "start": t})
            shift = t
    after = state.ptopics[-1]

    for o in [o for o in ops if o.get("op") == "info"][:1]:
        stats["info"] += 1
        text = str(o.get("text") or "").strip()[:200]
        span = ground(o.get("quote"), text, texts, flags) if text else None
        if text and span:
            state.info.append({"text": text, "t": chunks[span[0]]["start_time"], "k": k})
        else:
            flags.append("info_dropped")

    seq, n, made = 0, 0, []
    for o in ops:
        kind = o.get("op")
        if kind in ("topic", "info"):
            continue
        if kind not in ("new", "extend"):
            flags.append(f"unknown_op:{kind!r}")
            continue
        if n >= MAX_NOTE_OPS:
            flags.append("too_many_ops")
            continue
        n += 1
        stats[f"proposed_{kind}"] += 1
        if kind == "extend":
            target = next((b for b in state.drafts if b["id"] == o.get("block")), None)
            if target is None and made and made[-1]["type"] in EXTENDABLE:     # it meant the block it just made
                target = made[-1]
                current_ids.add(target["id"])
                flags.append("extend_resolved_to_new_block")
            if target is not None and target["id"] in current_ids and target["type"] in EXTENDABLE:
                items = clean_items(o.get("items"), whole, flags, [i["text"] for i in target["items"]] + [target["title"]])
                if items:
                    span = anchor(str(o.get("quote") or ""), texts)
                    t = chunks[span[0]]["start_time"] if span else chunks[0]["start_time"]
                    target["items"] += [{"text": x, "t": t, "k": k} for x in items]
                    stats["extend_ok"] += 1
                else:
                    stats["extend_empty"] += 1
                continue
            reason = "unknown_block" if target is None else (
                "other_topic" if target["id"] not in current_ids else "type_not_extendable")
            flags.append(f"extend_converted:{reason}")
            stats["extend_converted"] += 1
            raw = [str((i.get("text") if isinstance(i, dict) else i) or "") for i in (o.get("items") or [])]
            raw = [x for x in raw if x.strip()]
            if not raw:
                continue
            o = {"type": "key_idea", "title": raw[0], "items": raw[1:], "quote": o.get("quote")}

        btype = o.get("type")
        if btype not in LIVE_TYPES:
            flags.append(f"type_fixed:{btype!r}")
            btype = "key_idea"
        title = str(o.get("title") or "").strip()[:240]
        if not title:
            flags.append("empty_title")
            continue
        term = str(o.get("term") or "").strip()[:80] if btype == "definition" else None
        claim = claim_of(btype, term, title, o.get("items"))
        span = ground(o.get("quote"), claim, texts, flags, 3 if btype in ("list", "example") else 1)
        if span is None:
            stats["dropped"] += 1
            continue
        if btype == "definition" and (not term or not in_transcript(term, whole)):
            flags.append(f"term_not_in_transcript:{term!r}")
            btype, term = "key_idea", None
        code = str(o.get("code") or "").strip()[:600] if btype == "code" else None
        if btype == "code" and (not code or support(code, whole) < LOCAL_SUPPORT_MIN):
            flags.append("code_unsupported")
            btype, code = "key_idea", None
        score = support(claim, around(texts, span, 2))
        if score < LOCAL_SUPPORT_MIN:
            flags.append(f"low_support({score:.2f}): {title[:60]!r}")
            stats["dropped"] += 1
            continue
        if any(similar(title, s) >= DUPLICATE_MIN for s in seen_titles):
            flags.append(f"duplicate: {title[:60]!r}")
            stats["dropped"] += 1
            continue
        t = chunks[span[0]]["start_time"]
        items = clean_items(o.get("items"), whole, flags, [title])
        block = {"id": f"u{k}b{seq}", "k": k, "type": btype, "title": title, "term": term,
                 "items": [{"text": x, "t": t, "k": k} for x in items], "code": code, "t": t,
                 "quote": said(texts, span), "background": background_of(o.get("background"), title, flags),
                 "ptopic": after["id"] if shift is not None and t >= shift else before["id"]}
        seq += 1
        seen_titles.append(title)
        state.drafts.append(block)
        made.append(block)
        stats["kept_new"] += 1
    state.reach = max(state.reach, chunks[-1]["end_time"])
    state.last_k = k
    return flags, stats, shift


def extractive_live(state: State, chunks: list[dict], k: int) -> None:
    for seq, s in enumerate(top_sentences(chunks)):
        state.drafts.append({"id": f"u{k}b{seq}", "k": k, "type": "key_idea", "title": s["text"], "term": None,
                             "items": [], "code": None, "t": s["t"], "quote": s["text"], "background": None,
                             "ptopic": state.current["id"]})
    state.reach = max(state.reach, chunks[-1]["end_time"])
    state.last_k = k


# ============================================================================================== stage 2: consolidation
def draft_lines(blocks: list[dict]) -> str:
    out = []
    for b in blocks:
        head = f"{b['term']}: {b['title']}" if b["term"] else b["title"]
        out.append(f"- [{mmss(b['t'])}] {LABEL[b['type']].upper()}: {head}")
        out += [f"    * {i['text']}" for i in b["items"]]
        if b["code"]:
            out.append(f"    code: {b['code']}")
    return "\n".join(out) or "(none)"


def consolidate_user(state: State, chunks: list[dict], drafts: list[dict]) -> str:
    transcript = "\n".join(f"[{mmss(c['start_time'])}] {c['text']}" for c in chunks)
    return (f"{state.index()}\n\nTranscript, {mmss(chunks[0]['start_time'])}-{mmss(chunks[-1]['end_time'])}:\n"
            f"{transcript}\n\nRough live notes of this stretch:\n{draft_lines(drafts)}")


def validate_block(raw: dict, texts: list[str], chunks: list[dict], earlier: list[str], flags: list) -> dict | None:
    btype = raw.get("type")
    if btype not in TYPES:
        flags.append(f"type_fixed:{btype!r}")
        btype = "key_idea"
    title = str(raw.get("title") or "").strip()[:260]
    if not title:
        flags.append("empty_title")
        return None
    term = str(raw.get("term") or "").strip()[:80] if btype == "definition" else None
    claim = claim_of(btype, term, title, raw.get("items"))
    span = ground(raw.get("quote"), claim, texts, flags, 3 if btype in ("list", "example") else 1)
    if span is None:
        return None
    whole = " ".join(texts)
    if btype == "definition" and (not term or not in_transcript(term, whole)):
        flags.append(f"term_not_in_transcript:{term!r}")
        btype, term = "key_idea", None
    score = support(claim, around(texts, span, 3))
    if score < LOCAL_SUPPORT_MIN:
        flags.append(f"low_support({score:.2f}): {title[:60]!r}")
        return None
    if any(similar(title, e) >= DUPLICATE_MIN for e in earlier):
        flags.append(f"duplicate: {title[:60]!r}")
        return None
    items = clean_items(raw.get("items"), around(texts, span, 9), flags, [title])
    code = str(raw.get("code") or "").strip()[:800] if btype == "code" else None
    if btype == "code" and (not code or support(code, whole) < LOCAL_SUPPORT_MIN):
        flags.append("code_unsupported")
        btype, code = "key_idea", None
    table = None
    if btype == "comparison":
        tab = raw.get("table") if isinstance(raw.get("table"), dict) else {}
        cols = [str(c).strip()[:40] for c in (tab.get("columns") or [])[:3] if str(c).strip()]
        rows = []
        for r in (tab.get("rows") or [])[:5]:
            cells = [str(c).strip()[:140] for c in (r if isinstance(r, list) else [])][:len(cols)]
            cells += [""] * (len(cols) - len(cells))
            text = " ".join(cells)
            score = support(text, whole)
            if score < ITEM_SUPPORT_MIN:
                flags.append(f"row_unsupported({score:.2f}): {text[:60]!r}")
                continue
            rows.append(cells)
        if len(cols) >= 2 and rows:
            table = {"columns": cols, "rows": rows}
        else:
            flags.append("comparison_without_table")
            btype = "key_idea"
            items = items + [" — ".join(c for c in r if c) for r in rows]
    return {"type": btype, "title": title, "term": term, "items": [{"text": x} for x in items], "code": code,
            "table": table, "t": chunks[span[0]]["start_time"], "quote": said(texts, span),
            "background": background_of(raw.get("background"), title, flags)}


def strong_call(client, system: str, user: str):
    """Consolidation is quality-critical but nobody waits on it: wait (up to 120 s) for the first model of the chain
    (gpt-oss-120b) instead of dropping to the smaller one; the rest of the chain only if that still fails.
    Run 2 finding: in a burst the 120b budget was busy and gpt-oss-20b wrote 2 thin blocks for 6 minutes."""
    chain = client.chain
    client.chain = chain[:1]
    try:
        res = client.complete_json(system, user, max_tokens=4000, timeout_s=60, wait_s=120)
    finally:
        client.chain = chain
    if res.ok or len(chain) < 2:
        return res
    later = client.complete_json(system, user, max_tokens=4000, timeout_s=60, wait_s=30)
    later.attempts = res.attempts + later.attempts
    return later


def claim_of(btype: str, term: str | None, title: str, items) -> str:
    """What a block asserts, for grounding: a list or an example is named by its title, its content is the items."""
    texts = [str((i.get("text") if isinstance(i, dict) else i) or "") for i in (items if isinstance(items, list) else [])]
    return f"{term or ''} {title} {' '.join(texts) if btype in ('list', 'example') else ''}".strip()


def merge_short(topics: list[dict], state: State, flags: list) -> tuple[list[dict], set[int]]:
    """A topic shorter than MIN_TOPIC_S joins its neighbour: the previous new topic, else the last finished topic
    (its blocks are appended at its end: append-only), else the next one. Run 3: a 1-minute "Course objectives"
    topic, and a 30 s closing stretch that repeated the example of the topic before it."""
    kept, appended, carry = [], set(), None
    for t in topics:
        if carry is not None:
            t["start"], t["blocks"] = carry["start"], carry["blocks"] + t["blocks"]
            t["question"] = t["question"] or carry["question"]
            carry = None
        if t["end"] - t["start"] >= MIN_TOPIC_S:
            kept.append(t)
            continue
        prev = kept[-1] if kept else (state.topics[-1] if state.topics and state.topics[-1]["end"] == t["start"]
                                      else None)
        if prev is None:
            carry = t
            continue
        titles = [b["title"] for b in prev["blocks"]]
        extra = [b for b in t["blocks"] if not any(similar(b["title"], x) >= 0.5 for x in titles)]
        flags.append(f"short_topic_merged:{t['title']!r} -> {prev['title']!r} "
                     f"({len(extra)} blocks kept, {len(t['blocks']) - len(extra)} repeated)")
        prev["blocks"] += extra
        prev["end"] = t["end"]
        prev["question"] = prev["question"] or t["question"]
        if not kept:
            appended.add(prev["n"])
    if carry is not None:
        kept.append(carry)
    return kept, appended


def consolidate(state: State, client, chunks_all: list[dict], end: float, mode: str, report: list) -> dict:
    """mode: 'cut' (a topic shift at `end`), 'open' (may leave the last topic in progress), 'closed'."""
    S = state.S
    chunks = [c for c in chunks_all if S <= c["start_time"] < end]
    texts = [c["text"] for c in chunks]
    whole = " ".join(texts)
    drafts = [b for b in state.drafts if b["t"] < end]
    system = CONSOLIDATE_SYSTEM.replace("OPEN_RULE", OPEN_RULE if mode == "open" else "").replace(
        "OPEN_FIELD", ',\n "in_progress_from": null' if mode == "open" else "").replace(
        "NEXT_N", str(len(state.topics) + 1))
    user = consolidate_user(state, chunks, drafts)
    res = strong_call(client, system, user)
    flags: list[str] = []
    cut, new_topics = end, []
    if res.ok:
        reply = res.data
        if mode == "open":
            ipf = parse_t(reply.get("in_progress_from"))
            if ipf is not None:
                if S + 60 <= ipf <= end - 30:
                    cut = snap(ipf, chunks)
                    flags.append(f"in_progress_from {mmss(cut)}")
                else:
                    flags.append(f"in_progress_from_ignored:{reply.get('in_progress_from')!r}")
        earlier = [b["title"] for t in state.topics for b in t["blocks"]]
        by_n: dict = {}                                   # the reply's topic number -> topic (None: in progress)
        for i, rt in enumerate([t for t in (reply.get("topics") or []) if isinstance(t, dict)][:3]):
            title = str(rt.get("title") or "").strip()[:90] or "Untitled"
            start = S if i == 0 else parse_t(rt.get("starts_at"))
            start = None if start is None else snap(start, chunks)
            if new_topics and (start is None or start <= new_topics[-1]["start"]):
                flags.append(f"topic_start_invalid:{title!r} (merged into previous)")
                by_n[rt.get("n")] = new_topics[-1]
            elif start is not None and start >= cut:
                flags.append(f"topic_in_progress_dropped:{title!r}")
                by_n[rt.get("n")] = None
            else:
                rev = rt.get("revisits")
                rev = rev if isinstance(rev, int) and 1 <= rev <= len(state.topics) else None
                new_topics.append({"title": title, "start": start if start is not None else S, "revisits": rev,
                                   "blocks": [], "question": None})
                by_n[rt.get("n")] = new_topics[-1]
        if new_topics:
            # Blocks go to the topic their own time falls in (deterministic); the model's label is only checked.
            for rb in [b for b in (reply.get("blocks") or []) if isinstance(b, dict)][:24]:
                b = validate_block(rb, texts, chunks, earlier, flags)
                if b is None:
                    continue
                if b["t"] >= cut:
                    flags.append(f"block_after_cut: {b['title'][:50]!r}")
                    continue
                target = [t for t in new_topics if t["start"] <= b["t"]][-1]
                if rb.get("topic") in by_n and by_n[rb.get("topic")] is not target:
                    flags.append("block_topic_by_time")
                earlier.append(b["title"])
                target["blocks"].append(b)
            for q in [q for q in (reply.get("questions") or []) if isinstance(q, dict)]:
                target = by_n.get(q.get("topic"))
                question, answer = str(q.get("q") or "").strip()[:300], str(q.get("answer") or "").strip()[:400]
                if target is None or not question or not answer or target["question"] is not None:
                    continue
                score = support(answer, whole)
                if score >= LOCAL_SUPPORT_MIN:
                    target["question"] = {"q": question, "answer": answer}
                else:
                    flags.append(f"question_unsupported({score:.2f})")
        new_topics = [t for t in new_topics if t["blocks"]]
    generator = "llm" if new_topics else "fallback"
    if not new_topics:                                           # §4.3 fallback: keep the drafts under their headings
        flags.append(f"fallback ({res.reason or 'nothing survived'})")
        for p in state.ptopics:
            blocks = [{**b, "items": [{"text": i["text"]} for i in b["items"]], "table": None}
                      for b in drafts if b["ptopic"] == p["id"] and b["t"] < cut]
            if blocks:
                new_topics.append({"title": p["title"] or f"Part {len(state.topics) + len(new_topics) + 1}",
                                   "start": max(S, min(b["t"] for b in blocks)), "revisits": None, "blocks": blocks,
                                   "question": None})
        if new_topics:
            new_topics[0]["start"] = S
    for i, t in enumerate(new_topics):
        t["end"] = new_topics[i + 1]["start"] if i + 1 < len(new_topics) else cut
        for b in t["blocks"]:
            if b["type"] == "definition" and b["term"]:
                key = b["term"].lower()
                state.glossary[key] = {"term": b["term"], "definition": b["title"], "t": b["t"],
                                       "refined": key in state.glossary}
    new_topics, appended = merge_short(new_topics, state, flags)
    for t in new_topics + [t for t in state.topics if t["n"] in appended]:
        t["blocks"].sort(key=lambda b: b["t"])
    for t in new_topics:
        t["n"] = len(state.topics) + 1
        t["generator"] = generator
        state.topics.append(t)
    state.organised = {t["n"] for t in new_topics} | appended
    state.drafts = [b for b in state.drafts if b["t"] >= cut]
    keep = [p for p in state.ptopics if p["start"] >= cut]
    carry = [p for p in state.ptopics if p["start"] < cut]
    if carry and (not keep or keep[0]["start"] > cut):
        keep.insert(0, {**carry[-1], "start": cut})
    state.ptopics = keep
    state.S = cut

    report.append(f"\n## Consolidation {mmss(S)}-{mmss(end)} ({mode}) -> cut at {mmss(cut)}, {generator}\n")
    if res.ok:
        report.append(f"{res.model}, {res.latency_s} s, {res.prompt_tokens}+{res.completion_tokens} tokens"
                      f"{' (cached)' if res.cached else ''}\n")
        report.append("```json\n" + json.dumps(res.data, indent=1, ensure_ascii=False)[:9000] + "\n```\n")
    if res.attempts:
        report.append(f"Attempts that failed first: {res.attempts}\n")
    report.append("Validation: " + ("; ".join(f"`{f}`" for f in flags) or "all kept") + "\n")
    return {"span": f"{mmss(S)}-{mmss(end)}", "mode": mode, "cut": cut, "ok": res.ok, "generator": generator,
            "model": res.model, "latency_s": res.latency_s, "tokens": res.tokens if res.ok else None,
            "topics": [t["title"] for t in new_topics], "blocks": sum(len(t["blocks"]) for t in new_topics),
            "questions": sum(1 for t in new_topics if t["question"]), "flags": flags}


# ============================================================================================== page (§6)
CSS = """
:root{--bg:#ffffff;--panel:#f6f7f9;--text:#1d2433;--muted:#5b6475;--border:#dde1e8;--accent:#3159c9;--live:#c2410c;
--key:#3159c9;--def:#7c3aed;--list:#0f766e;--ex:#b45309;--cmp:#0e7490;--code:#475569;--imp:#dc2626;--codebg:#eef1f5;--new:#16a34a}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0e1117;--panel:#161b24;--text:#e6e9ef;
--muted:#9aa3b2;--border:#2a3140;--accent:#7aa2ff;--live:#fb923c;--key:#7aa2ff;--def:#b794f6;--list:#5eead4;--ex:#fbbf24;
--cmp:#67e8f9;--code:#cbd5e1;--imp:#f87171;--codebg:#1f2633;--new:#4ade80}}
:root[data-theme="dark"]{--bg:#0e1117;--panel:#161b24;--text:#e6e9ef;--muted:#9aa3b2;--border:#2a3140;--accent:#7aa2ff;
--live:#fb923c;--key:#7aa2ff;--def:#b794f6;--list:#5eead4;--ex:#fbbf24;--cmp:#67e8f9;--code:#cbd5e1;--imp:#f87171;
--codebg:#1f2633;--new:#4ade80}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 "Segoe UI",system-ui,sans-serif}
.page{max-width:1480px;margin:0 auto;padding:16px}
.head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;border-bottom:1px solid var(--border);padding-bottom:10px;margin-bottom:14px}
.head h1{font-size:20px;margin:0}.sub{color:var(--muted);font-size:13px}
.badge{font-weight:600;font-size:13px;padding:3px 10px;border-radius:12px;border:1px solid var(--border);white-space:nowrap}
.badge.live{color:var(--live);border-color:var(--live)}
.cols{display:grid;grid-template-columns:210px minmax(0,1fr) 340px;gap:22px;align-items:start}
.rail{position:sticky;top:12px;font-size:14px}
.rail h3{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:0 0 6px}
.rail ol{margin:0 0 16px;padding-left:20px}.rail li{margin:3px 0}
.ok{color:var(--new)}.rl{color:var(--live);font-size:12px}
.rail details{margin-bottom:12px}.rail summary{cursor:pointer;color:var(--muted);font-weight:600}
.rail dl{margin:6px 0 0}.rail dt{font-weight:600}.rail dd{margin:0 0 6px;color:var(--muted);font-size:13px}
.topic{border:1px solid var(--border);border-radius:8px;margin-bottom:12px;background:var(--panel)}
.topic>summary{cursor:pointer;padding:10px 14px;font-weight:600;font-size:16px;list-style:none;display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}
.topic>summary::before{content:"▸";color:var(--muted)}.topic[open]>summary::before{content:"▾"}
.range{color:var(--muted);font-weight:400;font-size:13px}
.chip{font-size:12px;font-weight:600;color:var(--new)}.rev{font-size:12px;color:var(--muted);font-weight:400}
.body{padding:2px 14px 12px}
.blk{padding:8px 0;border-top:1px solid var(--border)}.blk:first-child{border-top:0}
.bh{display:flex;gap:10px;align-items:baseline}
.tag{flex:none;font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;width:92px}
.t-key_idea{color:var(--key)}.t-definition{color:var(--def)}.t-list{color:var(--list)}.t-example{color:var(--ex)}
.t-comparison{color:var(--cmp)}.t-code{color:var(--code)}.t-important{color:var(--imp)}
.bt{flex:1}.ts{flex:none;color:var(--muted);font-size:12px;cursor:help;border-bottom:1px dotted var(--muted)}
.blk ul{margin:4px 0 0 102px;padding-left:16px}.blk li{margin:2px 0}
.blk pre{margin:6px 0 0 102px;background:var(--codebg);padding:8px 10px;border-radius:6px;overflow-x:auto;font-size:13px}
.blk table{margin:6px 0 0 102px;border-collapse:collapse;font-size:14px}
.blk th,.blk td{border:1px solid var(--border);padding:4px 10px;text-align:left;vertical-align:top}
.bg{margin:4px 0 0 102px;color:var(--muted);font-size:13px;font-style:italic}
.check{margin-top:8px;padding:8px 12px;border-left:3px solid var(--accent);background:var(--bg);border-radius:4px}
.check summary{cursor:pointer;color:var(--accent);font-size:13px}
.new{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--new);margin-left:6px}
.pending{color:var(--muted);font-style:italic}
.live{border:2px dashed var(--live);border-radius:8px;padding:10px 14px;margin-bottom:12px}
.lh{color:var(--live);font-weight:700;font-size:13px;letter-spacing:.04em;margin-bottom:4px}
.live .blk{opacity:.92}
.status{margin-top:8px;color:var(--muted);font-size:13px}
.now{margin-top:6px;font-size:13px;color:var(--muted);border-top:1px solid var(--border);padding-top:6px}
.chat{border:1px solid var(--border);border-radius:8px;padding:14px;min-height:420px;color:var(--muted);background:var(--panel)}
.empty{color:var(--muted);padding:20px 0}
@media (max-width:1000px){.cols{grid-template-columns:1fr}.rail{position:static}.chat{min-height:120px}
.blk ul,.blk pre,.blk table,.bg{margin-left:0}.bh{flex-wrap:wrap}.tag{width:auto}}
"""

e = html.escape


def render_block(b: dict, new_k: int | None = None, live: bool = False) -> str:
    is_new = new_k is not None and b.get("k") == new_k
    head = (f"<b>{e(b['term'])}</b>: {e(b['title'])}" if b.get("term") else e(b["title"]))
    out = [f'<div class="blk"><div class="bh"><span class="tag t-{b["type"]}">{LABEL[b["type"]]}</span>'
           f'<span class="bt">{head}{"<span class=new></span>" if is_new else ""}</span>'
           f'<span class="ts" title="&ldquo;{e(b["quote"])}&rdquo;">{mmss(b["t"])}</span></div>']
    if b["items"]:
        out.append("<ul>" + "".join(
            f"<li>{e(i['text'])}{'<span class=new></span>' if new_k is not None and i.get('k') == new_k and not is_new else ''}</li>"
            for i in b["items"]) + "</ul>")
    elif live and b["type"] == "list":
        out.append('<ul><li class="pending">listing…</li></ul>')
    if b.get("code"):
        out.append(f"<pre>{e(b['code'])}</pre>")
    if b.get("table"):
        tab = b["table"]
        out.append("<table><tr>" + "".join(f"<th>{e(c)}</th>" for c in tab["columns"]) + "</tr>" + "".join(
            "<tr>" + "".join(f"<td>{e(c)}</td>" for c in r) + "</tr>" for r in tab["rows"]) + "</table>")
    if b.get("background"):
        out.append(f'<div class="bg">Background: {e(b["background"])}</div>')
    out.append("</div>")
    return "".join(out)


def render(state: State, chunks: list[dict], now: float, status: str, finished: bool) -> str:
    topics = []
    for i, t in enumerate(state.topics):
        is_open = finished or i == len(state.topics) - 1
        chips = (' <span class="chip">✓ organised</span>' if t["n"] in state.organised and not finished else "")
        rev = f' <span class="rev">continues topic {t["revisits"]}</span>' if t["revisits"] else ""
        body = "".join(render_block(b) for b in t["blocks"])
        if t["question"]:
            body += (f'<div class="check"><b>Check yourself:</b> {e(t["question"]["q"])}'
                     f'<details><summary>Show answer</summary>{e(t["question"]["answer"])}</details></div>')
        topics.append(f'<details class="topic"{" open" if is_open else ""}><summary>{t["n"]}. {e(t["title"])}'
                      f'<span class="range">{mmss(t["start"])}–{mmss(t["end"])}</span>{rev}{chips}</summary>'
                      f'<div class="body">{body}</div></details>')
    live = ""
    if not finished:
        # Run 4: the live model never flagged a topic change after its first update, so a provisional topic name
        # went stale ("Introduction" over knowledge types). The box is labelled by time; topics come from hindsight.
        blocks = sorted(state.drafts, key=lambda b: b["t"])
        groups = [f'<div class="lh">LIVE NOTES SINCE {mmss(state.S)} (draft, organised into topics every few minutes)</div>'
                  + ("".join(render_block(b, state.last_k, live=True) for b in blocks)
                     or '<div class="pending">the next notes will appear here</div>')]
        tail = [c for c in chunks if c["end_time"] <= now][-2:]
        said = " ".join(c["text"] for c in tail)
        live = (f'<section class="live">{"".join(groups)}<div class="status">{e(status)}</div>'
                + (f'<div class="now">now: “…{e(said[-260:])}”</div>' if said else "") + "</section>")
    rail = ["<h3>Contents</h3><ol>"]
    rail += [f'<li>{e(t["title"])} <span class="ok">✓</span></li>' for t in state.topics]
    if not finished:
        rail.append(f'<li>Live notes since {mmss(state.S)} <span class="rl">live</span></li>')
    rail.append("</ol>")
    if state.info:
        rail.append(f"<details><summary>Course info ({len(state.info)})</summary><ul>"
                    + "".join(f"<li>{e(i['text'])}</li>" for i in state.info) + "</ul></details>")
    if state.glossary:
        rail.append(f"<details open><summary>Glossary ({len(state.glossary)})</summary><dl>"
                    + "".join(f"<dt>{e(g['term'])}</dt><dd>{e(g['definition'])}</dd>"
                              for g in sorted(state.glossary.values(), key=lambda g: g["term"].lower()))
                    + "</dl></details>")
    badge = (f'<span class="badge">Finished · {mmss(END_S)}</span>' if finished
             else f'<span class="badge live">● LIVE {mmss(min(now, END_S))}</span>')
    reach = ("" if finished else f'<div class="sub">Notes reach {mmss(state.reach)} '
                                 f'(they follow the lecture by about 1–2 min)</div>') if state.reach else \
        '<div class="sub">The first notes appear about 2 minutes into the lecture</div>'
    main = "".join(topics) + live or '<div class="empty">No notes yet.</div>'
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>Notebook prototype</title><style>{CSS}</style></head>'
            f'<body><div class="page"><div class="head"><div><h1>{e(TITLE)}</h1>{reach}</div>{badge}</div>'
            f'<div class="cols"><nav class="rail">{"".join(rail)}</nav><main>{main}</main>'
            f'<aside class="chat"><b>Lecture Assistant</b><br>Chat, unchanged (not part of this prototype).</aside>'
            f'</div></div></body></html>')


def status_at(now: float, events: list[dict]) -> str:
    pending = [ev for ev in events if ev["kind"] == "update" and ev["block_end"] <= now < ev["visible"]]
    if pending:
        ev = pending[0]
        return f"⏳ writing notes for {mmss(ev['block_start'])}–{mmss(ev['block_end'])} …"
    nxt = min((ev["block_end"] for ev in events if ev["kind"] == "update" and ev["block_end"] > now), default=None)
    return f"Listening · next notes after {mmss(nxt)}" if nxt is not None else "⏳ finishing the notes …"


# ============================================================================================== main
def load_chunks() -> list[dict]:
    if not CHUNKS.exists():
        con = sqlite3.connect(f"file:{(ROOT / 'data' / 'edustream.db').as_posix()}?mode=ro", uri=True)
        rows = con.execute("SELECT chunk_id, start_time, end_time, text FROM chunks WHERE video_id = ? "
                           "ORDER BY start_time", (VIDEO_ID,)).fetchall()
        CHUNKS.write_text("".join(json.dumps({"chunk_id": r[0], "start_time": r[1], "end_time": r[2], "text": r[3]},
                                             ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return [json.loads(line) for line in CHUNKS.open(encoding="utf-8")]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")       # model text has U+2011 etc.
    OUT.mkdir(parents=True, exist_ok=True)
    chunks = load_chunks()
    client = llm.Client("notes")
    if not client.chain:
        sys.exit("No LLM provider configured in .env")
    state, report, live_rows, cons_rows, events = State(), [], [], [], []
    report.append(f"# Prototype rev 2: structured live drafts + consolidation, {TITLE}, 00:00-{mmss(END_S)}\n")
    n_updates = -(-END_S // UPDATE_S)
    for k in range(n_updates):
        part = [c for c in chunks if k * UPDATE_S <= c["start_time"] < (k + 1) * UPDATE_S]
        res = client.complete_json(LIVE_SYSTEM, live_user(state, part), max_tokens=1500, wait_s=60)
        span = f"{mmss(part[0]['start_time'])}-{mmss(part[-1]['end_time'])}"
        report.append(f"\n## Update {k}: {span}\n")
        if res.ok:
            flags, stats, shift = apply_live(state, res.data, part, k)
            report.append(f"{res.model}, {res.latency_s} s, {res.prompt_tokens}+{res.completion_tokens} tokens"
                          f"{' (cached)' if res.cached else ''}\n")
            report.append("```json\n" + json.dumps(res.data, indent=1, ensure_ascii=False)[:5000] + "\n```\n")
        else:
            extractive_live(state, part, k)
            flags, stats, shift = [f"llm_failed:{res.reason}"], Counter(), None
        report.append("Validation: " + ("; ".join(f"`{f}`" for f in flags) or "all kept") + "\n")
        live_rows.append({"update": k, "span": span, "ok": res.ok, "model": res.model, "latency_s": res.latency_s,
                          "tokens": res.tokens if res.ok else None, "stats": dict(stats), "flags": flags,
                          "shift": mmss(shift) if shift is not None else None})
        print(f"update {k} {span}: {'ok' if res.ok else 'FAILED ' + str(res.reason)} {dict(stats)} flags={len(flags)}",
              flush=True)
        last = k == n_updates - 1
        visible = min((k + 1) * UPDATE_S, END_S) + VISIBLE_DELAY_S + (END_DETECT_S if last else 0)
        state.organised = set()
        events.append({"kind": "update", "visible": visible, "block_start": k * UPDATE_S,
                       "block_end": min((k + 1) * UPDATE_S, END_S), "state": copy.deepcopy(state)})
        block_end = part[-1]["end_time"]
        trigger = None
        if last:
            trigger = (END_S, "closed")
        elif shift is not None and shift - state.S >= CUT_MIN_S:
            trigger = (shift, "cut")
        elif block_end - state.S >= STRETCH_S:
            trigger = (block_end, "open" if block_end - state.S < FORCE_S else "closed")
        if trigger:
            row = consolidate(state, client, chunks, trigger[0], trigger[1], report)
            cons_rows.append(row)
            print(f"  consolidation {row['span']} {row['mode']}: {row['generator']} topics={row['topics']} "
                  f"blocks={row['blocks']} flags={len(row['flags'])}", flush=True)
            events.append({"kind": "consolidation", "visible": visible + (row["latency_s"] or 5),
                           "state": copy.deepcopy(state)})

    for name, now in MOMENTS.items():
        shown = [ev for ev in events if ev["visible"] <= now]
        st = shown[-1]["state"] if shown else State()
        finished = now >= events[-1]["visible"]
        (OUT / f"view_{name}.html").write_text(render(st, chunks, now, status_at(now, events), finished),
                                               encoding="utf-8")

    final = state.topics
    blocks = [b for t in final for b in t["blocks"]]
    dup_pairs = [(a["title"], b["title"]) for i, a in enumerate(blocks) for b in blocks[i + 1:]
                 if similar(a["title"], b["title"]) >= 0.5]
    live_ok = [r for r in live_rows if r["ok"]]
    total = Counter()
    for r in live_ok:
        total.update(r["stats"])
    metrics = {
        "live": {"updates": len(live_rows), "llm_ok": len(live_ok), **total,
                 "flags": Counter(re.sub(r"[(:].*", "", f) for r in live_rows for f in r["flags"]),
                 "tokens_mean": round(sum(r["tokens"] for r in live_ok) / len(live_ok)) if live_ok else None,
                 "latency_s_median": sorted(r["latency_s"] for r in live_ok)[len(live_ok) // 2] if live_ok else None},
        "consolidation": {"calls": len(cons_rows), "llm_ok": sum(r["generator"] == "llm" for r in cons_rows),
                          "tokens_mean": round(sum(r["tokens"] or 0 for r in cons_rows) / max(1, len(cons_rows))),
                          "flags": Counter(re.sub(r"[(:].*", "", f) for r in cons_rows for f in r["flags"])},
        "final": {"topics": [f"{t['n']}. {t['title']} ({mmss(t['start'])}-{mmss(t['end'])})" for t in final],
                  "blocks": len(blocks), "blocks_per_6_min": round(len(blocks) / (END_S / 360), 1),
                  "types": Counter(b["type"] for b in blocks), "questions": sum(1 for t in final if t["question"]),
                  "glossary": [g["term"] for g in state.glossary.values()], "info": [i["text"] for i in state.info],
                  "similar_block_pairs": dup_pairs,
                  "possible_housekeeping": [b["title"] for b in blocks if HOUSEKEEPING.search(b["title"])]},
        "baseline_28_oct": {"sections": 1, "bullets": 30, "housekeeping": 6, "near_duplicate_pairs": 4},
        "per_update": live_rows, "per_consolidation": cons_rows,
    }
    (OUT / "report.md").write_text("\n".join(report), encoding="utf-8")
    (OUT / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in metrics.items() if not k.startswith("per_")}, indent=2))


if __name__ == "__main__":
    main()
