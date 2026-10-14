"""Edge cases for the A5 flush timestamp: "tight" (candidate) vs "legacy" (current default).

A window [start, end) closes when stream time reaches end + GRACE (verified in M2 J4 and the
Java S-1 tests). Both formulas must close the lecture's last window; "tight" must do so at the
earliest possible moment, i.e. without shortening the grace period.
"""

import pytest

from producer.lecture_source import (aligned_session_start, chunk_event_ts, flush_event_ts, flush_send_at)

S = 1_792_051_200_000          # aligned to 30 s
W, G = 30, 10                  # WINDOW_SECONDS, GRACE_SECONDS

# (chunk seconds, number of chunks, lecture end in s, case)
CASES = [
    (10, 14, 140, "ends just before a boundary"),
    (10, 15, 150, "ends exactly on a boundary"),
    (10, 16, 160, "ends just after a boundary"),
    (5, 29, 145, "ends just before a boundary"),
    (5, 30, 150, "ends exactly on a boundary"),
    (5, 31, 155, "ends just after a boundary"),
]


def last_window_end(session_start, n_chunks, chunk_ms):
    last_ts = chunk_event_ts(session_start, n_chunks - 1, chunk_ms)
    return last_ts - last_ts % (W * 1000) + W * 1000          # Kafka TimeWindows: epoch-aligned


@pytest.mark.parametrize("chunk_s,n,end_s,case", CASES, ids=[f"{c[0]}s-{c[3]}" for c in CASES])
def test_tight_flush_closes_last_window_at_the_earliest_moment(chunk_s, n, end_s, case):
    chunk_ms = chunk_s * 1000
    tight = flush_event_ts(S, n - 1, chunk_ms, W, G, "tight")
    legacy = flush_event_ts(S, n - 1, chunk_ms, W, G, "legacy")
    close_at = last_window_end(S, n, chunk_ms) + G * 1000

    assert tight == close_at                     # closes the last window ...
    assert tight - 1 < close_at                  # ... and 1 ms earlier would not: grace fully preserved
    assert legacy >= close_at                    # the legacy formula also closes it, just later
    assert tight <= legacy
    assert tight > chunk_event_ts(S, n - 1, chunk_ms)          # S3: never runs backwards
    # S4: a next lecture on this partition starts at/after the flush's event time
    assert aligned_session_start(flush_send_at(S, n - 1, chunk_ms, W, G, "tight"), W, True) >= tight


def test_saving_is_a_whole_window_exactly_on_a_boundary():
    savings = {case: (flush_event_ts(S, n - 1, c * 1000, W, G, "legacy")
                      - flush_event_ts(S, n - 1, c * 1000, W, G, "tight")) // 1000
               for c, n, _, case in CASES if c == 10}
    assert savings == {"ends just before a boundary": 20, "ends exactly on a boundary": 30,
                       "ends just after a boundary": 10}


def test_tight_formula_uses_kafka_window_alignment_even_without_aligned_start():
    start = S + 7_000                            # --no-align: session_start is not on a boundary
    for n in (3, 4, 5):
        tight = flush_event_ts(start, n - 1, 10_000, W, G, "tight")
        assert tight == last_window_end(start, n, 10_000) + G * 1000


def test_unknown_formula_is_rejected():
    with pytest.raises(ValueError):
        flush_event_ts(S, 3, 10_000, W, G, "loose")
