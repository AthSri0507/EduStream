"""How much of a lecture its finished notes kept (live run 29 Oct: the Hypothesis Testing notes lost a worked
example and kept 1 of 37 glossary terms). Reads SQLite only: no Kafka, no LLM, so it runs after any lecture.

Per finished lecture:
  * notes          topics, elements, words of notes per minute of lecture, placeholder titles ("Part N")
  * who wrote it   live updates and passes by generator (llm / extractive / fallback)
  * lost           live-draft sentences that no finished element covers (agents/consolidation.py COVER_MIN), not
                   counting filler, logistics or questions; "worked" = from an example, steps, table or code, or a
                   sentence with numbers: the losses that matter most
  * glossary       terms kept vs terms the model proposed, and why the others were dropped
  * checks         how often each quality check removed something (sentence_unsupported, number_unsaid, ...)

    .venv\\Scripts\\python -m bench.coverage                          every finished lecture in data/edustream.db
    .venv\\Scripts\\python -m bench.coverage --video hypothesis_testing_0208 --db bench/results/replay_x/edustream.db

Writes bench/results/coverage_<label>.json.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from agents import study_notes as sn
from agents.consolidation import COVER_MIN, QUESTION_LOGISTICS, WORKED
from agents.text import similar, support
from common.config import ROOT
from storage.db import connect_readonly

PLACEHOLDER = re.compile(r"^Part \d+$")


def _flags(conn, table: str, video_id: str) -> list[str]:
    return [f for (raw,) in conn.execute(f"SELECT quality_flags FROM {table} WHERE video_id = ?", (video_id,))
            for f in json.loads(raw or "[]")]


def lost_sentences(drafts: list[dict], final: list[dict]) -> list[dict]:
    """Draft sentences the finished notes do not hold (repeats among drafts counted once)."""
    have = [sn.text_of(x) for x in final]
    lost, seen = [], []
    for d in drafts:
        worked_el = d["kind"] in WORKED
        for s in (d.get("sentences") if d["kind"] == "para" else [sn.text_of(d)]) or []:
            if sn.FILLER.search(s) or sn.LOGISTICS.search(s) or QUESTION_LOGISTICS.search(s) or s.rstrip().endswith("?") \
                    or any(similar(s, x) >= sn.DUPLICATE_MIN for x in seen):
                continue
            seen.append(s)
            if not any(support(s, h) >= COVER_MIN for h in have):
                lost.append({"t": d["t"], "worked": worked_el or bool(re.search(r"\d", s)), "text": s})
    return lost


def lecture(conn, video_id: str) -> dict:
    title, = conn.execute("SELECT COALESCE(title, video_id) FROM lectures WHERE video_id = ?", (video_id,)).fetchone()
    minutes = (conn.execute("SELECT COALESCE(MAX(end_time), 0) FROM chunks WHERE video_id = ?", (video_id,))
               .fetchone()[0]) / 60
    topics = [r[0] for r in conn.execute("SELECT title FROM topics WHERE video_id = ? ORDER BY topic_n", (video_id,))]
    final = [json.loads(b) for (b,) in conn.execute("SELECT body FROM elements WHERE video_id = ? ORDER BY t",
                                                     (video_id,))]
    drafts = [json.loads(b) for (b,) in conn.execute("SELECT body FROM drafts WHERE video_id = ? ORDER BY t, seq",
                                                      (video_id,))]
    words = sum(len(sn.words_of(sn.text_of(x))) for x in final)
    lost = lost_sentences(drafts, final)
    flags = _flags(conn, "live_updates", video_id) + _flags(conn, "passes", video_id)
    checks = Counter(re.match(r"[a-z_]+", f).group(0) for f in flags if re.match(r"[a-z_]+", f))
    kept_terms = [r[0] for r in conn.execute("SELECT term FROM glossary WHERE video_id = ?", (video_id,))]
    dropped = Counter()
    for f in flags:
        m = re.match(r"(term_dropped\w*):'(.*)'$", f)
        if m:
            dropped[(m.group(1), m.group(2).lower())] += 1
    proposed = {t.lower() for t in kept_terms} | {t for _, t in dropped}
    return {
        "video_id": video_id, "title": title, "minutes": round(minutes, 1),
        "notes": {"topics": len(topics), "elements": len(final), "words_per_minute": round(words / max(minutes, 1), 1),
                  "worked_elements": sum(x["kind"] in WORKED for x in final),
                  "placeholder_titles": [t for t in topics if PLACEHOLDER.match(t)]},
        "generators": {
            "live": dict(Counter(g for (g,) in conn.execute("SELECT generator FROM live_updates WHERE video_id = ?",
                                                            (video_id,)))),
            "passes": dict(Counter(g for (g,) in conn.execute("SELECT generator FROM passes WHERE video_id = ?",
                                                              (video_id,))))},
        "lost": {"sentences": len(lost), "worked": sum(x["worked"] for x in lost),
                 "draft_sentences": len({s for d in drafts for s in (d.get("sentences") or [])}),
                 "examples": [x for x in lost if x["worked"]][:20], "other": [x for x in lost if not x["worked"]][:20]},
        "glossary": {"kept": len(kept_terms), "proposed": len(proposed), "terms": sorted(kept_terms, key=str.lower),
                     "dropped_by": dict(Counter(why for why, _ in dropped))},
        "checks": dict(checks.most_common()),
    }


def show(r: dict) -> str:
    n, g, lost, gl = r["notes"], r["generators"], r["lost"], r["glossary"]
    out = [f"{r['title']} ({r['video_id']}, {r['minutes']} min)",
           f"  notes      {n['topics']} topics, {n['elements']} elements ({n['worked_elements']} worked), "
           f"{n['words_per_minute']} words/min" + (f", placeholder titles: {n['placeholder_titles']}"
                                                   if n["placeholder_titles"] else ""),
           f"  written by live {g['live']}  passes {g['passes']}",
           f"  lost       {lost['sentences']} of {lost['draft_sentences']} draft sentences, {lost['worked']} of them "
           f"worked (examples, numbers)",
           *[f"               [{sn.mmss(x['t'])}] {x['text'][:100]}" for x in lost["examples"][:6]],
           f"  glossary   {gl['kept']} kept of {gl['proposed']} proposed; dropped: {gl['dropped_by'] or '-'}",
           "  checks     " + ", ".join(f"{k} {v}" for k, v in list(r["checks"].items())[:8])]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=None, help="a SQLite file (default: data/edustream.db)")
    ap.add_argument("--video", action="append", default=[], help="a video_id (repeatable; default: every finished one)")
    ap.add_argument("--label", default="latest")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    conn = connect_readonly(args.db)
    try:
        videos = args.video or [v for (v,) in conn.execute(
            "SELECT DISTINCT video_id FROM passes WHERE final = 1 ORDER BY video_id")]
        if not videos:
            print("no finished lecture in the database")
            return 1
        results = [lecture(conn, v) for v in videos]
    finally:
        conn.close()
    print("\n\n".join(show(r) for r in results))
    out = ROOT / "bench" / "results" / f"coverage_{args.label}.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n-> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
