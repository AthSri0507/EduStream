"""Live check for the A5 flush formula with Streams crashes (PLAN M4 open note).

Plays three lectures at once that end just before / exactly on / just after a window boundary
(140 / 150 / 160 s at 10 s chunks, partitions 0 / 1 / 2) with the chosen FLUSH_FORMULA, and kills
the Streams JVM twice (whole process tree; run_component.ps1 restarts it):
  * mid-lecture (session_start + 75 s)
  * 2 s after the first flush was sent (a window was just emitted; its offsets may not be committed)
Kill times go to run/faults.csv. Afterwards run:  python -m bench.verify_run --label <label>

    .venv\\Scripts\\python -m bench.flush_crash_run --formula tight
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

from common.config import ROOT, RUN_DIR, load
from producer.lecture_source import flush_send_at

LECTURES = [("ocw6001_l01", "python_l1", 140), ("ocw6006_l01", "algorithms_ku_l1", 150),
            ("ocw6006_l02", "algorithms_demaine_l2", 160)]


def kill_streams_jvm(reason: str) -> None:
    runner = (RUN_DIR / "pids" / "streams.pid").read_text().strip()
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          f"(Get-CimInstance Win32_Process -Filter \"ParentProcessId={runner} AND Name='java.exe'\")"
                          ".ProcessId"], capture_output=True, text=True).stdout.split()
    for pid in out:
        subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True)
    now = int(time.time() * 1000)
    with (RUN_DIR / "faults.csv").open("a", encoding="utf-8") as f:
        f.write(f"{now},streams,{reason}\n")
    print(f"killed Streams JVM {out} at {now} ({reason})", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--formula", choices=["tight", "legacy"], required=True)
    args = parser.parse_args()
    settings = load()
    env = {**os.environ, "FLUSH_FORMULA": args.formula}
    procs = [subprocess.Popen([sys.executable, "-u", "-m", "producer.lecture_source", "--lecture", f"{item}={vid}",
                               "--limit-seconds", str(secs)], cwd=ROOT, env=env,
                              stdout=open(RUN_DIR / "logs" / f"src-{vid}.out", "w"), stderr=subprocess.STDOUT)
             for item, vid, secs in LECTURES]

    state_file = RUN_DIR / "lectures" / f"{LECTURES[0][1]}.json"
    while not state_file.exists():
        time.sleep(0.5)
    session_start = json.loads(state_file.read_text(encoding="utf-8"))["session_start"]
    chunk_ms = settings.chunk_wall_ms
    first_flush_sent = min(flush_send_at(session_start, secs // 10 - 1, chunk_ms, settings.window_seconds,
                                         settings.grace_seconds, args.formula) for _, _, secs in LECTURES)
    plan = [(session_start + 75_000, "mid-lecture"), (first_flush_sent + 2_000, "2 s after the first flush was sent")]
    print(f"session_start {session_start}; formula {args.formula}; kills at "
          f"{[(t - session_start) / 1000 for t, _ in plan]} s after session start", flush=True)
    for when, reason in plan:
        time.sleep(max(0.0, (when - time.time() * 1000) / 1000))
        kill_streams_jvm(reason)

    for p in procs:
        p.wait()
    print("all lectures finished:", [p.returncode for p in procs], flush=True)
    return max(p.returncode for p in procs)


if __name__ == "__main__":
    sys.exit(main())
