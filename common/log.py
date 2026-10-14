"""JSON-lines logging (ARCHITECTURE §10): run/logs/<component>.log plus a short console line."""

from __future__ import annotations

import json
import sys
import threading
import time

from common.config import RUN_DIR


class JsonLog:
    def __init__(self, component: str) -> None:
        self.component = component
        (RUN_DIR / "logs").mkdir(parents=True, exist_ok=True)
        self._file = (RUN_DIR / "logs" / f"{component}.log").open("a", encoding="utf-8")
        self._lock = threading.Lock()

    def _write(self, level: str, event: str, fields: dict) -> None:
        record = {"ts": int(time.time() * 1000), "component": self.component, "level": level, "event": event, **fields}
        line = json.dumps(record, default=str)
        detail = " ".join(f"{k}={v}" for k, v in fields.items() if k not in {"raw", "text"})
        with self._lock:
            self._file.write(line + "\n")
            self._file.flush()
            print(f"[{self.component}] {level.upper():5s} {event} {detail}", file=sys.stdout, flush=True)

    def info(self, event: str, **fields) -> None:
        self._write("info", event, fields)

    def warn(self, event: str, **fields) -> None:
        self._write("warn", event, fields)

    def error(self, event: str, **fields) -> None:
        self._write("error", event, fields)
