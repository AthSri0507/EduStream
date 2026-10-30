"""UI-2: the status row and tab title (dashboard/status.py) and the no-break rules (notebook_html.keep_together):
one audio warning at a time, device names that never wrap, numbers that stay with their units (docs/UI_DESIGN.md)."""

import pytest

from dashboard import notebook_html as nbh
from dashboard import status

NOW = 2_000_000_000
LIVE = {"video_id": "v", "title": "DBMS · Unit 3", "live": True, "said": 990.0, "age": 5.0}


def recorder(**over):
    return {"video_id": "v", "status": "active", "updated_ts": NOW, "last_chunk_sent": 9, "level_dbfs": -25.0,
            "devices": ["Headphones (2- WH-CH520)"], **over}


def test_listening_and_the_tab_title():
    s = status.compute(NOW, LIVE, recorder())
    assert (s["kind"], s["label"], s["detail"]) == ("listening", "Listening", "16 min 30 s into the class")
    assert s["title"] == "Listening 16:30 - EduStream"
    assert status.compute(NOW, None, None)["title"] == "EduStream"
    done = status.compute(NOW, {**LIVE, "live": False, "said": 4040.0}, None)
    assert (done["label"], done["detail"], done["title"]) == ("", "", "EduStream")   # no row when nothing runs


@pytest.mark.parametrize("rec, lecture_age, kind", [
    (recorder(level_dbfs=-80.0), 5.0, "no_sound"),
    (recorder(level_dbfs=-45.0), 5.0, "quiet"),
    (recorder(level_dbfs=-80.0), 300.0, "no_sound"),            # no sound wins over notes paused
    (recorder(level_dbfs=-45.0), 300.0, "quiet"),               # quiet wins over notes paused
    (recorder(updated_ts=NOW - 60_000, level_dbfs=-80.0), 5.0, "paused"),   # stale recorder: its level is old news
    (recorder(), 300.0, "paused"),                              # notes stopped arriving
    (None, 300.0, "paused"),                                    # a played file: no recorder at all
    (recorder(level_dbfs=-80.0, last_chunk_sent=1), 5.0, "listening"),      # the first 30 s: no judgement yet
])
def test_only_one_audio_warning_at_a_time(rec, lecture_age, kind):
    s = status.compute(NOW, {**LIVE, "age": lecture_age}, rec)
    assert s["kind"] == kind
    row = status.row_html(s)
    assert row.count('class="state') == 1                       # one state, one message, never a stack


def test_device_names_never_wrap_mid_name():
    s = status.compute(NOW, LIVE, recorder(level_dbfs=-80.0))
    assert "Headphones (2‑ WH‑CH520)" in s["detail"]
    assert " " not in status.device_label("Speakers (Realtek(R) Audio)")


@pytest.mark.parametrize("raw, kept", [
    ("typically 0.05 for a 95 % confidence level", "95 %"),
    ("the mean weight is 454 g and", "454 g"),
    ("critical values are ± 1.96", "±1.96"),
    ("4.54 ± 0.2 g", "4.54 ± 0.2 g"),
    ("a Type I error and a type II error", "Type I error and a type II error"),
    ("after 30 s of silence", "30 s"),
])
def test_numbers_units_and_type_names_stay_together(raw, kept):
    assert kept in nbh.keep_together(raw)


def test_ordinary_words_after_numbers_are_left_alone():
    assert nbh.keep_together("in 2 steps and 3 groups") == "in 2 steps and 3 groups"
    assert nbh.keep_together("Type In the box") == "Type In the box"
