"""Replay recorded transcripts into `transcriptions`, re-stamped to now (PLAN M5; ARCHITECTURE §6.2).

Plays lectures WITHOUT audio or Whisper, straight into the Streams input, on the same schedule as
producer/lecture_source.py: aligned session_start, scheduled event times, the A5 flush, the S1
partition check and run/lectures state files (so bench/verify_run.py works on the result).
Every timestamp is fresh: injecting OLD timestamps into a running pipeline is forbidden (§6.2).

Text source per lecture (--source auto picks the first available):
  whisper   bench/results/chunks_base.en-reppen_<item>_<N>s.jsonl  (real M2 Whisper output, real asr_score)
  captions  data/raw/<item>/*.srt  (captions grouped per chunk; asr_score is null, so no LOW_ASR_SCORE)

    .venv\\Scripts\\python -m tools.replay_fixtures --demo --limit-seconds 300
    .venv\\Scripts\\python -m tools.replay_fixtures --lecture ocw6001_l01=python_l1 --speedup 4
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

from common import schemas
from common.config import DEMO_LECTURES, ROOT, TOPIC_TRANSCRIPTS, load
from common.kafka_utils import EXIT_PRODUCE_FAILED, ProduceFailed, make_producer, send_and_wait
from common.partitioning import partition_for
from producer.lecture_source import (active_lectures, aligned_session_start, chunk_event_ts, chunk_send_at,
                                     flush_event_ts, flush_send_at, manifest, s1_conflicts, wait_until, write_state)

SIMULATED_TRANSCRIBE_MS = 1500     # a transcript appears ~1.5 s after its chunk was captured (as in M3/M4 runs)


def whisper_chunks(item_id: str, chunk_s: float) -> list[dict] | None:
    path = ROOT / "bench" / "results" / f"chunks_base.en-reppen_{item_id}_{int(chunk_s)}s.jsonl"
    if not path.exists():
        return None
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return [{"text": r["text"], "asr_score": r["asr_score"], "avg_logprob": r["avg_logprob"],
             "no_speech_prob": r["no_speech_prob"], "compression_ratio": r["compression_ratio"]} for r in rows]


def caption_chunks(item: dict, chunk_s: float) -> list[dict]:
    sys.path.insert(0, str(ROOT / "analysis"))
    from dataset_eda import parse_srt   # noqa: E402 - analysis/ is not a package
    cues = parse_srt(ROOT / "data" / item["transcript_file"])
    n = math.ceil(float(item["duration_s"]) / chunk_s)
    texts = [[] for _ in range(n)]
    for cue in cues:
        if cue.text and not cue.boilerplate:
            index = min(n - 1, int(((cue.start + cue.end) / 2) // chunk_s))
            texts[index].append(cue.text)
    return [{"text": " ".join(t), "asr_score": None, "avg_logprob": None, "no_speech_prob": None,
             "compression_ratio": None} for t in texts]


def play(item_id: str, video_id: str, title: str, chunks: list[dict], source: str, settings, session_start: int,
         clock: tuple[int, float], producer, stop: threading.Event, failures: list) -> None:
    wall0_ms, mono0 = clock
    chunk_wall, chunk_s = settings.chunk_wall_ms, settings.chunk_seconds
    partition = partition_for(video_id, settings.partitions)
    write_state(video_id, item_id=item_id, partition=partition, status="active", session_start=session_start,
                chunk_wall_ms=chunk_wall, last_chunk_sent=-1, chunks=len(chunks), window_s=settings.window_seconds,
                grace_s=settings.grace_seconds, flush_formula=settings.flush_formula, replay_source=source)
    try:
        for chunk_id, c in enumerate(chunks):
            due = chunk_send_at(session_start, chunk_id, chunk_wall) + SIMULATED_TRANSCRIBE_MS
            wait_until(due, wall0_ms, mono0, stop)
            if stop.is_set():
                write_state(video_id, status="aborted")
                return
            t = {"schema": "transcript.v1", "type": "chunk", "video_id": video_id, "session_start": session_start,
                 "chunk_id": chunk_id, "start_time": round(chunk_id * chunk_s, 3),
                 "end_time": round((chunk_id + 1) * chunk_s, 3),
                 "event_ts": chunk_event_ts(session_start, chunk_id, chunk_wall), **c, "retried": False,
                 "model": f"replay:{source}", "worker_id": "replay", "src_partition": partition,
                 "src_offset": chunk_id, "transcribed_ts": int(time.time() * 1000), "proc_ms": 0.0}
            if chunk_id == 0:
                t["title"] = title
            send_and_wait(producer, TOPIC_TRANSCRIPTS, schemas.encode("transcript.v1", t), key=video_id,
                          partition=partition)
            write_state(video_id, last_chunk_sent=chunk_id)
        last = len(chunks) - 1
        args = (session_start, last, chunk_wall, settings.window_seconds, settings.grace_seconds, settings.flush_formula)
        wait_until(flush_send_at(*args), wall0_ms, mono0, stop)
        if stop.is_set():
            write_state(video_id, status="aborted")
            return
        flush = {"schema": "transcript.v1", "type": "flush", "video_id": video_id, "session_start": session_start,
                 "last_chunk_id": last, "event_ts": flush_event_ts(*args)}
        send_and_wait(producer, TOPIC_TRANSCRIPTS, schemas.encode("transcript.v1", flush), key=video_id,
                      partition=partition)
        write_state(video_id, status="flushed", flush_event_ts=flush["event_ts"])
        print(f"[{video_id}] replayed {len(chunks)} chunks ({source}) and flushed", flush=True)
    except ProduceFailed as exc:
        write_state(video_id, status="aborted", error=str(exc))
        failures.append(exc)
        stop.set()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--lecture", action="append", default=[], metavar="ITEM_ID=VIDEO_ID")
    parser.add_argument("--limit-seconds", type=float, default=None)
    parser.add_argument("--speedup", type=float, default=None)
    parser.add_argument("--source", choices=["auto", "whisper", "captions"], default="auto")
    parser.add_argument("--no-align", action="store_true")
    args = parser.parse_args(argv)

    settings = load()
    if args.speedup is not None:
        settings = replace(settings, speedup=args.speedup)
    if args.no_align:
        settings = replace(settings, align_start=False)
    if settings.problems():
        print("Refusing to start, configuration invalid:\n  " + "\n  ".join(settings.problems()))
        return 2
    pairs = dict(DEMO_LECTURES) if args.demo else {}
    for spec in args.lecture:
        item_id, _, video_id = spec.partition("=")
        pairs[item_id] = video_id or item_id
    if not pairs:
        print("Nothing to replay: use --demo or --lecture ITEM_ID=VIDEO_ID")
        return 2

    items = manifest()
    plan = []
    for item_id, video_id in pairs.items():
        chunks, source = None, args.source
        if source in ("auto", "whisper"):
            chunks, source = whisper_chunks(item_id, settings.chunk_seconds), "whisper"
            if chunks is None and args.source == "whisper":
                print(f"no Whisper results for {item_id} at {settings.chunk_seconds:g} s chunks")
                return 2
        if chunks is None:
            chunks, source = caption_chunks(items[item_id], settings.chunk_seconds), "captions"
        if args.limit_seconds:
            chunks = chunks[: math.ceil(args.limit_seconds / settings.chunk_seconds)]
        plan.append((item_id, video_id, items[item_id]["display_name"], chunks, source))

    now_ms = int(time.time() * 1000)
    conflicts = s1_conflicts({vid: partition_for(vid, settings.partitions) for _, vid, *_ in plan}, active_lectures(now_ms))
    if conflicts:
        print("Refusing to start (S1):\n  " + "\n  ".join(conflicts))
        return 2
    session_start = aligned_session_start(now_ms, settings.window_seconds, settings.align_start)
    print(f"session_start = {session_start} (in {(session_start - now_ms) / 1000:.1f} s); "
          f"chunk wall {settings.chunk_wall_ms} ms; flush {settings.flush_formula}")
    for item_id, video_id, title, chunks, source in plan:
        print(f"  {title:34s} -> {video_id:24s} p{partition_for(video_id, settings.partitions)}  "
              f"{len(chunks)} chunks from {source}")

    producer = make_producer(settings, client_id="replay-fixtures")
    clock = (int(time.time() * 1000), time.monotonic())
    stop, failures = threading.Event(), []
    threads = [threading.Thread(target=play, args=(*p, settings, session_start, clock, producer, stop, failures),
                                daemon=True) for p in plan]
    for t in threads:
        t.start()
    try:
        while any(t.is_alive() for t in threads):
            time.sleep(0.5)
    except KeyboardInterrupt:
        stop.set()
        return 130
    finally:
        producer.close(timeout=5)
    return EXIT_PRODUCE_FAILED if failures else 0


if __name__ == "__main__":
    sys.exit(main())
