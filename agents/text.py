"""Small, deterministic text helpers shared by the agents (grounding checks, extractive scoring)."""

from __future__ import annotations

import re
import unicodedata

STOP = set("""a an the and or but if then so to of in on at for with by from as is are was were be been being it its
this that these those there here i you he she we they me my your our their them us do does did doing have has had
not no yes can could will would should may might just also very really some any all more most such than too what
which who whom how why when where about into over out up down only own same both each few other again further
once let's lets okay ok right yeah um uh like going gonna want wanted get got kind sort thing things way""".split())


def mmss(seconds: float) -> str:
    return f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}"


def parse_t(value) -> float | None:
    """'mm:ss' or a number of seconds -> seconds; anything else -> None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.match(r"^\s*(\d+):(\d{1,2})\s*$", str(value or ""))
    return float(int(m.group(1)) * 60 + int(m.group(2))) if m else None


def norm(text: str) -> str:
    """Lower-case words only. NFKC folds look-alikes such as the non-breaking hyphen (step-0 finding)."""
    text = unicodedata.normalize("NFKC", text or "").replace("‑", "-").replace("’", "'")
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "ly", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def content_words(text: str) -> list[str]:
    return [stem(w) for w in norm(text).split() if w not in STOP and len(w) > 1]


def find_quote(quote: str, chunk_texts: list[str]) -> tuple[int, int] | None:
    """(first, last) chunk index covered by a verbatim quote, or None.

    Matching ignores case and punctuation. A quote shortened with '...' matches if all its fragments occur
    in order (step-0 finding: the model elides). A quote may span chunk boundaries. Needs >= 3 words.
    """
    fragments = [norm(f) for f in re.split(r"\.\.\.|…", quote or "") if norm(f)]
    if not fragments or sum(len(f.split()) for f in fragments) < 3:
        return None
    full, starts = "", []
    for text in chunk_texts:
        starts.append(len(full))
        full += norm(text) + " "
    pos, first, last = 0, None, None
    for frag in fragments:
        hit = full.find(frag, pos)
        if hit < 0:
            return None
        first = hit if first is None else first
        last = hit + len(frag) - 1
        pos = hit + len(frag)
    index = lambda offset: max(i for i, s in enumerate(starts) if s <= offset)  # noqa: E731
    return index(first), index(last)


def support(text: str, evidence: str) -> float:
    """Share of `text`'s content words that occur in `evidence` (0..1)."""
    words = content_words(text)
    if not words:
        return 0.0
    have = set(content_words(evidence))
    return sum(w in have for w in words) / len(words)


def similar(a: str, b: str) -> float:
    """Jaccard similarity of content-word sets (near-duplicate points)."""
    x, y = set(content_words(a)), set(content_words(b))
    return len(x & y) / len(x | y) if x and y else 0.0
