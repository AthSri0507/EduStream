# Step 0: prototype results (15 Oct 2026)

Checks from ARCHITECTURE §12 items 8, 9 and 13, run before M6a/M6e are built.
Groq calls used: about 46 (notebook 22, follow-ups 24), roughly 60k tokens, free tier.

| Script | Output |
|---|---|
| `bench/proto_notebook.py` | `results/proto_notebook_run1.{md,json}` (first rules), `results/proto_notebook.{md,json}` (fixed rules) |
| `bench/proto_followups.py` | `results/proto_followups.{md,json}` |
| `bench/proto_streamlit_app.py` + `proto_streamlit_check.py` | `results/proto_streamlit.json` |

Responses are cached in `results/proto_llm_cache.json` (development only), so reruns cost no quota.

## 1. Notebook prompt (item 8)

Input: the first 12 min of Python · Lecture 1, real M2 Whisper output, 8 updates of 90 s.

| | Run 1 | Run 2 (fixed rules) |
|---|---|---|
| Calls succeeded | 8/8 (all gpt-oss-120b) | 8/8 (4 × 120b, then 4 × 20b after HTTP 429 on 120b) |
| Median latency | 1.14 s | 0.96 s |
| Tokens per call | ~1,220 | ~1,350 (estimate was 1,500–2,000) |
| Points kept / proposed | 14 / 19 | 22 / 23 |
| Sections | Introduction; Computer fundamentals | Introduction & Course Overview; Types of Calculations & Knowledge |

**What works:**
- The licence notice and admin chatter (update 0) produce **no points**.
- The notes read like a student's notes, not a transcript summary, and are far better than the extractive fallback, which picks admin sentences ("first name Anna, last name Belle").
- Section changes are sensible; the provider fallback on HTTP 429 works without a gap.

**Found and fixed in run 2:**
1. Quotes shortened with "…" failed the exact match → fragments must all match, in order.
2. Honest paraphrases were dropped by the 40 % overlap rule (0.33–0.38) → 0.25.
3. A Unicode non-breaking hyphen ("p‑sets") broke term matching → NFKC normalisation.
4. A section boundary landed 50 s early → `starts_at` on new sections.
5. A point came back as a bare string → malformed items are skipped and flagged.

**Still open (needs a decision): a real quote is not the same as support.**
- Some points pair genuine quotes with content the lecturer never said, e.g. "Python has built-in data types such as integers, floats, strings…" citing "we're going to go through Something class exercises". Glossary entries self-labelled "lecture" can be general knowledge.
- Measured offline on both runs: word overlap between a point and **its own quote's neighbourhood** separates them only partly: invented points score 0.08–0.33, honest paraphrases 0.25–0.88. No threshold removes all inventions without dropping honest points.

## 2. Assistant understand step (item 9)

12 scripted conversations at 07:25 into the lecture; the assistant's chain (gpt-oss-20b first).

- **7/12 plans fully correct** (first attempt with 120b first: 6/12). 0.4–0.9 s per call.
- Fine by design (2): an earlier part outside the recent context gets no span → retrieval finds it from the rewritten question; a wrong intent label with the right term and depth.
- Debatable test (1): "is it better than the other one?" was resolved to the lecturer's line "one program is better than the other".
- **Real gaps (2):** "tell me more about the second one" not rewritten to "programming skills"; "so far" gave no span.
- Deterministic guards (keywords for depth/style/previous answer, term extraction) fixed "modular → no term" and "in a lot more detail → normal" in the first attempt.

**Consequences for M6e:** parse time phrases ("just now", "last N minutes", "so far") in code; always pass the previous answer to the answer step when `previous_answer` is true; keep the editable chip.

## 3. Streamlit execution model (item 13)

| Scenario | Answer arrived? |
|---|---|
| A: LLM call in a background thread, another widget clicked mid-call | **Yes**, and it streamed (half the text visible at 1.5 s) |
| B: LLM call inline in a button handler, another widget clicked mid-call | **No: lost** |
| C: inline call, no interaction (only the 2 s auto-refresh fragment) | Yes |

**Consequence:** the background-thread design in ARCHITECTURE §8.3 is required, not optional.
