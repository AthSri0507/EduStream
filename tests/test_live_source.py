"""producer/live_source.py, the parts that need no audio device: cutting a capture into chunks (gaps filled with
silence, a fast clock trimmed), mixing loopback and microphone, and when a live lecture ends."""

import numpy as np
import pytest

from producer import live_source as L


def tone(n, value=0.5):
    return np.full(n, value, dtype=np.float32)


def test_a_chunk_is_cut_across_blocks_and_the_rest_waits_for_the_next():
    buf = L.SampleBuffer()
    for _ in range(3):
        buf.feed(tone(1600))                                  # 3 blocks of 100 ms
    piece, missing = buf.take(2000)
    assert len(piece) == 2000 and missing == 0 and buf.size == 2800
    piece, missing = buf.take(2800)
    assert missing == 0 and buf.size == 0


def test_audio_that_never_arrived_becomes_silence_so_chunk_ids_stay_contiguous():
    buf = L.SampleBuffer()
    buf.feed(tone(1000))
    piece, missing = buf.take(1600)
    assert missing == 600 and len(piece) == 1600 and np.all(piece[1000:] == 0) and np.all(piece[:1000] == 0.5)
    piece, missing = buf.take(1600)                           # a stalled device: a whole chunk of silence
    assert missing == 1600 and L.rms(piece) == 0.0


def test_a_capture_running_ahead_is_trimmed_from_the_oldest_end():
    buf = L.SampleBuffer()
    buf.feed(np.arange(5000, dtype=np.float32))
    assert L.drop_excess(buf, 3000) == 2000 and buf.size == 3000
    piece, _ = buf.take(1)
    assert piece[0] == 2000.0                                 # the newest audio is kept
    assert L.drop_excess(buf, 9000) == 0


def test_loopback_and_microphone_are_summed_and_clipped():
    out = L.mix([tone(4, 0.7), tone(4, 0.6)])
    assert np.allclose(out, 1.0)
    assert L.mix([tone(4, 0.2)]) is not None and np.allclose(L.mix([tone(4, 0.2)]), 0.2)
    pcm = np.frombuffer(L.to_pcm16(np.array([1.5, -1.5, 0.0], dtype=np.float32)), dtype="<i2")
    assert list(pcm) == [32767, -32767, 0]


def test_levels_for_the_console():
    assert L.dbfs(L.rms(tone(1600, 1.0))) == 0.0
    assert L.dbfs(0.0) == -120.0
    assert L.rms(tone(1600, 0.002)) < L.SILENCE_RMS < L.rms(tone(1600, 0.01))


@pytest.mark.parametrize("chunk_id, silent_run, max_min, silence_min, stop, reason", [
    (5, 0, 240, 15, False, None),
    (5, 0, 240, 15, True, "stop_button"),
    (1439, 0, 240, 15, False, "max_minutes"),                 # 240 min of 10 s chunks
    (300, 90, 240, 15, False, "silence"),                     # 15 min of silent chunks
    (300, 90, 240, 0, False, None),                           # --silence-end 0: never
    (300, 89, 240, 15, False, None),
])
def test_when_a_live_lecture_ends(chunk_id, silent_run, max_min, silence_min, stop, reason):
    assert L.end_reason(chunk_id, silent_run, 10.0, max_min, silence_min, stop) == reason


def test_a_live_class_gets_an_id_from_its_title_on_a_free_partition():
    from common.partitioning import partition_for
    when = 1793347590.0
    vid = L.free_video_id("DBMS · Unit 3 (live)!", 3, [], when)
    assert L.VIDEO_ID.fullmatch(vid) and vid.startswith("dbms_unit_3_live_")
    busy = [{"partition": partition_for(vid, 3)}]
    other = L.free_video_id("DBMS · Unit 3 (live)!", 3, busy, when)
    assert other != vid and partition_for(other, 3) != busy[0]["partition"]
    with pytest.raises(SystemExit):
        L.free_video_id("x", 3, [{"partition": p} for p in range(3)], when)


def test_a_device_is_found_by_part_of_its_name():
    class Dev:
        def __init__(self, name):
            self.name = name
    devs = [Dev("Speaker (Realtek(R) Audio)"), Dev("Headphones (2- WH-CH520)")]
    assert L.pick(devs, "headphones", devs[0]).name.startswith("Headphones")
    assert L.pick(devs, None, devs[0]) is devs[0]
    with pytest.raises(SystemExit):
        L.pick(devs, "zoom", devs[0])
