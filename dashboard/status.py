"""The status row at the top of every page and the live browser-tab title (docs/UI_DESIGN.md §3, §4).

One 2 s fragment, separate from the notes and the assistant (the fragment rule). It shows at most one state:
listening, no sound, quiet, paused, finished or nothing. The tab title follows it ("Listening 16:30 - EduStream"),
set by a tiny st.components.v2 component: components run in the page, so they can set document.title on every
refresh, whereas st.set_page_config inside a refreshing fragment stopped updating after its first run (30 Oct).
"""

from __future__ import annotations

import html
import sqlite3
import time

import streamlit as st

from dashboard import live_panel
from dashboard.notebook_html import NBSP, duration, keep_together
from producer.live_source import SILENCE_RMS, dbfs
from storage.db import connect_readonly, db_path

QUIET_DBFS = -42.0          # above silence but too quiet for good notes (loopback speech sits around -30 to -20)
RECORDER_STALE_S = 30       # the recorder rewrites its state every 10 s
NOTES_STALE_S = 60          # a live lecture with nothing new stored for a minute: the notes are paused
ABANDONED_S = 1800          # an unfinished lecture silent for 30 minutes is history, not "paused"
SITE = "EduStream"

CSS = """
.es{--ink:var(--es-ink,#1F2430);--pencil:var(--es-secondary,#55596A);--live:var(--es-live,#0B6B49);
--fault:var(--es-fault,#B42318);--caution:var(--es-caution,#8A5300);
display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;font-family:'Fira Sans',system-ui,sans-serif;
color:var(--ink);font-size:15px;line-height:1.5;margin:0}
.es .state{font-weight:600;display:inline-flex;align-items:center;gap:7px}
.es .dot{width:9px;height:9px;border-radius:50%;background:currentColor;display:inline-block}
.es .listening{color:var(--live)}.es .no_sound,.es .paused{color:var(--fault)}.es .quiet{color:var(--caution)}
.es .finished{color:var(--ink)}
.es .detail{color:var(--pencil)}.es .warn{font-weight:600}.es .no_sound+.detail,.es .paused+.detail{color:var(--fault)}
.es .quiet+.detail{color:var(--caution)}
.es .lecture{margin-left:auto;color:var(--pencil)}
.es .nw{white-space:nowrap}
"""

# Streamlit resets document.title to the page_title on its own reruns; a MutationObserver on <title> puts the live
# title back whenever that happens (found 30 Oct: the title stayed "EduStream" on the default page).
# The theme probe: a theme chosen in Streamlit's menu (System / Light / Dark) changes Streamlit's colours at once but
# does not rerun Python, so our --es-* variables would stay on the old theme. The text colour Streamlit gives this
# component (inherited, light text = dark theme) sets <html data-es-theme>, which dashboard/theme.py keys its
# variables on. Checked every 400 ms; no Streamlit class names involved.
TITLE_JS = """
export default function (component) {
  try { setup(component) } catch (e) { console.warn("edustream page hooks:", e) }   // never a red error box
}
function setup(component) {
  const { data, parentElement } = component
  window.__eduTitle = data && data.title
  const apply = () => {
    if (window.__eduTitle && document.title !== window.__eduTitle) document.title = window.__eduTitle
  }
  apply()
  const el = document.querySelector("title")
  if (el && !window.__eduTitleWatch) {
    window.__eduTitleWatch = new MutationObserver(apply)
    window.__eduTitleWatch.observe(el, {childList: true, characterData: true, subtree: true})
  }
  // parentElement can be a shadow root (styles are isolated): measure the <span> this component renders
  window.__eduProbe = (parentElement && parentElement.querySelector && parentElement.querySelector("span"))
    || (parentElement && parentElement.host) || parentElement
  const theme = () => {
    const probe = window.__eduProbe
    if (!probe || !probe.isConnected || !(probe instanceof Element)) return
    let rgb
    try { rgb = (getComputedStyle(probe).color.match(/[0-9.]+/g) || [0, 0, 0]).map(Number) } catch (e) { return }
    const t = (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255 > 0.5 ? "dark" : "light"
    if (document.documentElement.dataset.esTheme !== t) document.documentElement.dataset.esTheme = t
  }
  theme()
  if (!window.__eduThemeTimer) window.__eduThemeTimer = setInterval(theme, 400)
}
"""


def _declare():
    return st.components.v2.component("edustream_tab_title", html="<span></span>", js=TITLE_JS)


_TITLE = _declare()


def set_tab_title(title: str) -> None:
    """Mount the title component. Declared once at import; a new Streamlit runtime in the same process (the test
    runner starts one per test) has an empty registry, so it is declared again there."""
    global _TITLE
    try:
        _TITLE(key="tab_title", data={"title": title})
    except Exception as exc:  # noqa: BLE001 - StreamlitAPIException: "Component ... is not registered."
        if "not registered" not in str(exc):
            raise
        _TITLE = _declare()
        _TITLE(key="tab_title", data={"title": title})


def device_label(name: str) -> str:
    """A device name that never wraps mid-name: no-break spaces and non-breaking hyphens (both fonts have them)."""
    return name.replace("-", "‑").replace(" ", NBSP)


def audio_warning(state: dict | None, now_ms: int) -> tuple[str, str] | None:
    """At most one warning from the live recorder's state (docs/UI_DESIGN.md §4): when the recorder has stopped
    updating, only "paused" (its last sound reading is out of date); otherwise no sound before quiet."""
    if not state or state.get("status") != "active":
        return None
    age = (now_ms - state.get("updated_ts", 0)) / 1000
    if age >= RECORDER_STALE_S:
        return "paused", (f"Recording paused: nothing new from the recorder for {int(age)} s. Is the live recorder "
                          f"still open on the taskbar?")
    level = state.get("level_dbfs")
    if level is None or state.get("last_chunk_sent", -1) < 2:           # the first 30 s: no judgement yet
        return None
    where = " or ".join(device_label(d) for d in state.get("devices") or []) or "this laptop"
    if level < dbfs(SILENCE_RMS):
        return "no_sound", f"No sound right now. Is the class playing on {where}?"
    if level < QUIET_DBFS:
        return "quiet", "The sound is very quiet. Turn the class volume up."
    return None


def lecture_state(conn: sqlite3.Connection, now_ms: int) -> dict | None:
    """The lecture the status is about: the newest unfinished one that stored something in the last 30 minutes,
    else the newest lecture (finished)."""
    rows = conn.execute(
        "SELECT l.video_id, COALESCE(l.title, l.video_id), l.flushed_ts, MAX(c.sink_ts), MAX(c.end_time)"
        " FROM lectures l LEFT JOIN chunks c ON c.video_id = l.video_id GROUP BY l.video_id"
        " ORDER BY MAX(c.sink_ts) DESC").fetchall()
    for vid, title, flushed, sink, said in rows:
        if flushed is None and sink is not None and now_ms - sink < ABANDONED_S * 1000:
            age = (now_ms - sink) / 1000
            return {"video_id": vid, "title": title, "live": True, "said": said or 0.0, "age": age}
    if rows:
        vid, title, _, _, said = rows[0]
        return {"video_id": vid, "title": title, "live": False, "said": said or 0.0, "age": None}
    return None


def compute(now_ms: int, lecture: dict | None, recorder: dict | None) -> dict:
    """kind, label, detail and tab title: one state, one warning at most."""
    if lecture is None:
        return {"kind": "idle", "label": "", "detail": "", "title": SITE, "lecture": ""}
    if not lecture["live"]:                    # nothing running: no row (a finished lecture is said on In class)
        return {"kind": "finished", "label": "", "detail": "", "title": SITE, "lecture": ""}
    warning = audio_warning(recorder, now_ms) if recorder and recorder.get("video_id") == lecture["video_id"] else None
    if warning is None and lecture["age"] >= NOTES_STALE_S:
        m, s = divmod(int(lecture["said"]), 60)
        warning = ("paused", f"Notes paused since {m:02d}:{s:02d}. Restart EduStream on this laptop "
                             f"(scripts\\start_all.ps1).")
    if warning:
        kind, text = warning
        label = {"no_sound": "No sound", "quiet": "Quiet", "paused": "Paused"}[kind]
        return {"kind": kind, "label": label, "detail": text, "title": f"{label} - {SITE}",
                "lecture": lecture["title"]}
    m, s = divmod(int(lecture["said"]), 60)
    return {"kind": "listening", "label": "Listening", "detail": f"{duration(lecture['said'])} into the class",
            "title": f"Listening {m:02d}:{s:02d} - {SITE}", "lecture": lecture["title"]}


def row_html(st_: dict) -> str:
    e = lambda t: html.escape(keep_together(t))
    state = (f'<span class="state {st_["kind"]}"><span class="dot"></span>{e(st_["label"])}</span>'
             f'<span class="detail">{e(st_["detail"])}</span>') if st_["label"] else ""
    lecture = f'<span class="lecture">{e(st_["lecture"])}</span>' if st_["lecture"] else ""
    return f'<style>{CSS}</style><div class="es">{state}{lecture}</div>'


@st.fragment(run_every="2s")
def status_row() -> None:
    now_ms = int(time.time() * 1000)
    lecture = None
    if db_path().exists():
        try:
            conn = connect_readonly(db_path())
            try:
                lecture = lecture_state(conn, now_ms)
            finally:
                conn.close()
        except sqlite3.Error:
            lecture = None
    current = compute(now_ms, lecture, live_panel.latest_live())
    if current["label"]:                       # only while a class runs; the wordmark is in the top bar (st.logo)
        st.html(row_html(current))
    set_tab_title(current["title"])
