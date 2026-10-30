"""Live lecture source: records a class while it happens and sends it into the pipeline exactly like a file
(producer/lecture_source.py): the same audio_chunk.v1 records, schedule, S1 check, state file and flush, so the
workers, windows, notes and dashboard cannot tell the difference.

  * online class (Zoom, Meet, Teams): a laptop that has joined the meeting records what it plays, the "loopback" of
    its speaker or headphones. Nothing is installed in the meeting; no meeting API, account or key.
  * the lecturer's own laptop: Zoom does not play your own voice back to you, so add --with-mic (loopback + mic).
  * in the room: --mic records a microphone instead.
  * chunk i covers [session_start + i*10 s, +10 s) of the capture: the same event times as a file. A gap in the
    audio (a stalled device) is filled with silence so chunk ids stay contiguous and every window completes; the
    SILENCE alert shows it.
  * the end: Ctrl+C, the stop file run/lectures/<video_id>.stop (written by the dashboard's Stop button),
    --max-minutes, or --silence-end minutes without sound. Then the flush closes the last window and the Note Agent
    finishes the notes. A second Ctrl+C aborts without the flush.

    .venv\\Scripts\\python -m producer.live_source --list-devices
    .venv\\Scripts\\python -m producer.live_source --video-id dbms_live_1030 --title "DBMS · live 30 Oct"
    .venv\\Scripts\\python -m producer.live_source --video-id dbms_live_1030 --device Headphones --with-mic

Uses `soundcard` (WASAPI loopback on Windows). Tested by tests/test_live_source.py (pure parts) and a loopback
check on 30 Oct: 30 s of a lecture played and re-recorded gave the same Whisper transcript as the file.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np

from common import schemas
from common.config import TOPIC_AUDIO, Settings, load
from common.kafka_utils import EXIT_PRODUCE_FAILED, ProduceFailed, make_producer, send_and_wait
from common.log import JsonLog
from common.partitioning import partition_for
from producer.lecture_source import (SAMPLE_RATE, STATE_DIR, active_lectures, aligned_session_start, chunk_event_ts,
                                     chunk_send_at, flush_event_ts, flush_send_at, s1_conflicts, wait_until,
                                     write_state)

BLOCK = SAMPLE_RATE // 10            # 100 ms per read
SLACK_MS = 1000                      # a chunk is cut this long after its end: its last block has surely arrived
MAX_BACKLOG_CHUNKS = 2               # a capture running ahead of the clock is trimmed to stay live
SILENCE_RMS = 0.003                  # about -50 dBFS: nothing playing (loopback gives exact zeros then)
QUIET_WARN_CHUNKS = 6                # one minute without sound at the start: say where we are listening
VIDEO_ID = re.compile(r"[A-Za-z0-9_.-]{1,64}")
REQUEST_KEYS = ("video_id", "title", "device", "with_mic", "mic", "max_minutes", "silence_end")


# --------------------------------------------------
# Pure parts (unit-tested)
# --------------------------------------------------

class SampleBuffer:
    """Mono float32 samples from one capture thread, taken out a chunk at a time."""

    def __init__(self) -> None:
        self.blocks: deque = deque()
        self.size = 0
        self.lock = threading.Lock()

    def feed(self, samples) -> None:
        samples = np.asarray(samples, dtype=np.float32).reshape(-1)
        with self.lock:
            self.blocks.append(samples)
            self.size += len(samples)

    def clear(self) -> None:
        with self.lock:
            self.blocks.clear()
            self.size = 0

    def take(self, n: int) -> tuple[np.ndarray, int]:
        """The next n samples, padded with silence if fewer have arrived. Returns (samples, missing)."""
        out, have = [], 0
        with self.lock:
            while self.blocks and have < n:
                block = self.blocks.popleft()
                need = n - have
                if len(block) > need:
                    self.blocks.appendleft(block[need:])
                    block = block[:need]
                out.append(block)
                have += len(block)
            self.size -= have
        missing = n - have
        if missing:
            out.append(np.zeros(missing, dtype=np.float32))
        return (np.concatenate(out) if out else np.zeros(n, dtype=np.float32)), missing


def drop_excess(buf: SampleBuffer, keep: int) -> int:
    """Drop the oldest samples beyond `keep` (a capture clock running fast must not fall behind the lecture);
    returns how many were dropped."""
    excess = buf.size - keep
    if excess <= 0:
        return 0
    buf.take(excess)
    return excess


def mix(pieces: list[np.ndarray]) -> np.ndarray:
    """Loopback + microphone: summed, kept inside [-1, 1]."""
    return np.clip(np.sum(pieces, axis=0), -1.0, 1.0) if len(pieces) > 1 else pieces[0]


def rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(samples, dtype=np.float64)))) if len(samples) else 0.0


def dbfs(level: float) -> float:
    return round(20 * np.log10(max(level, 1e-6)), 1)


def to_pcm16(samples: np.ndarray) -> bytes:
    return (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()


def end_reason(chunk_id: int, silent_run: int, chunk_s: float, max_minutes: float | None,
               silence_end_minutes: float | None, stop_file: bool) -> str | None:
    """Why the lecture ends after chunk `chunk_id` was sent, or None to go on."""
    if stop_file:
        return "stop_button"
    if max_minutes and (chunk_id + 1) * chunk_s >= max_minutes * 60:
        return "max_minutes"
    if silence_end_minutes and silent_run * chunk_s >= silence_end_minutes * 60:
        return "silence"
    return None


def free_video_id(title: str, partitions: int, active: list[dict], when: float | None = None) -> str:
    """A video_id from the title and the start time, on a partition with no active lecture (S1)."""
    base = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:40] or "live"
    stamp = time.strftime("%m%d_%H%M", time.localtime(when))
    busy = {s["partition"] for s in active}
    for suffix in [""] + [f"_{c}" for c in "bcdefghijklmnop"]:
        video_id = f"{base}_{stamp}{suffix}"
        if partition_for(video_id, partitions) not in busy:
            return video_id
    raise SystemExit("every partition has an active lecture (S1): stop one first")


def pick(devices: list, name: str | None, default):
    """A device whose name contains `name` (case-insensitive), else the default."""
    if not name:
        return default
    found = [d for d in devices if name.lower() in d.name.lower()]
    if not found:
        raise SystemExit(f"no audio device matching {name!r}; see --list-devices")
    return found[0]


# --------------------------------------------------
# Capture
# --------------------------------------------------

class Capture(threading.Thread):
    """One recorder (a loopback or a microphone) feeding a SampleBuffer at 16 kHz mono until stopped."""

    def __init__(self, device, label: str) -> None:
        super().__init__(name=f"capture-{label}", daemon=True)
        self.device, self.label = device, label
        self.buffer = SampleBuffer()
        self.halt = threading.Event()
        self.error: Exception | None = None

    def run(self) -> None:
        try:
            with self.device.recorder(samplerate=SAMPLE_RATE, channels=1, blocksize=BLOCK) as rec:
                while not self.halt.is_set():
                    self.buffer.feed(rec.record(numframes=BLOCK)[:, 0])
        except Exception as exc:                       # device unplugged, driver error: the chunks become gaps
            self.error = exc


def devices(args):
    import soundcard as sc
    import warnings
    warnings.filterwarnings("ignore", message=".*discontinuity.*")
    loops = [m for m in sc.all_microphones(include_loopback=True) if m.isloopback]
    mics = sc.all_microphones()
    chosen = []
    if args.mic is not None:
        mic = pick(mics, args.mic, sc.default_microphone())
        chosen.append((mic, f"microphone: {mic.name}"))
    else:
        speaker = pick(sc.all_speakers(), args.device, sc.default_speaker())
        loop = next(m for m in loops if m.name == speaker.name)
        chosen.append((loop, f"what this PC plays on: {speaker.name}"))
        if args.with_mic is not None:
            mic = pick(mics, args.with_mic, sc.default_microphone())
            chosen.append((mic, f"plus microphone: {mic.name}"))
    return chosen


def list_devices(as_json: bool = False) -> None:
    import soundcard as sc
    if as_json:                                         # for the dashboard (its own process need not load COM audio)
        print(json.dumps({"speakers": [s.name for s in sc.all_speakers()], "default_speaker": sc.default_speaker().name,
                          "mics": [m.name for m in sc.all_microphones()], "default_mic": sc.default_microphone().name}))
        return
    print("Play-back devices (a Zoom/Meet/Teams class is recorded from the one the meeting plays on):")
    for s in sc.all_speakers():
        print(f"  {'*' if s.name == sc.default_speaker().name else ' '} {s.name}")
    print("Microphones (--mic / --with-mic):")
    for m in sc.all_microphones():
        print(f"  {'*' if m.name == sc.default_microphone().name else ' '} {m.name}")
    print("* = Windows default")


# --------------------------------------------------
# One live lecture
# --------------------------------------------------

def run_live(args, settings: Settings) -> int:
    video_id, title = args.video_id, (args.title or f"Live lecture {time.strftime('%d %b %H:%M')}")[:120]
    partition = partition_for(video_id, settings.partitions)
    now_ms = int(time.time() * 1000)
    conflicts = s1_conflicts({video_id: partition}, active_lectures(now_ms))
    if conflicts and not args.force:
        print("Refusing to start (S1):\n  " + "\n  ".join(conflicts))
        return 2
    log = JsonLog(f"source-{video_id}")
    stop_file = STATE_DIR / f"{video_id}.stop"
    stop_file.unlink(missing_ok=True)
    chosen = devices(args)
    producer = None
    if not args.dry_run:                                # before recording or claiming the partition
        try:
            producer = make_producer(settings, client_id=f"source-{video_id}")
        except Exception as exc:                        # noqa: BLE001 - kafka-python raises several kinds
            print(f"Kafka is not reachable ({type(exc).__name__}): start the pipeline first "
                  f"(scripts\\start_all.ps1), then start the class again.")
            return 2
    captures = [Capture(dev, label) for dev, label in chosen]
    for cap in captures:
        cap.start()

    chunk_wall, chunk_s = settings.chunk_wall_ms, settings.chunk_seconds
    chunk_samples = int(chunk_s * SAMPLE_RATE)
    session_start = aligned_session_start(now_ms, settings.window_seconds, settings.align_start)
    wall0_ms, mono0 = int(time.time() * 1000), time.monotonic()
    halt = threading.Event()
    print(f"Live: {title} -> video_id {video_id}, partition {partition}")
    for cap in captures:
        print(f"  recording {cap.label}")
    print(f"  starts in {(session_start - now_ms) / 1000:.1f} s; end with Ctrl+C or the dashboard's Stop button")
    wait_until(session_start, wall0_ms, mono0, halt)
    for cap in captures:
        cap.buffer.clear()                              # nothing from before the session start
    write_state(video_id, item_id="live", partition=partition, status="active", session_start=session_start,
                chunk_wall_ms=chunk_wall, last_chunk_sent=-1, chunks=None, window_s=settings.window_seconds,
                grace_s=settings.grace_seconds, flush_formula=settings.flush_formula, title=title,
                devices=[c.label for c in captures])
    log.info("live_started", video_id=video_id, partition=partition, session_start=session_start,
             devices=[c.label for c in captures])

    last, silent_run, gaps_s, dropped_s, reason, warned = -1, 0, 0.0, 0.0, None, False
    try:
        try:
            chunk_id = 0
            while reason is None:
                wait_until(chunk_send_at(session_start, chunk_id, chunk_wall) + SLACK_MS, wall0_ms, mono0, halt)
                pieces, missing = [], 0
                for cap in captures:
                    dropped_s += drop_excess(cap.buffer, MAX_BACKLOG_CHUNKS * chunk_samples + chunk_samples) \
                        / SAMPLE_RATE
                    piece, short = cap.buffer.take(chunk_samples)
                    pieces.append(piece)
                    missing = max(missing, short)
                audio = mix(pieces)
                gaps_s += missing / SAMPLE_RATE
                level = rms(audio)
                silent_run = silent_run + 1 if level < SILENCE_RMS else 0
                start_time = chunk_id * chunk_s
                event = {"schema": "audio_chunk.v1", "type": "chunk", "video_id": video_id,
                         "session_start": session_start, "chunk_id": chunk_id,
                         "start_time": round(start_time, 3), "end_time": round(start_time + chunk_s, 3),
                         "event_ts": chunk_event_ts(session_start, chunk_id, chunk_wall),
                         "sample_rate": SAMPLE_RATE, "encoding": "pcm_s16le", "channels": 1,
                         "audio_b64": base64.b64encode(to_pcm16(audio)).decode("ascii")}
                if chunk_id == 0:
                    event["title"] = title
                value = schemas.encode("audio_chunk.v1", event)
                where = "dry-run"
                if producer is not None:
                    md = send_and_wait(producer, TOPIC_AUDIO, value, key=video_id)
                    where = f"p{md.partition} off={md.offset}"
                last = chunk_id
                write_state(video_id, last_chunk_sent=chunk_id, level_dbfs=dbfs(level), gaps_s=round(gaps_s, 1))
                broken = [c.label for c in captures if c.error is not None]
                print(f"[{video_id}] chunk {chunk_id + 1} t={start_time / 60:5.1f} min  level {dbfs(level):6.1f} dBFS"
                      f"{'  (silent)' if level < SILENCE_RMS else ''}{f'  gap {missing / SAMPLE_RATE:.1f} s' if missing else ''}"
                      f"  {where}" + (f"  CAPTURE FAILED: {broken}" if broken else ""), flush=True)
                if silent_run == QUIET_WARN_CHUNKS and last + 1 == QUIET_WARN_CHUNKS and not warned:
                    warned = True
                    print(f"  No sound for a minute: is the meeting playing on {captures[0].label.split(': ')[-1]}? "
                          f"(see --list-devices)", flush=True)
                reason = end_reason(chunk_id, silent_run, chunk_s, args.max_minutes, args.silence_end,
                                    stop_file.exists())
                chunk_id += 1
        except KeyboardInterrupt:
            reason = "ctrl_c"
        print(f"[{video_id}] ending ({reason}) after {last + 1} chunks; Ctrl+C again aborts without finishing",
              flush=True)
        for cap in captures:
            cap.halt.set()
        if last < 0:
            write_state(video_id, status="aborted", end_reason=reason)
            return 1
        flush_ts = flush_event_ts(session_start, last, chunk_wall, settings.window_seconds, settings.grace_seconds,
                                  settings.flush_formula)
        wait_until(flush_send_at(session_start, last, chunk_wall, settings.window_seconds, settings.grace_seconds,
                                 settings.flush_formula), wall0_ms, mono0, halt)
        flush = {"schema": "audio_chunk.v1", "type": "flush", "video_id": video_id, "session_start": session_start,
                 "last_chunk_id": last, "event_ts": flush_ts}
        if producer is not None:
            md = send_and_wait(producer, TOPIC_AUDIO, schemas.encode("audio_chunk.v1", flush), key=video_id)
            log.info("flushed", video_id=video_id, last_chunk_id=last, event_ts=flush_ts, partition=md.partition,
                     offset=md.offset, reason=reason, gaps_s=round(gaps_s, 1), dropped_s=round(dropped_s, 1))
        write_state(video_id, status="flushed", flush_event_ts=flush_ts, end_reason=reason)
        stop_file.unlink(missing_ok=True)
        print(f"[{video_id}] flushed (last chunk {last}, {(last + 1) * chunk_s / 60:.1f} min); the notes are being "
              f"finished", flush=True)
        return 0
    except KeyboardInterrupt:
        write_state(video_id, status="aborted", end_reason="aborted")
        print(f"[{video_id}] aborted: the last window stays open (tools/send_flush.py closes it)")
        return 130
    except ProduceFailed as exc:
        log.error("produce_failed", video_id=video_id, error=str(exc))
        write_state(video_id, status="aborted", error=str(exc))
        return EXIT_PRODUCE_FAILED
    finally:
        for cap in captures:
            cap.halt.set()
        if producer is not None:
            producer.close(timeout=5)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--list-devices", action="store_true")
    p.add_argument("--json", action="store_true", help="with --list-devices: as JSON")
    p.add_argument("--request", default=None, help="a JSON file with these options (the dashboard's Start button: "
                                                   "titles with spaces and symbols survive the hand-over)")
    p.add_argument("--video-id", help="letters, digits, _ . - (at most 64); pick a free partition with "
                                      "tools/partition_of.py")
    p.add_argument("--title", default=None, help="shown on the dashboard")
    p.add_argument("--device", default=None, help="record what this play-back device plays (default: Windows "
                                                  "default; part of its name is enough)")
    p.add_argument("--with-mic", nargs="?", const="", default=None, help="also record a microphone (the lecturer's "
                                                                         "own laptop); optional name")
    p.add_argument("--mic", nargs="?", const="", default=None, help="record only a microphone (in the room)")
    p.add_argument("--max-minutes", type=float, default=240.0, help="end after this long (default 240)")
    p.add_argument("--silence-end", type=float, default=15.0, help="end after this many minutes without sound "
                                                                   "(0: never; default 15)")
    p.add_argument("--dry-run", action="store_true", help="record and encode, send nothing")
    p.add_argument("--force", action="store_true", help="skip the S1 check")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.list_devices:
        list_devices(args.json)
        return 0
    if args.request:
        for key, value in json.loads(Path(args.request).read_text(encoding="utf-8")).items():
            if key in REQUEST_KEYS and value is not None:
                setattr(args, key, value)
    if not args.video_id or not VIDEO_ID.fullmatch(args.video_id):
        print("--video-id is needed: letters, digits, '_', '.' or '-' (at most 64)")
        return 2
    settings = load()
    problems = list(settings.problems())
    if settings.speedup != 1:
        problems.append(f"SPEEDUP is {settings.speedup}: a live class runs at 1x")
    if problems:
        print("Refusing to start, configuration invalid:\n  " + "\n  ".join(problems))
        return 2
    return run_live(args, settings)


if __name__ == "__main__":
    sys.exit(main())
