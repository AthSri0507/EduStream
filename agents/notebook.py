"""The notebook's pure logic (docs/ARCHITECTURE.md §8.1, docs/NOTEBOOK_DESIGN.md §11): no Kafka, no network, no clock.

  * Window        a parsed window.v1 record and where it came from
  * update_of     which live update a window belongs to (§8.1.1)
  * Grouper       holds one partition's windows until their update is complete
  * Memory        one lecture's notebook so far, rebuilt from its own final_notes records (§8.1.5): live drafts
                  (notes.v3) and consolidated topics (consolidation.v1)
  * live stage    the 90 s call: prompt, validation into study-guide elements (agents/study_notes.py), the
                  extractive fallback, and the notes.v3 payload

The second stage, consolidation, is in agents/consolidation.py.
Tested by tests/test_notebook_grouping.py (N-1) and tests/test_notebook_live.py (N-2).
"""

from __future__ import annotations

import os
import time
from collections import Counter
from dataclasses import dataclass, field

from agents import study_notes as sn
from agents.extractive import top_sentences
from agents.text import mmss

LIVE_MAX_ELEMENTS = 2
LIVE_MAX_TOKENS = 1500
# The live stage and consolidation use DIFFERENT models, so each has its own free per-minute limit. Live run 28 Oct:
# on one model, a consolidation right after a live call got HTTP 429 (Groq counts each request's max_tokens).
LIVE_MODEL = os.environ.get("LLM_NOTES_LIVE_MODEL", "").strip() or "openai/gpt-oss-20b"
LIVE_CONTEXT_WORDS = 250        # the live text so far, as plain prose, so the model continues instead of repeating
KNOWN_SENTENCES = 200           # repeat check: the most recent sentences of the notes


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
    """One lecture's notebook, folded from its final_notes records (the same code path live and on rebuild):
    notes.v3 live updates add drafts, consolidation.v1 passes turn the drafts before their cut into topics."""

    def __init__(self, video_id: str) -> None:
        self.video_id = video_id
        self.partition: int | None = None          # where its records live (same number in every topic)
        self.sent: set[int] = set()
        self.sent_windows: set[int] = set()
        self.last_sent = -1
        self.media_end = 0.0                       # how far the live notes reach (media seconds)
        self.drafts: list[dict] = []               # live elements not consolidated yet, folded (study_notes.fold_draft)
        self.transcript: dict[int, dict] = {}      # chunk_id -> chunk, from consolidated_to on (consolidation input)
        self.topics: list[dict] = []               # {n, title, start, end, question, elements}
        self.glossary: dict[str, dict] = {}        # lower-case term -> {term, definition, t, topic}
        self.info: list[dict] = []                 # course logistics, kept out of the notes
        self.consolidated_to = 0.0                 # S: everything before it is in topics
        self.passes = 0
        self.finished = False                      # the pass that reached the lecture's end is out
        self.last_live_at = 0.0                    # runtime only (not rebuilt): pacing of consolidation
        self.retry_at = 0.0                        # runtime only: a deferred consolidation waits until then
        self.ending_since: float | None = None     # runtime only: when the lecture was first seen ended
        self.last_attempt_at = 0.0                 # runtime only: the last pass attempt (fair turns across lectures)

    def apply_update(self, p: dict, partition: int | None = None) -> None:
        if partition is not None:
            self.partition = partition
        k = p["update_index"]
        if k in self.sent:
            return                                  # duplicate record (at-least-once): first one wins
        for c in p["transcript"]:
            if c["start_time"] >= self.consolidated_to:
                self.transcript.setdefault(c["chunk_id"], c)
        for el in p["elements"]:
            sn.fold_draft(self.drafts, el, k)
        if p.get("info"):
            self.info.append(p["info"])
        self.media_end = max(self.media_end, float(p["media_end"]))
        self.sent.add(k)
        self.sent_windows.update(p["window_starts"])
        self.last_sent = max(self.last_sent, k)

    def apply_pass(self, p: dict, partition: int | None = None) -> None:
        if partition is not None:
            self.partition = partition
        if p["pass_index"] < self.passes:
            return                                  # duplicate record
        by_n = {t["n"]: t for t in self.topics}
        for t in p["topics"]:
            if t["new"]:
                by_n[t["n"]] = {"n": t["n"], "title": t["title"], "start": t["media_start"], "end": t["media_end"],
                                "question": t.get("question"), "elements": []}
                self.topics.append(by_n[t["n"]])
            elif t["n"] in by_n:                    # an earlier topic that this stretch continues
                old = by_n[t["n"]]
                old["end"] = max(old["end"], t["media_end"])
                old["question"] = old["question"] or t.get("question")
        for el in p["elements"]:
            if el["topic"] in by_n:
                by_n[el["topic"]]["elements"].append({k: v for k, v in el.items() if k != "topic"})
        for g in p["glossary"]:
            self.glossary[g["term"].lower()] = g
        self.consolidated_to = max(self.consolidated_to, float(p["media_end"]))
        self.drafts = [d for d in self.drafts if d["t"] >= self.consolidated_to]
        self.transcript = {cid: c for cid, c in self.transcript.items() if c["start_time"] >= self.consolidated_to}
        self.passes = p["pass_index"] + 1
        self.finished = self.finished or bool(p["final"])

    # ------------------------------------------------------------------ views for the prompts
    def chunks(self, end: float) -> list[dict]:
        """The transcript from consolidated_to up to `end`, in order."""
        return [c for _, c in sorted(self.transcript.items()) if c["start_time"] < end]

    def sentences(self) -> list[str]:
        done = [s for t in self.topics for el in t["elements"] for s in sn.sentences_of(el)]
        live = [s for el in self.drafts for s in sn.sentences_of(el)]
        return (done + live)[-KNOWN_SENTENCES:]

    def index(self) -> str:
        """The lecture so far (§4.2): earlier topic titles and the glossary terms, ~100 tokens."""
        done = "; ".join(f"{t['n']}. {t['title']} ({mmss(t['start'])}-{mmss(t['end'])})" for t in self.topics)
        terms = ", ".join(g["term"] for g in self.glossary.values())
        return f"Finished topics: {done or '(none yet)'}\nGlossary so far: {terms or '(none yet)'}"


# ----------------------------------------------------------------------------------------------- live stage (§11.4)
LIVE_SYSTEM = f"""You write the running notes of a live university lecture, the way a good student writes them up.
Every 90 seconds you receive the next part of the transcript (speech recognition, so it can contain errors) and the
notes written since the last organised topic.

Continue the notes with at most 2 elements for this part. A paragraph may continue the last paragraph of the notes
so far: give "continue": true and no "lead". Start a new paragraph when the idea changes. Never repeat what is
already in the notes. Returning no elements is fine. Course logistics go in "info" (one short line), not in the notes.

{sn.ELEMENTS_DOC}

{sn.STYLE}

Return ONLY a JSON object: {{"elements": [ ... ], "info": null or {{"text": "...", "quote": "..."}}}}"""


def live_user(memory: Memory, chunks: list[dict]) -> str:
    words = "\n".join(sn.text_of(el) for el in memory.drafts).split()
    so_far = ("… " if len(words) > LIVE_CONTEXT_WORDS else "") + " ".join(words[-LIVE_CONTEXT_WORDS:])
    return (f"{memory.index()}\n\nNotes so far (since {mmss(memory.consolidated_to)}):\n{so_far or '(none yet)'}\n\n"
            f"Transcript, {mmss(chunks[0]['start_time'])}-{mmss(chunks[-1]['end_time'])}:\n"
            f"{sn.transcript_block(chunks)}")


def live_delta(memory: Memory, reply: dict, chunks: list[dict], update_index: int) -> dict:
    """Validate a live reply into notes.v3 elements (§11.2-11.4). Ids are code-assigned: u<update>e<seq>."""
    flags: list[str] = []
    stats: Counter = Counter()
    texts = [c["text"] for c in chunks]
    info = None
    raw_info = reply.get("info") if isinstance(reply.get("info"), dict) else None
    if raw_info and str(raw_info.get("text") or "").strip():
        span = sn.ground(raw_info.get("quote"), str(raw_info["text"]), texts, flags)
        if span is not None:
            info = {"text": str(raw_info["text"]).strip()[:200], "t": float(chunks[span[0]]["start_time"])}
    proposed = [x for x in (reply.get("elements") if isinstance(reply.get("elements"), list) else [])
                if isinstance(x, dict)]
    if len(proposed) > LIVE_MAX_ELEMENTS:
        flags.append(f"too_many_elements({len(proposed)})")
        proposed = proposed[:LIVE_MAX_ELEMENTS]
    paras = [d for d in memory.drafts if d["kind"] == "para"]
    last_para = (paras[-1]["id"], len(paras[-1]["sentences"])) if paras else None
    known = memory.sentences()
    elements: list[dict] = []
    for raw in proposed:
        el = sn.validate(raw, chunks, flags, stats, known, live=True)
        if el is None:
            continue
        el_id = f"u{update_index}e{len(elements)}"
        cont = el.pop("continue", False)
        extends = None
        if el["kind"] == "para" and cont:
            if last_para and last_para[1] + len(el["sentences"]) <= sn.LIVE_PARA_MAX:
                extends = last_para[0]
                el["lead"] = ""
                stats["continued"] += 1
            else:
                flags.append("continue_as_new_paragraph")
        elements.append({"id": el_id, "extends": extends, **el})
        known += sn.sentences_of(el)
        if el["kind"] == "para":
            last_para = (extends, last_para[1] + len(el["sentences"])) if extends else (el_id, len(el["sentences"]))
        stats[f"kept_{el['kind']}"] += 1
    if proposed and not elements:
        flags.append("all_elements_dropped")
    return {"elements": elements, "info": info, "generator": "llm", "quality_flags": flags, "stats": dict(stats)}


def extractive_live(memory: Memory, chunks: list[dict], update_index: int, flags: list | None = None) -> dict:
    """No LLM: the update's best sentences as one paragraph, verbatim (agents/extractive.py)."""
    picks = top_sentences(chunks)
    elements = []
    if picks:
        elements.append({"id": f"u{update_index}e0", "extends": None, "kind": "para", "t": picks[0]["t"],
                         "said": picks[0]["text"][:400], "lead": "", "sentences": [p["text"] for p in picks],
                         "terms": [], "background": None})
    return {"elements": elements, "info": None, "generator": "extractive", "quality_flags": list(flags or []),
            "stats": {}}


def build_update(held: Held, delta: dict, model: str | None, agent_ms: float, now_ms: int | None = None) -> dict:
    chunks = held.chunks()
    payload = {
        "schema": "notes.v3", "video_id": held.video_id, "update_index": held.update_index,
        "media_start": min(c["start_time"] for c in chunks), "media_end": max(c["end_time"] for c in chunks),
        "window_starts": sorted(w.window_start for w in held.windows),
        "transcript": [{k: c[k] for k in ("chunk_id", "start_time", "end_time", "text")} for c in chunks],
        "elements": delta["elements"], "info": delta["info"],
        "generator": delta["generator"], "model": model if delta["generator"] == "llm" else None,
        "agent_ms": round(agent_ms, 1), "quality_flags": [f[:200] for f in delta["quality_flags"]][:40],
        "created_ts": now_ms if now_ms is not None else int(time.time() * 1000),
    }
    session_start = next((w.session_start for w in held.windows if w.session_start is not None), None)
    if session_start is not None:
        payload["session_start"] = session_start
    return payload
