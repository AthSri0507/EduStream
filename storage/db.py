"""SQLite connections (ARCHITECTURE §9, A10).

Exactly one writer process (storage/db_sink.py) opens the database read-write; every other
component (dashboard, agents) uses connect_readonly(), which SQLite enforces (mode=ro).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from common.config import ROOT

SCHEMA = Path(__file__).resolve().parent / "schema.sql"


def db_path() -> Path:
    return Path(os.environ.get("EDU_DB", str(ROOT / "data" / "edustream.db")))


def connect_writer(path: Path | str | None = None) -> sqlite3.Connection:
    """Read-write connection; creates the schema if needed. ':memory:' is allowed (tests)."""
    target = str(path if path is not None else db_path())
    if target != ":memory:":
        Path(target).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=5, isolation_level=None)   # explicit BEGIN/COMMIT
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.execute("PRAGMA synchronous = NORMAL")                      # safe with WAL
    # Columns added after a database was created (CREATE TABLE IF NOT EXISTS leaves old tables alone).
    have = {row[1] for row in conn.execute("PRAGMA table_info(lectures)")}
    if "speedup" not in have:
        conn.execute("ALTER TABLE lectures ADD COLUMN speedup REAL")
    return conn


def connect_readonly(path: Path | str | None = None) -> sqlite3.Connection:
    target = Path(path if path is not None else db_path())
    conn = sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True, timeout=2)
    conn.row_factory = sqlite3.Row
    return conn
