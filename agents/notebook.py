"""The notebook's pure logic (docs/ARCHITECTURE.md §8.1): no Kafka, no network, no clock of its own.

  * Window        a parsed window.v1 record and where it came from
  * update_of     which notebook update a window belongs to (§8.1.1)
  * Grouper       holds one partition's windows until their update is complete
  * Memory        one lecture's notebook so far, rebuilt from notes.v2 records (§8.1.5)
  * make_delta    validates an LLM reply, or builds the extractive one (§8.1.3, §8.1.4)
  * build_update  the notes.v2 payload for one update

Tested by tests/test_notebook_grouping.py (N-1) and tests/test_notebook_validation.py (N-2).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from agents.extractive import top_sentences
from agents.text import find_quote, mmss, norm, parse_t, similar, stem, support

MIN_SECTION_UPDATES = 2          # a new section needs >= 2 updates in the current one (§8.1.3)
EXTRACTIVE_SECTION_EVERY = 10    # fallback opens "Part N" every 10 updates (15 min)
LOCAL_SUPPORT_MIN = 0.30         # option A (step 0): point vs. its own quote's neighbourhood
DUPLICATE_MIN = 0.60             # Jaccard of content words: a near-repeat of an earlier point
MAX_POINTS, MAX_TERMS = 5, 4


# ----------------------------------------------------------------------------------------------- windows
@dataclass
class Window:
    video_id: str
    window_start: int
    window_end: int
    session_start: int | None
    chunks: list[dict]                 # [{chunk_id, start_time, end_time, text}] sorted by chunk_id
    partition: int = 0
    offset: int = 0
    arrived: float = 0.0

    @classmethod
    def from_payload(cls, p: dict, partition: int = 0, offset: int = 0, arrived: float = 0.0) -> "Window":
        chunks = sorted(({"chunk_id": c["chunk_id"], "start_time": float(c["start_time"]),
                          "end_time": float(c["end_time"]), "text": c.get("text") or ""} for c in p["chunks"]),
                        key=lambda c: c["chunk_id"])
        return cls(p["video_id"], p["window_start"], p["window_end"], p.get("session_start"), chunks,
                   partition, offset, arrived)

    @property
    def first_start(self) -> float:
        return self.chunks[0]["start_time"]


def update_of(window: Window, update_s: int, last_sent: int) -> int:
    """§8.1.1: floor(media time of the first chunk / NOTE_UPDATE_S); a window whose update was already
    sent (only after a max-hold timeout) joins the next one, so nothing is lost."""
    return max(int(window.first_start // update_s), last_sent + 1)


def last_chunk_of(update_index: int, update_s: int, chunk_s: float) -> int:
    return int((update_index + 1) * update_s // chunk_s) - 1


@dataclass
class Held:
    video_id: str
    update_index: int
    windows: list[Window] = field(default_factory=list)

    @property
    def partition(self) -> int:
        return self.windows[0].partition

    @property
    def last_offset(self) -> int:
        return max(w.offset for w in self.windows)

    @property
    def first_arrival(self) -> float:
        return min(w.arrived for w in self.windows)

    def chunk_ids(self) -> set[int]:
        return {c["chunk_id"] for w in self.windows for c in w.chunks}

    def chunks(self) -> list[dict]:
        seen = {}
        for w in self.windows:
            for c in w.chunks:
                seen.setdefault(c["chunk_id"], c)
        return [seen[k] for k in sorted(seen)]


class Grouper:
    """One partition's held windows (S1: one active lecture per partition). Pure: returns what to emit."""

    def __init__(self, update_s: int, chunk_s: float) -> None:
        self.update_s, self.chunk_s = update_s, chunk_s
        self.held: Held | None = None

    def add(self, window: Window, last_sent: int) -> list[tuple[Held, str]]:
        """Add a window; returns [(held update, reason)] that are complete now, oldest first."""
        out = []
        k = update_of(window, self.update_s, last_sent)
        if self.held is not None and self.held.video_id != window.video_id:
            out.append((self.held, "next_lecture"))
            self.held = None
        if self.held is not None and k > self.held.update_index:
            out.append((self.held, "next_update"))
            self.held = None
        if self.held is None:
            self.held = Held(window.video_id, k)
        self.held.windows.append(window)
        if last_chunk_of(self.held.update_index, self.update_s, self.chunk_s) in self.held.chunk_ids():
            out.append((self.held, "complete"))
            self.held = None
        return out

    def due(self, now: float, max_hold_s: float, lecture_end: "LectureEnd | None") -> str | None:
        """Reason to emit the held update now (timers), or None."""
        if self.held is None:
            return None
        if lecture_end is not None and lecture_end.ended(self.held, now):
            return "lecture_end"
        if now - self.held.first_arrival >= max_hold_s:
            return "max_hold"
        return None

    def take(self) -> Held | None:
        held, self.held = self.held, None
        return held


@dataclass
class LectureEnd:
    """§8.1.5: flushed (from SQLite) and either the last chunk's window was seen, or 30 s of quiet."""
    last_chunk_id: int
    flush_seen_at: float
    idle_s: float = 30.0

    def ended(self, held: Held, now: float) -> bool:
        if self.last_chunk_id in held.chunk_ids():
            return True
        newest = max(w.arrived for w in held.windows)
        return now - max(newest, self.flush_seen_at) >= self.idle_s


# ----------------------------------------------------------------------------------------------- memory
class Memory:
    """One lecture's notebook, folded from notes.v2 payloads (the same code path live and on rebuild)."""

    def __init__(self, video_id: str) -> None:
        self.video_id = video_id
        self.sections: dict[int, dict] = {}        # id -> {id, title, first_update, updates}
        self.points: list[dict] = []
        self.terms: dict[str, dict] = {}           # lower-case term -> term
        self.sent: set[int] = set()
        self.sent_windows: set[int] = set()
        self.last_sent = -1

    @property
    def current(self) -> dict | None:
        return self.sections[max(self.sections)] if self.sections else None

    def apply(self, p: dict) -> None:
        if p["update_index"] in self.sent:
            return                                  # duplicate record (at-least-once): first one wins
        sec = p["section"]
        if sec["id"] not in self.sections:
            self.sections[sec["id"]] = {"id": sec["id"], "title": sec["title"], "first_update": p["update_index"],
                                        "updates": 0}
        self.sections[sec["id"]]["updates"] += 1
        self.points += [dict(pt) for pt in p["points"]]
        for t in p["terms"]:
            self.terms.setdefault(t["term"].lower(), dict(t))
        self.sent.add(p["update_index"])
        self.sent_windows.update(p["window_starts"])
        self.last_sent = max(self.last_sent, p["update_index"])

    def context(self) -> str:
        if not self.sections:
            return "Notebook so far: (empty; this is the start of the lecture)"
        cur = self.current
        recent = [pt for pt in self.points if pt["section_id"] == cur["id"]][-6:]
        lines = ["Notebook so far:", "Sections: " + "; ".join(f"{s['id']}. {s['title']}" for s in self.sections.values()),
                 f"Current section: {cur['title']}", "Recent points in it:"]
        lines += [f"- [{mmss(pt['t'])}] {pt['text']}" for pt in recent] or ["- (none yet)"]
        names = [t["term"] for t in self.terms.values()][-40:]
        lines.append("Terms already defined: " + (", ".join(names) or "(none)"))
        return "\n".join(lines)


# ----------------------------------------------------------------------------------------------- the prompt
SYSTEM_PROMPT = """You are the note-taker for a live university lecture. Every 90 seconds you receive the next
part of the transcript (automatic speech recognition, so it can contain errors) and the notebook written so far.

Write what a diligent student would write down: ideas, definitions, worked examples, rules, warnings.
Write the notes themselves, not a description of the talk (never "the lecturer says ...").
Skip housekeeping (administration, logistics, recording or licence notices, jokes) unless it matters for studying.
Returning no points is fine when nothing in this part is worth noting. Do not repeat points already in the notebook.

Every point must restate ONLY what was said in this part. If a point needs an explanation the lecturer did
not give, put that explanation in the point's "background" field (it is shown separately, labelled as
background); never mix outside knowledge into "text".

Return ONLY a JSON object:
{"section": {"action": "continue" | "new", "title": "short topic title (new only)", "starts_at": "mm:ss (new only)"},
 "points": [{"text": "...", "t": "mm:ss", "kind": "point" | "example",
             "quote": "3-15 consecutive words copied exactly from the transcript", "background": "..." or null}],
 "terms": [{"term": "...", "definition": "...", "t": "mm:ss", "quote": "...", "source": "lecture" | "background"}]}

Rules:
- 0 to 5 points, each at most 300 characters, specific and understandable on its own.
- "quote" is copied word for word from the transcript: no "...", no changes; "t" is the [mm:ss] of its line.
- Terms: at most 4, only terms the lecturer explains or uses in this part; the term must appear in the transcript.
  Give "quote" (the words where it is said) and "source": "lecture" if your definition is what the lecturer said,
  "background" if you had to add general knowledge. Do not repeat terms already defined.
- Start a new section only when the topic clearly changes; otherwise continue the current one.
  For a new section also give "starts_at": the [mm:ss] where the new topic begins."""


def user_prompt(memory: Memory, chunks: list[dict]) -> str:
    lines = "\n".join(f"[{mmss(c['start_time'])}] {c['text']}" for c in chunks)
    return (f"{memory.context()}\n\nTranscript, {mmss(chunks[0]['start_time'])}-{mmss(chunks[-1]['end_time'])}:\n"
            f"{lines}")


# ----------------------------------------------------------------------------------------------- deltas
def _section(memory: Memory, action, title: str, starts_at, update_index: int, generator: str, flags: list):
    """Section decision made by code. Returns (section dict, previous section id or None, starts_at s)."""
    cur = memory.current
    if cur is None:
        if action not in ("new", None):
            flags.append("first_update_opens_section")
        name = title or ("Introduction" if generator == "llm" else "Part 1")
        return {"id": 1, "title": name[:80], "is_new": True}, None, None
    if generator == "extractive":
        if cur["updates"] >= EXTRACTIVE_SECTION_EVERY:
            return {"id": cur["id"] + 1, "title": f"Part {cur['id'] + 1}", "is_new": True}, None, None
        return {"id": cur["id"], "title": cur["title"], "is_new": False}, None, None
    if action == "new":
        if cur["updates"] < MIN_SECTION_UPDATES:
            flags.append(f"premature_new_section:{title[:40]!r}")
        elif title:
            return {"id": cur["id"] + 1, "title": title[:80], "is_new": True}, cur["id"], parse_t(starts_at)
    return {"id": cur["id"], "title": cur["title"], "is_new": False}, None, None


def extractive_delta(memory: Memory, chunks: list[dict], update_index: int, flags: list | None = None) -> dict:
    flags = list(flags or [])
    section, _, _ = _section(memory, None, "", None, update_index, "extractive", flags)
    points = [{"section_id": section["id"], "text": s["text"], "t": s["t"], "kind": "point", "quote": s["text"]}
              for s in top_sentences(chunks)]
    return {"section": section, "points": points, "terms": [], "generator": "extractive", "quality_flags": flags}


def llm_delta(memory: Memory, reply: dict, chunks: list[dict], update_index: int) -> dict:
    """Validate an LLM reply (§8.1.3 + step-0 option A). Falls back to extractive when nothing survives."""
    flags: list[str] = []
    texts = [c["text"] for c in chunks]
    whole = " ".join(texts)
    sec = reply.get("section") if isinstance(reply.get("section"), dict) else {}
    title = str(sec.get("title") or "").strip()
    section, previous_id, starts_at = _section(memory, sec.get("action"), title, sec.get("starts_at"),
                                               update_index, "llm", flags)

    proposed = reply.get("points") if isinstance(reply.get("points"), list) else []
    points: list[dict] = []
    earlier = [pt["text"] for pt in memory.points[-30:]]
    for pt in proposed[:MAX_POINTS]:
        if not isinstance(pt, dict):
            flags.append("malformed_point")
            continue
        text = str(pt.get("text") or "").strip()[:300]
        span = find_quote(str(pt.get("quote") or ""), texts)
        if not text:
            continue
        if span is None:
            flags.append("quote_not_found")
            continue
        neighbourhood = " ".join(texts[max(0, span[0] - 1): span[1] + 2])
        score = support(text, neighbourhood)
        if score < LOCAL_SUPPORT_MIN:
            flags.append(f"low_support({score:.2f})")
            continue
        if any(similar(text, other) >= DUPLICATE_MIN for other in earlier + [p["text"] for p in points]):
            flags.append("duplicate_point")
            continue
        t = chunks[span[0]]["start_time"]
        claimed = parse_t(pt.get("t"))
        if claimed is not None and abs(claimed - t) > 10:
            flags.append("timestamp_corrected")
        sid = previous_id if (previous_id and starts_at is not None and t < starts_at) else section["id"]
        background = pt.get("background")
        points.append({"section_id": sid, "text": text, "t": t, "kind": "example" if pt.get("kind") == "example" else "point",
                       "quote": str(pt.get("quote")).strip(),
                       "background": str(background).strip()[:300] if isinstance(background, str) and background.strip() else None})

    terms: list[dict] = []
    proposed_terms = reply.get("terms") if isinstance(reply.get("terms"), list) else []
    norm_whole = norm(whole)
    stem_whole = " ".join(stem(w) for w in norm_whole.split())
    for term in proposed_terms[:MAX_TERMS]:
        if not isinstance(term, dict):
            flags.append("malformed_term")
            continue
        name = str(term.get("term") or "").strip()[:80]
        key = name.lower()
        if not name or key in memory.terms or any(t["term"].lower() == key for t in terms):
            continue
        name_norm = norm(name)
        if not name_norm or (name_norm not in norm_whole and " ".join(stem(w) for w in name_norm.split()) not in stem_whole):
            flags.append("term_not_in_transcript")
            continue
        definition = str(term.get("definition") or "").strip()[:200]
        span = find_quote(str(term.get("quote") or ""), texts)
        lecture = (term.get("source") == "lecture" and span is not None
                   and support(definition, " ".join(texts[max(0, span[0] - 1): span[1] + 2])) >= LOCAL_SUPPORT_MIN)
        if term.get("source") == "lecture" and not lecture:
            flags.append("term_relabelled_background")
        where = span[0] if span else next((i for i, x in enumerate(texts) if name_norm in norm(x)), 0)
        terms.append({"term": name, "definition": definition, "t": chunks[where]["start_time"],
                      "source": "lecture" if lecture else "background"})

    if proposed and not points:
        return extractive_delta(memory, chunks, update_index, flags + ["llm_points_all_dropped"])
    return {"section": section, "points": points, "terms": terms, "generator": "llm", "quality_flags": flags}


def build_update(memory: Memory, held: Held, delta: dict, model: str | None, agent_ms: float,
                 now_ms: int | None = None) -> dict:
    chunks = held.chunks()
    payload = {
        "schema": "notes.v2", "video_id": held.video_id, "update_index": held.update_index,
        "media_start": min(c["start_time"] for c in chunks), "media_end": max(c["end_time"] for c in chunks),
        "window_starts": sorted(w.window_start for w in held.windows),
        "section": delta["section"], "points": delta["points"], "terms": delta["terms"],
        "generator": delta["generator"], "model": model if delta["generator"] == "llm" else None,
        "agent_ms": round(agent_ms, 1), "quality_flags": delta["quality_flags"],
        "created_ts": now_ms if now_ms is not None else int(time.time() * 1000),
    }
    session_start = next((w.session_start for w in held.windows if w.session_start is not None), None)
    if session_start is not None:
        payload["session_start"] = session_start
    return payload
