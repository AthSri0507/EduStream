"""Stage 2 of the notebook: consolidation (docs/NOTEBOOK_DESIGN.md §4, §11.5, §11.10). Pure: no Kafka, no network.

Every ~6 minutes of lecture (and at its end) one call turns the live drafts of the stretch, together with its
transcript, into finished topics: a clear title, study-guide elements (agents/study_notes.py), one check-yourself
question. The drafts before the cut then disappear (decision 3). The result is one consolidation.v1 record.

  * due()          when a pass runs and over which stretch (§4.1, capped so one request fits the free limit)
  * prompts        system prompt (with the "in progress" hand-over in open mode) and the user prompt with the
                   lecture-so-far index (§4.2)
  * from_reply()   validation: topics, elements by time, questions, short topics merged, "continues" (§11.10);
                   checked live drafts the reply left out come back (carry_over)
  * fallback()     no usable reply: the drafts themselves, de-duplicated (only at the lecture's end, when the LLM is
                   off, or after a long outage; otherwise the pass is deferred, §11.10 fix 2)
  * build_pass()   the consolidation.v1 payload

Tested by tests/test_consolidation.py.
"""

from __future__ import annotations

import re
import time
from collections import Counter
from dataclasses import dataclass

from agents import study_notes as sn
from agents.notebook import Memory
from agents.text import mmss, parse_t, similar, support

STRETCH_S = 360                  # a pass once 6 minutes of drafts have accumulated (§4.1)
FORCE_S = 720                    # after 12 minutes nothing is handed over ("closed" mode)
MAX_PASS_S = 540                 # one pass covers at most 9 minutes: the request must fit the per-minute limit
MIN_TOPIC_S = 120                # shorter topics join a neighbour (prototype run 3)
GAP_S = 45                       # a pass waits this long after the lecture's last live call (§11.10 fix 1)
PASS_SPACING_S = 61              # passes of different lectures one minute apart: each (~5,000 tokens with its
                                 # max_tokens) needs the strong model's minute to itself (dry run 28 Oct)
RETRY_S = 60                     # a deferred pass is tried again after this
GIVE_UP_S = 1080                 # 18 minutes without a successful pass: publish the oldest drafts as they are
END_GRACE_S = 180                # after the lecture's end a failed pass is retried this long, then the drafts stand in
MAX_TOKENS = 2400                # a pass used ~800-1,000 (29 Oct: too thin; worked examples now kept whole, and three
                                 # HTTP 400s fit replies cut off mid-JSON); the requested maximum counts against the
                                 # per-minute limit (§11.10): with a ~3,000-token prompt it stays well under 8,000
MAX_TOPICS, MAX_ELEMENTS = 3, 30
REPEAT_MIN = 0.5                 # an element of a merged short topic that repeats the topic it joins is left out
COVER_MIN = 0.5                  # a live-draft sentence is in the pass's notes if one new element holds half its words
THIN_RATIO = 0.5                 # a pass keeping under half the drafts' words lost content, not just repeats
WORKED = ("example", "steps", "table", "code")
OFF_REASONS = ("disabled", "forced_failure", "no_provider_configured")    # waiting cannot help
QUESTION_LOGISTICS = re.compile(r"\b(problem sets?|psets?|due|deadlines?|exams? (date|time)|quiz(zes)? (date|time)"
                                r"|office hours|slides|recitations?|grades?|grading)\b", re.I)

OPEN_RULE = ("- If the last topic is still going on at the end of the stretch (the lecturer is in the middle of it),"
             " do not write it: set \"in_progress_from\" to the mm:ss where it starts; it will be written with the"
             " next stretch. Otherwise \"in_progress_from\": null.")
CONTINUES_RULE = ("- If the first topic of this stretch simply continues the last finished topic (same subject),"
                  " give it \"continues\": true; it is then added to that topic.")

SYSTEM = f"""You write the final study notes for one stretch of a university lecture, like a section of a
good textbook. You receive the topics finished earlier in the lecture and the glossary so far, the transcript of the
stretch (speech recognition, so it can contain errors), and the rough live notes written during it.

- Split the stretch into 1-3 topics where the subject actually changes, each with a clear, specific title.
  Course logistics (recording, slides, problem-set dates) are never a topic and never a question.
- Write each topic mostly as paragraphs (2-4 sentences each, as many as the content needs: usually 3-6 per 6 minutes
  of teaching) that explain the ideas and how they connect. Use steps, table or code only where the lecturer really
  listed, compared or wrote something. Put each example right after the paragraph it illustrates.
- A worked problem the lecturer solves (a scenario with given values) is never dropped or cut to one sentence: write
  it as an "example" whose "text" gives the setup and the given values, and whose "steps" give the solution in the
  lecturer's order with the lecturer's numbers (hypotheses, test statistic, critical values, decision ...).
- Use the live notes as a draft: every correct point in them must appear in your notes (reworded or merged); fix
  what is wrong, merge repeats, and leave out only asides and course logistics.
- Do not define again a term already in the glossary unless the lecturer adds something new.
- One check-yourself question per topic that tests understanding of the subject (never about the lecturer or the
  class), with a short answer from the lecture.
CONTINUES_RULE
OPEN_RULE
{sn.ELEMENTS_DOC}

{sn.STYLE}

Return ONLY a JSON object with flat lists. Number the new topics from NEXT_N; elements and questions name their topic
by that number.
{{"topics": [{{"n": NEXT_N, "title": "...", "starts_at": "mm:ss"CONTINUES_FIELD}}],
 "elements": [{{"topic": NEXT_N, "kind": "para", "lead": "...", "text": "...", "terms": [], "quote": "..."}}],
 "questions": [{{"topic": NEXT_N, "q": "...", "answer": "..."}}]OPEN_FIELD}}"""


@dataclass(frozen=True)
class Plan:
    start: float                 # S, where the stretch starts (everything before is consolidated)
    end: float                   # the stretch ends here (the cut, unless an open topic is handed over)
    mode: str                    # "open": the last topic may be handed over; "closed": everything up to end
    final: bool                  # this pass reaches the lecture's end
    ending: bool = False         # the lecture has ended: a failed pass is never deferred (live run 28 Oct)


def due(memory: Memory, lecture_ended: bool) -> Plan | None:
    """§4.1: a pass once STRETCH_S of drafts have accumulated, and at the lecture's end until everything is done."""
    start, reach = memory.consolidated_to, memory.media_end
    if memory.finished or reach <= start:
        return None
    if not lecture_ended and reach - start < STRETCH_S:
        return None
    end = min(reach, start + MAX_PASS_S)
    final = lecture_ended and end >= reach
    mode = "closed" if lecture_ended or reach - start >= FORCE_S else "open"
    return Plan(start, end, mode, final, lecture_ended)


# ----------------------------------------------------------------------------------------------- prompts
def system_prompt(memory: Memory, plan: Plan) -> str:
    is_open = plan.mode == "open"
    can_continue = bool(memory.topics)
    return (SYSTEM.replace("CONTINUES_RULE\n", CONTINUES_RULE + "\n" if can_continue else "")
            .replace("OPEN_RULE\n", OPEN_RULE + "\n" if is_open else "")
            .replace("CONTINUES_FIELD", ', "continues": false' if can_continue else "")
            .replace("OPEN_FIELD", ',\n "in_progress_from": null' if is_open else "")
            .replace("NEXT_N", str(len(memory.topics) + 1)))


def user_prompt(memory: Memory, chunks: list[dict], drafts: list[dict]) -> str:
    return (f"{memory.index()}\n\nTranscript, {mmss(chunks[0]['start_time'])}-{mmss(chunks[-1]['end_time'])}:\n"
            f"{sn.transcript_block(chunks)}\n\nRough live notes of this stretch:\n"
            + ("\n".join(sn.text_of(d) for d in drafts) or "(none)"))


def drafts_for(memory: Memory, plan: Plan) -> list[dict]:
    return [d for d in memory.drafts if d["t"] < plan.end]


# ----------------------------------------------------------------------------------------------- validation
def _merge(topics: list[dict], last: dict | None, flags: list) -> tuple[list[dict], dict | None]:
    """Topics shorter than MIN_TOPIC_S join a neighbour; a first topic that "continues" (or is short) joins the last
    finished topic `last`. Returns (new topics, extension of `last` or None). Repeats are left out."""
    kept: list[dict] = []
    ext: dict | None = None
    carry: dict | None = None
    for i, t in enumerate(topics):
        if carry is not None:
            t["start"], t["elements"] = carry["start"], carry["elements"] + t["elements"]
            t["question"] = t["question"] or carry["question"]
            carry = None
        continues = i == 0 and t.get("continues") and last is not None
        if not continues and t["end"] - t["start"] >= MIN_TOPIC_S:
            kept.append(t)
            continue
        if kept:
            prev, have = kept[-1], [sn.text_of(x) for x in kept[-1]["elements"]]
        elif last is not None:
            ext = ext or {"n": last["n"], "title": last["title"], "start": last["start"], "end": last["end"],
                          "elements": [], "question": None}
            prev, have = ext, [sn.text_of(x) for x in last["elements"] + ext["elements"]]
        else:
            carry = t
            continue
        extra = [x for x in t["elements"] if not any(similar(sn.text_of(x), h) >= REPEAT_MIN for h in have)]
        why = "continues" if continues else "short_topic_merged"
        flags.append(f"{why}:{t['title'][:40]!r} -> {prev['title'][:40]!r} ({len(extra)} kept, "
                     f"{len(t['elements']) - len(extra)} repeated)")
        prev["elements"] += extra
        prev["end"] = t["end"]
        prev["question"] = prev["question"] or t["question"]
    if carry is not None:
        kept.append(carry)
    if ext is not None and last is not None and last.get("question"):
        ext["question"] = None
    return kept, ext


def from_reply(memory: Memory, reply: dict, plan: Plan, chunks: list[dict]) -> dict:
    """Validate a consolidation reply. Always returns pass fields; when nothing survives, the drafts stand in."""
    flags: list[str] = []
    stats: Counter = Counter()
    S, texts = plan.start, [c["text"] for c in chunks]
    whole = " ".join(texts)
    cut = plan.end
    if plan.mode == "open":
        ipf = parse_t(reply.get("in_progress_from"))
        if ipf is not None:
            if S + 60 <= ipf <= plan.end - 30:
                cut = sn.snap(ipf, chunks)
                flags.append(f"in_progress_from {mmss(cut)}")
            else:
                flags.append(f"in_progress_from_ignored:{str(reply.get('in_progress_from'))[:12]!r}")
    new_topics: list[dict] = []
    by_n: dict = {}
    for i, rt in enumerate([t for t in (reply.get("topics") if isinstance(reply.get("topics"), list) else [])
                            if isinstance(t, dict)][:MAX_TOPICS]):
        title = str(rt.get("title") or "").strip()[:90] or "Untitled"
        start = S if i == 0 else parse_t(rt.get("starts_at"))
        start = None if start is None else sn.snap(start, chunks)
        if new_topics and (start is None or start <= new_topics[-1]["start"]):
            flags.append(f"topic_start_invalid:{title[:40]!r}")
            by_n[rt.get("n")] = new_topics[-1]
        elif start is not None and start >= cut:
            by_n[rt.get("n")] = None                    # the handed-over topic: written with the next stretch
        else:
            new_topics.append({"title": title, "start": start if start is not None else S, "elements": [],
                               "question": None, "continues": i == 0 and rt.get("continues") is True})
            by_n[rt.get("n")] = new_topics[-1]
    known = [s for t in memory.topics for x in t["elements"] for s in sn.sentences_of(x)]
    for raw in [x for x in (reply.get("elements") if isinstance(reply.get("elements"), list) else [])
                if isinstance(x, dict)][:MAX_ELEMENTS]:
        if not new_topics:
            break
        el = sn.validate(raw, chunks, flags, stats, known, live=False)
        if el is None:
            continue
        if el["t"] >= cut:
            flags.append("element_after_cut")
            continue
        target = [t for t in new_topics if t["start"] <= el["t"]][-1] if el["t"] >= new_topics[0]["start"] \
            else new_topics[0]                           # by time; the model's order is kept within a topic
        if raw.get("topic") in by_n and by_n[raw.get("topic")] is not target:
            flags.append("element_topic_by_time")
        if el["kind"] in ("example", "code") and any(
                similar(sn.text_of(el), sn.text_of(x)) >= 0.5
                or (el.get("code") and x.get("code") and el["code"].strip() in x["code"])
                for t in new_topics for x in t["elements"] if x["kind"] in ("example", "code")):
            flags.append("example_repeats_earlier")
            continue
        target["elements"].append(el)
        known += sn.sentences_of(el)
    if any(t["elements"] for t in new_topics):          # the reply's topics stand: its own elements were sound
        for el in carry_over([d for d in memory.drafts if d["t"] < cut], new_topics, known, flags, stats):
            target = [t for t in new_topics if t["start"] <= el["t"]][-1] if el["t"] >= new_topics[0]["start"] \
                else new_topics[0]
            target["elements"].append(el)
    for q in [q for q in (reply.get("questions") if isinstance(reply.get("questions"), list) else [])
              if isinstance(q, dict)]:
        target = by_n.get(q.get("topic"))
        question, answer = str(q.get("q") or "").strip()[:300], str(q.get("answer") or "").strip()[:400]
        if target is None or not question or not answer or target["question"] is not None:
            continue
        if sn.LOGISTICS.search(question) or QUESTION_LOGISTICS.search(question):
            flags.append("logistics_question")
            continue
        score = sn.grounded(answer, whole)
        if score >= 0.30:
            target["question"] = {"q": question, "answer": answer}
        else:
            flags.append(f"question_unsupported({score:.2f})")
    new_topics = [t for t in new_topics if t["elements"]]
    if not new_topics:
        flags.append("nothing_survived")
        return fallback(memory, plan, flags)
    new_topics[0]["start"] = S                          # an emptied first topic must not leave a gap
    for i, t in enumerate(new_topics):
        t["end"] = new_topics[i + 1]["start"] if i + 1 < len(new_topics) else cut
        t["elements"] = sn.in_spoken_order(t["elements"])
    topics, ext = _merge(new_topics, memory.topics[-1] if memory.topics else None, flags)
    return _fields(memory, topics, ext, S, cut, plan.final, "llm", flags, dict(stats))


def carry_over(drafts: list[dict], new_topics: list[dict], known: list[str], flags: list, stats: Counter) -> list[dict]:
    """A pass may reorganise and rewrite the live notes, but not lose them (live run 29 Oct: 120b turned six minutes
    of a worked example into one sentence, and the drafts it replaced disappeared). The drafts were checked when
    they were written; those the new notes do not cover come back:
      * always worked material: an example, steps, table or code, or a sentence that states numbers;
      * everything else only when the pass is thin (it kept under THIN_RATIO of the drafts' words). A rich pass that
        left a sentence out usually dropped it on purpose (course intros, asides), so it stays out."""
    have = [sn.text_of(x) for t in new_topics for x in t["elements"]]

    def covered(text: str) -> bool:
        return any(support(text, h) >= COVER_MIN for h in have) or any(similar(text, k) >= sn.DUPLICATE_MIN
                                                                       for k in known)
    draft_words = sum(len(sn.words_of(s)) for d in drafts for s in (sn.sentences_of(d) or [sn.text_of(d)]))
    thin = draft_words > 0 and sum(len(sn.words_of(h)) for h in have) < THIN_RATIO * draft_words
    out, seen = [], []
    for d in drafts:
        el = sn.published(d)
        if el["kind"] == "para":
            keep = []
            for s in el.get("sentences", []):
                if not covered(s) and (thin or re.search(r"\d", s)) and not sn.FILLER.search(s) \
                        and not sn.LOGISTICS.search(s) and not QUESTION_LOGISTICS.search(s) \
                        and not s.rstrip().endswith("?") and not any(similar(s, x) >= sn.DUPLICATE_MIN
                                                                     for x in seen + keep):
                    keep.append(s)
            if not keep:
                continue
            el = {**el, "sentences": keep, "terms": [tm for tm in el.get("terms", []) if tm["definition"] in keep]}
        else:
            text = sn.text_of(el)
            if covered(text) or any(similar(text, x) >= sn.DUPLICATE_MIN for x in seen) \
                    or QUESTION_LOGISTICS.search(text) or not (thin or el["kind"] in WORKED or re.search(r"\d", text)):
                continue
        out.append(el)
        seen += sn.sentences_of(el) or [sn.text_of(el)]
    if out:
        flags.append(f"carried_from_live({len(out)}{', thin pass' if thin else ''})")
        stats["drafts_carried"] += len(out)
    return out


def fallback_title(elements: list[dict], n: int) -> str:
    """A topic written without the model is named after its fullest paragraph's run-in heading, else an example's
    title; "Part N" only when there is neither (live run 29 Oct: "Part 6" held the walnut t-test example)."""
    paras = [x for x in elements if x["kind"] == "para" and x.get("lead")]
    if paras:
        return max(paras, key=lambda x: len(x.get("sentences", [])))["lead"][:90]
    titled = [x for x in elements if x["kind"] == "example" and x.get("title")]
    return titled[0]["title"][:90] if titled else f"Part {n}"


def fallback(memory: Memory, plan: Plan, flags: list | None = None) -> dict:
    """No usable reply: the drafts of the stretch as they are, without repeats, as one topic "Part N"."""
    flags = list(flags or [])
    elements: list[dict] = []
    seen: list[str] = [s for t in memory.topics for x in t["elements"] for s in sn.sentences_of(x)]
    for d in drafts_for(memory, plan):
        el = sn.published(d)
        if "sentences" in el:
            el["sentences"] = [s for s in el["sentences"] if not any(similar(s, x) >= sn.DUPLICATE_MIN for x in seen)]
            if not el["sentences"] and el["kind"] == "para":
                continue
        if any(similar(sn.text_of(el), sn.text_of(x)) >= sn.DUPLICATE_MIN for x in elements):
            continue
        elements.append(el)
        seen += sn.sentences_of(el)
    S = plan.start
    n = len(memory.topics) + 1
    topics = [{"title": fallback_title(elements, n), "start": S, "end": plan.end, "elements": elements,
               "question": None}] if elements else []
    last = memory.topics[-1] if memory.topics else None
    topics, ext = _merge(topics, last, flags)
    if not topics and ext is None and last is not None:      # nothing to add: the last topic reaches the cut
        ext = {"n": last["n"], "title": last["title"], "start": last["start"], "end": plan.end, "elements": [],
               "question": None}
    return _fields(memory, topics, ext, S, plan.end, plan.final, "fallback", flags, {})


def _fields(memory: Memory, topics: list[dict], ext: dict | None, start: float, cut: float, final: bool,
            generator: str, flags: list, stats: dict) -> dict:
    out_topics, elements, glossary = [], [], []
    if ext is not None:
        out_topics.append({"n": ext["n"], "title": ext["title"], "media_start": ext["start"], "media_end": ext["end"],
                           "question": ext["question"], "new": False})
        elements += [{"topic": ext["n"], **x} for x in ext["elements"]]
    for i, t in enumerate(topics):
        n = len(memory.topics) + 1 + i
        out_topics.append({"n": n, "title": t["title"], "media_start": t["start"], "media_end": t["end"],
                           "question": t["question"], "new": True})
        elements += [{"topic": n, **x} for x in t["elements"]]
    for el in elements:
        for tm in el.get("terms", []):
            glossary.append({"term": tm["term"], "definition": tm["definition"], "t": el["t"], "topic": el["topic"]})
    return {"media_start": start, "media_end": cut, "final": final, "topics": out_topics, "elements": elements,
            "glossary": glossary, "generator": generator, "quality_flags": flags, "stats": stats}


def build_pass(memory: Memory, fields: dict, model: str | None, agent_ms: float, now_ms: int | None = None) -> dict:
    return {
        "schema": "consolidation.v1", "video_id": memory.video_id, "pass_index": memory.passes,
        "media_start": fields["media_start"], "media_end": fields["media_end"], "final": fields["final"],
        "topics": fields["topics"], "elements": fields["elements"], "glossary": fields["glossary"],
        "generator": fields["generator"], "model": model if fields["generator"] == "llm" else None,
        "agent_ms": round(agent_ms, 1), "quality_flags": [f[:200] for f in fields["quality_flags"]][:60],
        "created_ts": now_ms if now_ms is not None else int(time.time() * 1000),
    }
