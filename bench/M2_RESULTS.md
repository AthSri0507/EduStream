# M2: Verification and benchmark results

**Date:** 14 Oct 2026. **Machine:** the team laptop (i5-12500H, 12 cores / 16 threads, 15.7 GB RAM, Windows 11, browsers closed), with a single Kafka 4.3.1 broker running (`infra/kafka/single.properties`).

**Scope:** this milestone checks the design's assumptions (ARCHITECTURE §12) before any pipeline code is written. **Nothing here is pipeline code.** All scripts are in `bench/`, and the raw outputs are in `bench/results/`.

| §12 item | What was checked | Result |
|---|---|---|
| 1 | kafka-python 3.0.11 behaves as the design assumes | **10/10 pass**, after one API correction (below) |
| 2 | Python and Java choose the same partition for a key | **Pass:** 20/20 keys identical |
| 3 | The single broker runs consumer groups and Streams internal topics | **4/4 pass**, after recovering from a broker crash (below) |
| 4 | TopologyTestDriver uses one partition | **Confirmed:** every key arrives on partition 0 |
| 5 | Kafka Streams 4.3.1 has the APIs the design relies on | **Pass:** KIP-1033 handler and `dropped-records-total`. The window design also passed a dry run |
| 6 | Whisper is fast enough, deterministic and accurate | **Pass**, after fixing repetition loops. **10 s chunks + a repetition-penalty retry: mean WER 10.1 %** (§6) |
| 7 | A free LLM gives valid notes fast enough | **Pass (Groq).** Cerebras was dropped: it needs a card |

---

## 1. kafka-python 3.0.11 (`bench/verify_kafka_python.py`)

| Check | Result |
|---|---|
| K1 Admin creates a 3-partition topic | Pass |
| K2 Idempotent producer (`acks=all`) with delivery callbacks | Pass: 20/20 acknowledged, 0 errors |
| K3 Partition the client computes = partition the broker stored | Pass: all 20 keys |
| K4 `max_poll_records=1`, raw bytes, explicit commit `OffsetAndMetadata(offset+1, None, -1)` | Pass: committed exactly `offset+1` |
| **K5 A bare `commit()` after `poll()`** | **Over-commits:** it fetched 10, processed 1, and **committed all 10**. That would silently lose 9 records after a crash, so the design's explicit-offset rule is required |
| K6 Admin: group offsets, members, lag | Pass, **using the 3.x API names** (`list_group_offsets`, `describe_groups`). The 2.x names the design assumed **don't exist** |
| K7 Transactions: an aborted batch is hidden from `read_committed` | Pass: `read_committed` saw 5 committed and 0 aborted; `read_uncommitted` saw 5 and 10 |
| K8 Message sizes | 5 s (214 KB), 10 s (427 KB) and 15 s (640 KB) chunks accepted; 1.2 MB rejected (`MessageSizeTooLargeError`) |
| K9 Timestamp guard | Records stamped 1970 or 2 h in the future are rejected (`InvalidTimestampError`); records stamped now are accepted; the broker stays up |
| **K10 Producer after a rejected record** | **An idempotent producer then rejects valid records too**, while a non-idempotent one recovers. So the rule on a produce failure is: exit and restart with a fresh producer |

**Also found:** callables passed as `value_serializer` are deprecated in 3.x. The existing code uses `lambda`s there; the new code sends `bytes`.

## 2. Partitioning (`bench/run_java_checks.ps1`, J1 compared with K3)

Python's murmur2 partition matched Java's `Utils.murmur2` for **all 20 keys**.

**Natural lecture IDs collide.** `algorithms_l1` and `algorithms_l2` both hash to partition 1, as do `python_l1` and `python_l2` (to partition 0). Two demo lectures would then share a partition, which breaks the one-lecture-per-partition rule (S1). Readable IDs that spread across the three partitions:

| Demo lecture | `video_id` | Partition |
|---|---|---|
| Python · Lecture 1 (Bell) | `python_l1` | 0 |
| Algorithms · Lecture 1 (Ku) | `algorithms_ku_l1` | 1 |
| Algorithms · Lecture 2 (Demaine) | `algorithms_demaine_l2` | 2 |

`tools/partition_of.py` (M3) will compute these automatically.

## 3. The single broker and the existing Streams app (`bench/smoke_streams_baseline.py`)

| Check | Result |
|---|---|
| S1 Streams consumer group forms | Pass: Stable, 1 member |
| S2 Internal topics created with RF 1 | Pass: the `…-changelog` and `…-repartition` topics |
| S3 Window output reaches `generated_notes` | Pass |
| S4 The broker is still up after the run | Pass |

**A real Windows crash happened first.** On its first run, the old Streams app stamped its output records with 1970 timestamps (event time = `start_time × 1000`, defect D10).
1. Those records were already "older than the 7-day retention", so Kafka deleted their segment immediately.
2. On Windows the delete failed with "file in use".
3. The log directory was marked failed and **the broker shut down.**

This is risk K5, made concrete. **Fixed** by a guard in `single.properties`, which now rejects records more than 1 day in the past or 1 hour in the future (verified by K9). Further rules were added to ARCHITECTURE §11: no historic timestamps on a real broker, and `reset.ps1` between rehearsal days. ARCHITECTURE §6.1 now also sets `windowstore.changelog.additional.retention.ms` to 7 days.

**Also found:** `java` on this machine is Oracle's `javapath` launcher shim. Stopping the shim left the real JVM running, so kill scripts must kill the **process tree** (`taskkill /T`).

## 4–5. Kafka Streams 4.3.1 (`bench/java/M2StreamsChecks.java`)

| Check | Result |
|---|---|
| J2 TopologyTestDriver partitions | Every key arrives on **partition 0**. Partition isolation, stalls and delays therefore have to be tested on the real broker (tests I-1, I-2, I-3) |
| J3 `LogAndContinueProcessingExceptionHandler` (KIP-1033) | Exists |
| J4 Suppress + in-memory window store: output only after end + grace, in order, deduplicated | Pass: nothing before 40 s, then exactly one result `c0…c5`, even with chunks out of order and one duplicate |
| J5 The scheduled flush closes the last window; the empty flush window is never emitted | Pass |
| J6 A late record is dropped and counted | Pass: `dropped-records-total` = 1, in group `stream-task-metrics` |

J4–J6 are an early dry run of the core window design (ARCHITECTURE §6). The full S-1 test suite is built in M4.

## 6. Whisper (`bench/whisper_bench.py`)

Settings throughout: int8 on CPU, `cpu_threads=4` per worker, English, `temperature=0`, VAD filter on, one call per 5 s chunk. Each worker transcribed 10 minutes of a demo lecture.

| Model | Workers at once | RTF (worst) | Peak RAM per worker | Lectures sustainable (`L·RTF ≤ 0.7·N`) |
|---|---|---|---|---|
| base.en | 1 | 0.171 | 497 MB | 4 |
| base.en | 2 | 0.366 | 507 MB | 3 |
| **base.en** | **3** | **0.362** | **537 MB** | **5** |
| tiny.en | 3 | 0.171 | 537 MB | 12 |
| small.en | 1 | 0.631 | 892 MB | 1 |

**What the numbers mean:**
- **3 `base.en` workers can handle the 3 demo lectures with plenty of headroom**: each runs at about 36 % of real time. The rule in ARCHITECTURE §11 gives **N = 3** for L = 3. The minimum would be N = 2, but 3 matches the 3 partitions and shows a full consumer group.
- **Running workers together slows each one down.** Going from 1 to 2 workers roughly doubles each worker's RTF, then it levels off at 3. That's consistent with sharing the CPU's 4 performance cores, but not proven.
- `tiny.en` is a safe fallback, and `small.en` is affordable only for occasional re-transcription by the Verifier (E5).
- The model loads in 0.6 s, so a restarted worker is ready almost at once (which helps fault demo F1).

**Determinism (A/A test).** 20 chunks were transcribed in two separate processes: **20/20 identical texts, and identical `asr_score` values (difference 0.0).** The fault-run vs clean-run consistency check (ARCHITECTURE §10) can therefore compare transcripts exactly.

### Accuracy: 5 s vs 10 s chunks, and Whisper repetition loops

All four lectures (3.04 h) were transcribed at 5 s and at 10 s chunks and scored against the captions with jiwer, after the normalisation in `docs/DATASET.md` §8. The MIT licence notice is excluded.

**The first pass exposed Whisper repetition loops.** With `temperature=0` and no fallback (chosen so output would be reproducible), a few percent of chunks got stuck repeating themselves: "4, 4, 4, …", "s s s …", "student N plus one. Oh, student N plus one. …".
- Such chunks contained up to 223 words where the captions have 7. The resulting insertions pushed WER up to 42 %.
- **138 chunks were affected** (1–8 % per lecture; most in the Algorithms lectures).
- They are exactly the chunks that fail Whisper's own quality checks (`compression_ratio > 2.4` or `avg_logprob < −1`).
- **`asr_score` doesn't flag them**: loop chunks scored 0.80–0.97, i.e. "confident".

**Four fixes were tested on the flagged chunks only** (`bench/whisper_loop_fix.py`; every other chunk is unchanged):

| Fix | Loops left (of 138) | Reproducible? | Mean WER, 5 s / 10 s chunks |
|---|---|---|---|
| None (the first pass) | 138 | yes | 25.0 % / 18.4 % |
| Drop the flagged chunk's text | 0 | yes | 14.0 % / 13.6 % (turns insertions into deletions) |
| Block repeated 3-word phrases (`no_repeat_ngram_size=3`) | **100 survived** | yes | 17.7 % / 14.5 % |
| Whisper's standard temperature fallback | 0 | **no:** only 57/138 identical on a re-run | 12.7 % / 11.0 % |
| **Repeat at `temperature=0` with `repetition_penalty=1.3`** | **1** | **yes** (greedy/beam at temperature 0) | **12.0 % / 10.1 %** |

**Per lecture, with the chosen fix:**

| Lecture | WER, 5 s chunks | **WER, 10 s chunks** | Substitutions / deletions / insertions (10 s) |
|---|---|---|---|
| Python · Lecture 1 (Bell) | 13.8 % | **12.2 %** | 189 / 107 / 478 |
| Python · Lecture 2 (Bell) | 9.4 % | **7.1 %** | 183 / 121 / 156 |
| Algorithms · Lecture 1 (Ku) | 13.0 % | **11.4 %** | 139 / 80 / 428 |
| Algorithms · Lecture 2 (Demaine) | 11.7 % | **9.5 %** | 247 / 161 / 251 |
| **Mean** | **12.0 %** | **10.1 %** | |

**Decisions:**
1. **Transcription rule:** decode at `temperature=0`. If the result fails the quality check (`compression_ratio > 2.4` or `avg_logprob < −1.0`), **decode once more with `repetition_penalty=1.3`**.
   - This removes 137 of 138 loops and gives the lowest WER in 6 of 8 cells. The standard fallback is within about 0.3 points in the other two.
   - It stays reproducible, so the consistency check still works. The A/A test will be re-run with the retry in M7, because the 20 chunks tested earlier contained no retries.
   - It costs one extra decode on about 1–8 % of chunks.
2. **`CHUNK_SECONDS = 10`.**
   - **Lower WER for every lecture**: 10.1 % vs 12.0 % on average, matching the EDA's prediction that halving boundary cuts would help.
   - **About 40 % less CPU**: RTF 0.18–0.20 vs 0.28–0.33 with 3 workers in parallel.
   - The same Kafka volume, and 427 KB messages (under the 1 MB limit, K8).
   - **Cost:** the live transcript appears about 5 s later. Notes appear when a window closes (end + grace), so their timing barely changes.
   - The alert guards are already measured in seconds of audio (ARCHITECTURE §7), so they work unchanged.

**The remaining errors are mostly insertions** (Whisper writing words that the captions lack). This is consistent with the EDA finding that the captions are edited: no fillers, no false starts, cleaned repetitions. The WER above therefore *overstates* real errors. The paper will report it as WER against edited captions.

### `asr_score` calibration (ARCHITECTURE §7)

The calibration uses the chosen fix and 361 windows of 30 s per chunk size. A "bad" window has WER > 30 %.

| | 5 s chunks | 10 s chunks |
|---|---|---|
| Bad windows | 12 / 361 (3.3 %) | 9 / 361 (2.5 %) |
| Spearman ρ (score vs WER) | −0.37 | −0.33 |
| At `T_SCORE = 0.55` | 5 alerts, precision 0.40, recall 0.17 | 0 alerts |
| Best F1 | `T = 0.56`: precision 0.38, recall 0.25, F1 0.30 | `T = 0.63`: precision 0.29, recall 0.22, F1 0.25 |

**Verdict: `asr_score` is a weak signal.** It correlates in the right direction, and |ρ| clears the plan's 0.3 bar, but at any threshold it catches only about 1 in 4 bad windows, and most of its alerts are false.
- **The new transcription rule** removes the strongest failure mode (loops) at the source.
- **`LOW_ASR_SCORE` stays an informational alert**, with `T_SCORE = 0.63` (best F1 at 10 s) **or** a chunk that still loops after the retry (`compression_ratio_max > 2.4`).
- **Extension E5 (Verifier) stays parked.** Its gate was "the calibration shows `LOW_ASR_SCORE` catches genuinely bad windows", and the data says it doesn't.

Raw data: `results/whisper_wer_base.en-*.json` and `results/whisper_windows_base.en-*.csv`.

## 7. Free LLM (`bench/llm_bench.py`, 20 transcript window pairs per model)

| Provider / model | Valid JSON | Latency (median / worst) | Tokens per call | Errors |
|---|---|---|---|---|
| Groq `openai/gpt-oss-120b` | **20/20** | 1.06 s / 2.11 s | 528 | none |
| Groq `openai/gpt-oss-20b` | **20/20** | 0.71 s / 1.63 s | 495 | none |
| Groq `qwen/qwen3.8-27b` | 7/20 | 0.71 s | 524 | **13 × HTTP 429** (rate-limited at about 24 requests/min) |
| Cerebras | — | — | — | Not testable: the API requires a payment method, contrary to the third-party summaries |

**Decision:** `GROQ_MODEL=openai/gpt-oss-120b,openai/gpt-oss-20b`, then the extractive fallback.
- **Speed:** both models are far inside the 10 s budget.
- **Daily budget:** each free model reportedly has its own daily quota, so the two together roughly double it with one key.
- **Real token use:** measured at about 500 tokens per call, lower than the EDA's estimate of about 1,200. But the benchmark prompt doesn't yet include the rolling memory, so the real cost will fall between the two.

**Quality.** Side-by-side samples are in `results/llm_side_by_side_*.md`. Both models produce a usable summary, key points and review questions, clearly more useful than the extractive baseline (which just copies the first long sentences). `gpt-oss-120b` lists more terms, but it **sometimes writes a definition the lecturer never gave** (for example, "administrivia"). That's the faithfulness risk the M9 human rating must check.

## 8. What changed in the design because of M2

- ARCHITECTURE §11: the Windows crash guard, the kill-by-process-tree rule, and the single broker confirmed to work.
- ARCHITECTURE §6.1: `windowstore.changelog.additional.retention.ms = 7 days`. The KIP-1033 handler and the drop metric are verified.
- ARCHITECTURE §6.3: the kafka-python 3.x facts (explicit commits required, the idempotent producer stays poisoned, send `bytes`, the 3.x admin names).
- ARCHITECTURE §8.0: Groq only, as a two-model chain; Cerebras dropped.
- **N = 3 workers** and the demo `video_id`s above.
- **`CHUNK_SECONDS = 10`** and the **repetition-penalty retry** in the worker (§6).
- **`LOW_ASR_SCORE`**: `T_SCORE = 0.63` or a residual loop; informational only. **E5 (Verifier) stays parked**, because its calibration gate wasn't met.
- Every `[verify]` marker that M2 could check is resolved.

## 9. Still open

- The A/A determinism test should be re-run in M7 with the retry rule active (decoding at temperature 0 should be reproducible, but this hasn't been measured).
- A second free LLM provider (for example Gemini) is optional, and not needed for the demo.
- Groq's real daily limits should be read from the Groq console (Settings → Limits). The figures above come from third-party summaries.
