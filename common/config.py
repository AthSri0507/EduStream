"""EduStream configuration (docs/ARCHITECTURE.md §11).

Values come from environment variables; the repo's .env file only supplies
defaults and never overrides a variable that is already set. Every component
calls load() once at start-up.

    .venv\\Scripts\\python -m common.config --check     # invariant check (used by preflight.ps1)
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "run"
load_dotenv(ROOT / ".env", override=False)


# --------------------------------------------------
# Topic names and partition counts (ARCHITECTURE §4)
# --------------------------------------------------

TOPIC_AUDIO = "video_audio"
TOPIC_TRANSCRIPTS = "transcriptions"
TOPIC_WINDOWS = "window_summaries"
TOPIC_NOTES = "final_notes"          # notebook: live drafts (notes.v3) and consolidated topics (consolidation.v1)
TOPIC_ALERTS = "alerts"
TOPIC_DLQ = "dlq"

GROUP_WORKERS = "transcription-workers"
# Consumer group of the note stage: the Note Agent (agents/note_agent.py) since M6a. Until then it was the
# interim note generator ("note-generator-interim"); the lag monitor watches whichever is deployed.
GROUP_NOTES = "note-agent"

# Demo lectures and their Kafka video_ids, chosen in M2 so murmur2 places them
# on partitions 0, 1 and 2 (bench/M2_RESULTS.md §2).
DEMO_LECTURES = {
    "ocw6001_l01": "python_l1",               # Python · Lecture 1 (Bell)      -> partition 0
    "ocw6006_l01": "algorithms_ku_l1",        # Algorithms · Lecture 1 (Ku)    -> partition 1
    "ocw6006_l02": "algorithms_demaine_l2",   # Algorithms · Lecture 2 (Demaine) -> partition 2
}


def _get(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value if value else default


def _bool(name: str, default: bool) -> bool:
    return _get(name, str(default)).lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    kafka_bootstrap: str
    rf: int
    partitions: int
    chunk_seconds: float
    speedup: float
    window_seconds: int
    grace_seconds: int
    align_start: bool
    whisper_model: str
    whisper_cpu_threads: int
    t_score: float
    min_covered_s: float
    lag_alert_s: float
    forward_flush: bool
    flush_formula: str
    linger_ms: int
    worker_id: str
    note_update_s: int = 90          # rev 6 A14: one notebook update per 90 s of lecture audio
    note_max_hold_s: int = 300       # a held partial update is sent after this long (e.g. a crashed source)

    @property
    def chunk_wall_ms(self) -> int:
        """Wall-clock length of one chunk: CHUNK_SECONDS / SPEEDUP (ARCHITECTURE A3)."""
        return round(self.chunk_seconds * 1000 / self.speedup)

    @property
    def topic_partitions(self) -> dict[str, int]:
        return {TOPIC_AUDIO: self.partitions, TOPIC_TRANSCRIPTS: self.partitions,
                TOPIC_WINDOWS: self.partitions, TOPIC_NOTES: self.partitions, TOPIC_ALERTS: self.partitions,
                TOPIC_DLQ: 1}

    def problems(self) -> list[str]:
        """Invariant violations; an empty list means the configuration is usable."""
        found = []
        if not 0 < self.chunk_seconds <= 15:
            found.append(f"CHUNK_SECONDS={self.chunk_seconds} must be in (0, 15] (Kafka 1 MB message limit, A1)")
        if self.speedup <= 0:
            found.append(f"SPEEDUP={self.speedup} must be > 0")
        if self.window_seconds <= 0 or self.grace_seconds <= 0:
            found.append("WINDOW_SECONDS and GRACE_SECONDS must be > 0")
        if not 0 < self.min_covered_s <= self.window_seconds:
            found.append(f"MIN_COVERED_S={self.min_covered_s} must be in (0, WINDOW_SECONDS]")
        if self.flush_formula not in ("legacy", "tight"):
            found.append(f"FLUSH_FORMULA={self.flush_formula!r} must be 'legacy' or 'tight'")
        if self.lag_alert_s <= 0:
            found.append("LAG_ALERT_S must be > 0")
        if not 0 < self.t_score < 1:
            found.append(f"T_SCORE={self.t_score} must be in (0, 1)")
        if self.partitions < 1 or self.rf < 1:
            found.append("EDU_PARTITIONS and EDU_RF must be >= 1")
        span = self.window_seconds * self.speedup        # media seconds per window
        if span <= 0 or (self.note_update_s % span and span % self.note_update_s):
            found.append(f"WINDOW_SECONDS x SPEEDUP = {span:g} s must divide NOTE_UPDATE_S={self.note_update_s} "
                         "or be a multiple of it (a window must not straddle two notebook updates, §6.2 S5)")
        if self.note_update_s % self.chunk_seconds:
            found.append(f"NOTE_UPDATE_S={self.note_update_s} must be a whole number of chunks")
        if (self.window_seconds * 1000) % self.chunk_wall_ms:
            found.append(f"WINDOW_SECONDS={self.window_seconds} is not a whole number of chunks "
                         f"({self.chunk_wall_ms} ms); windows would hold uneven chunk counts")
        return found


def load() -> Settings:
    window = int(_get("WINDOW_SECONDS", "30"))
    return Settings(
        kafka_bootstrap=_get("KAFKA_BOOTSTRAP", "localhost:9092"),
        rf=int(_get("EDU_RF", "1")),
        partitions=int(_get("EDU_PARTITIONS", "3")),
        chunk_seconds=float(_get("CHUNK_SECONDS", "10")),
        speedup=float(_get("SPEEDUP", "1")),
        window_seconds=window,
        grace_seconds=int(_get("GRACE_SECONDS", "10")),
        align_start=_bool("ALIGN_START", True),
        whisper_model=_get("WHISPER_MODEL", "base.en"),
        whisper_cpu_threads=int(_get("WHISPER_CPU_THREADS", "4")),
        t_score=float(_get("T_SCORE", "0.63")),
        min_covered_s=float(_get("MIN_COVERED_S", str(window / 2))),
        lag_alert_s=float(_get("LAG_ALERT_S", "30")),
        # On since M4: the Streams app uses the flush to close a lecture's last window (A5).
        forward_flush=_bool("FORWARD_FLUSH", True),
        # A5 flush timestamp. "tight" (default since M4, verified: PLAN M4) = end of the last chunk's
        # window + GRACE; "legacy" = (last+1)*chunk + WINDOW + GRACE, kept for comparison runs.
        flush_formula=_get("FLUSH_FORMULA", "tight").lower(),
        linger_ms=int(_get("LINGER_MS", "5")),
        worker_id=_get("WORKER_ID", f"w{os.getpid()}"),
        note_update_s=int(_get("NOTE_UPDATE_S", "90")),
        note_max_hold_s=int(_get("NOTE_MAX_HOLD_S", "300")),
    )


def main() -> int:
    if "--check" not in sys.argv:
        print(load())
        return 0
    settings = load()
    problems = settings.problems()
    for problem in problems:
        print(f"CONFIG: {problem}")
    if not problems:
        print(f"CONFIG OK: chunk {settings.chunk_seconds:g} s (wall {settings.chunk_wall_ms} ms), "
              f"window {settings.window_seconds} s, grace {settings.grace_seconds} s, "
              f"{settings.partitions} partitions, RF {settings.rf}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
