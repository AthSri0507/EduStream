"""Which partition a video_id lands on: murmur2, identical in kafka-python and Java (M2 K3/J1, 20/20 keys)."""

from __future__ import annotations

from kafka.partitioner.default import murmur2


def partition_for(video_id: str, partitions: int) -> int:
    return (murmur2(video_id.encode("utf-8")) & 0x7FFFFFFF) % partitions
