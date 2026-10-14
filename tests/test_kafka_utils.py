"""§6.3 protocol helpers, with fakes (no broker needed)."""

import json
from types import SimpleNamespace

import pytest
from kafka.errors import CommitFailedError
from kafka.structs import OffsetAndMetadata, TopicPartition

from common import kafka_utils, schemas


class FakeConsumer:
    def __init__(self, fail=False):
        self.commits, self.fail = [], fail

    def commit(self, offsets=None):
        if self.fail:
            raise CommitFailedError("revoked")
        self.commits.append(offsets)


class FakeFuture:
    def __init__(self, error=None):
        self.error = error

    def add_callback(self, fn):
        return self

    def add_errback(self, fn):
        return self

    def get(self, timeout):
        if self.error:
            raise self.error
        return SimpleNamespace(topic="t", partition=0, offset=7)


class FakeProducer:
    def __init__(self, error=None):
        self.sent, self.error = [], error

    def send(self, topic, value, key, partition=None, timestamp_ms=None):
        self.sent.append((topic, value, key, partition))
        return FakeFuture(self.error)


def record(offset=41, value=b'{"x": 1}'):
    return SimpleNamespace(topic="video_audio", partition=2, offset=offset, key=b"python_l1", value=value)


def test_commit_is_explicit_offset_plus_one():
    consumer = FakeConsumer()
    assert kafka_utils.commit_record(consumer, record(41))
    assert consumer.commits == [{TopicPartition("video_audio", 2): OffsetAndMetadata(42, None, -1)}]


def test_commit_after_revocation_returns_false():
    assert kafka_utils.commit_record(FakeConsumer(fail=True), record()) is False


def test_produce_failure_raises_produce_failed():
    with pytest.raises(kafka_utils.ProduceFailed):
        kafka_utils.send_and_wait(FakeProducer(error=TimeoutError("broker down")), "t", b"v", key="k")


def test_send_encodes_key_and_keeps_partition():
    producer = FakeProducer()
    kafka_utils.send_and_wait(producer, "transcriptions", b"v", key="python_l1", partition=2)
    assert producer.sent == [("transcriptions", b"v", b"python_l1", 2)]


def test_dlq_record_is_valid_and_truncated():
    producer = FakeProducer()
    huge = json.dumps({"audio_b64": "A" * 500_000}).encode()
    kafka_utils.send_to_dlq(producer, "worker", record(value=huge), "ValidationError: x")
    topic, value, key, _ = producer.sent[0]
    payload = schemas.decode(value, "dlq.v1")
    assert topic == "dlq" and key == b"python_l1"
    assert len(payload["raw_value"]) <= 4096 and payload["src_offset"] == 41


def test_raw_preview_handles_binary():
    assert kafka_utils.raw_preview(b"\xff\x00\x01").startswith("b64:")
    assert kafka_utils.raw_preview(None) == ""
