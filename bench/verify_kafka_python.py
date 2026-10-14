"""M2 check 1 (+2, +E1 precondition): does kafka-python 3.0.11 behave as the design assumes?

Runs against the single local broker (infra/kafka/single.properties) and checks:
  K1  admin client creates a 3-partition topic
  K2  idempotent producer with acks=all, delivery callbacks, keyed partitioning
  K3  murmur2 partition for each key == partition the broker actually stored it in
  K4  consumer with max_poll_records=1, read_committed, explicit OffsetAndMetadata commit
  K5  hazard check: a bare commit() after poll() commits records that were never processed
  K6  admin reads group offsets, group membership and end offsets (lag)
  K7  transactions: aborted records are hidden from read_committed, visible to read_uncommitted
  K8  message sizes: 5 s / 10 s / 15 s audio chunks fit, a 1.2 MB message is rejected
  K9  Windows crash guard: 1970 and far-future timestamps are rejected; the broker stays up
  K10 what a producer does after one rejected record (idempotent vs not)

Topics get a unique suffix per run and are never deleted (deleting topics on
Windows can crash the broker; scripts/reset.ps1 wipes everything instead).

Usage (broker running on localhost:9092):
    .venv\\Scripts\\python bench\\verify_kafka_python.py
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from kafka import KafkaAdminClient, KafkaConsumer, KafkaProducer, TopicPartition
from kafka.admin import NewTopic
from kafka.partitioner.default import murmur2
from kafka.structs import OffsetAndMetadata

BOOTSTRAP = "localhost:9092"
RUN = uuid.uuid4().hex[:6]
TOPIC = f"m2_check_{RUN}"
TXN_TOPIC = f"m2_txn_{RUN}"
SIZE_TOPIC = f"m2_size_{RUN}"
PARTITIONS = 3
OUT = Path(__file__).resolve().parent / "results"

# Candidate lecture video_ids, plus generic keys, for the partitioner comparison.
KEYS = [
    "python_l1", "python_l2", "algorithms_l1", "algorithms_l2",
    "lecture_01", "lecture_02", "lecture_03", "demo_a", "demo_b", "demo_c",
] + [f"video_{i:02d}" for i in range(10)]

results: dict[str, dict] = {}


def record(check: str, ok: bool, detail) -> None:
    results[check] = {"ok": bool(ok), "detail": detail}
    print(f"[{'PASS' if ok else 'FAIL'}] {check}: {detail}")


def python_partition(key: str, partitions: int) -> int:
    return (murmur2(key.encode("utf-8")) & 0x7FFFFFFF) % partitions


def drain(consumer: KafkaConsumer, seconds: float = 6.0) -> list:
    records, deadline = [], time.time() + seconds
    while time.time() < deadline:
        for batch in consumer.poll(timeout_ms=500).values():
            records.extend(batch)
    return records


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    admin = KafkaAdminClient(bootstrap_servers=BOOTSTRAP, client_id="m2-admin")

    # K1 ------------------------------------------------------------------
    admin.create_topics([NewTopic(t, PARTITIONS, 1) for t in (TOPIC, TXN_TOPIC, SIZE_TOPIC)])
    time.sleep(1)
    described = admin.describe_topics([TOPIC])
    record("K1 create 3-partition topic", len(described[0]["partitions"]) == PARTITIONS,
           f"{TOPIC} has {len(described[0]['partitions'])} partitions")

    # K2 + K3 -------------------------------------------------------------
    acked, errors = {}, []
    producer = KafkaProducer(bootstrap_servers=BOOTSTRAP, acks="all", enable_idempotence=True,
                             retries=5, delivery_timeout_ms=120000, linger_ms=5)
    for key in KEYS:
        future = producer.send(TOPIC, key=key.encode(), value=json.dumps({"key": key}).encode())
        future.add_callback(lambda md, k=key: acked.__setitem__(k, md.partition))
        future.add_errback(lambda exc, k=key: errors.append((k, repr(exc))))
    producer.flush(30)
    record("K2 idempotent producer + callbacks", len(acked) == len(KEYS) and not errors,
           f"{len(acked)}/{len(KEYS)} acknowledged via callback, {len(errors)} errors")

    mismatches = {k: (acked.get(k), python_partition(k, PARTITIONS)) for k in KEYS
                  if acked.get(k) != python_partition(k, PARTITIONS)}
    record("K3 murmur2 == stored partition", not mismatches,
           "all keys match" if not mismatches else mismatches)
    (OUT / "m2_partitions_python.json").write_text(json.dumps(
        {k: acked.get(k) for k in KEYS}, indent=2), encoding="utf-8")

    # K4 ------------------------------------------------------------------
    group = f"m2-group-{RUN}"
    consumer = KafkaConsumer(bootstrap_servers=BOOTSTRAP, group_id=group, enable_auto_commit=False,
                             auto_offset_reset="earliest", max_poll_records=1,
                             isolation_level="read_committed", session_timeout_ms=10000,
                             value_deserializer=None)
    consumer.subscribe([TOPIC])
    first = None
    deadline = time.time() + 15
    while first is None and time.time() < deadline:
        for batch in consumer.poll(timeout_ms=500).values():
            first = batch[0]
    tp = TopicPartition(first.topic, first.partition)
    consumer.commit({tp: OffsetAndMetadata(first.offset + 1, None, -1)})
    committed = consumer.committed(tp)
    raw_bytes = isinstance(first.value, (bytes, bytearray))
    record("K4 max_poll_records=1 + explicit commit", committed == first.offset + 1 and raw_bytes,
           f"processed offset {first.offset} on p{first.partition}, committed={committed}, raw bytes={raw_bytes}")

    # K6 (while the group has a member) -------------------------------------
    # kafka-python 3.x names: list_group_offsets / describe_groups (not the 2.x
    # list_consumer_group_offsets / describe_consumer_groups).
    offsets = admin.list_group_offsets({group: None})[group]
    described_group = admin.describe_groups([group])[group]
    end = consumer.end_offsets([TopicPartition(TOPIC, p) for p in range(PARTITIONS)])
    lag = {tp_.partition: end[tp_] - offsets[tp_].offset for tp_ in offsets}
    members = len(described_group.get("members", []))
    record("K6 admin offsets / members / lag", members == 1 and tp in offsets,
           f"members={members}, state={described_group.get('group_state')}, "
           f"committed partitions={sorted(t.partition for t in offsets)}, lag={lag}")
    consumer.close()

    # K5 ------------------------------------------------------------------
    hazard_group = f"m2-hazard-{RUN}"
    greedy = KafkaConsumer(bootstrap_servers=BOOTSTRAP, group_id=hazard_group, enable_auto_commit=False,
                           auto_offset_reset="earliest", max_poll_records=10)
    greedy.subscribe([TOPIC])
    fetched, deadline = [], time.time() + 15
    while not fetched and time.time() < deadline:
        for batch in greedy.poll(timeout_ms=500).values():
            fetched = batch
    processed = fetched[0]                       # pretend we processed only the first record
    greedy.commit()                              # bare commit
    hazard_tp = TopicPartition(processed.topic, processed.partition)
    over = greedy.committed(hazard_tp) - (processed.offset + 1)
    greedy.close()
    record("K5 bare commit() over-commits", over > 0,
           f"fetched {len(fetched)}, processed 1, bare commit skipped {over} unprocessed record(s) "
           "-> design must commit explicit offsets")

    # K7 ------------------------------------------------------------------
    txn = KafkaProducer(bootstrap_servers=BOOTSTRAP, transactional_id=f"m2-txn-{RUN}",
                        enable_idempotence=True, acks="all")
    txn.init_transactions()
    txn.begin_transaction()
    for i in range(10):
        txn.send(TXN_TOPIC, key=b"k", value=f"aborted-{i}".encode())
    txn.flush()
    txn.abort_transaction()
    txn.begin_transaction()
    for i in range(5):
        txn.send(TXN_TOPIC, key=b"k", value=f"committed-{i}".encode())
    txn.commit_transaction()
    txn.close()

    seen = {}
    for level in ("read_committed", "read_uncommitted"):
        reader = KafkaConsumer(TXN_TOPIC, bootstrap_servers=BOOTSTRAP, auto_offset_reset="earliest",
                               enable_auto_commit=False, isolation_level=level, group_id=None)
        values = [r.value.decode() for r in drain(reader)]
        reader.close()
        seen[level] = (sum(v.startswith("committed") for v in values), sum(v.startswith("aborted") for v in values))
    ok = seen["read_committed"] == (5, 0) and seen["read_uncommitted"] == (5, 10)
    record("K7 aborted txn hidden from read_committed", ok,
           f"read_committed (committed, aborted)={seen['read_committed']}, "
           f"read_uncommitted={seen['read_uncommitted']}")

    # K8 ------------------------------------------------------------------
    sizer = KafkaProducer(bootstrap_servers=BOOTSTRAP, acks="all", enable_idempotence=True)
    outcome = {}
    for label, size in (("5s", 213_736), ("10s", 427_136), ("15s", 640_400), ("1.2MB", 1_200_000)):
        try:
            sizer.send(SIZE_TOPIC, value=b"x" * size).get(timeout=30)
            outcome[label] = "accepted"
        except Exception as exc:  # noqa: BLE001 - we want the exception class in the report
            outcome[label] = f"rejected ({type(exc).__name__})"
    ok = all(outcome[k] == "accepted" for k in ("5s", "10s", "15s")) and outcome["1.2MB"].startswith("rejected")
    record("K8 audio chunk message sizes", ok, outcome)

    # K9 ------------------------------------------------------------------
    # Windows crash guard (infra/kafka/single.properties): stale or far-future
    # timestamps must be rejected instead of triggering an immediate segment delete.
    sizer.close()

    def send_with(producer: KafkaProducer, ts: int) -> str:
        try:
            producer.send(SIZE_TOPIC, value=b"ts-check", timestamp_ms=ts).get(timeout=30)
            return "accepted"
        except Exception as exc:  # noqa: BLE001
            return f"rejected ({type(exc).__name__})"

    stamps = {}
    for label, ts in (("1970", 1_000), ("2h-future", int(time.time() * 1000) + 7_200_000),
                      ("now", int(time.time() * 1000))):
        fresh = KafkaProducer(bootstrap_servers=BOOTSTRAP, acks="all", enable_idempotence=True)
        stamps[label] = send_with(fresh, ts)
        fresh.close()
    alive = SIZE_TOPIC in admin.list_topics()
    ok = stamps["1970"].startswith("rejected") and stamps["2h-future"].startswith("rejected") \
        and stamps["now"] == "accepted" and alive
    record("K9 stale/future timestamps rejected, broker stays up", ok, {**stamps, "broker_alive": alive})

    # K10 -----------------------------------------------------------------
    # Documents a kafka-python behaviour the error policy relies on: after one rejected
    # record, an IDEMPOTENT producer also rejects later valid records, so the process must
    # exit and restart (ARCHITECTURE §6.3), not keep using the producer.
    after = {}
    for idempotent in (True, False):
        p = KafkaProducer(bootstrap_servers=BOOTSTRAP, acks="all", enable_idempotence=idempotent)
        send_with(p, 1_000)
        after["idempotent" if idempotent else "non_idempotent"] = send_with(p, int(time.time() * 1000))
        p.close()
    record("K10 producer state after a rejected record", after["non_idempotent"] == "accepted",
           f"next valid send: {after} -> on produce failure exit and restart with a fresh producer")

    producer.close()
    admin.close()
    passed = sum(r["ok"] for r in results.values())
    (OUT / "m2_kafka_python.json").write_text(json.dumps(
        {"run": RUN, "kafka_python": __import__("kafka").__version__, "results": results}, indent=2), encoding="utf-8")
    print(f"\n{passed}/{len(results)} checks passed. Results in bench/results/m2_kafka_python.json")


if __name__ == "__main__":
    main()
