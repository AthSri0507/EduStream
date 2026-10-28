"""Lecture Assistant (docs/ARCHITECTURE.md §8.2, A17): understand -> fetch -> answer -> verify.

  1. understand  the LLM (assistant model) turns the message + conversation + lecture position into a plan;
                 code then fixes what keywords make certain (time phrases, depth, style, follow-ups, terms)
                 and clamps the span to transcript that exists (step-0 findings, bench/STEP0_RESULTS.md).
  2. fetch       deterministic tools (agents/lecture_tools.py) gather the evidence: transcript lines.
  3. answer      the LLM writes the answer from the evidence only, within a word budget set by code;
                 each "from the lecture" statement carries a verbatim quote.
  4. verify      code checks every quote against the evidence (exact match) and takes the [mm:ss] from it;
                 a statement whose quote is not found is moved to "background" (labelled, never hidden).

If the LLM is off or fails, the user still gets the plan (the chip) and the evidence itself. Statistics
questions ("data") never use the LLM. No word-by-word streaming: the answer is shown only after step 4.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field

from agents import lecture_tools as tools
from agents import retrieval
from agents.text import content_words, find_quote, mmss, parse_t

INTENTS = ("explain_recent", "summarise", "define", "ask", "quiz", "data", "other")
DEFAULT_SPAN_S = 30
BUDGET_WORDS = {"explain_recent": 90, "summarise": 120, "define": 50, "ask": 110, "quiz": 120, "data": 40,
                "other": 40}
DEPTH = {"brief": 0.5, "normal": 1.0, "detailed": 2.0}
MAX_TURNS = 4                        # conversation turns passed to the LLM


# ----------------------------------------------------------------------------------------------- data
@dataclass
class Position:
    """Where the user is: `ref` is the moment "now"/"just now" refers to (lecture seconds)."""
    video_id: str
    title: str
    live: bool
    ref: float                       # the lecture clock (live), a clicked/slider moment, or the end
    covered_s: float                 # transcript stored so far


@dataclass
class Plan:
    intent: str = "ask"
    question: str = ""
    span: list | None = None
    term: str | None = None
    previous_answer: bool = False
    depth: str = "normal"
    style: str = "same"
    ambiguous: bool = False
    source: str = "rules"            # "llm" or "rules"

    def chip(self) -> str:
        what = {"explain_recent": "Explaining", "summarise": "Summarising", "define": "Defining", "ask": "Answering",
                "quiz": "Quiz on", "data": "Stats for", "other": "General question"}.get(self.intent, "Answering")
        target = f" **{self.term}**" if self.term else ""
        if self.span:
            target += f" **{mmss(self.span[0])}–{mmss(self.span[1])}**"
        extras = [x for x in (self.depth if self.depth != "normal" else "",
                              self.style.replace("_", " ") if self.style != "same" else "",
                              "follow-up" if self.previous_answer else "") if x]
        return f"{what}{target}" + (" · " + " · ".join(extras) if extras else "")


@dataclass
class Answer:
    plan: Plan
    items: list = field(default_factory=list)          # [{text, quote, t}] verified, from the lecture
    background: list = field(default_factory=list)     # [text] labelled "not from the lecture"
    questions: list = field(default_factory=list)      # quiz: [{q, answer, t}]
    evidence: list = field(default_factory=list)       # [{t, end, text}] what was fetched
    stats: dict | None = None
    note: str | None = None                            # e.g. "not covered yet", "nothing found"
    flags: list = field(default_factory=list)
    generator: str = "evidence"                        # "llm" or "evidence" (fallback / data)
    model: str | None = None
    latency_s: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    def as_text(self) -> str:
        """Plain text of the answer, for the conversation memory and the log."""
        parts = [f"{i['text']} [{mmss(i['t'])}]" for i in self.items] + [f"Background: {b}" for b in self.background]
        parts += [f"Q: {q['q']}" for q in self.questions]
        if self.stats:
            parts.append(json.dumps(self.stats))
        return " ".join(parts) or (self.note or "")


# ----------------------------------------------------------------------------------------------- 1. understand
UNDERSTAND_PROMPT = """You are the request-understanding step of a lecture assistant. You do NOT answer the question.
You turn the student's latest message into a plan, using the conversation and the lecture position.
All times are in seconds from the start of the lecture.

Intents:
- explain_recent: explain something just said ("didn't get that", "what did she mean just now")
- summarise: summarise a time range or section
- define: define or explain a term
- ask: any other question about the lecture content (including about an earlier part)
- quiz: test me
- data: statistics about the lecture (speaking rate, alerts, timings)
- other: unrelated to the lecture

Return ONLY JSON:
{"intent": "...", "standalone_question": "the request rewritten so it makes sense with no conversation",
 "refers_to": {"span": [start_s, end_s] or null, "term": "..." or null, "previous_answer": true|false},
 "depth": "brief" | "normal" | "detailed", "style": "simpler" | "same" | "more_technical", "ambiguous": true|false}

Rules:
- If the message refers to the assistant's last answer ("that", "the second one", "more", "simpler"), set
  previous_answer to true and rewrite standalone_question using the last answer's content.
- If the message refers to an earlier part of the lecture, give that part's span from the transcript or outline.
- ambiguous is true ONLY if two different readings would need different answers and nothing resolves it."""

DETAIL = re.compile(r"\b(more detail|in detail|lot more|elaborate|in depth|deeper|everything about)\b", re.I)
BRIEF = re.compile(r"\b(short|brief|briefly|quick|one line|tl;?dr|in a sentence)\b", re.I)
SIMPLER = re.compile(r"\b(simpler|simply|easier|plain english|like i'?m (5|five)|eli5|dumb it down)\b", re.I)
TECH = re.compile(r"\b(more technical|formally|precisely|technically)\b", re.I)
FOLLOW = re.compile(r"\b(that|again|this|it|the (first|second|third|last) one|more|simpler)\b", re.I)
AGAIN = re.compile(r"\b(again|simpler|more|the (first|second|third|last) one)\b", re.I)   # surely about the answer
DEFINE = re.compile(r"\bwhat(?:(?:'s| is| are)\s+(?:an?\s+|the\s+)?([a-z][\w\- ]{1,40}?)"
                    r"|\s+does\s+(?:an?\s+|the\s+)?([a-z][\w\- ]{1,40}?)\s+mean)\s*\?$", re.I)
LECTURER_CLAIM = re.compile(r"\b(lecturer|professor|instructor|speaker)\b|\b(she|he) (says|said|explains|explained|"
                            r"mentions|mentioned|stresses|emphasi[sz]es|encourages|notes|describes|states)\b"
                            r"|\bin the lecture\b", re.I)
RECENT = re.compile(r"\b(just now|right now|just said|didn'?t (get|understand|catch)|lost me|what did (she|he|they) "
                    r"(just )?(say|mean)|explain (that|this)( part)?)\b", re.I)
LAST_N = re.compile(r"\b(?:last|past|previous)\s+(?:(\d+|a|one|two|three|five|ten)\s*)?(seconds?|secs?|minutes?|mins?)\b",
                    re.I)
SO_FAR = re.compile(r"\b(so far|whole lecture|entire lecture|everything (we'?ve|we have) (covered|done))\b", re.I)
AT_TIME = re.compile(r"\b(\d{1,2}):(\d{2})\b")                      # "what happened at 12:30", "explain 03:10"
RANGE = re.compile(r"\b(\d{1,2}):(\d{2})\s*(?:-|–|to|and|until)\s*(\d{1,2}):(\d{2})\b", re.I)
BEGINNER = re.compile(r"\b(beginner|i'?m new|new to (this|programming|coding|python)|no background)\b", re.I)
# Answers must never talk about the machinery (your feedback, 15 Oct): such sentences are dropped in code.
META = re.compile(r"\b(transcript|evidence|lecture text|source material|lines? (provided|given)|provided (text|lines)"
                  r"|the text (provided|given|you provided))\b", re.I)
WORDS_N = {"a": 1, "one": 1, "two": 2, "three": 3, "five": 5, "ten": 10}


def rule_intent(msg: str) -> str:
    low = msg.lower()
    if RECENT.search(msg):
        return "explain_recent"
    if re.search(r"\b(summar|recap|overview)", low):
        return "summarise"
    if re.search(r"\b(quiz|test me|questions? for me)\b", low):
        return "quiz"
    if re.search(r"\b(how fast|speaking rate|words per minute|wpm|how many (alerts|words))\b", low):
        return "data"
    if DEFINE.search(msg.split("?")[0] + "?") or re.search(r"\b(define|definition|meaning of)\b", low):
        return "define"
    return "ask"


def time_span(msg: str, ref: float, recent: bool = True) -> list | None:
    """Spans that wording makes certain (step 0: the LLM missed "so far"); code wins over the LLM here."""
    m = LAST_N.search(msg)
    if m:
        word = m.group(1) or "one"                                # "the last minute"
        n = int(word) if word.isdigit() else WORDS_N[word.lower()]
        seconds = n * 60 if m.group(2).lower().startswith("min") else n
        return [max(0.0, ref - seconds), ref]
    if SO_FAR.search(msg):
        return [0.0, ref]
    m = RANGE.search(msg)
    if m:
        a, b = int(m.group(1)) * 60 + int(m.group(2)), int(m.group(3)) * 60 + int(m.group(4))
        return [float(min(a, b)), float(max(a, b))]
    m = AT_TIME.search(msg)
    if m:
        t = int(m.group(1)) * 60 + int(m.group(2))
        return [max(0.0, t - 15.0), t + 15.0]
    if recent and RECENT.search(msg):
        return [max(0.0, ref - DEFAULT_SPAN_S), ref]
    return None


def guard(plan: Plan, msg: str, has_turns: bool, pos: Position, span_s: float | None = None) -> Plan:
    """Deterministic corrections after the LLM (or the rules) produced a plan."""
    if plan.source != "button":
        # Depth and style come from the user's own words, never from the model's guess (M6e live check:
        # an LLM-chosen "brief" shrank a summary's budget until it gave none).
        plan.depth = "detailed" if DETAIL.search(msg) else "brief" if BRIEF.search(msg) else "normal"
        plan.style = ("simpler" if SIMPLER.search(msg) or BEGINNER.search(msg)
                      else "more_technical" if TECH.search(msg) else "same")
    follow_up = has_turns and bool(AGAIN.search(msg)) and len(msg.split()) <= 12
    if follow_up:
        plan.previous_answer = True                           # "explain that again", "the second one", "simpler"
    elif RECENT.search(msg):
        plan.previous_answer = False                          # "didn't get that" is about the lecture, not the answer
    elif has_turns and FOLLOW.search(msg) and len(msg.split()) <= 12:
        plan.previous_answer = True
    if plan.intent == "define" and not plan.term:
        m = DEFINE.search(msg.split("?")[0] + "?")
        if m:
            plan.term = (m.group(1) or m.group(2)).strip()
    certain = time_span(msg, pos.ref, recent=not follow_up)
    if certain is not None:
        plan.span = certain
    if plan.intent == "explain_recent" and plan.span is None:
        plan.span = [max(0.0, pos.ref - (span_s or DEFAULT_SPAN_S)), pos.ref]
    if plan.intent == "summarise" and plan.span is None and not plan.previous_answer:
        plan.span = [0.0, pos.ref]                            # "summarise the lecture": everything so far
    if plan.intent == "explain_recent" and span_s and RECENT.search(msg) and not LAST_N.search(msg) and not follow_up:
        plan.span = [max(0.0, pos.ref - span_s), pos.ref]     # the user's chosen span (10/30/60/120 s)
    if plan.intent not in INTENTS:
        plan.intent = "ask"
    if plan.depth not in DEPTH:
        plan.depth = "normal"
    if plan.style not in ("simpler", "same", "more_technical"):
        plan.style = "same"
    if plan.span is not None:                                 # clamp to transcript that exists (and to "now")
        limit = min(pos.covered_s, pos.ref) if pos.live else pos.covered_s
        start, end = sorted(float(x) for x in plan.span[:2])
        plan.span = [max(0.0, min(start, limit)), max(0.0, min(end, limit))]
    plan.question = plan.question or msg
    return plan


def understand(client, msg: str, turns: list[dict], pos: Position, context: str, span_s: float | None = None) -> Plan:
    convo = "\n".join(f"{t['role'].upper()}: {t['text']}" for t in turns[-MAX_TURNS:]) or "(no earlier turns)"
    user = f"{context}\n\nConversation so far:\n{convo}\n\nLatest student message: {msg}"
    result = client.complete_json(UNDERSTAND_PROMPT, user, max_tokens=600) if client else None
    plan = Plan(intent=rule_intent(msg), question=msg)
    if result is not None and result.ok:
        d = result.data
        ref = d.get("refers_to") if isinstance(d.get("refers_to"), dict) else {}
        span = ref.get("span")
        plan = Plan(intent=d.get("intent") if d.get("intent") in INTENTS else plan.intent,
                    question=str(d.get("standalone_question") or msg)[:400],
                    span=span if isinstance(span, list) and len(span) == 2 and all(isinstance(x, (int, float)) for x in span) else None,
                    term=str(ref.get("term")).strip()[:80] if ref.get("term") else None,
                    previous_answer=bool(ref.get("previous_answer")), depth=str(d.get("depth") or "normal"),
                    style=str(d.get("style") or "same"), ambiguous=bool(d.get("ambiguous")), source="llm")
    return guard(plan, msg, bool(turns), pos, span_s)


SECTION_N = re.compile(r"\b(?:section|part)\s+(\d{1,2})\b", re.I)
THIS_SECTION = re.compile(r"\b(this|current|the last|previous) (section|part|topic)\b", re.I)


def resolve_section(plan: Plan, msg: str, outline: list[dict], pos: Position) -> Plan:
    """ "Summarise section 3", "this section", or a section's title -> that section's time span (code, not LLM)."""
    if not outline or plan.intent not in ("summarise", "explain_recent", "ask", "quiz"):
        return plan
    starts = [(s["id"], float(s["t"] or 0.0), s["title"]) for s in outline]
    end_of = lambda i: starts[i + 1][1] if i + 1 < len(starts) else max(pos.covered_s, starts[i][1])  # noqa: E731
    chosen = None
    m = SECTION_N.search(msg)
    if m:
        chosen = next((i for i, s in enumerate(starts) if s[0] == int(m.group(1))), None)
    elif THIS_SECTION.search(msg):
        before = [i for i, s in enumerate(starts) if s[1] <= pos.ref]
        if before:
            chosen = before[-1] - (1 if re.search(r"\b(last|previous)\b", msg, re.I) and len(before) > 1 else 0)
    else:
        words = set(content_words(msg))
        best = max(((len(words & set(content_words(t))), i) for i, (_, _, t) in enumerate(starts)), default=(0, None))
        if best[0] >= 2:                                      # at least two of the title's words in the message
            chosen = best[1]
    if chosen is not None:
        plan.span = [starts[chosen][1], end_of(chosen)]
    return plan


# ----------------------------------------------------------------------------------------------- 2. fetch
def fetch(conn, plan: Plan, pos: Position, vconn=None, embedder=None) -> tuple[list[dict], dict | None, str | None]:
    """Evidence lines (time-ordered, de-duplicated), stats for "data", and a note when there is nothing."""
    until = pos.ref if pos.live else None
    vid = pos.video_id
    lines: list[dict] = []
    if plan.intent == "data":
        span = plan.span or [0.0, pos.ref]
        return [], {"span": span, **tools.speaking_stats(conn, vid, span[0], span[1])}, None
    if plan.intent == "other":
        return [], None, None
    if plan.span is not None and plan.intent in ("explain_recent", "summarise", "ask", "quiz"):
        lines = tools.transcript(conn, vid, plan.span[0], plan.span[1])
        if len(lines) > tools.MAX_LINES:                       # long range: the notebook stands in for it,
            lines = tools.notebook_digest(conn, vid, plan.span[0], plan.span[1])   # trimmed evenly per section
    if plan.intent == "define" and plan.term:
        for g in tools.glossary(conn, vid, plan.term):
            lines.append({"t": g["t"], "end": g["t"] + 10, "text": f"Glossary: {g['term']}: {g['definition']}"})
        for p in tools.term_mentions(conn, vid, plan.term, until=until):
            lines += p["lines"]
    term_unknown = plan.intent == "define" and bool(plan.term) and not lines   # never said: no loose matches
    if not lines and not term_unknown and plan.intent in ("ask", "define", "quiz", "summarise"):
        for p in retrieval.search(conn, vid, plan.term or plan.question, limit=5, until=until, vconn=vconn,
                                  embedder=embedder):                 # keywords + meaning, fused (§8.5)
            lines += p["lines"]
    seen, out = set(), []
    for ln in sorted(lines, key=lambda x: x["t"]):
        key = (ln["t"], ln["text"])
        if key not in seen:
            seen.add(key)
            out.append(ln)
    note = None
    if not out and plan.span is not None and plan.intent in ("explain_recent", "summarise", "quiz"):
        note = "Nothing has been said in that part of the lecture yet."
    elif not out:
        note = ("This hasn't come up in the lecture yet." if pos.live else "I couldn't find this in the lecture.")
    return out, None, note


# ----------------------------------------------------------------------------------------------- 3. answer
ANSWER_PROMPT = """You are a lecture assistant helping a student understand a university lecture.

The lecture text below (lines with [mm:ss]) is what the lecturer said. Put everything the lecturer said into
"lecture" items: each states one idea in your own words and carries "quote": 3-15 words copied EXACTLY from one
line (no "...", no changes), and "t": that line's [mm:ss]. Use the lecturer's own terms and examples.
Use what the lecture text contains even if it covers only part of the requested time; never complain that it is
incomplete, and never mention "evidence", "transcript" or "lines" to the student.
For a question, use only lines that actually answer it; ignore lines that merely share words with it.
"background" is ONLY for general knowledge the lecturer did not give (it is shown labelled as not from the
lecture); never put something the lecturer said into "background". Leave it empty when it is not needed. If the
lecture text does not touch the question at all, say in one sentence in "background" that the lecture has not
covered it (yet).

Length: at most {budget} words in total. Start with the most useful sentence; do not pad.
Style: {style}. Level: {level}.
{extra}
Return ONLY JSON: {schema}"""

SCHEMA_DEFAULT = '{"lecture": [{"text": "...", "quote": "...", "t": "mm:ss"}], "background": "" }'
SCHEMA_QUIZ = '{"questions": [{"q": "...", "answer": "...", "t": "mm:ss"}]}'
STYLE = {"simpler": "simpler than usual: short sentences, an everyday analogy is welcome",
         "same": "clear and direct", "more_technical": "precise and technical"}


def budget_for(plan: Plan) -> int:
    """Words the answer may use. A summary grows with the time it covers (the notebook is the condensed lecture
    and the assistant is the only summariser, so "summarise the lecture" must scale): about 120 words for 5 min,
    260 for 30 min, up to 600 for an hour or more; "in detail" doubles it."""
    base = BUDGET_WORDS.get(plan.intent, 100)
    if plan.intent == "summarise" and plan.span is not None:
        minutes = max(0.0, plan.span[1] - plan.span[0]) / 60
        base = max(base, min(600, int(80 + 6 * minutes)))
    return int(base * DEPTH.get(plan.depth, 1.0))


def answer_prompt(plan: Plan, level: str, explained: list[str]) -> str:
    extra = []
    if plan.intent == "explain_recent":
        extra.append("Explain what was just said: first what the lecturer said, then what it means.")
    if plan.intent == "summarise":
        extra.append("Summarise as short items in time order.")
    if plan.intent == "define":
        extra.append("Give the definition as the lecturer used it, then one example from the lecture if there is one.")
    if plan.intent == "quiz":
        extra.append("Write 3 to 5 questions that test understanding of the evidence, each with a short answer.")
    if plan.intent == "other":
        extra.append("The question is not about this lecture: answer in one short 'background' sentence and suggest "
                     "returning to the lecture. Leave 'lecture' empty.")
    if explained:
        extra.append("Already explained in this conversation (refer to them, do not re-explain): " + ", ".join(explained))
    return ANSWER_PROMPT.format(budget=budget_for(plan), style=STYLE.get(plan.style, "clear"), level=level,
                                extra="\n".join(extra), schema=SCHEMA_QUIZ if plan.intent == "quiz" else SCHEMA_DEFAULT)


def answer_user(plan: Plan, pos: Position, evidence: list[dict], turns: list[dict], previous: str | None) -> str:
    # For a time range, the request is fixed by code: the model must not compare the range with how far the
    # transcript reaches (M6e live check: "from 03:05 to 05:05" made it refuse when the text ended at 05:00).
    request = {"summarise": "Summarise this part of the lecture.",
               "explain_recent": "Explain this part of the lecture: what was said, then what it means."}
    question = request[plan.intent] if plan.span is not None and plan.intent in request and not plan.previous_answer \
        else plan.question
    parts = [f"Lecture: {pos.title} ({'live, now at ' + mmss(pos.ref) if pos.live else 'recorded'})",
             f"Request: {question}"]
    if plan.previous_answer and previous:
        parts.append(f"The assistant's previous answer (the student refers to it):\n{previous}")
    convo = "\n".join(f"{t['role'].upper()}: {t['text']}" for t in turns[-MAX_TURNS:])
    if convo:
        parts.append(f"Conversation:\n{convo}")
    parts.append("Lecture text:\n" + ("\n".join(f"[{mmss(e['t'])}] {e['text']}" for e in evidence) or "(none)"))
    return "\n\n".join(parts)


# ----------------------------------------------------------------------------------------------- 4. verify
def verify(reply: dict, plan: Plan, evidence: list[dict]) -> tuple[list, list, list, list]:
    """Quotes must occur in the evidence; times come from the quote's line; the budget is enforced."""
    flags, items, background, questions = [], [], [], []
    texts = [e["text"] for e in evidence]
    for it in reply.get("lecture") if isinstance(reply.get("lecture"), list) else []:
        if not isinstance(it, dict) or not str(it.get("text") or "").strip():
            continue
        text = str(it["text"]).strip()[:500]
        span = find_quote(str(it.get("quote") or ""), texts)
        if span is None:
            if LECTURER_CLAIM.search(text):                   # claims to be the lecture but can't be shown: drop
                flags.append("unverified_removed")
            else:                                             # honest: shown, but labelled not-from-lecture
                background.append(text)
                flags.append("unverified_moved_to_background")
            continue
        t = evidence[span[0]]["t"]
        claimed = parse_t(it.get("t"))
        if claimed is not None and abs(claimed - t) > 15:
            flags.append("timestamp_corrected")
        items.append({"text": text, "quote": str(it["quote"]).strip(), "t": t})
    bg = reply.get("background")
    if isinstance(bg, str) and bg.strip():
        background.insert(0, bg.strip()[:600])
    kept = []
    for text in background:                                  # no talk about transcripts or "evidence"
        sentences = [x for x in re.split(r"(?<=[.!?])\s+", text) if x.strip() and not META.search(x)]
        if len(sentences) < len(re.split(r"(?<=[.!?])\s+", text.strip())):
            flags.append("meta_talk_removed")
        if sentences:
            kept.append(" ".join(sentences))
    background = kept
    for q in reply.get("questions") if isinstance(reply.get("questions"), list) else []:
        if isinstance(q, dict) and str(q.get("q") or "").strip():
            t = parse_t(q.get("t"))
            near = min(evidence, key=lambda e: abs(e["t"] - t)) if (t is not None and evidence) else None
            questions.append({"q": str(q["q"]).strip()[:300], "answer": str(q.get("answer") or "").strip()[:300],
                              "t": near["t"] if near and abs(near["t"] - t) <= 60 else None})
    budget = budget_for(plan)
    words = lambda: sum(len(i["text"].split()) for i in items) + sum(len(b.split()) for b in background)  # noqa: E731
    while words() > 1.6 * budget and len(items) > 1:          # cut whole items, never mid-sentence
        items.pop()
        flags.append("trimmed_to_budget")
    return items, background, questions, flags


# ----------------------------------------------------------------------------------------------- one turn
def run_turn(conn, client, msg: str, turns: list[dict], pos: Position, level: str = "unknown",
             explained: list[str] | None = None, span_s: float | None = None, plan: Plan | None = None,
             vconn=None, embedder=None) -> Answer:
    """One assistant turn. `plan` may be given (buttons such as More/Simpler re-use the last plan)."""
    started = time.perf_counter()
    if plan is None:
        recent = tools.transcript(conn, pos.video_id, max(0.0, pos.ref - 90), pos.ref, before=0)
        outline = tools.outline(conn, pos.video_id)
        context = (f"Lecture: {pos.title}. {'Live; current position' if pos.live else 'Recorded; selected moment'}: "
                   f"{int(pos.ref)} s ({mmss(pos.ref)}).\nOutline so far:\n"
                   + ("\n".join(f"{s['id']}. {s['title']} (from {int(s['t'] or 0)} s)" for s in outline) or "(none yet)")
                   + "\n\nLast 90 s of transcript:\n" + "\n".join(f"[{int(r['t'])} s] {r['text']}" for r in recent))
        plan = understand(client, msg, turns, pos, context, span_s)
        plan = resolve_section(plan, msg, outline, pos)
    evidence, stats, note = fetch(conn, plan, pos, vconn, embedder)
    answer = Answer(plan=plan, evidence=evidence, stats=stats, note=note)
    if plan.intent == "data":
        answer.latency_s = round(time.perf_counter() - started, 2)
        return answer                                         # statistics: computed, never written by the LLM
    previous = next((t["text"] for t in reversed(turns) if t["role"] == "assistant"), None)
    not_covered = plan.intent == "define" and bool(plan.term) and not evidence
    if not evidence and plan.intent != "other" and not plan.previous_answer and not not_covered:
        answer.latency_s = round(time.perf_counter() - started, 2)
        return answer
    prompt = answer_prompt(plan, level, explained or [])
    if not_covered:                  # a term never said: one labelled background line, nothing "from the lecture"
        prompt += ("\nThe term has NOT been used in the lecture" + (" yet" if pos.live else "")
                   + ". Leave 'lecture' empty and give a one-sentence general hint in 'background'.")
    result = client.complete_json(prompt,
                                  answer_user(plan, pos, evidence, turns, previous),
                                  max_tokens=max(800, min(3000, 300 + 3 * budget_for(plan)))) if client else None
    if result is not None and result.ok:
        answer.items, answer.background, answer.questions, answer.flags = verify(result.data, plan, evidence)
        answer.generator, answer.model = "llm", result.model
        if not (answer.items or answer.background or answer.questions):
            answer.generator, answer.flags = "evidence", answer.flags + ["llm_answer_empty"]
        elif not answer.items and evidence and plan.intent in ("explain_recent", "summarise"):
            answer.flags.append("no_lecture_items")           # the dashboard also shows what was said
    else:
        answer.flags.append(f"llm_unavailable:{getattr(result, 'reason', 'no_client')}")
    answer.latency_s = round(time.perf_counter() - started, 2)
    return answer
