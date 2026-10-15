"""N-1: grouping windows into 90 s notebook updates (ARCHITECTURE §8.1.1). Pure logic, no Kafka."""

from agents.notebook import Grouper, Held, LectureEnd, Window, last_chunk_of, update_of

UPDATE_S, CHUNK_S = 90, 10


def window(first_chunk: int, n: int, video: str = "python_l1", offset: int | None = None, arrived: float = 0.0,
           partition: int = 0) -> Window:
    chunks = [{"chunk_id": c, "start_time": c * CHUNK_S, "end_time": (c + 1) * CHUNK_S, "text": f"chunk {c}"}
              for c in range(first_chunk, first_chunk + n)]
    start = 1_792_051_200_000 + first_chunk * 10_000
    return Window(video, start, start + 30_000, 1_792_051_200_000, chunks, partition,
                  offset if offset is not None else first_chunk // 3, arrived)


def test_update_boundaries_come_from_media_time():
    assert [update_of(window(c, 3), UPDATE_S, -1) for c in (0, 3, 6, 9, 12)] == [0, 0, 0, 1, 1]
    assert last_chunk_of(0, UPDATE_S, CHUNK_S) == 8 and last_chunk_of(3, UPDATE_S, CHUNK_S) == 35


def test_live_three_windows_make_one_update_completed_by_its_last_chunk():
    g = Grouper(UPDATE_S, CHUNK_S)
    assert g.add(window(0, 3), -1) == [] and g.add(window(3, 3), -1) == []
    (held, reason), = g.add(window(6, 3), -1)
    assert reason == "complete" and held.update_index == 0 and len(held.windows) == 3 and g.held is None
    assert [c["chunk_id"] for c in held.chunks()] == list(range(9))


def test_at_3x_every_window_is_one_update():
    g = Grouper(UPDATE_S, CHUNK_S)
    emitted = [g.add(window(c, 9, offset=i), i - 1) for i, c in enumerate((0, 9, 18))]
    assert [[(h.update_index, r) for h, r in e] for e in emitted] == [[(0, "complete")], [(1, "complete")],
                                                                     [(2, "complete")]]


def test_a_missing_window_completes_the_update_when_the_next_one_starts():
    g = Grouper(UPDATE_S, CHUNK_S)
    g.add(window(0, 3), -1)
    g.add(window(3, 3), -1)                       # chunks 6-8 never arrive (e.g. all dead-lettered)
    (held, reason), = g.add(window(9, 3, offset=7), -1)
    assert (held.update_index, reason, len(held.windows)) == (0, "next_update", 2)
    assert held.last_offset == 1                  # the commit stops before the window that starts update 1
    assert g.held.update_index == 1 and g.held.windows[0].offset == 7


def test_another_lecture_on_the_partition_completes_the_held_update():
    g = Grouper(UPDATE_S, CHUNK_S)
    g.add(window(0, 3), -1)
    (held, reason), = g.add(window(0, 3, video="algorithms_ku_l1", offset=9), -1)
    assert (held.video_id, reason) == ("python_l1", "next_lecture") and g.held.video_id == "algorithms_ku_l1"


def test_max_hold_and_lecture_end_timers():
    g = Grouper(UPDATE_S, CHUNK_S)
    g.add(window(0, 3, arrived=100.0), -1)
    assert g.due(399.0, 300, None) is None and g.due(400.0, 300, None) == "max_hold"
    # flushed, and the window holding the last chunk (id 2) has been seen
    assert g.due(101.0, 300, LectureEnd(last_chunk_id=2, flush_seen_at=101.0)) == "lecture_end"
    # flushed, last chunk never arrives: 30 s of quiet after the flush was seen
    end = LectureEnd(last_chunk_id=5, flush_seen_at=110.0)
    assert g.due(139.0, 300, end) is None and g.due(140.0, 300, end) == "lecture_end"


def test_a_late_window_after_a_timeout_joins_the_next_update():
    g = Grouper(UPDATE_S, CHUNK_S)
    g.add(window(9, 3, arrived=0.0), 0)           # update 1 held
    sent = g.take()                               # emitted by max_hold: last_sent becomes 1
    assert isinstance(sent, Held) and sent.update_index == 1
    g.add(window(12, 3), last_sent=1)             # still media time of update 1 ...
    assert g.held.update_index == 2               # ... but update 1 is sent, so it joins update 2: nothing lost
