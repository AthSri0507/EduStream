"""storage/snapshot.py: the demo's safety net. Save while the writers are connected, restore into live files that
other connections still hold open, undo a restore."""

import json

import pytest

from storage import db, indexer
from storage import snapshot as S


@pytest.fixture()
def live(tmp_path):
    files = {"edustream.db": tmp_path / "data" / "edustream.db", "vectors.db": tmp_path / "data" / "vectors.db"}
    writer = db.connect_writer(files["edustream.db"])
    writer.execute("INSERT INTO lectures(video_id, title, first_event_ts) VALUES ('python_l1', 'Python 1', 1)")
    writer.execute("INSERT INTO additions(video_id, addition_id, shape, removed) VALUES ('python_l1', 'a1', 'table', 0)")
    vectors = indexer.connect_writer(files["vectors.db"])
    vectors.execute("INSERT INTO passages(video_id, last_chunk_id, text) VALUES ('python_l1', 2, 'hello')")
    yield files, writer, tmp_path / "snapshots"
    writer.close()
    vectors.close()


def titles(path):
    conn = db.connect_readonly(path)
    try:
        return [r[0] for r in conn.execute("SELECT title FROM lectures ORDER BY first_event_ts")]
    finally:
        conn.close()


def test_save_while_the_writer_is_connected_gives_self_contained_checked_copies(live):
    files, _writer, root = live
    manifest = S.save("demo-ok", root, files)
    folder = root / "demo-ok"
    assert sorted(p.name for p in folder.iterdir()) == ["edustream.db", "manifest.json", "vectors.db"]   # no -wal
    assert manifest["lectures"] == [{"video_id": "python_l1", "title": "Python 1"}]
    assert manifest["counts"]["additions"] == 1 and manifest["counts"]["passages"] == 1
    assert json.loads((folder / "manifest.json").read_text(encoding="utf-8"))["files"] == ["edustream.db", "vectors.db"]
    assert S.list_snapshots(root)[0]["name"] == "demo-ok"
    assert "1 lecture, 0 topics, 1 additions, 1 passages" in S.summary(manifest)


def test_restore_reaches_connections_that_are_still_open_and_can_be_undone(live):
    files, writer, root = live
    S.save("demo-ok", root, files)
    writer.execute("INSERT INTO lectures(video_id, title, first_event_ts) VALUES ('stats_l1', 'Stats 1', 2)")
    reader = db.connect_readonly(files["edustream.db"])                      # the dashboard, mid-session
    try:
        assert len(reader.execute("SELECT * FROM lectures").fetchall()) == 2
        result = S.restore("demo-ok", root, files, now=0)
        assert [r[0] for r in reader.execute("SELECT title FROM lectures")] == ["Python 1"]
    finally:
        reader.close()
    assert result["undo"].startswith("before-restore-")
    writer.execute("INSERT INTO lectures(video_id, title, first_event_ts) VALUES ('w', 'After', 3)")  # sink goes on
    assert titles(files["edustream.db"]) == ["Python 1", "After"]
    assert writer.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    S.restore(result["undo"], root, files)
    assert titles(files["edustream.db"]) == ["Python 1", "Stats 1"]


def test_restore_into_an_empty_data_folder(live, tmp_path):
    files, _writer, root = live
    S.save("demo-ok", root, files)
    fresh = {"edustream.db": tmp_path / "fresh" / "edustream.db", "vectors.db": tmp_path / "fresh" / "vectors.db"}
    assert S.restore("demo-ok", root, fresh)["undo"] is None
    assert titles(fresh["edustream.db"]) == ["Python 1"]


def test_names_and_mistakes_are_refused_without_touching_anything(live):
    files, _writer, root = live
    S.save("demo-ok", root, files)
    with pytest.raises(S.SnapshotError, match="already exists"):
        S.save("demo-ok", root, files)
    for bad in ("", "../x", "a b", "-x"):
        with pytest.raises(S.SnapshotError):
            S.save(bad, root, files)
    with pytest.raises(S.SnapshotError, match="no snapshot"):
        S.restore("missing", root, files)
    assert [m["name"] for m in S.list_snapshots(root)] == ["demo-ok"]                # no undo copy was made
    S.save("demo-ok", root, files, overwrite=True)
