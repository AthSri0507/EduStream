"""M2 check 3 (B-1 smoke): does the single broker support the EXISTING Streams app?

Compiles stream_processor/.../StreamProcessor.java against the local Kafka jars,
starts it against localhost:9092, feeds it a few transcript records in the old
schema, and checks:
  S1  the app's consumer group forms (state Stable, >= 1 member)
  S2  Streams creates its internal topics (repartition + changelog) with RF 1
  S3  window output reaches generated_notes
  S4  the broker is still up afterwards (the first run crashed it; see single.properties)
Then stops the app (whole process tree). Results: bench/results/m2_streams_smoke.json

Usage (broker running):
    .venv\\Scripts\\python bench\\smoke_streams_baseline.py
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from kafka import KafkaAdminClient, KafkaConsumer, KafkaProducer
from kafka.admin import NewTopic
from kafka.errors import TopicAlreadyExistsError

ROOT = Path(__file__).resolve().parents[1]
KAFKA_HOME = Path(os.environ.get("KAFKA_HOME", r"C:\kafka_2.13-4.3.1"))
SOURCE = ROOT / "stream_processor" / "src" / "main" / "java" / "com" / "educationalstream" / "StreamProcessor.java"
CLASSES = ROOT / "run" / "java-classes" / "legacy"
LOG = ROOT / "run" / "logs" / "streams-legacy.log"
OUT = ROOT / "bench" / "results" / "m2_streams_smoke.json"
BOOTSTRAP = "localhost:9092"
APP_ID = "educational-stream-processor"     # hard-coded in the existing app

results: dict[str, dict] = {}


def record(check: str, ok: bool, detail) -> None:
    results[check] = {"ok": bool(ok), "detail": detail}
    print(f"[{'PASS' if ok else 'FAIL'}] {check}: {detail}", flush=True)


def main() -> None:
    CLASSES.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    classpath = str(KAFKA_HOME / "libs" / "*")
    subprocess.run(["javac", "--release", "17", "-cp", classpath, "-d", str(CLASSES), str(SOURCE)], check=True)

    admin = KafkaAdminClient(bootstrap_servers=BOOTSTRAP)
    for topic in ("transcriptions", "generated_notes"):
        try:
            admin.create_topics([NewTopic(topic, 3, 1)])
        except TopicAlreadyExistsError:
            pass

    with LOG.open("w", encoding="utf-8") as log:
        app = subprocess.Popen(["java", "-Xmx512m", "-cp", f"{CLASSES};{classpath}", "com.educationalstream.StreamProcessor"],
                               stdout=log, stderr=subprocess.STDOUT)
    try:
        # The legacy app uses event time = start_time * 1000. Relative start_times (0, 5, ...)
        # give 1970 timestamps, which crashed the Windows broker in the first M2 run (now
        # rejected by the timestamp guard). Use wall-clock seconds so this smoke test
        # checks the infrastructure, not defect D10.
        producer = KafkaProducer(bootstrap_servers=BOOTSTRAP, acks="all")
        base = int(time.time())
        for chunk in range(4):
            event = {"video_id": "smoke_lecture", "chunk_id": chunk,
                     "start_time": base + chunk * 5, "end_time": base + chunk * 5 + 5,
                     "text": f"sentence number {chunk} of the smoke test."}
            producer.send("transcriptions", json.dumps(event).encode())
        producer.flush()

        state, members, deadline = None, 0, time.time() + 60
        while time.time() < deadline and not (state == "Stable" and members >= 1):
            time.sleep(2)
            try:
                group = admin.describe_groups([APP_ID])[APP_ID]
                state, members = group.get("group_state"), len(group.get("members", []))
            except Exception:  # noqa: BLE001 - group not created yet
                pass
        record("S1 Streams consumer group forms", state == "Stable" and members >= 1,
               f"group {APP_ID}: state={state}, members={members}")

        internal = []
        deadline = time.time() + 30
        while time.time() < deadline and len(internal) < 2:
            internal = sorted(t for t in admin.list_topics() if t.startswith(APP_ID))
            time.sleep(1)
        rf = {t["name"]: max(len(p["replica_nodes"]) for p in t["partitions"]) for t in admin.describe_topics(internal)}
        record("S2 internal topics created with RF 1", len(internal) >= 2 and set(rf.values()) == {1},
               rf)

        consumer = KafkaConsumer("generated_notes", bootstrap_servers=BOOTSTRAP, auto_offset_reset="earliest",
                                 enable_auto_commit=False, group_id=None)
        outputs, deadline = [], time.time() + 45   # at_least_once commits every 30 s by default
        while time.time() < deadline and not outputs:
            for batch in consumer.poll(timeout_ms=1000).values():
                outputs.extend(json.loads(r.value) for r in batch)
        consumer.close()
        record("S3 window output reaches generated_notes", bool(outputs),
               outputs[:2] if outputs else "no output within 45 s")
    finally:
        # On this machine "java" is Oracle's javapath launcher shim, which starts the
        # real JVM as a child: terminate() would orphan it. Kill the whole tree.
        subprocess.run(["taskkill", "/PID", str(app.pid), "/T", "/F"], capture_output=True)
        app.wait(timeout=20)
        alive = "transcriptions" in admin.list_topics()
        record("S4 broker still up after the run", alive, "list_topics ok" if alive else "broker unreachable")
        admin.close()

    OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"{sum(r['ok'] for r in results.values())}/{len(results)} checks passed. Log: {LOG.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
