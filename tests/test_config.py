from dataclasses import replace

from common.config import DEMO_LECTURES, load
from common.partitioning import partition_for


def test_defaults_match_m2_decisions(monkeypatch):
    # Check the code defaults, not whatever a local .env says
    for name in ("CHUNK_SECONDS", "SPEEDUP", "WINDOW_SECONDS", "GRACE_SECONDS", "T_SCORE", "MIN_COVERED_S"):
        monkeypatch.delenv(name, raising=False)
    s = load()
    assert s.chunk_seconds == 10 and s.chunk_wall_ms == 10_000          # M2: 10 s chunks
    assert s.t_score == 0.63                                            # M2 calibration
    assert s.problems() == []


def test_invariants_are_enforced(monkeypatch):
    monkeypatch.delenv("CHUNK_SECONDS", raising=False)
    s = load()
    assert any("CHUNK_SECONDS" in p for p in replace(s, chunk_seconds=20).problems())   # > 1 MB messages
    assert any("MIN_COVERED_S" in p for p in replace(s, min_covered_s=45).problems())
    assert any("whole number of chunks" in p for p in replace(s, chunk_seconds=7).problems())
    assert replace(s, chunk_seconds=5).problems() == []


def test_demo_video_ids_cover_partitions_0_1_2():
    # M2 chose these so the three demo lectures never share a partition (S1).
    assert sorted(partition_for(v, 3) for v in DEMO_LECTURES.values()) == [0, 1, 2]
    assert partition_for("python_l1", 3) == 0
    assert partition_for("algorithms_ku_l1", 3) == 1
    assert partition_for("algorithms_demaine_l2", 3) == 2


def test_natural_ids_collide_which_is_why_they_were_replaced():
    assert partition_for("algorithms_l1", 3) == partition_for("algorithms_l2", 3)   # M2 finding
