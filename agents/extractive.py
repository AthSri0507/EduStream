"""Extractive fallback and baseline (docs/ARCHITECTURE.md §8.1.4): no LLM, deterministic.

Picks the highest-scoring sentences of a stretch of transcript (by how often their content words occur
in it, normalised by sentence length) and keeps them in spoken order, each with its chunk's media time.
Boilerplate such as MIT's licence notice (window 0 of the OCW lectures, M5 finding) is skipped.
"""

from __future__ import annotations

import re
from collections import Counter

from agents.text import content_words

BOILERPLATE = re.compile(r"creative commons|opencourseware|ocw\.mit|make a donation|additional materials"
                         r"|this lecture will be recorded", re.I)
MIN_WORDS = 6


def top_sentences(chunks: list[dict], top: int = 3) -> list[dict]:
    """chunks: [{start_time, text}] in order. Returns [{text, t}] (at most `top`), in spoken order."""
    sentences = []
    for c in chunks:
        for s in re.split(r"(?<=[.!?])\s+", c.get("text") or ""):
            s = s.strip()
            if len(s.split()) >= MIN_WORDS and not BOILERPLATE.search(s):
                sentences.append((s, float(c["start_time"])))
    freq = Counter(w for s, _ in sentences for w in content_words(s))
    scored = [(sum(freq[w] for w in content_words(s)) / (len(s.split()) ** 0.5), -i, i, s, t)
              for i, (s, t) in enumerate(sentences)]
    best = sorted(sorted(scored, reverse=True)[:top], key=lambda x: x[2])
    return [{"text": s[:300], "t": t} for *_, s, t in best]
