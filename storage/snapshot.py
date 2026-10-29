"""Snapshots of the stored data, the demo's safety net (PLAN §3): save a known-good copy of both databases, and put
it back in seconds if the live run goes wrong on the day.

  * save     SQLite's backup API copies page by page under SQLite's own locks, so the copy is consistent while the
             db-sink and the indexer keep writing (a file copy of a WAL database is not). Each database becomes one
             self-contained file (journal_mode DELETE, no -wal beside it), checked with integrity_check, and
             manifest.json says what is in it.
  * restore  the same API the other way, INTO the live files: the writers' and the dashboard's open connections see
             the restored data at their next read, so nothing has to be stopped. The current data is saved first as
             "before-restore-<time>", so a restore can be undone.

A restore does not rewind Kafka. The db-sink carries on from its committed offsets, so records it stored after the
snapshot are not stored again, and a lecture that is still playing keeps writing on top. So restore with the lecture
source stopped. For a clean slate, run scripts\\reset.ps1, then start_all.ps1, then restore.

    .venv\\Scripts\\python -m storage.snapshot save demo-ok
    .venv\\Scripts\\python -m storage.snapshot list
    .venv\\Scripts\\python -m storage.snapshot restore demo-ok

Tested by tests/test_snapshot.py.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path

from common.config import ROOT
from storage.db import db_path
from storage.indexer import vectors_path

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,59}$")
MANIFEST = "manifest.json"
COUNTED = {"chunks": "SELECT COUNT(*) FROM chunks", "topics": "SELECT COUNT(*) FROM topics",
           "elements": "SELECT COUNT(*) FROM elements", "glossary": "SELECT COUNT(*) FROM glossary",
           "additions": "SELECT COUNT(*) FROM additions WHERE removed = 0"}


class SnapshotError(RuntimeError):
    pass


def snapshots_dir() -> Path:
    return Path(os.environ.get("EDU_SNAPSHOTS", str(ROOT / "data" / "snapshots")))


def live_files() -> dict[str, Path]:
    return {"edustream.db": db_path(), "vectors.db": vectors_path()}


def _open_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)


def _copy(src: Path, dst: Path, journal: str) -> None:
    """src -> dst through the backup API; dst left in the given journal mode."""
    source, target = _open_ro(src), sqlite3.connect(dst, timeout=30)
    try:
        source.backup(target)
        target.execute(f"PRAGMA journal_mode = {journal}")
    finally:
        source.close()
        target.close()


def _describe(folder: Path) -> dict:
    """What a snapshot holds: its lectures and a few counts (None for a table an older database does not have)."""
    out: dict = {"lectures": [], "counts": {}}
    main = folder / "edustream.db"
    if main.exists():
        conn = _open_ro(main)
        try:
            out["lectures"] = [{"video_id": v, "title": t} for v, t in conn.execute(
                "SELECT video_id, COALESCE(title, video_id) FROM lectures ORDER BY first_event_ts")]
            for name, sql in COUNTED.items():
                try:
                    out["counts"][name] = conn.execute(sql).fetchone()[0]
                except sqlite3.OperationalError:
                    out["counts"][name] = None
        finally:
            conn.close()
    vectors = folder / "vectors.db"
    if vectors.exists():
        conn = _open_ro(vectors)
        try:
            out["counts"]["passages"] = conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
        finally:
            conn.close()
    return out


def save(name: str, root: Path | None = None, live: dict[str, Path] | None = None, overwrite: bool = False,
         now: float | None = None) -> dict:
    """Copy the live databases into <root>/<name>/ and return its manifest."""
    if not NAME.match(name or ""):
        raise SnapshotError(f"bad snapshot name {name!r}: letters, digits, '-', '_' and '.', up to 60")
    root, live = root or snapshots_dir(), live or live_files()
    folder = root / name
    if folder.exists() and not overwrite:
        raise SnapshotError(f"snapshot {name!r} already exists (save under another name, or overwrite it)")
    present = {f: p for f, p in live.items() if p.exists()}
    if "edustream.db" not in present:
        raise SnapshotError(f"there is no database to save at {live['edustream.db']}")
    partial = root / f".{name}.partial"
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(parents=True)
    try:
        for f, path in present.items():
            _copy(path, partial / f, "DELETE")
            check = sqlite3.connect(partial / f)
            try:
                result = check.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                check.close()
            if result != "ok":
                raise SnapshotError(f"the copy of {f} failed its integrity check: {result}")
        manifest = {"name": name, "saved_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
                    "files": sorted(present), **_describe(partial)}
        (partial / MANIFEST).write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        shutil.rmtree(folder, ignore_errors=True)
        partial.rename(folder)
        return manifest
    finally:
        shutil.rmtree(partial, ignore_errors=True)


def load_manifest(name: str, root: Path | None = None) -> dict:
    path = (root or snapshots_dir()) / name / MANIFEST
    if not NAME.match(name or "") or not path.exists():
        raise SnapshotError(f"no snapshot named {name!r} (see: python -m storage.snapshot list)")
    return json.loads(path.read_text(encoding="utf-8"))


def restore(name: str, root: Path | None = None, live: dict[str, Path] | None = None,
            now: float | None = None) -> dict:
    """Put snapshot <name> into the live databases. Returns {"restored", "undo"} (undo: the snapshot of the data that
    was there before, or None when there was none)."""
    root, live = root or snapshots_dir(), live or live_files()
    manifest = load_manifest(name, root)
    undo = None
    if live["edustream.db"].exists():
        undo = save(time.strftime("before-restore-%Y%m%d-%H%M%S", time.localtime(now)), root, live,
                    overwrite=True, now=now)["name"]
    for f in manifest["files"]:
        live[f].parent.mkdir(parents=True, exist_ok=True)
        _copy(root / name / f, live[f], "WAL")
    return {"restored": name, "undo": undo}


def list_snapshots(root: Path | None = None) -> list[dict]:
    root = root or snapshots_dir()
    if not root.exists():
        return []
    found = []
    for folder in root.iterdir():
        if folder.is_dir() and (folder / MANIFEST).exists():
            found.append(json.loads((folder / MANIFEST).read_text(encoding="utf-8")))
    return sorted(found, key=lambda m: m["saved_at"])


def summary(manifest: dict) -> str:
    c = manifest.get("counts", {})
    n = len(manifest.get("lectures", []))
    parts = [f"{n} lecture" + ("" if n == 1 else "s")] + [
        f"{c[k]} {k}" for k in ("topics", "additions", "passages") if c.get(k) is not None]
    return f"{manifest['name']:<32} {manifest['saved_at']}   " + ", ".join(parts)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("save", help="save the live databases as a snapshot")
    s.add_argument("name")
    s.add_argument("--overwrite", action="store_true")
    sub.add_parser("restore", help="put a snapshot back into the live databases").add_argument("name")
    sub.add_parser("list", help="the saved snapshots")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "save":
            manifest = save(args.name, overwrite=args.overwrite)
            print(f"saved   {summary(manifest)}")
            for lec in manifest["lectures"]:
                print(f"          {lec['title']}")
        elif args.cmd == "restore":
            result = restore(args.name)
            print(f"restored {summary(load_manifest(args.name))}")
            if result["undo"]:
                print(f"the data from before is saved as {result['undo']} (restore that to undo)")
            print("the dashboard shows it at its next refresh")
        else:
            snaps = list_snapshots()
            print("\n".join(summary(m) for m in snaps) if snaps else f"no snapshots in {snapshots_dir()}")
    except (SnapshotError, sqlite3.Error) as exc:
        print(f"snapshot: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
