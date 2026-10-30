"""Small helpers shared by the dashboard pages."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from common.config import load

SETTINGS = load()


def mode() -> str:
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:  # noqa: BLE001 - older/unknown theme info
        return "light"


def mmss(seconds) -> str:
    if seconds is None or pd.isna(seconds):
        return "--:--"
    seconds = int(seconds)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def clock(ms) -> str:
    return "" if ms is None or pd.isna(ms) else datetime.fromtimestamp(ms / 1000).strftime("%H:%M:%S")
