"""The System page (docs/UI_DESIGN.md §5): pipeline health, window stats, alerts and the read-only data box, for the
team and the examiners. Pipeline words are allowed here and only here (.claude/skills/edustream-ui rule 2)."""

from __future__ import annotations

import sqlite3

import altair as alt
import pandas as pd
import streamlit as st

from dashboard import queries, sql_box
from dashboard.shared import SETTINGS, clock, mmss, mode
from storage.db import connect_readonly, db_path

# Categorical slots (dataviz reference palette): colour follows the lecture (partition order), never its rank.
SERIES = {"light": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
          "dark": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]}
MUTED = {"light": "#43544A", "dark": "#a3a29b"}
SEVERITY = {"info": "info", "warn": "warning", "crit": "critical"}
# Tab labels double as URL values (bind="query-params"): e.g. http://localhost:8501/system?view=Alerts
VIEWS = ["Pipeline health", "Window stats", "Alerts", "Data"]


def lecture_colors(lectures: pd.DataFrame) -> tuple[list[str], list[str]]:
    slots = SERIES[mode()]
    titles = list(lectures["title"])
    return titles, [slots[i % len(slots)] for i in range(len(titles))]


def data_tab() -> None:
    """Storage you can query (A19): ready-made queries and a locked, read-only SQL box."""
    st.markdown("**Query the stored data** (SQLite, read-only). Pick a ready-made query or write your own SELECT.")
    name = st.selectbox("Ready-made query", list(sql_box.READY_MADE), key="data_query")
    sql = st.text_area("SQL", sql_box.READY_MADE[name], key=f"data_sql_{name}", height=110)
    if st.button("Run query", type="primary", key="data_run"):
        try:
            conn = connect_readonly(db_path())
            try:
                df, truncated = sql_box.run_query(conn, sql)
            finally:
                conn.close()
        except sql_box.QueryRefused as exc:
            st.error(f"Query refused: {exc}")
            return
        except sqlite3.Error as exc:
            st.error(f"Database not readable: {exc}")
            return
        st.dataframe(df, hide_index=True, width="stretch")
        st.caption(f"{len(df)} rows" + (f" (first {sql_box.MAX_ROWS} only)" if truncated else ""))
        st.download_button("Download CSV", df.to_csv(index=False).encode("utf-8"), file_name="edustream_query.csv",
                           mime="text/csv", key="data_csv")
    st.caption(f"Only SELECT on the EduStream tables is allowed; queries stop after {sql_box.TIME_LIMIT_S:g} s "
               f"and return at most {sql_box.MAX_ROWS} rows. Tables: " + ", ".join(sorted(
                   t for t in sql_box.ALLOWED if not t.startswith("sqlite"))) + ".")


def stats_tab(conn: sqlite3.Connection, lectures: pd.DataFrame) -> None:
    ws = queries.window_stats(conn)
    if ws.empty:
        st.info("No closed windows yet.")
        return
    ws["minute"] = ws["media_start"] / 60
    domain, colors = lecture_colors(lectures)
    color = alt.Color("title:N", title=None, scale=alt.Scale(domain=domain, range=colors),
                      legend=alt.Legend(orient="bottom", direction="vertical", labelLimit=400))
    tooltip = [alt.Tooltip("title:N", title="Lecture"), alt.Tooltip("minute:Q", title="Minute", format=".1f"),
               alt.Tooltip("words_per_min:Q", title="Words/min"), alt.Tooltip("score_avg:Q", title="asr_score avg",
                                                                              format=".3f"),
               alt.Tooltip("chunk_count:Q", title="Chunks")]
    base = alt.Chart(ws).encode(x=alt.X("minute:Q", title="Lecture time (minutes)"), color=color, tooltip=tooltip)
    line = {"strokeWidth": 2, "point": alt.OverlayMarkDef(size=40, filled=True)}

    left, right = st.columns(2)
    with left:
        st.markdown("**Speaking rate per 30 s window**")
        silence = alt.Chart(pd.DataFrame({"y": [40]})).mark_rule(color=MUTED[mode()], strokeWidth=1).encode(y="y:Q")
        chart = base.mark_line(**line).encode(y=alt.Y("words_per_min:Q", title="Words per minute")) + silence
        st.altair_chart(chart.properties(height=240), width="stretch", height=400)
        st.caption("Grey rule: 40 words/min, the SILENCE alert threshold.")
    with right:
        st.markdown("**Transcription confidence (asr_score) per window**")
        scored = ws[ws["score_avg"].notna()]
        if scored.empty:
            st.info("No asr_score values (e.g. a caption replay has none).")
        else:
            threshold = alt.Chart(pd.DataFrame({"y": [SETTINGS.t_score]})).mark_rule(
                color=MUTED[mode()], strokeWidth=1).encode(y="y:Q")
            chart = base.transform_filter("datum.score_avg != null").mark_line(**line).encode(
                y=alt.Y("score_avg:Q", title="Average asr_score", scale=alt.Scale(domain=[0.4, 1.0]))) + threshold
            st.altair_chart(chart.properties(height=240), width="stretch", height=400)
            st.caption(f"Grey rule: T_SCORE = {SETTINGS.t_score} (LOW_ASR_SCORE, informational only: "
                       "M2 found asr_score a weak signal).")
    with st.expander("Table view"):
        table = ws[["title", "media_start", "media_end", "chunk_count", "word_count", "words_per_min",
                    "score_avg", "score_min", "score_max", "compression_ratio_max", "top_terms"]].copy()
        table["media_start"] = table["media_start"].map(mmss)
        table["media_end"] = table["media_end"].map(mmss)
        st.dataframe(table, hide_index=True, width="stretch")


def alerts_tab(conn: sqlite3.Connection) -> None:
    df = queries.alerts(conn)
    if df.empty:
        st.info("No alerts.")
        return
    window = [mmss((ws - s) / 1000) if pd.notna(ws) and pd.notna(s) else "" for ws, s in
              zip(df["window_start"], df["session_start"])]
    table = pd.DataFrame({"time": df["created_ts"].map(clock), "severity": df["severity"].map(SEVERITY),
                          "type": df["type"], "lecture": df["lecture"].fillna("(system)"), "window at": window,
                          "value": df["value"].round(3), "threshold": df["threshold"], "reason": df["reason"]})
    st.dataframe(table, hide_index=True, width="stretch")
    st.caption("LOW_ASR_SCORE and SILENCE are informational. CONSUMER_LAG = a stage is more than "
               f"{SETTINGS.lag_alert_s:g} s of audio behind. LATE_DROP must never appear (S1 tripwire).")


def kpi_strip(kpi: dict) -> None:
    cols = st.columns(7)
    cols[0].metric("Lectures", kpi["lectures"], border=True)
    cols[1].metric("Chunks transcribed", kpi["chunks"], border=True)
    cols[2].metric("Windows closed", kpi["windows"], border=True)
    cols[3].metric("Notebook updates", kpi["updates"] or kpi["notes"], border=True,
                   help="Live notes: one per 90 s of lecture")
    cols[4].metric("Consolidations", kpi["passes"], border=True,
                   help="Live notes organised into topics: one per ~6 minutes, and one at the lecture's end")
    cols[5].metric("Alerts", kpi["alerts"], border=True, help="LOW_ASR_SCORE, SILENCE, CONSUMER_LAG")
    cols[6].metric("LATE_DROP", kpi["late_drop"], border=True,
                   help="Records dropped as late. Must stay 0 (S1: one lecture per partition).")
    if kpi["last_sink_ts"]:
        st.caption(f"Last write by the sink at {clock(kpi['last_sink_ts'])}. DLQ: {kpi['dlq']} records.")


def health_tab(conn: sqlite3.Connection, lectures: pd.DataFrame, kpi: dict) -> None:
    kpi_strip(kpi)
    st.markdown("**Partitions: lecture → transcription worker**")
    pmap = queries.partition_map(conn)
    if pmap.empty:
        st.info("No lectures yet.")
    else:
        st.dataframe(pmap.rename(columns={"owner_now": "owned now by", "latest_chunk_by": "latest chunk by",
                                          "workers_used": "workers used"}), hide_index=True, width="stretch")

    st.markdown("**Consumer lag (seconds of audio behind)**")
    lag = queries.lag(conn)
    if lag.empty:
        st.info("No lag samples yet (the sink samples every 5 s).")
    else:
        lag["over threshold"] = lag["lag_seconds"] > SETTINGS.lag_alert_s
        lag["sampled"] = lag["sampled_ts"].map(clock)
        st.dataframe(lag[["group_id", "partition", "lecture", "owner", "lag", "lag_seconds", "over threshold",
                          "sampled"]], hide_index=True, width="stretch")

    st.markdown("**Completeness**")
    if not lectures.empty:
        st.dataframe(lectures[["title", "partition", "status", "chunks_stored", "expected_chunks",
                               "completeness_pct", "windows", "updates", "passes"]], hide_index=True, width="stretch")

    st.markdown(f"**Dead-letter queue** ({kpi['dlq']} records)")
    dlq = queries.dlq(conn)
    if dlq.empty:
        st.caption("Empty.")
    else:
        dlq["failed_ts"] = dlq["failed_ts"].map(clock)
        st.dataframe(dlq, hide_index=True, width="stretch")


@st.fragment(run_every="2s")
def refreshing(view: str) -> None:
    try:
        conn = connect_readonly(db_path())
    except sqlite3.Error:
        return
    try:
        lectures = queries.lectures(conn)
        if view == "Window stats":
            stats_tab(conn, lectures)
        elif view == "Alerts":
            alerts_tab(conn)
        else:
            health_tab(conn, lectures, queries.kpis(conn))
    finally:
        conn.close()


def page() -> None:
    if not db_path().exists():
        st.info("No database yet. Start the pipeline with `scripts\\start_all.ps1`.")
        return
    tabs = st.tabs(VIEWS, key="view", bind="query-params", on_change="rerun")
    for tab, view in zip(tabs, VIEWS):
        with tab:
            if tab.open or (tab.open is None and view == VIEWS[0]):   # only the open tab runs (the first by default)
                data_tab() if view == "Data" else refreshing(view)
