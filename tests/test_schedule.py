"""A3/A5 schedule and the S1 check (ARCHITECTURE §6.2)."""

from producer.lecture_source import (aligned_session_start, chunk_event_ts, chunk_send_at, flush_event_ts,
                                     flush_send_at, s1_conflicts)

S = 1_792_051_200_000   # aligned to 30 s
WALL = 10_000           # 10 s chunks, speedup 1


def test_session_start_aligns_to_next_window_boundary():
    assert aligned_session_start(S + 1, 30, True) == S + 30_000
    assert aligned_session_start(S, 30, True) == S
    assert aligned_session_start(S + 1, 30, False) == S + 1


def test_chunk_timestamps_are_scheduled_and_monotonic():
    stamps = [chunk_event_ts(S, i, WALL) for i in range(10)]
    assert stamps == sorted(stamps) and stamps[3] == S + 30_000
    assert chunk_send_at(S, 3, WALL) == stamps[3] + WALL        # sent when capture ends


def test_flush_closes_the_last_window_and_never_runs_backwards():
    for last in (0, 2, 3, 258):
        ts = flush_event_ts(S, last, WALL, 30, 10)
        last_window_end = S + ((chunk_event_ts(S, last, WALL) - S) // 30_000 + 1) * 30_000
        assert ts >= last_window_end + 10_000                     # end + grace -> window closes
        assert ts > chunk_event_ts(S, last, WALL)                 # S3: never decreases
        assert flush_send_at(S, last, WALL, 30, 10) == ts + WALL  # published at/after its event_ts
    assert flush_event_ts(S, 258, WALL, 30, 10) == S + 259 * WALL + 40_000   # matches the fixture


def test_s4_next_lecture_starts_after_previous_flush():
    flush_ts = flush_event_ts(S, 5, WALL, 30, 10)
    published = flush_send_at(S, 5, WALL, 30, 10)
    assert aligned_session_start(published, 30, True) >= flush_ts


def test_s1_conflicts():
    assert s1_conflicts({"python_l1": 0, "algorithms_ku_l1": 1}, []) == []
    assert s1_conflicts({"a": 1, "b": 1}, [])                                # own lectures collide
    active = [{"video_id": "other", "partition": 0}]
    assert s1_conflicts({"python_l1": 0}, active)                            # partition busy
    assert s1_conflicts({"algorithms_ku_l1": 1}, active) == []
