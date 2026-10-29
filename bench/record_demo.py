"""The backup recording of the demo (PLAN §3: "If the live run fails: play the backup recording, then load the DB
snapshot into the dashboard").

A headless browser plays the demo script on the dashboard while the real pipeline runs a clean session with two live
lectures. Frames are captured and joined into an MP4; waits are fast-forwarded and marked on screen ("8x"). The
terminal steps (start the source, kill a worker, send a malformed record) run from here and are captioned at the top
of the video, so nothing on screen is staged.

Output in data/recordings/<date>/:
  demo.mp4        the recording
  chapters.md     where each block starts in the video (to skip to it during the review)
  notes_*.pdf/.docx/.md  the finished notes, downloaded with the dashboard's own buttons
  record.log      what happened, with the times
and a DB snapshot "recording-<date>" that matches the end of the video (scripts\\snapshot.ps1 restore ...).

Dev only: needs `pip install playwright imageio-ffmpeg` (not in requirements). Uses about one demo's Groq quota
(PLAN §3 quota rule: not on the demo day or the day before).

    .venv\\Scripts\\python -m bench.record_demo --reset     # reset.ps1 -Force, start_all -Workers 3, then record
    .venv\\Scripts\\python -m bench.record_demo --smoke     # 20 s of the running dashboard: checks the recorder
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import imageio_ffmpeg
from playwright.async_api import Page, async_playwright

from common.config import ROOT
from dashboard import queries
from storage import snapshot
from storage.db import connect_readonly, db_path

URL = "http://localhost:8501"
VIEW = {"width": 1600, "height": 960}
FPS = 4                          # captured frames per second of real time at 1x
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
LECTURES = [("ocw6001_l01", "python_l1"), ("ocw6006_l01", "algorithms_ku_l1")]
LIMIT_S = 900                    # media seconds per lecture, as in the demo (PLAN §3 block 2)
SHOWN = "python_l1"              # the lecture the notebook and the assistant blocks use

CAPTION_JS = """([text, speed]) => {
  let el = document.getElementById('rec-cap');
  if (!el) {
    el = document.createElement('div'); el.id = 'rec-cap'; document.body.appendChild(el);
    Object.assign(el.style, {position: 'fixed', top: '10px', left: '50%', transform: 'translateX(-50%)',
      maxWidth: '72%', zIndex: 999999, background: 'rgba(17,24,39,.9)', color: '#fff', borderRadius: '10px',
      font: '500 16px/1.45 system-ui, Segoe UI, sans-serif', padding: '8px 16px', pointerEvents: 'none',
      boxShadow: '0 4px 18px rgba(0,0,0,.25)'});
  }
  const badge = speed > 1 ? `<span style="background:#f59e0b;color:#111;border-radius:6px;padding:1px 7px;
    margin-right:10px;font-weight:700">${speed}x</span>` : '';
  const html = badge + text;
  if (el.dataset.html !== html) { el.innerHTML = html; el.dataset.html = html; }
  el.style.display = text ? 'block' : 'none';
}"""


class Recorder:
    """Screenshots at FPS (fewer while fast-forwarding), each kept with its real time and speed, then one MP4 in which a
    frame lasts its real time divided by the speed."""

    def __init__(self, page: Page, folder: Path, log):
        self.page, self.frames_dir, self.log = page, folder / "frames", log
        self.frames: list[tuple[float, Path, int]] = []
        self.speed, self.text, self.video_t = 1, "", 0.0
        self._stop = False
        shutil.rmtree(self.frames_dir, ignore_errors=True)
        self.frames_dir.mkdir(parents=True)

    async def run(self) -> None:
        while not self._stop:
            start = time.monotonic()
            path = self.frames_dir / f"f{len(self.frames):06d}.jpg"
            try:
                await self.page.evaluate(CAPTION_JS, [self.text, self.speed])
                await self.page.screenshot(path=str(path), type="jpeg", quality=82)
                if self.frames:
                    prev_t, _, prev_speed = self.frames[-1]
                    self.video_t += (start - prev_t) / prev_speed
                self.frames.append((start, path, self.speed))
            except Exception as exc:  # noqa: BLE001 - a frame lost during a page rerun is harmless
                self.log(f"frame skipped: {type(exc).__name__}")
            await asyncio.sleep(max(0.0, self.speed / FPS - (time.monotonic() - start)))

    def stop(self) -> None:
        self._stop = True

    def encode(self, out: Path) -> None:
        listing = self.frames_dir / "frames.txt"
        lines = []
        for (t, path, speed), nxt in zip(self.frames, self.frames[1:] + [None]):
            duration = ((nxt[0] - t) if nxt else 1.0) / speed
            lines += [f"file '{path.as_posix()}'", f"duration {max(duration, 0.04):.3f}"]
        lines.append(f"file '{self.frames[-1][1].as_posix()}'")              # the concat demuxer drops the last one
        listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                        "-i", str(listing), "-vf", "fps=25,format=yuv420p", "-c:v", "libx264", "-crf", "20",
                        "-preset", "medium", "-movflags", "+faststart", str(out)], check=True)


class Demo:
    def __init__(self, page: Page, rec: Recorder, folder: Path, log):
        self.page, self.rec, self.folder, self.log = page, rec, folder, log
        self.chapters: list[tuple[float, str]] = []

    # ------------------------------------------------------------------ showing
    def caption(self, text: str, speed: int = 1) -> None:
        self.rec.text, self.rec.speed = text, speed
        self.log(f"caption [{speed}x] {re.sub('<[^>]+>', '', text)}")

    def chapter(self, title: str) -> None:
        self.chapters.append((self.rec.video_t, title))
        self.log(f"chapter {title}")

    async def hold(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    async def tab(self, name: str) -> None:
        try:
            await self.page.get_by_role("tab", name=name, exact=True).click(timeout=10_000)
            await self.page.evaluate("() => document.activeElement && document.activeElement.blur()")  # no red outline
            await asyncio.sleep(2.0)
        except Exception as exc:  # noqa: BLE001 - keep recording
            self.log(f"tab {name} failed: {exc!r}")

    async def select(self, key: str, option: str) -> None:
        """A selectbox by its Streamlit key (its label text is aria-hidden, so it cannot be matched by label)."""
        try:
            box = self.page.locator(f'.st-key-{key} [data-testid="stSelectbox"] [role="combobox"]').first
            await box.click(timeout=10_000)
            await self.page.get_by_role("option", name=re.compile(option)).first.click(timeout=10_000)
            await asyncio.sleep(2.0)
        except Exception as exc:  # noqa: BLE001
            self.log(f"select {key}={option} failed: {exc!r}")
            await self.page.keyboard.press("Escape")

    async def scroll(self, x: int, y: int, steps: int, dy: int = 300, pause: float = 1.2) -> None:
        await self.page.mouse.move(x, y)
        for _ in range(steps):
            await self.page.mouse.wheel(0, dy)
            await asyncio.sleep(pause)

    async def to_top(self) -> None:
        await self.page.mouse.move(500, 500)
        await self.page.mouse.wheel(0, -20_000)
        await asyncio.sleep(0.8)

    async def ask(self, text: str, wait_s: float = 120) -> None:
        """Type into the assistant's chat like a person and wait until the answer is shown."""
        box = self.page.get_by_placeholder("Ask about the lecture")
        try:
            await box.click(timeout=10_000)
            await box.press_sequentially(text, delay=45)
            await asyncio.sleep(0.6)
            await box.press("Enter")
            await asyncio.sleep(3.0)
            deadline = time.monotonic() + wait_s
            while time.monotonic() < deadline and not await box.is_enabled():
                await asyncio.sleep(0.5)
            await asyncio.sleep(1.0)
            await self.scroll(1290, 500, 6, dy=600, pause=0.25)              # the chat's own scroll box
        except Exception as exc:  # noqa: BLE001
            self.log(f"ask {text!r} failed: {exc!r}")

    # ------------------------------------------------------------------ waiting on the pipeline
    def db(self, fn, default=None):
        try:
            conn = connect_readonly(db_path())
            try:
                return fn(conn)
            finally:
                conn.close()
        except (sqlite3.Error, KeyError, IndexError):
            return default

    async def until(self, what: str, test, timeout_s: float) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.db(test, False):
                self.log(f"reached: {what}")
                return True
            await asyncio.sleep(2.0)
        self.log(f"TIMEOUT waiting for: {what}")
        return False


def one(conn, sql, *args):
    return conn.execute(sql, args).fetchone()[0]


def finished(conn, video_id):
    return queries.notebook(conn, video_id)["finished"]


def run_ps(script: str, *args: str, log) -> None:
    env = {**os.environ, "LLM_ENABLED": "true"}
    out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                          str(ROOT / "scripts" / script), *args], cwd=ROOT, env=env, capture_output=True, text=True,
                         timeout=600)
    log(f"{script} {' '.join(args)} -> exit {out.returncode}\n{(out.stdout + out.stderr).strip()[-1500:]}")


def wait_http(url: str, timeout_s: float) -> bool:
    import urllib.request
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(1.0)
    return False


async def script(d: Demo, source_cmd: list[str], log) -> None:
    """PLAN §3, blocks 2-8, on the dashboard."""
    page = d.page
    d.chapter("Start: a clean pipeline")
    d.caption("EduStream · backup recording of the demo · a clean run: <b>reset.ps1</b>, then "
              "<b>start_all.ps1 -Workers 3</b> (broker, Streams, 3 Whisper workers, Note Agent, db-sink, indexer)")
    await d.hold(7)

    d.chapter("Block 2: two live lectures on their own partitions")
    d.caption("Terminal: <b>python -m producer.lecture_source --lecture ocw6001_l01=python_l1 "
              "--lecture ocw6006_l01=algorithms_ku_l1 --limit-seconds 900</b>")
    source = subprocess.Popen(source_cmd, cwd=ROOT, stdout=open(d.folder / "source.log", "w", encoding="utf-8"),
                              stderr=subprocess.STDOUT)
    t0 = time.monotonic()
    await d.until("2 lectures", lambda c: one(c, "SELECT COUNT(*) FROM lectures") >= 2, 120)
    await asyncio.sleep(3)
    await d.tab("Pipeline health")
    d.caption("Pipeline health: each lecture is on its own partition (key = video_id), each partition owned by one "
              "transcription worker; completeness and consumer lag per partition")
    await d.hold(22)

    d.chapter("Block 3: 30 s tumbling windows")
    d.caption("Waiting for the first 30 s windows to close (Kafka Streams: tumbling window, grace, suppress)", 4)
    await d.until("windows", lambda c: one(c, "SELECT COUNT(*) FROM window_latest") >= 2, 240)
    await d.tab("Window stats")
    d.caption("Window stats: one result per closed window · words per minute, Whisper score min/avg/max, top terms")
    await d.hold(20)

    d.chapter("Block 4: live notes")
    await d.tab("Notebook")
    await d.select("notes_lecture", "Python")
    d.caption("The notebook: waiting for the first live notes (every 90 s of lecture, gpt-oss-20b)", 8)
    await d.until("first live notes", lambda c: one(c, "SELECT COUNT(*) FROM live_updates WHERE video_id = ?",
                                                     SHOWN) >= 1, 420)
    await asyncio.sleep(4)
    d.caption("Live notes (dashed box): up to 2 new study-guide elements every 90 s; every sentence is checked against "
              "what was said around it · hover a margin time for the words said")
    await d.hold(10)
    await d.scroll(600, 600, 4)
    await d.hold(6)
    await d.to_top()

    d.chapter("Block 4: the first topic")
    d.caption("Waiting for the first consolidation: the live drafts become a topic (about every 6 min, gpt-oss-120b)", 8)
    await d.until("first topic", lambda c: one(c, "SELECT COUNT(*) FROM topics WHERE video_id = ?", SHOWN) >= 1, 900)
    await asyncio.sleep(5)
    d.caption("A topic: a title, paragraphs with run-in leads, examples or steps only where the lecturer gave them, "
              "a check-yourself question; glossary terms in the rail; its drafts leave the live box")
    await d.hold(8)
    await d.scroll(600, 600, 7)
    await d.hold(5)
    await d.to_top()

    d.chapter("Block 5: storage you can query")
    await d.tab("Data")
    d.caption("The Data tab: SQLite, read-only; ready-made queries or your own SELECT")
    await d.select("data_query", "Notebook: topics")
    try:
        await page.get_by_role("button", name="Run query").click(timeout=10_000)
    except Exception as exc:  # noqa: BLE001
        log(f"run query failed: {exc!r}")
    await d.hold(14)

    d.chapter("Block 6: the Lecture Assistant")
    await d.tab("Notebook")
    await d.select("notes_lecture", "Python")
    d.caption("The Lecture Assistant: a plain chat · the switch “Use general knowledge” starts <b>off</b> "
              "(answers only from what was said)")
    await d.hold(4)
    await d.ask("I didn't get the last 10 seconds")
    d.caption("A short answer with [mm:ss] times; hover a time for the words said")
    await d.hold(7)
    await d.ask("summarise the last 5 minutes")
    await d.hold(7)
    d.caption("A term the lecture does not explain, with the switch off:")
    await d.ask("what is a p-value?")
    await d.hold(6)
    d.caption("Switch on: the lecture part first, then general knowledge, always labelled “Beyond the lecture”")
    try:
        await page.get_by_text("Use general knowledge", exact=True).click(timeout=10_000)
    except Exception as exc:  # noqa: BLE001
        log(f"switch failed: {exc!r}")
    await d.hold(2)
    await d.ask("what is a p-value?")
    await d.hold(8)
    await part_b(d, source, t0, log)


async def part_b(d: Demo, source, t0: float, log) -> None:
    """From the figures step to the end (also the --resume entry point: source None, the lectures already playing)."""
    page = d.page
    if source is None:
        await d.tab("Notebook")
    d.caption("Figures: ask for a table, worked steps, a flowchart, a concept map or a timeline; "
              "it is drawn, then offered for the notes")
    await d.ask("create a mind map of what has been covered so far")
    await d.hold(8)
    await d.ask("yes")
    d.caption("Saved into the notes, under the topic it belongs to (marked as your addition; ✕ removes it, "
              "↻ redraws it)")
    await d.hold(4)
    await d.scroll(600, 600, 8, pause=0.9)
    await d.hold(4)
    await d.to_top()

    d.chapter("Block 7: fault recovery")
    await d.tab("Pipeline health")
    d.caption("F1 · Terminal: <b>scripts\\kill.ps1 -Name w2</b> (a worker stopped for good): Kafka moves its "
              "partition to another worker of the group")
    run_ps("kill.ps1", "-Name", "w2", log=log)
    await d.hold(15)
    d.caption("F1 · partition reassigned; a CONSUMER_LAG alert may fire while it catches up; completeness stays 100%", 2)
    await d.hold(40)
    d.caption("F1 · Terminal: <b>scripts\\start_all.ps1 -Workers 3</b> starts only what is missing: w2 rejoins")
    run_ps("start_all.ps1", "-Workers", "3", log=log)
    await d.hold(10)
    d.caption("F4 · Terminal: <b>python -m tools.send_malformed</b>: poison records go to the dead-letter queue, the "
              "pipeline is unaffected")
    out = subprocess.run([PY, "-m", "tools.send_malformed"], cwd=ROOT, capture_output=True, text=True, timeout=120)
    log(f"send_malformed -> exit {out.returncode} {out.stdout.strip()[-400:]}")
    await d.hold(6)
    await d.scroll(800, 600, 4)
    await d.hold(8)
    await d.to_top()
    await d.tab("Alerts")
    d.caption("Alerts: LOW_ASR_SCORE, SILENCE, CONSUMER_LAG · LATE_DROP stays 0")
    await d.hold(10)

    d.chapter("Block 8: the lectures end, the notes are finished")
    await d.tab("Notebook")
    await d.select("notes_lecture", "Python")
    d.caption("Waiting for the lectures to end: the flush closes the last window, then the last consolidation "
              "finishes the notes", 8)
    remaining = LIMIT_S + 60 - (time.monotonic() - t0)
    if source is not None:
        await d.until("source done", lambda c: source.poll() is not None, max(remaining, 0) + 600)
    else:
        await d.until("lectures flushed", lambda c: one(c, "SELECT COUNT(*) FROM lectures WHERE flushed_ts IS NOT "
                                                           "NULL") >= len(LECTURES), 1500)
    await d.until("both finished", lambda c: all(finished(c, v) for _, v in LECTURES), 900)
    await asyncio.sleep(5)
    d.caption("Finished: every topic of the lecture, with the student's addition where it belongs")
    await d.hold(5)
    await d.scroll(600, 600, 14, pause=1.0)
    await d.hold(3)
    await d.to_top()
    d.caption("Download the notes: Markdown, Word, PDF (answers to the check-yourself questions at the end)")
    for name in ("PDF", "Word", "Markdown"):
        try:
            async with page.expect_download(timeout=60_000) as info:
                await page.get_by_role("button", name=name).first.click(timeout=10_000)
            dl = await info.value
            await dl.save_as(str(d.folder / dl.suggested_filename))
            log(f"downloaded {dl.suggested_filename}")
        except Exception as exc:  # noqa: BLE001
            log(f"download {name} failed: {exc!r}")
        await asyncio.sleep(2)
    await d.select("notes_lecture", "Algorithms")
    d.caption("The second lecture, on its own partition, finished the same way")
    await d.hold(6)
    await d.scroll(600, 600, 5, pause=1.0)
    await d.to_top()
    await d.tab("Pipeline health")
    d.caption("Completeness 100% for both lectures · the DB snapshot of this moment is saved with the recording")
    await d.hold(10)
    d.chapter("End")
    d.caption("End of the backup recording")
    await d.hold(3)


async def main_async(args) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")      # a caption's ✕ crashed a cp1252 console (29 Oct)
    day = date.today().isoformat()
    folder = ROOT / "data" / "recordings" / (day if not args.smoke else f"{day}-smoke") / ("part2" if args.resume else "")
    folder.mkdir(parents=True, exist_ok=True)
    logfile = open(folder / "record.log", "a", encoding="utf-8")

    def log(msg: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        print(line, flush=True)
        logfile.write(line + "\n")
        logfile.flush()

    if args.reset:
        if db_path().exists():
            log(f"saved {snapshot.save('before-recording-' + day, overwrite=True)['name']}")
        run_ps("reset.ps1", "-Force", log=log)
        run_ps("preflight.ps1", log=log)
    if not args.smoke and not args.resume:
        run_ps("start_all.ps1", "-Workers", "3", log=log)
    if not wait_http(f"{URL}/_stcore/health", 120):
        log("the dashboard is not up")
        return 1

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        context = await browser.new_context(viewport=VIEW, accept_downloads=True)
        page = await context.new_page()
        await page.goto(f"{URL}/?tab=Notebook", wait_until="domcontentloaded")
        await page.wait_for_selector('[data-testid="stApp"]', timeout=60_000)
        await asyncio.sleep(4)
        rec = Recorder(page, folder, log)
        demo = Demo(page, rec, folder, log)
        task = asyncio.create_task(rec.run())
        try:
            if args.smoke:
                demo.chapter("Smoke test")
                demo.caption("Smoke test of the recorder: the running dashboard")
                await demo.hold(6)
                await demo.tab("Pipeline health")
                demo.caption("Fast-forward mark", 8)
                await demo.hold(12)
            elif args.resume:
                await part_b(demo, None, time.monotonic(), log)
            else:
                cmd = [PY, "-m", "producer.lecture_source", "--limit-seconds", str(LIMIT_S)]
                for item, vid in LECTURES:
                    cmd += ["--lecture", f"{item}={vid}"]
                await script(demo, cmd, log)
        finally:
            rec.stop()
            await task
            await browser.close()

    out = folder / "demo.mp4"
    rec.encode(out)
    lines = [f"# Backup recording, {day}", "", f"Video: `{out.name}` ({rec.video_t / 60:.1f} min)", "",
             "| Time | Block |", "|---|---|"]
    lines += [f"| {int(t) // 60:02d}:{int(t) % 60:02d} | {title} |" for t, title in demo.chapters]
    (folder / "chapters.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    shutil.rmtree(rec.frames_dir, ignore_errors=True)
    log(f"video {out} ({out.stat().st_size / 1e6:.1f} MB, {rec.video_t / 60:.1f} min)")
    if not args.smoke:
        log(f"saved snapshot {snapshot.save('recording-' + day, overwrite=True)['name']}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="snapshot, reset.ps1 -Force, preflight, then start")
    parser.add_argument("--resume", action="store_true", help="part 2 only, from the figures step (lectures playing)")
    parser.add_argument("--smoke", action="store_true", help="20 s of the running dashboard (checks the recorder)")
    return asyncio.run(main_async(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
