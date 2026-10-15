"""Transcription worker: video_audio -> Whisper -> transcriptions (docs/ARCHITECTURE.md §6.3, A4, A13).

One member of consumer group `transcription-workers`; run several for parallelism
(one per partition at most). For each record:
  1. parse + validate audio_chunk.v1   (invalid -> DLQ, commit, continue)
  2. transcribe with the A13 rule      (2 retries on exception, then DLQ)
  3. send transcript.v1 to the SAME partition number, key = video_id, and wait
  4. commit exactly offset + 1         (explicit offset; never a bare commit())
A produce failure exits with code 3; scripts/run_component.ps1 restarts the worker
with a fresh producer, and it re-reads from the last commit (<= 1 duplicate).

Flush records are forwarded to the same partition (default since M4: the Streams app
uses them to close a lecture's last window, A5). FORWARD_FLUSH=false turns that off.

    set WORKER_ID=w1 && .venv\\Scripts\\python -m summarizer.transcription.transcription_worker
"""

from __future__ import annotations

import base64
import sys
import time

import numpy as np

from common import schemas
from common.config import GROUP_WORKERS, TOPIC_AUDIO, TOPIC_TRANSCRIPTS, load
from common.kafka_utils import (EXIT_PRODUCE_FAILED, ProduceFailed, commit_record, make_consumer, make_producer,
                                poll_one, send_and_wait, send_to_dlq)
from common.log import JsonLog
from summarizer.transcription import asr

PROCESSING_RETRIES = 2


def pcm_to_float(audio_b64: str) -> np.ndarray:
    pcm = np.frombuffer(base64.b64decode(audio_b64, validate=True), dtype="<i2")
    return pcm.astype(np.float32) / 32768.0


def handle(record, model, producer, settings, log) -> None:
    """Process one record completely (including its DLQ path). Raises ProduceFailed on delivery failure."""
    try:
        event = schemas.decode(record.value, "audio_chunk.v1")
    except schemas.ContractError as exc:
        send_to_dlq(producer, "worker", record, str(exc), log=log)
        return

    if event["type"] == "flush":
        if settings.forward_flush:
            flush = {"schema": "transcript.v1", "type": "flush", "video_id": event["video_id"],
                     "session_start": event["session_start"], "last_chunk_id": event["last_chunk_id"],
                     "event_ts": event["event_ts"]}
            send_and_wait(producer, TOPIC_TRANSCRIPTS, schemas.encode("transcript.v1", flush),
                          key=event["video_id"], partition=record.partition)
            log.info("flush_forwarded", video_id=event["video_id"], partition=record.partition)
        else:
            log.info("flush_not_forwarded", video_id=event["video_id"], reason="FORWARD_FLUSH=false")
        return

    try:
        audio = pcm_to_float(event["audio_b64"])
    except ValueError as exc:      # includes binascii.Error from strict base64 decoding
        send_to_dlq(producer, "worker", record, f"bad audio_b64: {exc}", log=log)
        return
    if audio.size == 0:
        send_to_dlq(producer, "worker", record, "empty audio", log=log)
        return

    started = time.perf_counter()
    for attempt in range(1, PROCESSING_RETRIES + 2):
        try:
            result = asr.transcribe(model, audio)
            break
        except Exception as exc:  # noqa: BLE001 - processing error class (ARCHITECTURE §10b)
            log.warn("transcribe_failed", attempt=attempt, error=repr(exc))
            if attempt > PROCESSING_RETRIES:
                send_to_dlq(producer, "worker", record, f"transcription failed: {exc!r}", attempts=attempt, log=log)
                return
            time.sleep(attempt)
    proc_ms = (time.perf_counter() - started) * 1000

    transcript = {
        "schema": "transcript.v1", "type": "chunk", "video_id": event["video_id"],
        "session_start": event["session_start"], "chunk_id": event["chunk_id"],
        "start_time": event["start_time"], "end_time": event["end_time"], "event_ts": event["event_ts"],
        **result, "model": settings.whisper_model, "worker_id": settings.worker_id,
        "src_partition": record.partition, "src_offset": record.offset,
        "transcribed_ts": int(time.time() * 1000), "proc_ms": round(proc_ms, 1),
    }
    if "title" in event:                      # display name, carried on a lecture's first chunk
        transcript["title"] = event["title"]
    send_and_wait(producer, TOPIC_TRANSCRIPTS, schemas.encode("transcript.v1", transcript),
                  key=event["video_id"], partition=record.partition)       # A4: same partition number
    log.info("transcribed", video_id=event["video_id"], chunk_id=event["chunk_id"], partition=record.partition,
             offset=record.offset, proc_ms=round(proc_ms), retried=result["retried"],
             asr_score=None if result["asr_score"] is None else round(result["asr_score"], 3),
             words=len(result["text"].split()))


def main() -> int:
    settings = load()
    log = JsonLog(f"worker-{settings.worker_id}")
    problems = settings.problems()
    if problems:
        log.error("config_invalid", problems=problems)
        return 2
    log.info("loading_model", model=settings.whisper_model, cpu_threads=settings.whisper_cpu_threads)
    model = asr.load_model(settings.whisper_model, settings.whisper_cpu_threads)
    consumer = make_consumer(settings, GROUP_WORKERS, [TOPIC_AUDIO], client_id=f"worker-{settings.worker_id}")
    producer = make_producer(settings, client_id=f"worker-{settings.worker_id}")
    log.info("started", worker_id=settings.worker_id, group=GROUP_WORKERS)
    try:
        while True:
            record = poll_one(consumer)
            if record is None:
                continue
            handle(record, model, producer, settings, log)
            if not commit_record(consumer, record):
                log.warn("commit_failed_revoked", partition=record.partition, offset=record.offset)
    except ProduceFailed as exc:
        log.error("produce_failed_exiting", error=str(exc))
        producer.close(timeout=0)          # never reuse a failed idempotent producer (M2 K10)
        return EXIT_PRODUCE_FAILED
    except KeyboardInterrupt:
        log.info("stopping")
        return 0
    finally:
        consumer.close()


if __name__ == "__main__":
    sys.exit(main())
