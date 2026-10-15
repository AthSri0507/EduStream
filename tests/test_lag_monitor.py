"""CONSUMER_LAG decision rule (ARCHITECTURE §7): seconds of audio, 2 consecutive polls, one alert per minute."""

from types import SimpleNamespace

from kafka import TopicPartition
from kafka.structs import OffsetAndMetadata

from storage.lag_monitor import LagAlerter, LagRow, Watched, sample

ALERTING = {"transcription-workers"}


class FakeAdmin:
    """Partitions 0-2 of video_audio, 6 records each; the group state is configurable."""

    def __init__(self, committed, members):
        self.committed, self.members = committed, members

    def describe_topics(self, topics):
        return [{"name": "video_audio", "partitions": [{"partition_index": i} for i in range(3)]}]

    def list_partition_offsets(self, specs):
        from kafka.admin import OffsetSpec
        return {tp: SimpleNamespace(offset=6 if spec == OffsetSpec.LATEST else 0) for tp, spec in specs.items()}

    def list_group_offsets(self, spec):
        return {"transcription-workers": self.committed}

    def describe_groups(self, groups):
        return {"transcription-workers": {"group_state": "Stable" if self.members else "Dead",
                                          "members": self.members}}


def test_a_dead_group_with_no_commits_is_still_measured():
    # M5 bug: all workers stopped before ever committing -> Kafka deletes the group ("Dead").
    rows = sample(FakeAdmin(committed={}, members=[]), [Watched("transcription-workers", "video_audio", 10, True)])
    assert [(r.partition, r.lag, r.lag_seconds, r.owner) for r in rows] == [(0, 6, 60, None), (1, 6, 60, None),
                                                                           (2, 6, 60, None)]


def test_owners_and_committed_offsets_are_used_when_present():
    committed = {TopicPartition("video_audio", 1): OffsetAndMetadata(4, None, -1)}
    members = [{"client_id": "worker-w2", "member_assignment": {"assigned_partitions": [
        {"topic": "video_audio", "partitions": [1]}]}}]
    rows = sample(FakeAdmin(committed, members), [Watched("transcription-workers", "video_audio", 10, True)])
    p1 = [r for r in rows if r.partition == 1][0]
    assert (p1.committed, p1.position, p1.lag, p1.owner) == (4, 4, 2, "worker-w2")


def row(lag_s, group="transcription-workers", partition=1):
    return LagRow(group, "video_audio", partition, 10, 10, 10 + int(lag_s // 10), int(lag_s // 10), lag_s, "worker-w2")


def test_needs_two_consecutive_polls_over_the_threshold():
    a = LagAlerter(30)
    assert a.check([row(40)], ALERTING, 0) == []
    assert len(a.check([row(40)], ALERTING, 5_000)) == 1


def test_a_poll_under_the_threshold_resets_the_streak():
    a = LagAlerter(30)
    a.check([row(40)], ALERTING, 0)
    a.check([row(20)], ALERTING, 5_000)
    assert a.check([row(40)], ALERTING, 10_000) == []


def test_at_most_one_alert_per_partition_per_minute():
    a = LagAlerter(30)
    fired = [len(a.check([row(40)], ALERTING, t)) for t in range(0, 60_000, 5_000)]
    assert sum(fired) == 1
    assert len(a.check([row(40)], ALERTING, 60_000)) == 1      # next minute, still lagging


def test_threshold_is_exclusive_and_other_groups_never_alert():
    a = LagAlerter(30)
    for t in (0, 5_000, 10_000):
        assert a.check([row(30), row(90, group="edustream-streams")], ALERTING, t) == []
