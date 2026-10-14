"""Create the six application topics (ARCHITECTURE §4) and verify their partition counts.

    .venv\\Scripts\\python -m tools.create_topics            # create missing topics, verify all
    .venv\\Scripts\\python -m tools.create_topics --check    # verify only (preflight); exit 1 on mismatch

video_audio and transcriptions MUST have the same partition count (A4: the worker
writes to the partition number it read from). Topics are never deleted here;
scripts/reset.ps1 wipes the broker instead (deleting topics on Windows can crash it).
"""

from __future__ import annotations

import argparse
import sys
import time

from kafka import KafkaAdminClient
from kafka.admin import NewTopic
from kafka.errors import KafkaError, TopicAlreadyExistsError   # 3.x has no NoBrokersAvailable

from common.config import TOPIC_AUDIO, TOPIC_TRANSCRIPTS, load

RETENTION_MS = str(7 * 24 * 3600 * 1000)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    settings = load()
    try:
        admin = KafkaAdminClient(bootstrap_servers=settings.kafka_bootstrap, client_id="create-topics",
                                 request_timeout_ms=10_000)
    except (KafkaError, OSError) as exc:
        print(f"TOPICS: no broker at {settings.kafka_bootstrap} ({type(exc).__name__})")
        return 2

    wanted = settings.topic_partitions
    existing = set(admin.list_topics())
    if not args.check:
        for topic, partitions in wanted.items():
            if topic in existing:
                continue
            try:
                admin.create_topics([NewTopic(topic, partitions, settings.rf,
                                              topic_configs={"retention.ms": RETENTION_MS})])
                print(f"created {topic} ({partitions} partitions, RF {settings.rf})")
            except TopicAlreadyExistsError:
                pass

    # Newly created topics take a moment to appear in metadata: retry for up to 15 s.
    deadline = time.time() + 15
    while True:
        actual = {t["name"]: len(t["partitions"]) for t in admin.describe_topics(list(wanted))
                  if t.get("error_code", 0) == 0 and t.get("partitions")}
        if len(actual) == len(wanted) or args.check or time.time() > deadline:
            break
        time.sleep(1)
    admin.close()
    problems = [f"{topic} missing" for topic in wanted if topic not in actual]
    problems += [f"{topic} has {actual[topic]} partitions, expected {n}" for topic, n in wanted.items()
                 if topic in actual and actual[topic] != n]
    if actual.get(TOPIC_AUDIO) != actual.get(TOPIC_TRANSCRIPTS):
        problems.append(f"{TOPIC_AUDIO} and {TOPIC_TRANSCRIPTS} partition counts differ (A4 invariant)")
    for problem in problems:
        print(f"TOPICS: {problem}")
    if not problems:
        print("TOPICS OK: " + ", ".join(f"{t}={n}" for t, n in actual.items()))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
