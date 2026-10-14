"""Read-only tap on any topic (replaces consumer/consumer.py; fixes D6).

Uses assign() with NO consumer group and never commits, so it can't steal
partitions or offsets from the pipeline. Audio payloads are shortened.

    .venv\\Scripts\\python -m tools.tap video_audio                 # follow new records
    .venv\\Scripts\\python -m tools.tap final_notes --from-beginning
    .venv\\Scripts\\python -m tools.tap window_summaries --from-beginning --count
    .venv\\Scripts\\python -m tools.tap alerts --read-uncommitted   # compare with the default read_committed
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter

from kafka import KafkaConsumer, TopicPartition

from common.config import load


def shorten(raw: bytes | None) -> str:
    if raw is None:
        return "<null>"
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return f"<{len(raw)} bytes, not JSON> {raw[:80]!r}"
    if isinstance(payload, dict) and "audio_b64" in payload:
        payload["audio_b64"] = f"<{len(payload['audio_b64'])} base64 chars>"
    return json.dumps(payload, ensure_ascii=False)[:600]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("topic")
    parser.add_argument("--from-beginning", action="store_true")
    parser.add_argument("--count", action="store_true", help="count records per partition and key, then exit")
    parser.add_argument("--read-uncommitted", action="store_true")
    parser.add_argument("--idle-seconds", type=float, default=5.0, help="--count stops after this long without data")
    args = parser.parse_args(argv)

    settings = load()
    consumer = KafkaConsumer(bootstrap_servers=settings.kafka_bootstrap, group_id=None, enable_auto_commit=False,
                             isolation_level="read_uncommitted" if args.read_uncommitted else "read_committed")
    partitions = consumer.partitions_for_topic(args.topic)
    if not partitions:
        print(f"topic {args.topic!r} not found")
        return 1
    tps = [TopicPartition(args.topic, p) for p in sorted(partitions)]
    consumer.assign(tps)
    if args.from_beginning or args.count:
        consumer.seek_to_beginning(*tps)
    else:
        consumer.seek_to_end(*tps)

    by_partition, by_key = Counter(), Counter()
    last_data = time.time()
    try:
        while True:
            batches = consumer.poll(timeout_ms=500)
            for batch in batches.values():
                for r in batch:
                    last_data = time.time()
                    key = r.key.decode("utf-8", "replace") if r.key else None
                    if args.count:
                        by_partition[r.partition] += 1
                        by_key[key] += 1
                    else:
                        print(f"p{r.partition} off={r.offset} key={key} {shorten(r.value)}", flush=True)
            if args.count and time.time() - last_data > args.idle_seconds:
                break
    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()
    if args.count:
        print(f"{args.topic}: {sum(by_partition.values())} records")
        print("  per partition:", dict(sorted(by_partition.items())))
        print("  per key:      ", dict(sorted(by_key.items(), key=lambda kv: str(kv[0]))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
