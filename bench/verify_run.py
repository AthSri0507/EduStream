"""Verify a finished pipeline run against the foundation's guarantees (Tier-1 I-1; reusable for I-2/I-3).

Reads every topic from the beginning (no consumer group, read_committed), validates every record
against the shared JSON Schemas, and checks, per lecture played (run/lectures/*.json):
  * completeness   - the windows' chunk_ids cover 0..last_chunk_id exactly once
  * emit-once      - no (video_id, window_start, revision) appears twice in window_summaries
  * never early    - every window was emitted at or after window_end + GRACE (wall clock)
  * own flush      - the lecture's last window was emitted only after its own flush was due
  * notebook       - NOTEBOOK_DESIGN §11: one notes.v3 live update per 90 s block, each exactly once, every
                     window in exactly one update; consolidation.v1 passes numbered 0..n-1 once each, back to
                     back from 00:00, exactly one final pass, reaching the end of the live notes, topics numbered
                     1..N (the notebook itself is saved for comparisons)
  * no late drops  - zero LATE_DROP alerts; DLQ empty unless --expect-dlq N
  * --db           - SQLite (written by db-sink) holds exactly the distinct chunks, windows, notes and
                     alerts found in the topics, with matching content (end-to-end to storage)
Exit code 0 only if every check passes. Results: bench/results/verify_<label>.json

    .venv\\Scripts\\python -m bench.verify_run --label m4_i1
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict

from kafka import KafkaConsumer, TopicPartition

from agents.study_notes import text_of
from common import schemas
from common.config import (ROOT, RUN_DIR, TOPIC_ALERTS, TOPIC_DLQ, TOPIC_NOTES, TOPIC_TRANSCRIPTS, TOPIC_USER_NOTES,
                           TOPIC_WINDOWS, load)

SCHEMA_OF = {TOPIC_TRANSCRIPTS: "transcript.v1", TOPIC_WINDOWS: "window.v1", TOPIC_NOTES: None,
             TOPIC_USER_NOTES: "addition.v1", TOPIC_ALERTS: "alert.v1", TOPIC_DLQ: "dlq.v1"}


def notes_schema(value: bytes) -> str:
    """final_notes carries live updates and consolidation passes: validate each against its own schema."""
    return "consolidation.v1" if b'"consolidation.v1"' in (value or b"")[:200] else "notes.v3"


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
    parser.add_argument("--db", action="store_true", help="also check data/edustream.db against the topics")
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
                payloads[topic].append(schemas.decode(record.value, schema_name or notes_schema(record.value)))
            except schemas.ContractError as exc:
                invalid.append(f"{topic} p{record.partition} off={record.offset}: {exc}")
    check("all records match the JSON Schemas", not invalid,
          f"{sum(len(v) for v in payloads.values())} records" + (f"; invalid: {invalid[:3]}" if invalid else ""))

    lectures = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((RUN_DIR / "lectures").glob("*.json"))]
    windows_by_video = defaultdict(list)
    for w in payloads[TOPIC_WINDOWS]:
        windows_by_video[w["video_id"]].append(w)
    updates_by_video, passes_by_video = defaultdict(list), defaultdict(list)
    for u in payloads[TOPIC_NOTES]:
        (passes_by_video if u["schema"] == "consolidation.v1" else updates_by_video)[u["video_id"]].append(u)
    notebooks = {}
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
        ups = sorted(updates_by_video.get(vid, []), key=lambda u: u["update_index"])
        expected = set(range(math.ceil((last + 1) * settings.chunk_seconds / settings.note_update_s)))
        counts = Counter(u["update_index"] for u in ups)
        check(f"{vid}: one notebook update per {settings.note_update_s} s block, each once",
              set(counts) == expected and all(n == 1 for n in counts.values()),
              f"{len(counts)}/{len(expected)} updates, {len(ups)} records")
        in_updates = Counter(ws_ for u in ups for ws_ in u["window_starts"])
        check(f"{vid}: every window in exactly one update",
              set(in_updates) == {w["window_start"] for w in ws} and all(n == 1 for n in in_updates.values()),
              f"{len(in_updates)} windows in updates, {len(ws)} windows emitted")
        passes = sorted(passes_by_video.get(vid, []), key=lambda q: q["pass_index"])
        once = Counter(q["pass_index"] for q in passes)
        check(f"{vid}: consolidation passes 0..n-1, each once, back to back",
              sorted(once) == list(range(len(once))) and all(n == 1 for n in once.values()) and bool(passes)
              and passes[0]["media_start"] == 0
              and all(a["media_end"] == b["media_start"] for a, b in zip(passes, passes[1:])),
              f"{len(once)} passes, {len(passes)} records: "
              + ", ".join(f"{q['media_start']:.0f}-{q['media_end']:.0f} {q['generator']}" for q in passes))
        finals = [q for q in passes if q["final"]]
        reach = max((u["media_end"] for u in ups), default=0.0)
        check(f"{vid}: finished once, by the last pass, covering all live notes",
              len(finals) == 1 and finals[0] is passes[-1] and finals[0]["media_end"] >= reach,
              f"{len(finals)} final pass(es); notes reach {reach:.0f} s, last cut "
              f"{passes[-1]['media_end'] if passes else 0:.0f} s")
        new = [t["n"] for q in passes for t in q["topics"] if t["new"]]
        check(f"{vid}: topics numbered 1..N", new == list(range(1, len(new) + 1)), f"{len(new)} topics")
        summary[vid]["updates"] = dict(Counter(u["generator"] for u in ups))
        summary[vid]["passes"] = dict(Counter(q["generator"] for q in passes))
        topics: dict = {}
        for q in passes:
            for t in q["topics"]:
                topics.setdefault(t["n"], {"title": t["title"], "elements": [], "question": None})
                topics[t["n"]]["question"] = topics[t["n"]]["question"] or t["question"]
                topics[t["n"]]["end"] = t["media_end"]
            for el in q["elements"]:
                topics[el["topic"]]["elements"].append([el["kind"], el["t"], text_of(el)])
        notebooks[vid] = {"topics": topics, "live": [{"update": u["update_index"], "generator": u["generator"],
                                                      "elements": [[e["id"], e["extends"], text_of(e)]
                                                                   for e in u["elements"]]} for u in ups]}

    late = [a for a in payloads[TOPIC_ALERTS] if a["type"] == "LATE_DROP"]
    check("no LATE_DROP alerts", not late, f"{len(late)} LATE_DROP")
    check("DLQ as expected", len(payloads[TOPIC_DLQ]) == args.expect_dlq,
          f"{len(payloads[TOPIC_DLQ])} DLQ record(s), expected {args.expect_dlq}")
    if args.db:
        from storage.db import connect_readonly
        db = connect_readonly()
        chunk_keys = {(t["video_id"], t["chunk_id"], t["model"]) for t in payloads[TOPIC_TRANSCRIPTS] if t["type"] == "chunk"}
        db_chunks = {tuple(r) for r in db.execute("SELECT video_id, chunk_id, model FROM chunks")}
        check("db: chunks == distinct transcripts", db_chunks == chunk_keys, f"{len(db_chunks)} in SQLite, {len(chunk_keys)} in Kafka")
        topic_windows = {(w["video_id"], w["window_start"], w["revision"]): (json.dumps(w["chunk_ids"]), w["transcript"])
                         for w in payloads[TOPIC_WINDOWS]}
        db_windows = {(r[0], r[1], r[2]): (r[3], r[4]) for r in
                      db.execute("SELECT video_id, window_start, revision, chunk_ids, transcript FROM window_stats")}
        check("db: windows == topic windows (keys and content)", db_windows == topic_windows,
              f"{len(db_windows)} in SQLite, {len(topic_windows)} distinct in Kafka")
        first, first_pass = {}, {}
        for u in payloads[TOPIC_NOTES]:                               # first writer wins, as in the sink
            if u["schema"] == "notes.v3":
                first.setdefault((u["video_id"], u["update_index"]), u)
            else:
                first_pass.setdefault((u["video_id"], u["pass_index"]), u)
        db_updates = {tuple(r) for r in db.execute("SELECT video_id, update_index FROM live_updates")}
        n_drafts = db.execute("SELECT COUNT(*) FROM drafts").fetchone()[0]
        check("db: live updates == topic updates, with all their drafts",
              db_updates == set(first) and n_drafts == sum(len(u["elements"]) for u in first.values()),
              f"{len(db_updates)} updates and {n_drafts} drafts in SQLite, {len(first)} distinct updates in Kafka")
        db_passes = {tuple(r) for r in db.execute("SELECT video_id, pass_index FROM passes")}
        n_elements = db.execute("SELECT COUNT(*) FROM elements").fetchone()[0]
        n_topics = db.execute("SELECT COUNT(*) FROM topics").fetchone()[0]
        check("db: passes == topic passes, with all their topics and elements",
              db_passes == set(first_pass) and n_elements == sum(len(q["elements"]) for q in first_pass.values())
              and n_topics == sum(t["new"] for q in first_pass.values() for t in q["topics"]),
              f"{len(db_passes)} passes, {n_topics} topics, {n_elements} elements in SQLite")
        left = db.execute("SELECT COUNT(*) FROM notebook_fts WHERE kind = 'draft'").fetchone()[0]
        check("db: no draft left in the search index of a finished lecture", left == 0, f"{left} draft rows")
        topic_alerts = {a["alert_id"] for a in payloads[TOPIC_ALERTS]}
        db_alerts = {r[0] for r in db.execute("SELECT alert_id FROM alerts")}
        check("db: alerts == distinct topic alerts", db_alerts == topic_alerts, f"{len(db_alerts)} in SQLite")
        db.close()

    alert_types = Counter(a["type"] for a in payloads[TOPIC_ALERTS])
    print(f"alerts by type: {dict(alert_types)}")

    out = ROOT / "bench" / "results" / f"verify_{args.label}.json"
    out.write_text(json.dumps({"checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks],
                               "lectures": summary, "notebooks": notebooks, "alerts_by_type": alert_types,
                               "counts": {t: len(v) for t, v in payloads.items()}}, indent=2), encoding="utf-8")
    failed = sum(not ok for _, ok, _ in checks)
    print(f"{len(checks) - failed}/{len(checks)} checks passed -> {out.relative_to(ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
