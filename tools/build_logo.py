"""Build the EduStream wordmark for the top bar (st.logo): "EduStream" set in Literata SemiBold, drawn as SVG paths.

st.logo shows an <img>, which cannot use the page's web fonts, so the letters are outlines taken from the self-hosted
font. One colour, #5C6FD9, readable on both themes (about 4.1:1 on Warm paper and on Midnight ink; the wordmark is
large text, which needs 3:1).

    .venv\\Scripts\\python tools\\build_logo.py
"""

from __future__ import annotations

from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / "dashboard" / "static" / "fonts" / "Literata.woff"
OUT = ROOT / "dashboard" / "static" / "edustream_wordmark.svg"
TEXT, COLOUR, WEIGHT = "EduStream", "#5C6FD9", 600


def main() -> None:
    font = instancer.instantiateVariableFont(TTFont(FONT), {"wght": WEIGHT, "opsz": 24})
    glyphs, cmap, hmtx = font.getGlyphSet(), font.getBestCmap(), font["hmtx"]
    upm = font["head"].unitsPerEm
    ascent, descent = font["hhea"].ascent, font["hhea"].descent
    paths, x = [], 0
    for ch in TEXT:
        name = cmap[ord(ch)]
        pen = SVGPathPen(glyphs)
        glyphs[name].draw(TransformPen(pen, (1, 0, 0, -1, x, ascent)))      # flip y: font units grow upwards
        paths.append(pen.getCommands())
        x += hmtx[name][0]
    height = ascent - descent
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 {int(height * 0.12)} {x} {int(height * 0.86)}" '
           f'role="img" aria-label="{TEXT}"><path fill="{COLOUR}" d="{" ".join(paths)}"/></svg>')
    OUT.write_text(svg, encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: {len(svg) // 1024} KB, {upm} units per em")


if __name__ == "__main__":
    main()
