"""Verify a finished pipeline run against the foundation's guarantees (Tier-1 I-1; reusable for I-2/I-3).

Reads every topic from the beginning (no consumer group, read_committed), validates every record
against the shared JSON Schemas, and checks, per lecture played (run/lectures/*.json):
  * completeness   - the windows' chunk_ids cover 0..last_chunk_id exactly once
  * emit-once      - no (video_id, window_start, revision) appears twice in window_summaries
  * never early    - every window was emitted at or after window_end + GRACE (wall clock)
  * own flush      - the lecture's last window was emitted only after its own flush was due
  * notes          - one final_notes record per window
  * no late drops  - zero LATE_DROP alerts; DLQ empty unless --expect-dlq N
Exit code 0 only if every check passes. Results: bench/results/verify_<label>.json

    .venv\\Scripts\\python -m bench.verify_run --label m4_i1
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict

from kafka import KafkaConsumer, TopicPartition

from common import schemas
from common.config import (ROOT, RUN_DIR, TOPIC_ALERTS, TOPIC_DLQ, TOPIC_NOTES, TOPIC_TRANSCRIPTS, TOPIC_WINDOWS,
                           load)

SCHEMA_OF = {TOPIC_TRANSCRIPTS: "transcript.v1", TOPIC_WINDOWS: "window.v1", TOPIC_NOTES: "notes.v1",
             TOPIC_ALERTS: "alert.v1", TOPIC_DLQ: "dlq.v1"}


def read_topic(bootstrap: str, topic: str) -> list:
    consumer = KafkaConsumer(bootstrap_servers=bootstrap, group_id=None, enable_auto_commit=False,
                             isolation_level="read_committed", consumer_timeout_ms=4000)
    tps = [TopicPartition(topic, p) for p in sorted(consumer.partitions_for_topic(topic) or [])]
    consumer.assign(tps)
    consumer.seek_to_beginning(*tps)
    records = list(consumer)
    consumer.close()
    return records


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", default="run")
    parser.add_argument("--expect-dlq", type=int, default=0)
    args = parser.parse_args(argv)
    settings = load()
    grace_ms = settings.grace_seconds * 1000
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append((name, ok, detail))
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")

    payloads, invalid = defaultdict(list), []
    for topic, schema_name in SCHEMA_OF.items():
        for record in read_topic(settings.kafka_bootstrap, topic):
            try:
                payloads[topic].append(schemas.decode(record.value, schema_name))
            except schemas.ContractError as exc:
                invalid.append(f"{topic} p{record.partition} off={record.offset}: {exc}")
    check("all records match the JSON Schemas", not invalid,
          f"{sum(len(v) for v in payloads.values())} records" + (f"; invalid: {invalid[:3]}" if invalid else ""))

    lectures = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((RUN_DIR / "lectures").glob("*.json"))]
    windows_by_video = defaultdict(list)
    for w in payloads[TOPIC_WINDOWS]:
        windows_by_video[w["video_id"]].append(w)
    notes_keys = Counter((n["video_id"], n["window_start"], n["revision"]) for n in payloads[TOPIC_NOTES])
    flushes = Counter(t["video_id"] for t in payloads[TOPIC_TRANSCRIPTS] if t["type"] == "flush")

    summary = {}
    for lec in lectures:
        vid, last = lec["video_id"], lec["last_chunk_sent"]
        ws = sorted(windows_by_video.get(vid, []), key=lambda w: w["window_start"])
        keys = Counter((w["video_id"], w["window_start"], w["revision"]) for w in ws)
        chunk_ids = [c for w in ws for c in w["chunk_ids"]]
        early = [w["window_start"] for w in ws if w["emitted_ts"] < w["window_end"] + grace_ms]
        last_window = ws[-1] if ws else None
        flush_ts = lec.get("flush_event_ts")
        summary[vid] = {"partition": lec["partition"], "chunks_sent": last + 1, "windows": len(ws),
                        "last_window_emitted_after_flush_ms": (last_window["emitted_ts"] - flush_ts)
                        if last_window and flush_ts else None}
        check(f"{vid}: flush forwarded once", flushes[vid] == 1, f"{flushes[vid]} flush record(s) in transcriptions")
        check(f"{vid}: complete", sorted(chunk_ids) == list(range(last + 1)),
              f"{len(set(chunk_ids))}/{last + 1} chunks across {len(ws)} windows")
        check(f"{vid}: each window emitted once", all(n == 1 for n in keys.values()),
              f"{len(keys)} distinct windows, {len(ws)} records")
        check(f"{vid}: never emitted before end + grace", not early,
              "all on time" if not early else f"early windows {early}")
        check(f"{vid}: last window closed by its own flush",
              bool(last_window and flush_ts and last_window["emitted_ts"] >= flush_ts),
              f"emitted {summary[vid]['last_window_emitted_after_flush_ms']} ms after the flush's event time")
        check(f"{vid}: one note per window", all(notes_keys[k] >= 1 for k in keys) and len(keys) > 0,
              f"{sum(1 for k in keys if notes_keys[k])}/{len(keys)} windows have notes")

    late = [a for a in payloads[TOPIC_ALERTS] if a["type"] == "LATE_DROP"]
    check("no LATE_DROP alerts", not late, f"{len(late)} LATE_DROP")
    check("DLQ as expected", len(payloads[TOPIC_DLQ]) == args.expect_dlq,
          f"{len(payloads[TOPIC_DLQ])} DLQ record(s), expected {args.expect_dlq}")
    alert_types = Counter(a["type"] for a in payloads[TOPIC_ALERTS])
    print(f"alerts by type: {dict(alert_types)}")

    out = ROOT / "bench" / "results" / f"verify_{args.label}.json"
    out.write_text(json.dumps({"checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks],
                               "lectures": summary, "alerts_by_type": alert_types,
                               "counts": {t: len(v) for t, v in payloads.items()}}, indent=2), encoding="utf-8")
    failed = sum(not ok for _, ok, _ in checks)
    print(f"{len(checks) - failed}/{len(checks)} checks passed -> {out.relative_to(ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
