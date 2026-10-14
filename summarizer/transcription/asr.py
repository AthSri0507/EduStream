"""Whisper decoding rule (docs/ARCHITECTURE.md A13, measured in bench/M2_RESULTS.md §6).

1. Decode at temperature 0 (reproducible).
2. If the result fails Whisper's own quality check (compression_ratio > 2.4 or
   avg_logprob < -1.0), decode ONCE more at temperature 0 with
   repetition_penalty=1.3 and keep that result.

M2: this retry removed 137 of 138 repetition loops ("4, 4, 4, ...") and gave the
lowest WER, while staying reproducible. Whisper's standard temperature fallback
was not reproducible (57/138 identical on a re-run), so it is not used.
"""

from __future__ import annotations

import math

from common.config import ROOT

COMPRESSION_MAX = 2.4
LOGPROB_MIN = -1.0
RETRY_REPETITION_PENALTY = 1.3
BASE_OPTIONS = {"language": "en", "beam_size": 5, "temperature": 0.0,
                "vad_filter": True, "condition_on_previous_text": False}


def load_model(name: str, cpu_threads: int):
    """Load a model downloaded by scripts/setup.ps1 into models/<name> (no network at run time)."""
    from faster_whisper import WhisperModel
    path = ROOT / "models" / name
    if not (path / "model.bin").exists():
        raise FileNotFoundError(f"Whisper model {name!r} not found in {path}; run scripts\\setup.ps1")
    return WhisperModel(str(path), device="cpu", compute_type="int8", cpu_threads=cpu_threads, num_workers=1)


def summarize_segments(segments) -> dict:
    """Text plus duration-weighted quality figures; asr_score = exp(mean avg_logprob), a heuristic proxy."""
    segments = list(segments)
    if not segments:
        return {"text": "", "asr_score": None, "avg_logprob": None, "no_speech_prob": None, "compression_ratio": None}
    weights = [max(s.end - s.start, 1e-3) for s in segments]
    total = sum(weights)
    logprob = sum(s.avg_logprob * w for s, w in zip(segments, weights)) / total
    return {
        "text": " ".join(s.text.strip() for s in segments).strip(),
        "asr_score": min(1.0, math.exp(logprob)),
        "avg_logprob": logprob,
        "no_speech_prob": sum(s.no_speech_prob * w for s, w in zip(segments, weights)) / total,
        "compression_ratio": max(s.compression_ratio for s in segments),
    }


def needs_retry(result: dict) -> bool:
    ratio, logprob = result["compression_ratio"], result["avg_logprob"]
    return (ratio is not None and ratio > COMPRESSION_MAX) or (logprob is not None and logprob < LOGPROB_MIN)


def transcribe(model, audio) -> dict:
    """Apply the A13 rule to one chunk of 16 kHz float32 audio."""
    segments, _ = model.transcribe(audio, **BASE_OPTIONS)
    result = summarize_segments(segments)
    retried = needs_retry(result)
    if retried:
        segments, _ = model.transcribe(audio, **BASE_OPTIONS, repetition_penalty=RETRY_REPETITION_PENALTY)
        result = summarize_segments(segments)
    return {**result, "retried": retried}
