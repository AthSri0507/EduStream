"""M2 follow-up: fixing Whisper repetition loops found by the WER pass.

With temperature=0 and no fallback (chosen for determinism), a few percent of
chunks fall into repetition loops ("4, 4, 4, ..."), which inflate WER through
insertions. Only chunks that fail Whisper's own quality thresholds are affected
(compression_ratio > 2.4 or avg_logprob < -1.0), so this script re-decodes just
those chunks with each candidate fix, splices the result into a copy of the
per-chunk files, and lets `whisper_bench.py analyze --model <variant>` score it.

Variants:
  fallback    faster-whisper's standard temperature fallback (0.0 .. 1.0); NOT deterministic
  norepeat    temperature 0 + no_repeat_ngram_size=3 (deterministic)
  reppen      temperature 0 + repetition_penalty=1.3 (deterministic)
  drop        discard the flagged chunk's text (no re-decode)

    .venv\\Scripts\\python bench\\whisper_loop_fix.py
    .venv\\Scripts\\python bench\\whisper_bench.py analyze --model base.en-norepeat   (etc.)
"""

from __future__ import annotations

import json
import multiprocessing as mp
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "bench" / "results"
sys.path.insert(0, str(ROOT / "bench"))

from whisper_bench import SAMPLE_RATE, load_audio, load_model, manifest  # noqa: E402

VARIANTS = {
    "fallback": {"temperature": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]},
    "norepeat": {"temperature": 0.0, "no_repeat_ngram_size": 3},
    "reppen": {"temperature": 0.0, "repetition_penalty": 1.3},
}


def flagged(row: dict) -> bool:
    return (row["compression_ratio"] or 0) > 2.4 or (row["avg_logprob"] is not None and row["avg_logprob"] < -1.0)


def decode(model, audio, options: dict) -> dict:
    import math
    segments, _ = model.transcribe(audio, language="en", beam_size=5, vad_filter=True,
                                   condition_on_previous_text=False, **options)
    segments = list(segments)
    if not segments:
        return {"text": "", "asr_score": None, "avg_logprob": None, "no_speech_prob": None, "compression_ratio": None}
    weights = [max(s.end - s.start, 1e-3) for s in segments]
    total = sum(weights)
    logprob = sum(s.avg_logprob * w for s, w in zip(segments, weights)) / total
    return {"text": " ".join(s.text.strip() for s in segments).strip(), "asr_score": math.exp(logprob),
            "avg_logprob": logprob,
            "no_speech_prob": sum(s.no_speech_prob * w for s, w in zip(segments, weights)) / total,
            "compression_ratio": max(s.compression_ratio for s in segments)}


def fix_lecture(item: dict) -> dict:
    model = load_model("base.en", 4)
    audio = load_audio(item)
    report = {}
    for chunk_s in (5, 10):
        rows = [json.loads(line) for line in
                (OUT / f"chunks_base.en_{item['item_id']}_{chunk_s}s.jsonl").read_text(encoding="utf-8").splitlines()]
        targets = [r for r in rows if flagged(r)]
        replaced = {name: {} for name in VARIANTS}
        repeat_same = 0
        for row in targets:
            piece = audio[int(row["start_time"] * SAMPLE_RATE):int(row["end_time"] * SAMPLE_RATE)]
            for name, options in VARIANTS.items():
                replaced[name][row["chunk_id"]] = decode(model, piece, options)
            again = decode(model, piece, VARIANTS["fallback"])        # fallback twice: is it repeatable?
            repeat_same += again["text"] == replaced["fallback"][row["chunk_id"]]["text"]
        replaced["drop"] = {r["chunk_id"]: {"text": "", "asr_score": None, "avg_logprob": None,
                                            "no_speech_prob": None, "compression_ratio": None} for r in targets}
        still = {}
        for name, fixes in replaced.items():
            out = OUT / f"chunks_base.en-{name}_{item['item_id']}_{chunk_s}s.jsonl"
            with out.open("w", encoding="utf-8") as sink:
                for row in rows:
                    sink.write(json.dumps({**row, **fixes.get(row["chunk_id"], {})}) + "\n")
            still[name] = sum(1 for fix in fixes.values() if (fix["compression_ratio"] or 0) > 2.4)
        report[f"{chunk_s}s"] = {"flagged": len(targets), "still_looping_after": still,
                                 "fallback_identical_on_rerun": repeat_same}
        print(f"  {item['item_id']} {chunk_s}s: flagged {len(targets)}, still looping {still}, "
              f"fallback repeatable {repeat_same}/{len(targets)}", flush=True)
    return {item["item_id"]: report}


def main() -> None:
    items = list(manifest().values())
    with mp.Pool(3) as pool:
        results = pool.map(fix_lecture, items)
    merged = {k: v for r in results for k, v in r.items()}
    (OUT / "whisper_loop_fix.json").write_text(json.dumps(merged, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
