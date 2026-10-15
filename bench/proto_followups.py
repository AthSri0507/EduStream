"""Step-0 prototype 2 (ARCHITECTURE §12 item 9): does the assistant's "understand" step read follow-ups?

12 scripted conversations at a live position in Python · Lecture 1 (real M2 Whisper output). For each,
the understand prompt (§8.2 step 1) turns the last user message into a plan; code scores the plan
against the expected intent / span / term / style / ambiguity. Uses the assistant's model order
(gpt-oss-20b first, §8.0). Responses are cached, so a rerun costs no quota.

    .venv\\Scripts\\python bench\\proto_followups.py

Writes bench/results/proto_followups.md and .json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import proto_notebook as P  # noqa: E402  (reuses the cached Groq client and transcript loader)

NOW = 445                     # live position: 07:25 into the lecture
OUTLINE = ["1. Course overview and how to succeed (00:30-04:30)", "2. What you will learn (04:30-06:50)",
           "3. What does a computer do? (06:50-now)"]

SYSTEM = """You are the request-understanding step of a lecture assistant. You do NOT answer the question.
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
- "just now", "that", "the last N seconds" without other context refer to the most recent speech:
  span ends at the current position; default length 30 s.
- "the last N minutes" -> span [now - N*60, now]. "so far" -> [0, now].
- If the message refers to an earlier part of the lecture, give that part's span from the transcript or outline.
- previous_answer is true when the message is about the assistant's last answer ("simpler", "more", "the second one").
- ambiguous is true ONLY if two different readings would need different answers and nothing resolves it."""

T = lambda m, s: m * 60 + s  # noqa: E731
CASES = [
    {"id": 1, "turns": [], "msg": "wait what did she mean just now",
     "expect": {"intent": ["explain_recent"], "span": (NOW - 30, NOW)}},
    {"id": 2, "turns": [("user", "what is a computer good at according to her?"),
                        ("assistant", "From the lecture: a computer does two things: it performs calculations, "
                                      "about a billion per second [07:00], and it remembers the results in memory [07:10].")],
     "msg": "explain that again but simpler",
     "expect": {"intent": ["ask", "explain_recent"], "previous_answer": True, "style": "simpler"}},
    {"id": 3, "turns": [], "msg": "summarise the last 5 minutes",
     "expect": {"intent": ["summarise"], "span": (NOW - 300, NOW)}},
    {"id": 4, "turns": [], "msg": "what does modular mean? short answer please",
     "expect": {"intent": ["define"], "term": "modular", "depth": "brief"}},
    {"id": 5, "turns": [("user", "what are the three big things we should get out of the course?"),
                        ("assistant", "Knowledge of concepts [03:50], programming skills [04:00], and problem "
                                      "solving, practised through the problem sets [04:10].")],
     "msg": "tell me more about the second one",
     "expect": {"intent": ["ask", "define", "explain_recent"], "previous_answer": True, "q_contains": "programming skill"}},
    {"id": 6, "turns": [], "msg": "go back to the part about not being afraid of breaking the computer, why did she say that?",
     "expect": {"intent": ["ask", "explain_recent"], "span": (T(3, 5), T(3, 35))}},
    {"id": 7, "turns": [], "msg": "quiz me on what we've covered so far",
     "expect": {"intent": ["quiz"], "span": (0, NOW)}},
    {"id": 8, "turns": [], "msg": "how fast was she speaking in the last minute?",
     "expect": {"intent": ["data"], "span": (NOW - 60, NOW)}},
    {"id": 9, "turns": [], "msg": "is it better than the other one?",
     "expect": {"ambiguous": True}},
    {"id": 10, "turns": [], "msg": "who won the football world cup in 2022?",
     "expect": {"intent": ["other"]}},
    {"id": 11, "turns": [], "msg": "what is recursion?",
     "expect": {"intent": ["define"], "term": "recursion"}},
    {"id": 12, "turns": [("user", "what's declarative knowledge?"),
                         ("assistant", "Background: declarative knowledge is knowledge stated as facts. "
                                       "(Not covered yet in this lecture.)")],
     "msg": "ok and in a lot more detail please",
     "expect": {"intent": ["define", "ask"], "previous_answer": True, "depth": "detailed",
                "q_contains": "declarative"}},
]


def context() -> str:
    chunks = [c for c in P.load_chunks(8) if c["start_time"] < NOW]
    recent = [c for c in chunks if c["start_time"] >= NOW - 90]
    return (f"Live lecture: Python · Lecture 1. Current position: {NOW} s ({P.mmss(NOW)}).\n"
            "Outline so far:\n" + "\n".join(OUTLINE) + "\n\nLast 90 s of transcript:\n"
            + "\n".join(f"[{int(c['start_time'])} s] {c['text']}" for c in recent))


import re  # noqa: E402

DETAIL = re.compile(r"\b(more detail|in detail|lot more|elaborate|in depth|deeper|everything about)\b", re.I)
BRIEF = re.compile(r"\b(short|brief|briefly|quick|one line|tl;?dr|in a sentence)\b", re.I)
SIMPLER = re.compile(r"\b(simpler|simply|easier|plain english|like i'?m (5|five)|eli5|dumb it down)\b", re.I)
TECH = re.compile(r"\b(more technical|formally|precisely|technically)\b", re.I)
FOLLOW = re.compile(r"\b(that|again|this|it|the (first|second|third|last) one|more|simpler)\b", re.I)
DEFINE = re.compile(r"\bwhat(?:'s| is| are| does)\s+(?:an?\s+|the\s+)?([a-z][\w\- ]{1,40}?)(?:\s+mean)?\s*\?$", re.I)


def guard(plan: dict, msg: str, has_turns: bool) -> dict:
    """Deterministic corrections after the LLM plan: code decides what a keyword makes certain."""
    plan = json.loads(json.dumps(plan))
    ref = plan["refers_to"] = plan.get("refers_to") if isinstance(plan.get("refers_to"), dict) else {}
    if DETAIL.search(msg):
        plan["depth"] = "detailed"
    elif BRIEF.search(msg):
        plan["depth"] = "brief"
    if SIMPLER.search(msg):
        plan["style"] = "simpler"
    elif TECH.search(msg):
        plan["style"] = "more_technical"
    elif plan.get("style") == "simpler":
        plan["style"] = "same"            # never simplify unless asked
    if has_turns and FOLLOW.search(msg) and len(msg.split()) <= 12:
        ref["previous_answer"] = True
    if plan.get("intent") == "define" and not ref.get("term"):
        m = DEFINE.search(msg.split("?")[0] + "?")
        if m:
            ref["term"] = m.group(1).strip()
    return plan


def score(plan: dict, exp: dict) -> list[str]:
    misses = []
    if "intent" in exp and plan.get("intent") not in exp["intent"]:
        misses.append(f"intent {plan.get('intent')} (want {'/'.join(exp['intent'])})")
    ref = plan.get("refers_to") if isinstance(plan.get("refers_to"), dict) else {}
    if "span" in exp:
        span = ref.get("span")
        if not (isinstance(span, list) and len(span) == 2 and all(isinstance(x, (int, float)) for x in span)):
            misses.append(f"span {span} (want ~{list(exp['span'])})")
        elif abs(span[0] - exp["span"][0]) > 20 or abs(span[1] - exp["span"][1]) > 20:
            misses.append(f"span {span} (want ~{list(exp['span'])} ±20 s)")
    if "term" in exp and exp["term"].lower() not in str(ref.get("term") or "").lower():
        misses.append(f"term {ref.get('term')!r} (want {exp['term']!r})")
    if "previous_answer" in exp and bool(ref.get("previous_answer")) != exp["previous_answer"]:
        misses.append(f"previous_answer {ref.get('previous_answer')}")
    for key in ("depth", "style", "ambiguous"):
        if key in exp and plan.get(key) != exp[key]:
            misses.append(f"{key} {plan.get(key)!r} (want {exp[key]!r})")
    if "q_contains" in exp and exp["q_contains"] not in str(plan.get("standalone_question", "")).lower():
        misses.append(f"standalone question lacks {exp['q_contains']!r}")
    return misses


def main() -> None:
    chain = P.providers()
    chain = sorted(chain, key=lambda p: not p["model"].endswith("-20b"))   # assistant: gpt-oss-20b first (§8.0)
    # (first run's bug: '"20b" in model' also matched gpt-oss-120b, so the order never changed)
    ctx, rows, md = context(), [], ["# Step-0 prototype: the assistant's understand step\n",
                                    f"Live position {P.mmss(NOW)} in Python · Lecture 1.\n"]
    for case in CASES:
        convo = "\n".join(f"{who.upper()}: {text}" for who, text in case["turns"]) or "(no earlier turns)"
        user = f"{ctx}\n\nConversation so far:\n{convo}\n\nLatest student message: {case['msg']}"
        res = P.chat(chain, SYSTEM, user, max_tokens=800)
        if not res["ok"]:
            rows.append({"id": case["id"], "ok": False, "attempts": res["attempts"]})
            md.append(f"## {case['id']}. \"{case['msg']}\": **call failed** {res['attempts']}\n")
            continue
        raw_misses = score(res["data"], case["expect"])
        guarded = guard(res["data"], case["msg"], bool(case["turns"]))
        misses = score(guarded, case["expect"])
        rows.append({"id": case["id"], "ok": True, "pass": not misses, "raw_pass": not raw_misses, "misses": misses,
                     "raw_misses": raw_misses, "model": res["model"], "latency_s": res["latency_s"],
                     "plan": res["data"], "guarded": guarded})
        if raw_misses:
            md.append("LLM plan alone: " + "; ".join(raw_misses) + "\n")
        md.append(f"## {case['id']}. \"{case['msg']}\" {'PASS' if not misses else 'MISS'}\n")
        if case["turns"]:
            md.append("Earlier turns: " + " / ".join(f"*{w}:* {t}" for w, t in case["turns"]) + "\n")
        md.append("```json\n" + json.dumps(res["data"], indent=1, ensure_ascii=False) + "\n```\n")
        if misses:
            md.append("Misses: " + "; ".join(misses) + "\n")
        print(f"case {case['id']:2d}: raw {'ok  ' if not raw_misses else 'MISS'} -> guarded "
              f"{'PASS' if not misses else 'MISS ' + '; '.join(misses)}"
              f"  ({res['model'].split('/')[-1]}, {res['latency_s']} s{', cached' if res.get('cached') else ''})",
              flush=True)
    passed = sum(r.get("pass", False) for r in rows)
    raw = sum(r.get("raw_pass", False) for r in rows)
    summary = {"cases": len(rows), "raw_llm_correct": raw, "with_guards_correct": passed, "rows": rows}
    md.insert(2, f"**LLM plan alone: {raw}/{len(rows)} correct; with the deterministic guards: {passed}/{len(rows)}.**\n")
    (P.OUT / "proto_followups.md").write_text("\n".join(md), encoding="utf-8")
    (P.OUT / "proto_followups.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"LLM alone {raw}/{len(rows)}, with guards {passed}/{len(rows)}")


if __name__ == "__main__":
    main()
