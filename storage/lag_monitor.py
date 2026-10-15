"""Consumer-lag thread inside db-sink (ARCHITECTURE §7 CONSUMER_LAG; dashboard "Pipeline health").

Every 5 s, for each watched consumer group: committed offsets, end offsets and partition owners
(kafka-python 3.x admin API: list_group_offsets, list_partition_offsets, describe_groups; M2 K6).
Lag is converted to SECONDS OF AUDIO behind, using what one record represents for that group
(one chunk for the workers and Streams, one window for the note stage), so the same threshold
LAG_ALERT_S (30 s) means the same thing everywhere and at any chunk size. The Note Agent HOLDS up to
G - 1 windows uncommitted by design (G = windows per 90 s update, rev 6 §8.1.1); those records are an
allowance and do not count as lag, so a normal hold never alerts.

CONSUMER_LAG is raised when a partition is over the threshold on 2 consecutive polls;
alert_id = CONSUMER_LAG:<group>:<partition>:<epoch_minute>, so repeats within a minute collapse.
Rows go to the SQLite `lag` table (this thread has its own connection; same process = one writer).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from kafka import KafkaAdminClient, KafkaConsumer, TopicPartition
from kafka.admin import OffsetSpec

from common import schemas
from common.config import (GROUP_NOTES, GROUP_WORKERS, TOPIC_ALERTS, TOPIC_AUDIO, TOPIC_TRANSCRIPTS, TOPIC_WINDOWS,
                           Settings)
from common.kafka_utils import ProduceFailed, make_producer, send_and_wait
from storage.db import connect_writer

POLL_S = 5
CONSECUTIVE = 2


@dataclass(frozen=True)
class Watched:
    group: str
    topic: str
    seconds_per_record: float
    alert: bool
    allowance_records: int = 0        # records held uncommitted by design (the Note Agent's open update)


def watched_groups(settings: Settings) -> list[Watched]:
    return [
        Watched(GROUP_WORKERS, TOPIC_AUDIO, settings.chunk_seconds, True),
        Watched("edustream-streams", TOPIC_TRANSCRIPTS, settings.chunk_seconds, False),
        Watched(GROUP_NOTES, TOPIC_WINDOWS, settings.window_seconds * settings.speedup, True,
                max(0, settings.note_update_s // max(1, int(settings.window_seconds * settings.speedup)) - 1)),
    ]


@dataclass
class LagRow:
    group: str
    topic: str
    partition: int
    committed: int | None
    position: int                  # next offset the group will read (committed, else earliest)
    end_offset: int
    lag: int
    lag_seconds: float
    owner: str | None


class LagAlerter:
    """Pure decision logic: over threshold on CONSECUTIVE polls -> one alert per partition per minute."""

    def __init__(self, threshold_s: float) -> None:
        self.threshold_s = threshold_s
        self.streak: dict[tuple, int] = {}
        self.last_minute: dict[tuple, int] = {}

    def check(self, rows: list[LagRow], alerting_groups: set[str], now_ms: int) -> list[LagRow]:
        due = []
        for row in rows:
            key = (row.group, row.topic, row.partition)
            if row.group not in alerting_groups or row.lag_seconds <= self.threshold_s:
                self.streak[key] = 0
                continue
            self.streak[key] = self.streak.get(key, 0) + 1
            minute = now_ms // 60_000
            if self.streak[key] >= CONSECUTIVE and self.last_minute.get(key) != minute:
                self.last_minute[key] = minute
                due.append(row)
        return due


def sample(admin: KafkaAdminClient, groups: list[Watched]) -> list[LagRow]:
    topics = sorted({g.topic for g in groups})
    partitions = [TopicPartition(t["name"], p["partition_index"])
                  for t in admin.describe_topics(topics) for p in t["partitions"]]
    ends = admin.list_partition_offsets({tp: OffsetSpec.LATEST for tp in partitions})
    starts = admin.list_partition_offsets({tp: OffsetSpec.EARLIEST for tp in partitions})
    rows = []
    for g in groups:
        # A group with no members and no commits ("Dead") is still measured: a stopped stage is exactly
        # what CONSUMER_LAG is for. Its position is then the topic's earliest offset (M5 finding).
        committed = admin.list_group_offsets({g.group: None}).get(g.group, {})
        described = admin.describe_groups([g.group]).get(g.group, {})
        owners = {}
        for member in described.get("members", []) or []:
            assignment = member.get("member_assignment") or {}
            for a in assignment.get("assigned_partitions", []) if isinstance(assignment, dict) else []:
                for part in a.get("partitions", []):
                    owners[(a.get("topic"), part)] = member.get("client_id")
        for tp in partitions:
            if tp.topic != g.topic:
                continue
            meta = committed.get(tp)
            position = meta.offset if meta is not None and meta.offset >= 0 else starts[tp].offset
            end = ends[tp].offset
            lag = max(0, end - position)
            beyond = max(0, lag - g.allowance_records)
            rows.append(LagRow(g.group, tp.topic, tp.partition, meta.offset if meta is not None else None,
                               position, end, lag, beyond * g.seconds_per_record, owners.get((tp.topic, tp.partition))))
    return rows


class LagMonitorThread(threading.Thread):
    def __init__(self, settings: Settings, stop: threading.Event, log) -> None:
        super().__init__(name="lag-monitor", daemon=True)
        self.settings, self.stop_event, self.log = settings, stop, log

    def run(self) -> None:
        groups = watched_groups(self.settings)
        alerting = {g.group for g in groups if g.alert}
        alerter = LagAlerter(self.settings.lag_alert_s)
        conn = connect_writer()
        admin = KafkaAdminClient(bootstrap_servers=self.settings.kafka_bootstrap, client_id="db-sink-lag")
        producer = make_producer(self.settings, client_id="db-sink-lag")
        self.peeker = KafkaConsumer(bootstrap_servers=self.settings.kafka_bootstrap, client_id="db-sink-lag-peek",
                                    group_id=None, enable_auto_commit=False, max_poll_records=1)
        try:
            while not self.stop_event.wait(POLL_S):
                now = int(time.time() * 1000)
                try:
                    rows = sample(admin, groups)
                except Exception as exc:  # noqa: BLE001 - broker hiccup: skip this poll
                    self.log.warn("lag_sample_failed", error=repr(exc))
                    continue
                conn.execute("BEGIN IMMEDIATE")
                conn.executemany(
                    "INSERT INTO lag VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(group_id, topic, partition) DO UPDATE SET"
                    " committed=excluded.committed, end_offset=excluded.end_offset, lag=excluded.lag,"
                    " lag_seconds=excluded.lag_seconds, owner=excluded.owner, sampled_ts=excluded.sampled_ts",
                    [(r.group, r.topic, r.partition, r.committed, r.end_offset, r.lag, r.lag_seconds, r.owner, now)
                     for r in rows])
                conn.execute("COMMIT")
                for row in alerter.check(rows, alerting, now):
                    self._raise_alert(conn, producer, row, now)
        except ProduceFailed as exc:
            self.log.error("lag_alert_produce_failed", error=str(exc))
            self.stop_event.set()        # main loop exits; run_component.ps1 restarts with fresh producers
        finally:
            conn.close()
            admin.close()
            self.peeker.close()

    def _waiting_video(self, row: LagRow) -> str | None:
        """video_id of the first record the group has not processed yet: its key (A4).

        M5 finding: looking the lecture up by partition in SQLite named the PREVIOUS lecture on that
        partition, because a lecture only reaches SQLite once its first transcript exists, and a
        stalled stage is exactly when it doesn't.
        """
        tp = TopicPartition(row.topic, row.partition)
        try:
            self.peeker.assign([tp])
            self.peeker.seek(tp, row.position)
            for batch in self.peeker.poll(timeout_ms=3000, max_records=1).values():
                if batch and batch[0].key:
                    return batch[0].key.decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001 - the alert still goes out, just without a lecture
            self.log.warn("lag_peek_failed", partition=row.partition, error=repr(exc))
        return None

    def _raise_alert(self, conn, producer, row: LagRow, now: int) -> None:
        video_id = self._waiting_video(row)
        alert = {"schema": "alert.v1", "alert_id": f"CONSUMER_LAG:{row.group}:{row.partition}:{now // 60_000}",
                 "type": "CONSUMER_LAG", "severity": "warn", "video_id": video_id, "window_start": None,
                 "revision": None, "value": round(row.lag_seconds, 1), "threshold": self.settings.lag_alert_s,
                 "details": {"group": row.group, "topic": row.topic, "partition": row.partition,
                             "lag_records": row.lag, "owner": row.owner, "position": row.position},
                 "source": "db-sink", "created_ts": now}
        send_and_wait(producer, TOPIC_ALERTS, schemas.encode("alert.v1", alert), key=video_id or "_system")
        self.log.warn("consumer_lag", group=row.group, partition=row.partition, lag_s=round(row.lag_seconds, 1),
                      owner=row.owner)
