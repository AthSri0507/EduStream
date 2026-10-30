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
    if word.endswith(("eses", "yses")) and len(word) > 6:      # hypotheses -> hypothesis, analyses -> analysis
        return word[:-2] + "is"
    for suffix in ("ing", "ed", "es", "ly", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


# ---------------------------------------------------------------------------------------------- spoken vs written
# Speech recognition writes what was said ("four hundred and fifty four grams", "type one error", "h naught"); the
# model writes notation ("454 g", "type I error", "H₀"). Both sides go through spoken_tokens(), so a sentence and the
# transcript it came from compare in one form (live run 29 Oct: a correct paragraph about H₀: μ = 454 scored 0.14).
SYMBOLS = {"α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon", "θ": "theta", "λ": "lambda",
           "μ": "mu", "π": "pi", "ρ": "rho", "σ": "sigma", "τ": "tau", "φ": "phi", "χ": "chi", "ω": "omega",
           "≠": "not equal", "%": "percent"}          # < > ≤ ≥ stay unread: said as "greater", "more", "above" ...
ONES = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                   "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
TENS = {w: 10 * i for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split(), start=2)}
SCALES = {"hundred": 100, "thousand": 1000, "million": 1_000_000}
SAME = {"alternative": "alternate", "mew": "mu", "nought": "naught"}
ALIASES = [(re.compile(r"\bh (?:naught|not|knot|zero|0|o)\b"), "h0"), (re.compile(r"\bh (?:one|1)\b"), "h1"),
           (re.compile(r"\b(type|phase|stage) (iii|ii|i)\b"), lambda m: f"{m.group(1)} {len(m.group(2))}"),
           (re.compile(r"\b(type|phase|stage) iv\b"), r"\1 4")]
TOKEN = re.compile(r"\d+(?:\.\d+)?|[a-z0-9]+")


def _numbers(tokens: list[str]) -> list[str]:
    """Number words -> digits: "four hundred and fifty four" -> 454, "zero point zero five" -> 0.05. Digits said one
    by one ("four five four") stay separate numbers."""
    out, i = [], 0
    while i < len(tokens):
        if tokens[i] not in ONES and tokens[i] not in TENS:
            out.append(tokens[i])
            i += 1
            continue
        total, current, last = 0, 0, None
        while i < len(tokens):
            w = tokens[i]
            if w in ONES and (last is None or last in SCALES or (last == "tens" and ONES[w] < 10)):
                current, last = current + ONES[w], "ones"
            elif w in TENS and (last is None or last in SCALES):
                current, last = current + TENS[w], "tens"
            elif w in SCALES and last in ("ones", "tens"):
                if SCALES[w] == 100:
                    current, last = current * 100, w
                else:
                    total, current, last = total + current * SCALES[w], 0, w
            elif w == "and" and last in SCALES and i + 1 < len(tokens) and (tokens[i + 1] in ONES or tokens[i + 1] in TENS):
                pass
            else:
                break
            i += 1
        number = str(total + current)
        if i + 1 < len(tokens) and tokens[i] == "point" and tokens[i + 1] in ONES and ONES[tokens[i + 1]] < 10:
            i += 1
            digits = ""
            while i < len(tokens) and tokens[i] in ONES and ONES[tokens[i]] < 10:
                digits += str(ONES[tokens[i]])
                i += 1
            number += "." + digits
        out.append(number)
    return out


def spoken_tokens(text: str) -> list[str]:
    """Words and numbers in one canonical form for written notes and recognised speech alike (not stemmed)."""
    text = unicodedata.normalize("NFKC", text or "").replace("‑", "-").replace("’", "'")
    text = "".join(f" {SYMBOLS[ch]} " if ch in SYMBOLS else ch for ch in text.lower())
    text = " ".join(TOKEN.findall(text))
    for pattern, repl in ALIASES:
        text = pattern.sub(repl, text)
    return [SAME.get(w, w) for w in _numbers(text.split())]


def numbers_in(text: str) -> set[str]:
    """The numbers a text states that carry data: decimals and integers above 10 (step numbers, "/2" stay free:
    in the Python lecture's notes 3 of 4 sentences with numbers used small ones the lecturer never said)."""
    return {w for w in spoken_tokens(text) if re.fullmatch(r"\d+\.\d+", w) or (w.isdigit() and int(w) > 10)}


def content_words(text: str) -> list[str]:
    return [stem(w) for w in spoken_tokens(text)
            if w not in STOP and (len(w) > 1 or w.isdigit())]    # digits count: "type 1" is not "type 2"


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
