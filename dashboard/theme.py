"""Warm paper (light) and Midnight ink (dark): the semantic colours as CSS variables (docs/UI_DESIGN.md §2).

Base colours are in .streamlit/config.toml ([theme.light], [theme.dark]); the browser picks the theme from the
laptop's setting. Everything our own HTML draws (notes, status row, landing) and the few keyed Streamlit containers
we style read these variables. CSS here targets only our own classes (.nb, .es) and Streamlit's documented key classes
(.st-key-<key>), never Streamlit's internal class names; LAYOUT_CSS is the one documented exception.
"""

from __future__ import annotations

import streamlit as st

from dashboard.shared import mode

TOKENS = {
    "light": {"page": "#F7F5EF", "panel": "#EFECE3", "card": "#FFFEFB", "livecard": "#FFFCF7", "liveborder": "#E5C779",
              "border": "#DAD5C8", "edge": "#8C8676", "ink": "#1F2430", "secondary": "#55596A", "accent": "#2F4BD8",
              "onaccent": "#FFFEFB", "tint": "#E6EAFB", "live": "#0B6B49", "fault": "#B42318", "caution": "#8A5300",
              "mark": "#FFF0A8"},
    "dark": {"page": "#12161F", "panel": "#1A2030", "card": "#222A3B", "livecard": "#222A3B", "liveborder": "#8A6F2A",
             "border": "#313A50", "edge": "#6E7896", "ink": "#E8EAF0", "secondary": "#A3AABD", "accent": "#7C93FF",
             "onaccent": "#0E1220", "tint": "#262F52", "live": "#4ADE9B", "fault": "#FF8A7A", "caution": "#F5C451",
             "mark": "rgba(255,214,102,0.22)"},
}

GLOBAL_CSS = """
/* Notes card and assistant: raised cards on the page (keyed containers). */
.st-key-notes_card,.st-key-assistant{background:var(--es-card);border-radius:8px}
/* Assistant text as readable as the notes. */
.st-key-assistant p,.st-key-assistant li{font-size:18px;line-height:1.6}
/* A send button that is always visible. */
.st-key-a_input button{background:var(--es-accent);color:var(--es-onaccent);opacity:1}
.st-key-a_input button svg{fill:var(--es-onaccent);color:var(--es-onaccent)}
/* Primary actions: text on the accent in both themes (Streamlit always draws it white). A container keyed act_*
   holds exactly one primary button and nothing else. */
[class*="st-key-act_"] button,[class*="st-key-act_"] button p{color:var(--es-onaccent)}
"""


def _block(theme: str) -> str:
    return "".join(f"--es-{k}:{v};" for k, v in TOKENS[theme].items())


def variables(theme: str) -> str:
    """Both themes' variables. <html data-es-theme> (set in the browser by status.py's component from the colours
    Streamlit is really using) picks one, so a theme chosen in Streamlit's menu applies at once; until it is set, the
    theme Python saw on this run applies."""
    return (":root{" + _block(theme) + "}"
            + "".join(f':root[data-es-theme="{t}"]{{{_block(t)}}}' for t in TOKENS))


# The one rule on a Streamlit test id (docs/UI_DESIGN.md §3, owner's request 30 Oct): Streamlit's large empty band
# between the top bar and the page. If an upgrade renames the id, the band simply comes back.
LAYOUT_CSS = '[data-testid="stMainBlockContainer"]{padding-top:4.25rem}'


def inject() -> None:
    """Once per run, above the page: the theme variables and the keyed-container rules."""
    st.html(f"<style>{variables(mode())}{GLOBAL_CSS}{LAYOUT_CSS}</style>")
