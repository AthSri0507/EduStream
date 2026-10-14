"""M2 check 7: free-tier LLM providers for the Note Agent (docs/ARCHITECTURE.md §8.0).

Sends the same 20 transcript window PAIRS (NOTE_EVERY_N_WINDOWS=2), cut from the
caption references, to every provider in LLM_PROVIDERS, through the same
OpenAI-compatible chat-completions call the Note Agent will use. Measures:
  latency per call, tokens per call (from the API's usage field),
  valid-JSON rate against the notes fields, and errors (incl. HTTP 429)
and writes a side-by-side markdown file (with the extractive baseline) for a
manual quality check. API keys are read from .env and never printed.

    .venv\\Scripts\\python bench\\llm_bench.py            # all providers in LLM_PROVIDERS
    .venv\\Scripts\\python bench\\llm_bench.py --list     # show each provider's model ids
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "bench" / "results"
WINDOW_S = 30
PAIRS = 20
TIMEOUT_S = 15
MIN_GAP_S = 2.5          # stay well under ~30 requests/min free-tier limits
REQUIRED = {"summary": str, "key_points": list, "terms": list, "questions": list}

sys.path.insert(0, str(ROOT / "analysis"))

SYSTEM_PROMPT = (
    "You write concise study notes from a short slice of a university lecture transcript. "
    "Return ONLY a JSON object with keys: summary (1-2 sentences), key_points (2-4 short strings), "
    "terms (list of {term, definition} for technical terms actually defined or used), "
    "questions (1-2 review questions). Use only information present in the transcript."
)


def provider_config(name: str) -> dict:
    prefix = name.upper()
    return {"name": name, "base_url": os.environ.get(f"{prefix}_BASE_URL", "").rstrip("/"),
            "model": os.environ.get(f"{prefix}_MODEL", ""), "key": os.environ.get(f"{prefix}_API_KEY", "")}


def window_pairs() -> list[dict]:
    """20 consecutive-window pairs spread evenly over the four lectures (deterministic)."""
    # Original cue text keeps punctuation and casing, like real Whisper output
    # (the extractive baseline needs sentence boundaries).
    from dataset_eda import parse_srt
    with (DATA / "manifest.csv").open(encoding="utf-8-sig") as handle:
        items = list(csv.DictReader(handle))
    pairs = []
    per_item = PAIRS // len(items)
    for item in items:
        by_window: dict[int, list[str]] = {}
        for cue in parse_srt(DATA / item["transcript_file"]):
            if cue.text and not cue.boilerplate:
                by_window.setdefault(int(((cue.start + cue.end) / 2) // WINDOW_S), []).append(cue.text)
        full = [w for w in sorted(by_window) if w + 1 in by_window]
        step = max(1, len(full) // per_item)
        for w in full[::step][:per_item]:
            pairs.append({"lecture": item["display_name"], "window": w,
                          "text": " ".join(by_window[w] + by_window[w + 1])})
    return pairs


def extractive(text: str) -> list[str]:
    """Same rule as the existing summarizer/notes/note_generator.py (the fallback baseline)."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    return [s for s in sentences if len(s.split()) >= 5][:5]


def call(provider: dict, transcript: str) -> dict:
    body = {"model": provider["model"], "temperature": 0.2, "max_tokens": 1000,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": f"Transcript:\n{transcript}"}]}
    if "gpt-oss" in provider["model"]:
        # Reasoning models: hidden reasoning tokens count against the per-minute token
        # limit and the output budget, so ask for the minimum.
        body["reasoning_effort"] = "low"
    started = time.perf_counter()
    try:
        response = requests.post(f"{provider['base_url']}/chat/completions", json=body, timeout=TIMEOUT_S,
                                 headers={"Authorization": f"Bearer {provider['key']}"})
    except requests.RequestException as exc:
        return {"ok": False, "error": type(exc).__name__, "latency_s": time.perf_counter() - started}
    latency = time.perf_counter() - started
    if response.status_code != 200:
        return {"ok": False, "error": f"HTTP {response.status_code}", "latency_s": latency,
                "detail": response.text[:200]}
    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    usage = payload.get("usage", {})
    try:
        notes = json.loads(content)
        valid = all(isinstance(notes.get(k), t) for k, t in REQUIRED.items())
    except json.JSONDecodeError:
        notes, valid = None, False
    return {"ok": True, "valid_json": valid, "latency_s": latency, "notes": notes, "raw": content[:1500],
            "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true", help="list model ids offered by each provider")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    providers = [provider_config(p.strip()) for p in os.environ.get("LLM_PROVIDERS", "").split(",") if p.strip()]
    ready = [p for p in providers if p["key"] and p["base_url"]]
    if not ready:
        print("No provider has an API key in .env (CEREBRAS_API_KEY / GROQ_API_KEY). Nothing to benchmark.")
        return

    if args.list:
        for p in ready:
            r = requests.get(f"{p['base_url']}/models", headers={"Authorization": f"Bearer {p['key']}"}, timeout=15)
            ids = [m.get("id") for m in r.json().get("data", [])] if r.ok else [f"HTTP {r.status_code}"]
            print(f"{p['name']}: {ids}")
        return

    pairs = window_pairs()
    OUT.mkdir(parents=True, exist_ok=True)
    summary, side_by_side = {}, ["# LLM vs extractive notes (M2 sample)\n"]
    for p in ready:
        if not p["model"]:
            print(f"{p['name']}: {p['name'].upper()}_MODEL is empty; run with --list and set it in .env")
            continue
        results, last = [], 0.0
        for pair in pairs:
            time.sleep(max(0.0, MIN_GAP_S - (time.time() - last)))
            last = time.time()
            results.append(call(p, pair["text"]))
            print(f"  {p['name']} {pair['lecture']} w{pair['window']}: "
                  f"{'ok' if results[-1]['ok'] else results[-1]['error']} {results[-1]['latency_s']:.1f}s", flush=True)
        ok = [r for r in results if r["ok"]]
        latencies = sorted(r["latency_s"] for r in ok)
        summary[p["name"]] = {
            "model": p["model"], "calls": len(results), "succeeded": len(ok),
            "valid_json": sum(r.get("valid_json", False) for r in ok),
            "errors": sorted({r["error"] for r in results if not r["ok"]}),
            "latency_median_s": round(latencies[len(latencies) // 2], 2) if latencies else None,
            "latency_max_s": round(latencies[-1], 2) if latencies else None,
            "tokens_per_call_mean": round(sum((r["prompt_tokens"] or 0) + (r["completion_tokens"] or 0) for r in ok)
                                          / len(ok)) if ok else None}
        for pair, r in zip(pairs[:5], results[:5]):
            side_by_side.append(f"## {pair['lecture']}, windows {pair['window']}-{pair['window'] + 1} ({p['name']})\n")
            side_by_side.append("**Extractive:** " + " / ".join(extractive(pair["text"])) + "\n")
            side_by_side.append("**LLM:** ```" + (r.get("raw") or r.get("error", "")) + "```\n")

    tag = "_".join(re.sub(r"[^\w.-]", "-", f"{p['name']}-{p['model']}") for p in ready if p["model"])
    (OUT / f"llm_bench_{tag}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (OUT / f"llm_side_by_side_{tag}.md").write_text("\n".join(side_by_side), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
