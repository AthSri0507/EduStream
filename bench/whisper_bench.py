"""M2 check 6: Whisper speed, memory, determinism and accuracy on the EduStream dataset.

Modes (run from the repo root with the .venv Python):
    speed        real-time factor (RTF) and peak memory with N = 1..3 concurrent workers
    determinism  A/A test: the same chunks transcribed twice give identical output?
    wer          transcribe all four lectures at 5 s and 10 s chunks (per-chunk JSONL)
    analyze      WER per lecture and chunk size, plus a first asr_score calibration

Settings match docs/ARCHITECTURE.md: int8 on CPU, cpu_threads=4, language=en,
temperature=0 (no fallback, reproducible), vad_filter=True, one call per chunk.

    .venv\\Scripts\\python bench\\whisper_bench.py speed
    .venv\\Scripts\\python bench\\whisper_bench.py determinism
    .venv\\Scripts\\python bench\\whisper_bench.py wer
    .venv\\Scripts\\python bench\\whisper_bench.py analyze
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import multiprocessing as mp
import re
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MODELS = ROOT / "models"
OUT = ROOT / "bench" / "results"
SAMPLE_RATE = 16000
WINDOW_S = 30
BAD_WINDOW_WER = 0.30
DEMO_ITEMS = ["ocw6001_l01", "ocw6006_l01", "ocw6006_l02"]

sys.path.insert(0, str(ROOT / "analysis"))


# --------------------------------------------------
# Shared helpers
# --------------------------------------------------

def manifest() -> dict[str, dict]:
    with (DATA / "manifest.csv").open(encoding="utf-8-sig") as handle:
        return {row["item_id"]: row for row in csv.DictReader(handle)}


def load_model(name: str, threads: int):
    from faster_whisper import WhisperModel
    return WhisperModel(str(MODELS / name), device="cpu", compute_type="int8",
                        cpu_threads=threads, num_workers=1)


def load_audio(item: dict, limit_s: float | None = None) -> np.ndarray:
    from faster_whisper.audio import decode_audio
    audio = decode_audio(str(DATA / item["media_file"]), sampling_rate=SAMPLE_RATE)
    return audio[: int(limit_s * SAMPLE_RATE)] if limit_s else audio


def transcribe_chunk(model, audio: np.ndarray) -> dict:
    segments, _ = model.transcribe(audio, language="en", beam_size=5, temperature=0.0,
                                   vad_filter=True, condition_on_previous_text=False)
    segments = list(segments)
    text = " ".join(s.text.strip() for s in segments).strip()
    if not segments:
        return {"text": "", "asr_score": None, "avg_logprob": None, "no_speech_prob": None, "compression_ratio": None}
    weights = [max(s.end - s.start, 1e-3) for s in segments]
    total = sum(weights)
    logprob = sum(s.avg_logprob * w for s, w in zip(segments, weights)) / total
    return {
        "text": text,
        "asr_score": math.exp(logprob),
        "avg_logprob": logprob,
        "no_speech_prob": sum(s.no_speech_prob * w for s, w in zip(segments, weights)) / total,
        "compression_ratio": max(s.compression_ratio for s in segments),
    }


def run_chunks(model, audio: np.ndarray, chunk_s: int, item_id: str, sink=None) -> dict:
    size = chunk_s * SAMPLE_RATE
    n_chunks = math.ceil(len(audio) / size)
    proc = 0.0
    for chunk_id in range(n_chunks):
        piece = audio[chunk_id * size:(chunk_id + 1) * size]
        started = time.perf_counter()
        result = transcribe_chunk(model, piece)
        elapsed = time.perf_counter() - started
        proc += elapsed
        if sink is not None:
            sink.write(json.dumps({"item_id": item_id, "chunk_s": chunk_s, "chunk_id": chunk_id,
                                   "start_time": chunk_id * chunk_s,
                                   "end_time": min((chunk_id + 1) * chunk_s, len(audio) / SAMPLE_RATE),
                                   "proc_ms": round(elapsed * 1000, 1), **result}) + "\n")
    audio_s = len(audio) / SAMPLE_RATE
    return {"chunks": n_chunks, "audio_s": round(audio_s, 1), "proc_s": round(proc, 1), "rtf": round(proc / audio_s, 4)}


def peak_rss_mb() -> float:
    import psutil
    info = psutil.Process().memory_info()
    return round(getattr(info, "peak_wset", info.rss) / 1e6, 1)


# --------------------------------------------------
# speed
# --------------------------------------------------

def speed_worker(model_name: str, threads: int, item: dict, limit_s: float, barrier) -> dict:
    audio = load_audio(item, limit_s)
    load_start = time.perf_counter()
    model = load_model(model_name, threads)
    load_s = time.perf_counter() - load_start
    barrier.wait()                     # all N workers transcribe at the same time
    stats = run_chunks(model, audio, 5, item["item_id"])
    return {"item_id": item["item_id"], "model_load_s": round(load_s, 1), "peak_rss_mb": peak_rss_mb(), **stats}


def mode_speed(args) -> None:
    items = manifest()
    plan = [("base.en", 1), ("base.en", 2), ("base.en", 3), ("tiny.en", 3), ("small.en", 1)]
    rows = []
    for model_name, workers in plan:
        with mp.Manager() as manager:
            barrier = manager.Barrier(workers)
            with mp.Pool(workers) as pool:
                jobs = [pool.apply_async(speed_worker, (model_name, args.threads, items[DEMO_ITEMS[i]],
                                                        args.limit_seconds, barrier)) for i in range(workers)]
                results = [job.get() for job in jobs]
        worst = max(r["rtf"] for r in results)
        row = {"model": model_name, "workers": workers, "cpu_threads_each": args.threads,
               "rtf_worst": worst, "rtf_mean": round(float(np.mean([r["rtf"] for r in results])), 4),
               "peak_rss_mb_each": max(r["peak_rss_mb"] for r in results),
               "model_load_s": max(r["model_load_s"] for r in results),
               # sustainable lectures: L * rtf <= 0.7 * N  (ARCHITECTURE §11 rule)
               "max_lectures_at_70pct": math.floor(0.7 * workers / worst) if worst > 0 else None,
               "per_worker": results}
        rows.append(row)
        print(f"{model_name:9s} N={workers}  RTF worst {worst:.3f}  mean {row['rtf_mean']:.3f}  "
              f"peak RSS {row['peak_rss_mb_each']:.0f} MB/worker  -> sustains {row['max_lectures_at_70pct']} lecture(s)",
              flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "whisper_speed.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")


# --------------------------------------------------
# determinism
# --------------------------------------------------

def determinism_run(model_name: str, threads: int, item: dict, n_chunks: int) -> list[dict]:
    model = load_model(model_name, threads)
    audio = load_audio(item, n_chunks * 5)
    return [transcribe_chunk(model, audio[i * 5 * SAMPLE_RATE:(i + 1) * 5 * SAMPLE_RATE]) for i in range(n_chunks)]


def mode_determinism(args) -> None:
    item = manifest()["ocw6001_l01"]
    with mp.Pool(1) as pool:
        first = pool.apply(determinism_run, ("base.en", args.threads, item, args.chunks))
    with mp.Pool(1) as pool:                     # a fresh process, like a restarted worker
        second = pool.apply(determinism_run, ("base.en", args.threads, item, args.chunks))
    text_same = sum(a["text"] == b["text"] for a, b in zip(first, second))
    score_diff = max(abs((a["asr_score"] or 0) - (b["asr_score"] or 0)) for a, b in zip(first, second))
    report = {"chunks": args.chunks, "identical_text": text_same, "max_asr_score_diff": score_diff,
              "differences": [{"chunk_id": i, "a": a["text"], "b": b["text"]}
                              for i, (a, b) in enumerate(zip(first, second)) if a["text"] != b["text"]]}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "whisper_determinism.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"identical text: {text_same}/{args.chunks}; max asr_score difference: {score_diff:.2e}")


# --------------------------------------------------
# wer (transcription pass) and analyze
# --------------------------------------------------

def wer_worker(model_name: str, threads: int, item: dict, chunk_s: int) -> dict:
    model = load_model(model_name, threads)
    audio = load_audio(item)
    path = OUT / f"chunks_{model_name}_{item['item_id']}_{chunk_s}s.jsonl"
    with path.open("w", encoding="utf-8") as sink:
        stats = run_chunks(model, audio, chunk_s, item["item_id"], sink)
    print(f"  done {item['item_id']} {chunk_s}s: RTF {stats['rtf']:.3f}", flush=True)
    return {"item_id": item["item_id"], "chunk_s": chunk_s, **stats}


def mode_wer(args) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    items = manifest()
    tasks = [(args.model, args.threads, items[i], size) for size in (5, 10) for i in items]
    with mp.Pool(args.workers) as pool:
        stats = pool.starmap(wer_worker, tasks)
    (OUT / f"whisper_pass_{args.model}.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")


PUNCT = re.compile(r"[^\w\s']")
# Only sound annotations are dropped; other parentheses (e.g. "O(n)") keep their content.
BRACKETED = re.compile(r"\[[^\]]*\]|\((?:laughs?|laughter|music|applause|inaudible|silence|coughs?|[A-Z][A-Z ]+)\)",
                       re.IGNORECASE)


def normalise(text: str) -> list[str]:
    text = BRACKETED.sub(" ", text.lower()).replace("-", " ").replace("—", " ")
    text = PUNCT.sub(" ", text)
    return [w.strip("'") for w in text.split() if w.strip("'")]


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    rx = np.argsort(np.argsort(x)).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    return float(np.corrcoef(rx, ry)[0, 1])


def mode_analyze(args) -> None:
    import jiwer
    from dataset_eda import parse_srt, word_spans, TOKEN

    items = manifest()
    summary, windows = [], []
    for item_id, item in items.items():
        cues = parse_srt(DATA / item["transcript_file"])
        notice_end = max((c.end for c in cues if c.boilerplate), default=0.0)
        cut = math.ceil(notice_end / 10) * 10            # common start for 5 s and 10 s chunks
        ref_words = [w for c in cues if not c.boilerplate and c.start >= cut for w in normalise(c.text)]
        ref_spans = [(s, e, w) for s, e, w in word_spans(cues) if s >= cut]

        for chunk_s in (5, 10):
            path = OUT / f"chunks_{args.model}_{item_id}_{chunk_s}s.jsonl"
            if not path.exists():
                continue
            chunks = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            kept = [c for c in chunks if c["start_time"] >= cut]
            hyp_words = [w for c in kept for w in normalise(c["text"])]
            measure = jiwer.process_words(" ".join(ref_words), " ".join(hyp_words))
            no_fillers = [w for w in hyp_words if w not in {"um", "uh", "uhm", "hmm", "mm"}]
            wer_no_fillers = jiwer.wer(" ".join(ref_words), " ".join(no_fillers))
            summary.append({"item_id": item_id, "lecture": item["display_name"], "chunk_s": chunk_s,
                            "ref_words": len(ref_words), "hyp_words": len(hyp_words),
                            "wer": round(measure.wer, 4), "substitutions": measure.substitutions,
                            "deletions": measure.deletions, "insertions": measure.insertions,
                            "wer_without_hyp_fillers": round(wer_no_fillers, 4),
                            "filler_tokens_in_hyp": len(hyp_words) - len(no_fillers),
                            "mean_proc_ms": round(float(np.mean([c["proc_ms"] for c in chunks])), 1)})

            # Per-window WER vs asr_score (first calibration data, ARCHITECTURE §7)
            ref_by_window: dict[int, list[str]] = {}
            for s, e, w in ref_spans:
                ref_by_window.setdefault(int(((s + e) / 2) // WINDOW_S), []).extend(normalise(w))
            for window in sorted(ref_by_window):
                in_window = [c for c in kept if int(c["start_time"] // WINDOW_S) == window]
                scores = [c["asr_score"] for c in in_window if c["asr_score"] is not None]
                ref = ref_by_window[window]
                if len(ref) < 20 or not scores:
                    continue
                hyp = [w for c in in_window for w in normalise(c["text"])]
                windows.append({"item_id": item_id, "chunk_s": chunk_s, "window": window,
                                "ref_words": len(ref), "wer": jiwer.wer(" ".join(ref), " ".join(hyp)),
                                "score_avg": float(np.mean(scores)), "score_min": float(np.min(scores))})

    calibration = {}
    for chunk_s in (5, 10):
        rows = [w for w in windows if w["chunk_s"] == chunk_s]
        if not rows:
            continue
        wer = np.array([r["wer"] for r in rows])
        score = np.array([r["score_avg"] for r in rows])
        bad = wer > BAD_WINDOW_WER
        best = None
        for t in np.arange(0.30, 0.90, 0.01):
            alert = score < t
            tp, fp, fn = int(np.sum(alert & bad)), int(np.sum(alert & ~bad)), int(np.sum(~alert & bad))
            precision = tp / (tp + fp) if tp + fp else 0.0
            recall = tp / (tp + fn) if tp + fn else 0.0
            f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
            entry = {"t_score": round(float(t), 2), "precision": round(precision, 3),
                     "recall": round(recall, 3), "f1": round(f1, 3), "alerts": int(alert.sum())}
            if abs(t - 0.55) < 1e-9:
                calibration.setdefault(chunk_s, {})["at_0.55"] = entry
            if best is None or f1 > best["f1"]:
                best = entry
        calibration.setdefault(chunk_s, {}).update({
            "windows": len(rows), "bad_windows": int(bad.sum()),
            "window_wer_median": round(float(np.median(wer)), 4),
            "spearman_score_vs_wer": round(spearman(score, wer), 3),
            "score_avg_range": [round(float(score.min()), 3), round(float(score.max()), 3)],
            "best_f1": best})

    report = {"model": args.model, "per_lecture": summary, "calibration": calibration}
    (OUT / f"whisper_wer_{args.model}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    with (OUT / f"whisper_windows_{args.model}.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(windows[0]))
        writer.writeheader()
        writer.writerows(windows)
    for row in summary:
        print(f"{row['lecture']:34s} {row['chunk_s']:>2d}s  WER {row['wer']:.3f}  "
              f"(S {row['substitutions']}, D {row['deletions']}, I {row['insertions']}; "
              f"without fillers {row['wer_without_hyp_fillers']:.3f})")
    print(json.dumps(calibration, indent=2))


# --------------------------------------------------
# Main
# --------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["speed", "determinism", "wer", "analyze"])
    parser.add_argument("--threads", type=int, default=4, help="cpu_threads per worker")
    parser.add_argument("--limit-seconds", type=float, default=600, help="audio per worker in speed mode")
    parser.add_argument("--chunks", type=int, default=20, help="chunks in determinism mode")
    parser.add_argument("--model", default="base.en", help="model for wer/analyze")
    parser.add_argument("--workers", type=int, default=3, help="parallel processes in wer mode")
    args = parser.parse_args()
    {"speed": mode_speed, "determinism": mode_determinism, "wer": mode_wer, "analyze": mode_analyze}[args.mode](args)


if __name__ == "__main__":
    main()
