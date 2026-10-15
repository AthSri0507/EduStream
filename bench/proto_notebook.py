"""Step-0 prototype 1 (ARCHITECTURE §12 item 8): the notebook prompt on real lecture audio.

Feeds the first 12 minutes of Python · Lecture 1 (real M2 Whisper output, 10 s chunks, A13 rule)
to the notebook prompt as 8 updates of 90 s, keeping the notebook memory between calls, and
applies the §8.1.3 validation in code: section IDs by code, minimum section length, verbatim
quote check, timestamp from the quote's chunk, lexical grounding of points and terms.
The extractive fallback runs on the same updates for comparison.

    .venv\\Scripts\\python bench\\proto_notebook.py [--minutes 12]

Writes bench/results/proto_notebook.md (side by side, for your judgement) and
bench/results/proto_notebook.json (metrics). API keys come from .env and are never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "bench" / "results"
CHUNKS = OUT / "chunks_base.en-reppen_ocw6001_l01_10s.jsonl"
UPDATE_S, CHUNK_S = 90, 10
PER_UPDATE = UPDATE_S // CHUNK_S
MIN_SECTION_UPDATES = 2
GROUNDING_MIN = 0.25          # run 1: 0.40 dropped 3 honest paraphrases (0.33-0.38); the quote check is the main guard
TIMEOUT_S = 30
MIN_GAP_S = 3.0

STOP = set("""a an the and or but if then so to of in on at for with by from as is are was were be been being it its
this that these those there here i you he she we they me my your our their them us do does did doing have has had
not no yes can could will would should may might just also very really some any all more most such than too what
which who whom how why when where about into over out up down only own same both each few other again further
once let's lets okay ok right yeah um uh like going gonna want wanted get got kind sort thing things way""".split())
BOILERPLATE = re.compile(r"creative commons|opencourseware|ocw\.mit|make a donation|additional materials", re.I)

SYSTEM = """You are the note-taker for a live university lecture. Every 90 seconds you receive the next part of
the transcript (automatic speech recognition, so it can contain errors) and the notebook written so far.

Write what a diligent student would write down: ideas, definitions, worked examples, rules, warnings.
Write the notes themselves, not a description of the talk (never "the lecturer says ...").
Skip housekeeping (administration, logistics, recording or licence notices, jokes) unless it matters for studying.
Returning no points is fine when nothing in this part is worth noting.

Return ONLY a JSON object:
{"section": {"action": "continue" | "new", "title": "short topic title (new only)", "starts_at": "mm:ss (new only)"},
 "points": [{"text": "...", "t": "mm:ss", "kind": "point" | "example",
             "quote": "3-15 consecutive words copied exactly from ONE transcript line"}],
 "terms": [{"term": "...", "definition": "...", "t": "mm:ss", "quote": "...", "source": "lecture" | "background"}]}

Rules:
- 0 to 5 points, each at most 300 characters, specific and understandable on its own.
- "quote" is copied word for word from the transcript: no "...", no changes; "t" is the [mm:ss] of its line.
- Terms: at most 4, only terms the lecturer explains or uses in this part; the term must appear in the transcript.
  Give "quote" (the words where it is said) and "source": "lecture" if your definition is what the lecturer said,
  "background" if you had to add general knowledge. Do not repeat terms already defined.
- Start a new section only when the topic clearly changes; otherwise continue the current one.
  For a new section also give "starts_at": the [mm:ss] where the new topic begins."""


# ----------------------------------------------------------------------------- helpers
def mmss(seconds: float) -> str:
    return f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}"


def parse_t(value) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    m = re.match(r"^\s*(\d+):(\d{1,2})\s*$", str(value or ""))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def norm(text: str) -> str:
    # NFKC folds non-breaking hyphens and similar look-alikes (run 1 dropped "p‑sets" for U+2011)
    text = unicodedata.normalize("NFKC", text).replace("‑", "-").replace("’", "'")
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def find_quote(quote: str, chunks_norm: list[str]) -> int | None:
    """Index of the chunk where the quote starts. Fragments split by '...' must all occur, in order
    (run 1 dropped 2 good points whose quotes were shortened with an ellipsis)."""
    fragments = [norm(f) for f in re.split(r"\.\.\.|…", quote) if norm(f)]
    if not fragments or sum(len(f.split()) for f in fragments) < 3:
        return None
    full, starts, pos = "", [], 0
    for c in chunks_norm:
        starts.append(len(full))
        full += c + " "
    for i, frag in enumerate(fragments):
        hit = full.find(frag, pos)
        if hit < 0:
            return None
        if i == 0:
            first = hit
        pos = hit + len(frag)
    return max(i for i, st in enumerate(starts) if st <= first)


def stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "ly", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def content_words(text: str) -> list[str]:
    return [stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 1]


def load_chunks(minutes: float) -> list[dict]:
    rows = [json.loads(line) for line in CHUNKS.open(encoding="utf-8")]
    return [r for r in rows if r["start_time"] < minutes * 60]


# ----------------------------------------------------------------------------- LLM
def providers() -> list[dict]:
    load_dotenv(ROOT / ".env")
    base = os.environ.get("GROQ_BASE_URL", "").rstrip("/")
    key = os.environ.get("GROQ_API_KEY", "")
    models = [m.strip() for m in os.environ.get("GROQ_MODEL", "").split(",") if m.strip()]
    if not (base and key and models):
        sys.exit("GROQ_BASE_URL / GROQ_API_KEY / GROQ_MODEL missing in .env")
    return [{"base": base, "key": key, "model": m} for m in models]


CACHE = OUT / "proto_llm_cache.json"


def chat(chain: list[dict], system: str, user: str, max_tokens: int = 1500) -> dict:
    """Cached wrapper (development only): an identical prompt is never sent twice."""
    import hashlib
    key = hashlib.sha256(json.dumps([system, user, [p["model"] for p in chain]]).encode()).hexdigest()
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    if key in cache:
        return {**cache[key], "cached": True}
    res = _chat(chain, system, user, max_tokens)
    if res["ok"]:
        cache[key] = res
        CACHE.write_text(json.dumps(cache), encoding="utf-8")
    return res


def _chat(chain: list[dict], system: str, user: str, max_tokens: int = 1500) -> dict:
    """First model in the chain that answers with valid JSON wins; errors fall through (as in §8.0)."""
    attempts = []
    for p in chain:
        body = {"model": p["model"], "temperature": 0.2, "max_tokens": max_tokens,
                "response_format": {"type": "json_object"}, "reasoning_effort": "low",
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        started = time.perf_counter()
        try:
            r = requests.post(f"{p['base']}/chat/completions", json=body, timeout=TIMEOUT_S,
                              headers={"Authorization": f"Bearer {p['key']}"})
        except requests.RequestException as exc:
            attempts.append({"model": p["model"], "error": type(exc).__name__})
            continue
        latency = time.perf_counter() - started
        if r.status_code != 200:
            attempts.append({"model": p["model"], "error": f"HTTP {r.status_code}", "detail": r.text[:160]})
            continue
        payload = r.json()
        content = payload["choices"][0]["message"].get("content") or ""
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            attempts.append({"model": p["model"], "error": "invalid JSON"})
            continue
        usage = payload.get("usage", {})
        return {"ok": True, "data": data, "model": p["model"], "latency_s": round(latency, 2),
                "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
                "attempts": attempts}
    return {"ok": False, "attempts": attempts}


# ----------------------------------------------------------------------------- notebook
class Notebook:
    def __init__(self) -> None:
        self.sections: list[dict] = []        # {id, title, updates, points: [...]}
        self.terms: dict[str, dict] = {}

    @property
    def current(self) -> dict | None:
        return self.sections[-1] if self.sections else None

    def context(self) -> str:
        if not self.sections:
            return "Notebook so far: (empty; this is the start of the lecture)"
        lines = ["Notebook so far:", "Sections: " + "; ".join(f"{s['id']}. {s['title']}" for s in self.sections)]
        cur = self.current
        lines.append(f"Current section: {cur['title']}")
        recent = cur["points"][-6:]
        lines += ["Recent points in it:"] + ([f"- [{mmss(pt['t'])}] {pt['text']}" for pt in recent] or ["- (none yet)"])
        lines.append("Terms already defined: " + (", ".join(self.terms) or "(none)"))
        return "\n".join(lines)

    def open_section(self, title: str, update: int) -> dict:
        section = {"id": len(self.sections) + 1, "title": title.strip()[:80] or "Untitled", "first_update": update,
                   "updates": 0, "points": []}
        self.sections.append(section)
        return section

    def render(self) -> str:
        out = []
        for s in self.sections:
            out.append(f"### {s['id']}. {s['title']}")
            out += [f"- `[{mmss(pt['t'])}]` {'*Example:* ' if pt['kind'] == 'example' else ''}{pt['text']}"
                    + (f"  \n  <sub>quote: \"{pt['quote']}\"</sub>" if pt.get("quote") else "") for pt in s["points"]]
            if not s["points"]:
                out.append("- *(no points)*")
        if self.terms:
            out.append("\n**Glossary:** " + "; ".join(f"**{k}**{' *(background)*' if v.get('source') == 'background' else ''}: {v['definition']} `[{mmss(v['t'])}]`"
                                                     for k, v in self.terms.items()))
        return "\n".join(out)


def apply_delta(nb: Notebook, delta: dict, chunks: list[dict], update: int) -> dict:
    """§8.1.3 validation. Returns flags; mutates the notebook only with what survives."""
    flags = []
    transcript_norm = [norm(c["text"]) for c in chunks]
    joined_words = set(content_words(" ".join(c["text"] for c in chunks)))
    full_lower = " ".join(c["text"] for c in chunks).lower()

    # --- section, IDs assigned by code
    sec = delta.get("section") if isinstance(delta.get("section"), dict) else {}
    action, title = sec.get("action"), (sec.get("title") or "").strip()
    if nb.current is None:
        nb.open_section(title or "Introduction", update)
        if action != "new":
            flags.append("first_update_forced_new")
    previous, starts_at = None, None
    if nb.current is not None and action == "new":
        if nb.current["updates"] < MIN_SECTION_UPDATES:
            flags.append(f"premature_new_section_ignored:{title!r}")
        else:
            previous = nb.current
            nb.open_section(title or "Untitled", update)
            starts_at = parse_t(sec.get("starts_at"))
    section = nb.current
    section["updates"] += 1

    # --- points: quote must match exactly (normalised), t comes from the quote's chunk, overlap >= 40 %
    kept = 0
    for pt in (delta.get("points") or [])[:5]:
        if not isinstance(pt, dict):
            flags.append(f"dropped_malformed_point:{str(pt)[:40]!r}")
            continue
        text = str(pt.get("text", "")).strip()[:300]
        quote = norm(str(pt.get("quote", "")))
        if not text:
            continue
        where = find_quote(str(pt.get("quote", "")), transcript_norm)
        if where is None:
            flags.append(f"dropped_quote_not_found:{text[:50]!r}")
            continue
        words = content_words(text)
        overlap = sum(w in joined_words for w in words) / max(1, len(words))
        if overlap < GROUNDING_MIN:
            flags.append(f"dropped_low_overlap({overlap:.2f}):{text[:50]!r}")
            continue
        t_claimed, t = parse_t(pt.get("t")), chunks[where]["start_time"]
        if t_claimed is not None and abs(t_claimed - t) > CHUNK_S:
            flags.append(f"timestamp_corrected:{mmss(t_claimed)}->{mmss(t)}")
        target = previous if (previous and starts_at is not None and t < starts_at) else section
        if target is previous:
            flags.append(f"point_kept_in_previous_section:{mmss(t)}")
        target["points"].append({"text": text, "t": t, "kind": "example" if pt.get("kind") == "example" else "point",
                                  "quote": str(pt.get("quote", "")).strip(), "overlap": round(overlap, 2)})
        kept += 1

    # --- terms: must occur verbatim (ignoring case), not already defined
    for term in (delta.get("terms") or [])[:4]:
        if not isinstance(term, dict):
            flags.append(f"dropped_malformed_term:{str(term)[:40]!r}")
            continue
        name = str(term.get("term", "")).strip()
        if not name or name.lower() in (k.lower() for k in nb.terms):
            continue
        name_norm = norm(name)
        joined_norm = " ".join(transcript_norm)
        name_stems = " ".join(stem(w) for w in name_norm.split())
        joined_stems = " ".join(stem(w) for w in joined_norm.split())
        if not name_norm or (name_norm not in joined_norm and name_stems not in joined_stems):
            flags.append(f"dropped_term_not_in_transcript:{name!r}")
            continue
        where = find_quote(str(term.get("quote", "")), transcript_norm)
        if where is None:
            flags.append(f"term_quote_not_found:{name!r}")
        source = "lecture" if term.get("source") == "lecture" and where is not None else "background"
        nb.terms[name] = {"definition": str(term.get("definition", "")).strip()[:200], "source": source,
                          "t": chunks[where]["start_time"] if where is not None else (parse_t(term.get("t")) or chunks[0]["start_time"])}
    proposed = len((delta.get("points") or [])[:5])
    return {"flags": flags, "points_proposed": proposed, "points_kept": kept}


# ----------------------------------------------------------------------------- extractive fallback
def extractive(chunks: list[dict], top: int = 3) -> list[dict]:
    sentences = []
    for c in chunks:
        for s in re.split(r"(?<=[.!?])\s+", c["text"]):
            s = s.strip()
            if len(s.split()) >= 6 and not BOILERPLATE.search(s):
                sentences.append((s, c["start_time"]))
    freq = Counter(w for s, _ in sentences for w in content_words(s))
    scored = [(sum(freq[w] for w in content_words(s)) / (len(s.split()) ** 0.5), i, s, t)
              for i, (s, t) in enumerate(sentences)]
    best = sorted(sorted(scored, reverse=True)[:top], key=lambda x: x[1])
    return [{"text": s, "t": t} for _, _, s, t in best]


# ----------------------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=12)
    args = ap.parse_args()
    chain = providers()
    chunks = load_chunks(args.minutes)
    updates = [chunks[i:i + PER_UPDATE] for i in range(0, len(chunks), PER_UPDATE)]

    nb, report, metrics, last = Notebook(), [], [], 0.0
    report.append("# Step-0 prototype: notebook prompt on Python · Lecture 1 (first "
                  f"{args.minutes:g} min, real Whisper output)\n")
    extract_md = []
    for k, part in enumerate(updates):
        lines = "\n".join(f"[{mmss(c['start_time'])}] {c['text']}" for c in part)
        user = f"{nb.context()}\n\nTranscript, {mmss(part[0]['start_time'])}-{mmss(part[-1]['end_time'])}:\n{lines}"
        time.sleep(max(0.0, MIN_GAP_S - (time.time() - last)))
        last = time.time()
        res = chat(chain, SYSTEM, user)
        row = {"update": k, "span": f"{mmss(part[0]['start_time'])}-{mmss(part[-1]['end_time'])}",
               "ok": res["ok"], "attempts": res.get("attempts", [])}
        report.append(f"\n## Update {k}: {row['span']}\n")
        report.append("<details><summary>Transcript sent</summary>\n\n```\n" + lines + "\n```\n</details>\n")
        if res["ok"]:
            result = apply_delta(nb, res["data"], part, k)
            row.update(model=res["model"], latency_s=res["latency_s"], prompt_tokens=res["prompt_tokens"],
                       completion_tokens=res["completion_tokens"], **result,
                       section_action=(res["data"].get("section") or {}).get("action"),
                       section_title=(res["data"].get("section") or {}).get("title"))
            report.append(f"**LLM** ({res['model']}, {res['latency_s']} s, "
                          f"{res['prompt_tokens']}+{res['completion_tokens']} tokens): "
                          f"section `{row['section_action']}` {row['section_title'] or ''}; "
                          f"points kept {result['points_kept']}/{result['points_proposed']}\n")
            report.append("```json\n" + json.dumps(res["data"], indent=1, ensure_ascii=False)[:3000] + "\n```\n")
            if result["flags"]:
                report.append("Validation flags: " + "; ".join(f"`{f}`" for f in result["flags"]) + "\n")
        else:
            report.append(f"**LLM failed:** {res['attempts']} (the extractive fallback would be used)\n")
        ext = extractive(part)
        extract_md.append(f"**{row['span']}**\n" + "\n".join(f"- `[{mmss(e['t'])}]` {e['text']}" for e in ext))
        metrics.append(row)
        print(f"update {k} {row['span']}: {'ok' if res['ok'] else 'FAILED'} "
              f"{row.get('points_kept', '-')}/{row.get('points_proposed', '-')} points, "
              f"{row.get('latency_s', '-')} s, flags {len(row.get('flags', []))}", flush=True)

    report.append("\n---\n\n# Resulting notebook (LLM, after validation)\n")
    report.append(nb.render())
    report.append("\n\n# Extractive fallback on the same updates\n")
    report.append("\n\n".join(extract_md))

    ok = [m for m in metrics if m["ok"]]
    summary = {
        "updates": len(metrics), "llm_ok": len(ok),
        "models": Counter(m["model"] for m in ok),
        "points_proposed": sum(m["points_proposed"] for m in ok),
        "points_kept": sum(m["points_kept"] for m in ok),
        "quotes_not_found": sum(f.startswith("dropped_quote") for m in ok for f in m["flags"]),
        "low_overlap_drops": sum(f.startswith("dropped_low_overlap") for m in ok for f in m["flags"]),
        "timestamps_corrected": sum(f.startswith("timestamp_corrected") for m in ok for f in m["flags"]),
        "premature_sections": sum(f.startswith("premature") for m in ok for f in m["flags"]),
        "sections": [s["title"] for s in nb.sections],
        "terms": {k: v["source"] for k, v in nb.terms.items()},
        "points_moved_to_previous_section": sum(f.startswith("point_kept_in_previous") for m in ok for f in m["flags"]),
        "latency_s_median": sorted(m["latency_s"] for m in ok)[len(ok) // 2] if ok else None,
        "tokens_per_call_mean": round(sum((m["prompt_tokens"] or 0) + (m["completion_tokens"] or 0) for m in ok)
                                      / len(ok)) if ok else None,
        "per_update": metrics,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "proto_notebook.md").write_text("\n".join(report), encoding="utf-8")
    (OUT / "proto_notebook.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "per_update"}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
