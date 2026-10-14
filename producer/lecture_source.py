"""Lecture source: replays lecture audio into Kafka on a fixed real-time schedule.

Implements docs/ARCHITECTURE.md A1-A6 and §6.2:
  * audio is decoded once (PyAV via faster-whisper), cut into CHUNK_SECONDS slices of
    16 kHz mono PCM and sent inside the message (base64), key = video_id;
  * session_start is the next WINDOW_SECONDS boundary; chunk i has
    event_ts = session_start + i * chunk_wall and is sent no earlier than event_ts + chunk_wall;
  * after the last chunk a scheduled flush (A5) closes the lecture's last window;
  * S1: refuses to start two active lectures on one partition (advisory check);
  * every send waits for its acknowledgement; on a failure the process exits
    (EXIT_PRODUCE_FAILED) instead of re-sending or reusing the producer.

Usage (repo root, broker running):
    .venv\\Scripts\\python -m producer.lecture_source --demo
    .venv\\Scripts\\python -m producer.lecture_source --lecture ocw6001_l01=python_l1 --limit-seconds 600
Options: --speedup X, --stall-at N --stall-seconds S (fault tests), --no-align, --dry-run, --force
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import math
import sys
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path

from common import schemas
from common.config import DEMO_LECTURES, ROOT, RUN_DIR, TOPIC_AUDIO, Settings, load
from common.kafka_utils import EXIT_PRODUCE_FAILED, ProduceFailed, make_producer, send_and_wait
from common.log import JsonLog
from common.partitioning import partition_for

SAMPLE_RATE = 16_000
STATE_DIR = RUN_DIR / "lectures"
ACTIVE_STALE_S = 120


# --------------------------------------------------
# Schedule (pure functions; unit-tested in tests/test_schedule.py)
# --------------------------------------------------

def aligned_session_start(now_ms: int, window_s: int, align: bool) -> int:
    """Next WINDOW_SECONDS boundary (A3); without alignment, now."""
    if not align:
        return now_ms
    window_ms = window_s * 1000
    return math.ceil(now_ms / window_ms) * window_ms


def chunk_event_ts(session_start: int, chunk_id: int, chunk_wall_ms: int) -> int:
    return session_start + chunk_id * chunk_wall_ms


def chunk_send_at(session_start: int, chunk_id: int, chunk_wall_ms: int) -> int:
    """A chunk is sent when its capture has ended: event_ts + chunk_wall."""
    return chunk_event_ts(session_start, chunk_id, chunk_wall_ms) + chunk_wall_ms


def flush_event_ts(session_start: int, last_chunk_id: int, chunk_wall_ms: int, window_s: int, grace_s: int) -> int:
    """A5: session_start + (last_chunk_id + 1) * chunk_wall + WINDOW + GRACE."""
    return session_start + (last_chunk_id + 1) * chunk_wall_ms + (window_s + grace_s) * 1000


def flush_send_at(session_start: int, last_chunk_id: int, chunk_wall_ms: int, window_s: int, grace_s: int) -> int:
    """The flush is published no earlier than its own event_ts + chunk_wall (keeps S4 and §6.2's bound)."""
    return flush_event_ts(session_start, last_chunk_id, chunk_wall_ms, window_s, grace_s) + chunk_wall_ms


# --------------------------------------------------
# S1: at most one active lecture per partition (ARCHITECTURE §6.2)
# --------------------------------------------------

def active_lectures(now_ms: int) -> list[dict]:
    """Lectures whose state file says active and was updated recently (a crashed source goes stale)."""
    found = []
    for path in STATE_DIR.glob("*.json"):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if state.get("status") == "active" and now_ms - state.get("updated_ts", 0) < ACTIVE_STALE_S * 1000:
            found.append(state)
    return found


def s1_conflicts(requested: dict[str, int], active: list[dict]) -> list[str]:
    """requested: video_id -> partition. Returns human-readable conflicts (empty = OK)."""
    problems = []
    by_partition: dict[int, list[str]] = {}
    for video_id, partition in requested.items():
        by_partition.setdefault(partition, []).append(video_id)
    for partition, ids in sorted(by_partition.items()):
        if len(ids) > 1:
            problems.append(f"{', '.join(ids)} all map to partition {partition} (S1: one lecture per partition); "
                            f"pick other video_ids with tools/partition_of.py")
    for state in active:
        for video_id, partition in requested.items():
            if state["partition"] == partition:
                problems.append(f"partition {partition} already has active lecture {state['video_id']!r} "
                                f"(state file run/lectures/{state['video_id']}.json)")
    return problems


def write_state(video_id: str, **fields) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = STATE_DIR / f"{video_id}.json"
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"video_id": video_id}
    state.update(fields, updated_ts=int(time.time() * 1000))
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(path)


# --------------------------------------------------
# One lecture
# --------------------------------------------------

@dataclass
class Lecture:
    item_id: str
    video_id: str
    title: str
    media_path: Path
    partition: int


def load_pcm16(media_path: Path, limit_s: float | None):
    """Decode to 16 kHz mono and keep it as int16 (half the memory of float32)."""
    import numpy as np
    from faster_whisper.audio import decode_audio
    audio = decode_audio(str(media_path), sampling_rate=SAMPLE_RATE)
    if limit_s:
        audio = audio[: int(limit_s * SAMPLE_RATE)]
    return (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")


def wait_until(target_wall_ms: int, wall0_ms: int, mono0: float, stop: threading.Event) -> None:
    """Sleep until a wall-clock instant, measured with the monotonic clock (immune to NTP jumps)."""
    target = mono0 + (target_wall_ms - wall0_ms) / 1000
    while not stop.is_set():
        remaining = target - time.monotonic()
        if remaining <= 0:
            return
        stop.wait(min(remaining, 0.5))


def run_lecture(lecture: Lecture, settings: Settings, session_start: int, clock: tuple[int, float],
                args, stop: threading.Event, failures: list) -> None:
    log = JsonLog(f"source-{lecture.video_id}")
    wall0_ms, mono0 = clock
    chunk_wall = settings.chunk_wall_ms
    chunk_samples = int(settings.chunk_seconds * SAMPLE_RATE)
    pcm = load_pcm16(lecture.media_path, args.limit_seconds)
    n_chunks = math.ceil(len(pcm) / chunk_samples)
    duration_s = len(pcm) / SAMPLE_RATE
    log.info("lecture_ready", video_id=lecture.video_id, item_id=lecture.item_id, partition=lecture.partition,
             chunks=n_chunks, media_s=round(duration_s, 1), session_start=session_start, chunk_wall_ms=chunk_wall)
    write_state(lecture.video_id, item_id=lecture.item_id, partition=lecture.partition, status="active",
                session_start=session_start, chunk_wall_ms=chunk_wall, last_chunk_sent=-1, chunks=n_chunks,
                window_s=settings.window_seconds, grace_s=settings.grace_seconds)

    producer = None if args.dry_run else make_producer(settings, client_id=f"source-{lecture.video_id}")
    try:
        for chunk_id in range(n_chunks):
            if stop.is_set():
                write_state(lecture.video_id, status="aborted")
                return
            if args.stall_at is not None and chunk_id == args.stall_at:
                log.warn("stall_injected", chunk_id=chunk_id, seconds=args.stall_seconds)
                stop.wait(args.stall_seconds)
            wait_until(chunk_send_at(session_start, chunk_id, chunk_wall), wall0_ms, mono0, stop)
            piece = pcm[chunk_id * chunk_samples:(chunk_id + 1) * chunk_samples]
            start_time = chunk_id * settings.chunk_seconds
            event = {
                "schema": "audio_chunk.v1", "type": "chunk", "video_id": lecture.video_id,
                "session_start": session_start, "chunk_id": chunk_id,
                "start_time": round(start_time, 3), "end_time": round(min(start_time + settings.chunk_seconds, duration_s), 3),
                "event_ts": chunk_event_ts(session_start, chunk_id, chunk_wall),
                "sample_rate": SAMPLE_RATE, "encoding": "pcm_s16le", "channels": 1,
                "audio_b64": base64.b64encode(piece.tobytes()).decode("ascii"),
            }
            if chunk_id == 0:
                event["title"] = lecture.title
            value = schemas.encode("audio_chunk.v1", event)
            if producer is not None:
                md = send_and_wait(producer, TOPIC_AUDIO, value, key=lecture.video_id)
                where = f"p{md.partition} off={md.offset}"
            else:
                where = "dry-run"
            write_state(lecture.video_id, last_chunk_sent=chunk_id)
            print(f"[{lecture.video_id}] chunk {chunk_id + 1}/{n_chunks} t={start_time:.0f}s {where} "
                  f"({len(value) / 1000:.0f} KB)", flush=True)

        last = n_chunks - 1
        flush_ts = flush_event_ts(session_start, last, chunk_wall, settings.window_seconds, settings.grace_seconds)
        wait_until(flush_send_at(session_start, last, chunk_wall, settings.window_seconds, settings.grace_seconds),
                   wall0_ms, mono0, stop)
        if stop.is_set():
            write_state(lecture.video_id, status="aborted")
            return
        flush = {"schema": "audio_chunk.v1", "type": "flush", "video_id": lecture.video_id,
                 "session_start": session_start, "last_chunk_id": last, "event_ts": flush_ts}
        if producer is not None:
            md = send_and_wait(producer, TOPIC_AUDIO, schemas.encode("audio_chunk.v1", flush), key=lecture.video_id)
            log.info("flushed", video_id=lecture.video_id, last_chunk_id=last, event_ts=flush_ts,
                     partition=md.partition, offset=md.offset)
        write_state(lecture.video_id, status="flushed", flush_event_ts=flush_ts)
        print(f"[{lecture.video_id}] flushed (last chunk {last}); lecture complete", flush=True)
    except ProduceFailed as exc:
        log.error("produce_failed", video_id=lecture.video_id, error=str(exc))
        write_state(lecture.video_id, status="aborted", error=str(exc))
        failures.append(exc)
        stop.set()
    finally:
        if producer is not None:
            producer.close(timeout=5)


# --------------------------------------------------
# Main
# --------------------------------------------------

def manifest() -> dict[str, dict]:
    with (ROOT / "data" / "manifest.csv").open(encoding="utf-8-sig") as handle:
        return {row["item_id"]: row for row in csv.DictReader(handle)}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--demo", action="store_true", help="the 3 demo lectures with their M2 video_ids")
    parser.add_argument("--lecture", action="append", default=[], metavar="ITEM_ID=VIDEO_ID")
    parser.add_argument("--limit-seconds", type=float, default=None, help="media seconds per lecture (dev split: 600)")
    parser.add_argument("--speedup", type=float, default=None, help="override SPEEDUP (window semantics change!)")
    parser.add_argument("--stall-at", type=int, default=None, help="inject a stall before this chunk (test I-3)")
    parser.add_argument("--stall-seconds", type=float, default=60.0)
    parser.add_argument("--no-align", action="store_true", help="start now instead of the next window boundary")
    parser.add_argument("--dry-run", action="store_true", help="schedule and encode, but send nothing")
    parser.add_argument("--force", action="store_true", help="skip the S1 check (unsupported; LATE_DROP will tell)")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    settings = load()
    if args.speedup is not None:
        settings = replace(settings, speedup=args.speedup)
    if args.no_align:
        settings = replace(settings, align_start=False)
    problems = settings.problems()
    if problems:
        print("Refusing to start, configuration invalid:\n  " + "\n  ".join(problems))
        return 2

    pairs = dict(DEMO_LECTURES) if args.demo else {}
    for spec in args.lecture:
        item_id, _, video_id = spec.partition("=")
        pairs[item_id] = video_id or item_id
    if not pairs:
        print("Nothing to play: use --demo or --lecture ITEM_ID=VIDEO_ID")
        return 2
    items = manifest()
    lectures = [Lecture(item_id, video_id, items[item_id]["display_name"], ROOT / "data" / items[item_id]["media_file"],
                        partition_for(video_id, settings.partitions)) for item_id, video_id in pairs.items()]

    now_ms = int(time.time() * 1000)
    conflicts = s1_conflicts({lec.video_id: lec.partition for lec in lectures}, active_lectures(now_ms))
    if conflicts and not args.force:
        print("Refusing to start (S1):\n  " + "\n  ".join(conflicts))
        return 2

    session_start = aligned_session_start(now_ms, settings.window_seconds, settings.align_start)
    clock = (int(time.time() * 1000), time.monotonic())
    print(f"session_start = {session_start} (in {(session_start - now_ms) / 1000:.1f} s), "
          f"chunk {settings.chunk_seconds:g} s / wall {settings.chunk_wall_ms} ms")
    for lec in lectures:
        print(f"  {lec.title:34s} -> video_id {lec.video_id:24s} partition {lec.partition}")

    stop, failures = threading.Event(), []
    threads = [threading.Thread(target=run_lecture, name=lec.video_id,
                                args=(lec, settings, session_start, clock, args, stop, failures), daemon=True)
               for lec in lectures]
    for thread in threads:
        thread.start()
    try:
        while any(t.is_alive() for t in threads):
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("Stopping: lectures marked aborted (send tools/send_flush.py to close their last window)")
        stop.set()
        for thread in threads:
            thread.join(timeout=10)
        return 130
    return EXIT_PRODUCE_FAILED if failures else 0


if __name__ == "__main__":
    sys.exit(main())
