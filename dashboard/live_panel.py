"""Live class control (sidebar): record an online class (Zoom, Meet, Teams) that this laptop has joined, see that
sound arrives, and stop it.

The recording is producer/live_source.py in its own minimised window (scripts/run_component.ps1, pid file
run/pids/live.pid, so stop_all.ps1 and kill.ps1 -Name live reach it), and it keeps going if the dashboard reloads.
Start hands its options over in run/live/<video_id>.json (titles with spaces and symbols survive). Stop writes
run/lectures/<video_id>.stop: the source ends the lecture cleanly (flush, then the Note Agent finishes the notes).
The status comes from the source's state file, rewritten every 10 s chunk.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time

import streamlit as st

from common.config import ROOT, load
from producer.lecture_source import STATE_DIR, active_lectures
from producer.live_source import SILENCE_RMS, dbfs, free_video_id

REQUEST_DIR = ROOT / "run" / "live"
PID_FILE = ROOT / "run" / "pids" / "live.pid"
RUNNER = ROOT / "scripts" / "run_component.ps1"
FRESH_S = 30                         # a state file older than this: the source is gone
FINISHED_SHOWN_S = 300


@st.cache_data(ttl=60, show_spinner=False)
def audio_devices() -> dict:
    """Asked of a child process: the dashboard's own threads never load Windows audio (COM)."""
    out = subprocess.run([sys.executable, "-m", "producer.live_source", "--list-devices", "--json"], cwd=ROOT,
                         capture_output=True, text=True, encoding="utf-8", timeout=60)
    lines = [ln for ln in out.stdout.splitlines() if ln.startswith("{")]
    return json.loads(lines[-1]) if lines else {"speakers": [], "default_speaker": None, "mics": [], "default_mic": None}


def latest_live() -> dict | None:
    """The newest live lecture's state (run/lectures/*.json with item_id "live")."""
    best = None
    for path in STATE_DIR.glob("*.json"):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if state.get("item_id") == "live" and (best is None or state.get("updated_ts", 0) > best.get("updated_ts", 0)):
            best = state
    return best


def phase(state: dict | None, now_ms: int) -> str:
    """idle | recording | stopping | finished"""
    if state is None:
        return "idle"
    age = (now_ms - state.get("updated_ts", 0)) / 1000
    if state.get("status") == "active" and age < FRESH_S:
        return "stopping" if (STATE_DIR / f"{state['video_id']}.stop").exists() else "recording"
    if state.get("status") == "flushed" and age < FINISHED_SHOWN_S:
        return "finished"
    return "idle"


def start(title: str, device: str | None, with_mic: bool) -> str:
    settings = load()
    title = title.strip() or f"Live lecture {time.strftime('%d %b %H:%M')}"
    video_id = free_video_id(title, settings.partitions, active_lectures(int(time.time() * 1000)))
    REQUEST_DIR.mkdir(parents=True, exist_ok=True)
    request = REQUEST_DIR / f"{video_id}.json"
    request.write_text(json.dumps({"video_id": video_id, "title": title[:120], "device": device,
                                   "with_mic": "" if with_mic else None}, ensure_ascii=False), encoding="utf-8")
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = 7                                  # minimised, not focused
    proc = subprocess.Popen(["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", str(RUNNER), "-Name", "live",
                             "-Module", "producer.live_source",
                             "-ModuleArgs", f"--request {request.relative_to(ROOT).as_posix()}"],
                            cwd=ROOT, creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=info)
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(proc.pid))
    st.session_state["live_started"] = (video_id, time.time())
    st.session_state["follow_live"] = video_id            # app.py opens its notes once its first chunk is stored
    return video_id


def stop(video_id: str) -> None:
    (STATE_DIR / f"{video_id}.stop").touch()


@st.fragment(run_every="2s")
def status() -> None:
    now_ms = int(time.time() * 1000)
    state = latest_live()
    now = phase(state, now_ms)
    started = st.session_state.get("live_started")
    if now == "idle" and started and time.time() - started[1] < 60:
        st.info("Starting: the recording begins at the next 30-second mark …")
        now = "starting"
    elif now == "idle" and started and time.time() - started[1] < 600:
        st.error("The live class did not start. The window 'edustream-live' (minimised) says why; is the pipeline "
                 "running (scripts\\start_all.ps1)?")
    if st.session_state.get("live_phase") not in (None, now) and now != "starting":
        st.session_state["live_phase"] = now
        st.rerun(scope="app")                             # show / hide the start form
    st.session_state["live_phase"] = now
    if now in ("recording", "stopping"):
        minutes = (state.get("last_chunk_sent", -1) + 1) * 10 / 60
        level = state.get("level_dbfs")
        st.markdown(f"🔴 **Recording** · {state.get('title', state['video_id'])}")
        st.caption(f"{minutes:.1f} min · sound {level if level is not None else '–'} dBFS"
                   + (f" · {state['gaps_s']:.0f} s of gaps" if state.get("gaps_s") else ""))
        if level is not None and level < dbfs(SILENCE_RMS) and minutes >= 0.5:
            st.warning("No sound right now. Is the class playing on this laptop, on the device chosen below "
                       f"({', '.join(state.get('devices', []))})?")
        if now == "stopping":
            st.info("Stopping: the last window closes in about 30 s, then the notes are finished.")
        else:
            st.button("Stop and finish the notes", type="primary", on_click=stop, args=(state["video_id"],),
                      key="live_stop", width="stretch")
    elif now == "finished":
        st.success(f"Finished · {state.get('title', state['video_id'])}: the notes are being completed in the "
                   f"Notebook tab.")


def panel() -> None:
    st.subheader("Live class")
    status()
    if st.session_state.get("live_phase") in ("recording", "stopping", "starting"):
        return
    devices = audio_devices()
    with st.form("live_start", border=False):
        title = st.text_input("Title", placeholder="e.g. DBMS · Unit 3", max_chars=120)
        speakers = devices["speakers"]
        device = st.selectbox("Record what plays on", speakers,
                              index=speakers.index(devices["default_speaker"])
                              if devices["default_speaker"] in speakers else 0,
                              help="Where this laptop plays the meeting's sound (speaker or headphones)")
        with_mic = st.checkbox("Also record my microphone", help="Tick this if you are the lecturer on this laptop: "
                                                                  "Zoom/Meet/Teams don't play your own voice back")
        go = st.form_submit_button("Start live class", type="primary", width="stretch", disabled=not speakers)
    if go:
        try:
            start(title, device, with_mic)
            st.rerun(scope="app")
        except SystemExit as exc:                          # every partition busy (S1)
            st.error(str(exc))
    st.caption("Join the class in Zoom, Meet or Teams on this laptop first. The notes appear in the Notebook tab "
               "about a minute after it starts.")
