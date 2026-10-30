"""Build the dashboard's self-hosted web fonts (docs/UI_DESIGN.md §2): Literata (what the lecturer said) and Fira Sans
(the interface), from Google Fonts' repository, subset to what lecture notes use and saved as WOFF in
dashboard/static/fonts/ (served by Streamlit's static serving; .streamlit/config.toml [[theme.fontFaces]]).

Both fonts are SIL Open Font License 1.1 with no reserved font name, so subsetting is allowed; the licences are copied
next to the fonts. Two characters the notes often contain are missing from both fonts and are mapped to existing
glyphs: U+2011 non-breaking hyphen ("t‑test") -> the hyphen, U+202F narrow no-break space ("Type I") -> the thin
space. Without this the browser draws them from another font.

    .venv\\Scripts\\python tools\\build_fonts.py      (needs internet once; the output is kept in the repo)
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import requests
from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dashboard" / "static" / "fonts"
SOURCE = "https://raw.githubusercontent.com/google/fonts/main/ofl/"
FONTS = {"Literata.woff": "literata/Literata%5Bopsz,wght%5D.ttf",
         "Literata-Italic.woff": "literata/Literata-Italic%5Bopsz,wght%5D.ttf",
         "FiraSans-Regular.woff": "firasans/FiraSans-Regular.ttf",
         "FiraSans-Medium.woff": "firasans/FiraSans-Medium.ttf",
         "FiraSans-SemiBold.woff": "firasans/FiraSans-SemiBold.ttf",
         "FiraSans-Bold.woff": "firasans/FiraSans-Bold.ttf"}
LICENCES = {"OFL-Literata.txt": "literata/OFL.txt", "OFL-FiraSans.txt": "firasans/OFL.txt"}
# Latin + Latin-1 + Extended A/B, combining marks, Greek, general punctuation, super/subscripts, currency, letterlike,
# arrows, mathematical operators, misc technical, geometric shapes (● ▸), ligatures.
UNICODES = ("U+0000-024F,U+0300-036F,U+0370-03FF,U+2000-206F,U+2070-209F,U+20A0-20BF,U+2100-214F,U+2190-21FF,"
            "U+2200-22FF,U+2300-23FF,U+25A0-25FF,U+FB00-FB06")
ALIASES = {0x2011: 0x2010, 0x202F: 0x2009}            # missing -> drawn with this glyph (falls back to - and space)
FALLBACK = {0x2010: 0x002D, 0x2009: 0x0020}
NEEDED = "μσαβχλθπΣΔ≠±≤≥≈×÷−₀₁₂²³√∑∞→‑ "


def fetch(path: str) -> bytes:
    r = requests.get(SOURCE + path, timeout=60)
    r.raise_for_status()
    return r.content


def add_aliases(font: TTFont) -> None:
    for table in font["cmap"].tables:
        if not table.isUnicode():
            continue
        for missing, like in ALIASES.items():
            glyph = table.cmap.get(like) or table.cmap.get(FALLBACK[like])
            if missing not in table.cmap and glyph:
                table.cmap[missing] = glyph


def build(name: str, data: bytes) -> TTFont:
    font = TTFont(io.BytesIO(data))
    add_aliases(font)
    options = subset.Options()
    options.flavor = "woff"
    options.layout_features = ["*"]                   # keep kerning, ligatures, tabular figures ("tnum")
    options.name_IDs = ["*"]
    options.notdef_outline = True
    sub = subset.Subsetter(options)
    sub.populate(unicodes=subset.parse_unicodes(UNICODES))
    sub.subset(font)
    font.flavor = "woff"
    font.save(OUT / name)
    return font


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    missing = {}
    for name, path in FONTS.items():
        font = build(name, fetch(path))
        cmap = font.getBestCmap()
        missing[name] = [c for c in NEEDED if ord(c) not in cmap]
        print(f"{name}: {(OUT / name).stat().st_size // 1024} KB")
    for name, path in LICENCES.items():
        (OUT / name).write_bytes(fetch(path))
    bad = {k: v for k, v in missing.items() if v}
    print("all needed characters present" if not bad else f"MISSING: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
