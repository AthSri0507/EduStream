"""Kafka factories and the commit/produce protocol (ARCHITECTURE §6.3, verified in M2).

Rules this module enforces for every Python stage:
  * consumers: raw bytes, read_committed, max_poll_records=1, manual commits only;
  * commits are EXPLICIT offsets (OffsetAndMetadata(offset + 1, None, -1)); a bare
    commit() was shown to commit records that were never processed (M2 K5);
  * producers: idempotent, acks=all; values are bytes (no serializer callables);
  * a produce that fails raises ProduceFailed, and the caller exits with
    EXIT_PRODUCE_FAILED. The failed producer is never reused: an idempotent
    kafka-python producer keeps rejecting valid records after one failure (M2 K10).
    scripts/run_component.ps1 restarts the process, which creates a fresh producer
    and re-reads from the last committed offset.
  * never re-send a record by hand (a manual re-send is a new, un-deduplicated record).
"""

from __future__ import annotations

import base64
import time

from kafka import KafkaConsumer, KafkaProducer, TopicPartition
from kafka.errors import CommitFailedError
from kafka.structs import OffsetAndMetadata

from common import schemas
from common.config import TOPIC_DLQ, Settings

EXIT_PRODUCE_FAILED = 3
SEND_TIMEOUT_S = 130          # > delivery_timeout_ms (120 s), so the producer gives up first
RAW_LIMIT = 4096


class ProduceFailed(RuntimeError):
    """A record could not be delivered; the producer must be discarded."""


def make_producer(settings: Settings, client_id: str) -> KafkaProducer:
    return KafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap,
        client_id=client_id,
        acks="all",
        enable_idempotence=True,
        delivery_timeout_ms=120_000,
        linger_ms=settings.linger_ms,
        max_request_size=1_048_576,
    )


def make_consumer(settings: Settings, group_id: str | None, topics: list[str] | None, client_id: str) -> KafkaConsumer:
    consumer = KafkaConsumer(
        bootstrap_servers=settings.kafka_bootstrap,
        client_id=client_id,
        group_id=group_id,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        isolation_level="read_committed",
        max_poll_records=1,
        session_timeout_ms=10_000,
        heartbeat_interval_ms=3_000,
        max_poll_interval_ms=300_000,
    )
    if topics:
        consumer.subscribe(topics)
    return consumer


def poll_one(consumer: KafkaConsumer, timeout_ms: int = 1000):
    """Return the next record or None (max_poll_records=1, so at most one is fetched)."""
    for batch in consumer.poll(timeout_ms=timeout_ms, max_records=1).values():
        if batch:
            return batch[0]
    return None


def send_and_wait(producer: KafkaProducer, topic: str, value: bytes, key: str | None,
                  partition: int | None = None, log=None, timestamp_ms: int | None = None):
    """Send one record and block until it is acknowledged. Raises ProduceFailed on any failure.

    Delivery callbacks log the partition/offset (CIE lab: producer callbacks).
    """
    future = producer.send(topic, value=value, key=key.encode("utf-8") if key is not None else None,
                           partition=partition, timestamp_ms=timestamp_ms)
    if log is not None:
        future.add_callback(lambda md: log.info("delivered", topic=md.topic, partition=md.partition, offset=md.offset))
        future.add_errback(lambda exc: log.error("delivery_failed", topic=topic, error=repr(exc)))
    try:
        return future.get(timeout=SEND_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 - any failure means the producer is no longer trustworthy
        raise ProduceFailed(f"send to {topic} failed: {type(exc).__name__}: {exc}") from exc


def commit_record(consumer: KafkaConsumer, record) -> bool:
    """Commit exactly up to (and including) `record`. False if the partition was revoked."""
    tp = TopicPartition(record.topic, record.partition)
    try:
        consumer.commit({tp: OffsetAndMetadata(record.offset + 1, None, -1)})
        return True
    except CommitFailedError:
        return False   # the new owner of the partition will reprocess this record (<= 1 duplicate)


def raw_preview(raw: bytes | None) -> str:
    """UTF-8 text if possible, otherwise 'b64:'-prefixed base64; truncated to 4 KB."""
    if raw is None:
        return ""
    head = raw[:RAW_LIMIT]
    try:
        return head.decode("utf-8")
    except UnicodeDecodeError:
        return "b64:" + base64.b64encode(head[:3000]).decode("ascii")


def send_to_dlq(producer: KafkaProducer, stage: str, record, error: str, attempts: int = 1, log=None) -> None:
    """Dead-letter a poison record (ARCHITECTURE §4, DLQ path 1). Raises ProduceFailed if the DLQ is unreachable."""
    payload = {
        "schema": "dlq.v1", "stage": stage, "source_topic": record.topic,
        "src_partition": record.partition, "src_offset": record.offset,
        "key": record.key.decode("utf-8", "replace") if record.key else None,
        "raw_value": raw_preview(record.value), "error": error[:1000],
        "attempts": attempts, "failed_ts": int(time.time() * 1000),
    }
    send_and_wait(producer, TOPIC_DLQ, schemas.encode("dlq.v1", payload), key=payload["key"])
    if log is not None:
        log.warn("dead_lettered", topic=record.topic, partition=record.partition, offset=record.offset, error=error[:200])
