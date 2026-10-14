"""Exploratory data analysis of the EduStream lecture dataset (milestone M1).

Reads data/manifest.csv (written by tools/fetch_dataset.py) and the media
and caption files under data/raw/, then writes:

    analysis/tables/dataset_*.csv        one table per EDA section
    analysis/figures/dataset_*.svg       figures used in analysis/DATASET_EDA.md
    analysis/tables/dataset_eda_summary.json   headline numbers

No Kafka and no Whisper: audio is decoded with PyAV (bundled with
faster-whisper) and captions are parsed directly. Run from the repo root:

    .venv\\Scripts\\python analysis\\dataset_eda.py
"""

from __future__ import annotations

import csv
import json
import math
import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import av
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from faster_whisper.audio import decode_audio  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MANIFEST = DATA / "manifest.csv"
OUT = Path(__file__).resolve().parent
FIGURES = OUT / "figures"
TABLES = OUT / "tables"


# --------------------------------------------------
# Parameters (mirrors docs/ARCHITECTURE.md defaults)
# --------------------------------------------------

SAMPLE_RATE = 16000
FRAME_S = 0.05                 # 50 ms analysis frames
CHUNK_OPTIONS_S = (5, 10)      # candidate CHUNK_SECONDS
WINDOW_S = 30                  # WINDOW_SECONDS
NOTE_EVERY_N_WINDOWS = 2
SILENCE_DBFS = -45.0           # a 5 s chunk quieter than this is "silent"
ACTIVE_MARGIN_DB = 10.0        # frame is "active" if > noise floor + margin
CLIP_LEVEL = 0.999
LONG_PAUSE_S = 2.0
MATTR_WINDOW = 500             # moving-average type-token ratio window
TOKENS_PER_WORD = 1.33         # rough English tokens-per-word for LLM budgeting
PROMPT_OVERHEAD_TOKENS = 700   # instructions + rolling memory per call (estimate)
OUTPUT_TOKENS = 300            # max notes JSON per call (estimate)
JSON_OVERHEAD_BYTES = 400      # non-audio fields of an audio_chunk.v1 record

STOPWORDS = set("""
a about above after again against all also am an and any are aren't as at be because been before being
below between both but by can can't cannot could couldn't did didn't do does doesn't doing don't down
during each few for from further get gets getting go going gonna got had hadn't has hasn't have haven't
having he he'd he'll he's her here here's hers herself him himself his how how's i i'd i'll i'm i've if
in into is isn't it it's its itself just kind know let let's like lot me more most mustn't my myself
no nor not now of off ok okay on once one only or other ought our ours ourselves out over own really
right same say says see shan't she she'd she'll she's should shouldn't so some such sort than that
that's the their theirs them themselves then there there's these they they'd they'll they're they've
thing things think this those through to too um uh under until up us very want was wasn't way we we'd
we'll we're we've well were weren't what what's when when's where where's which while who who's whom
why why's will with won't would wouldn't yeah yes you you'd you'll you're you've your yours yourself
yourselves actually basically going gonna wanna maybe sure mean two three first second something
""".split())

BOILERPLATE_END = re.compile(r"ocw\.mit\.edu", re.IGNORECASE)
ANNOTATION = re.compile(r"\[[^\]]*\]|\([A-Z][A-Z ]+\)")
SPEAKER_LABEL = re.compile(r"(?m)^\s*([A-Z][A-Z .'\-]{1,40}):\s*")
TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


# --------------------------------------------------
# Figure style (validated palette: slots 1-2, light surface)
# --------------------------------------------------

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SERIES = ["#2a78d6", "#eb6834"]

plt.rcParams.update({
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "font.family": ["Segoe UI", "DejaVu Sans", "sans-serif"],
    "font.size": 9,
    "axes.edgecolor": AXIS,
    "axes.labelcolor": INK_2,
    "axes.titlecolor": INK,
    "axes.titlesize": 10,
    "axes.titleweight": "semibold",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "axes.grid.axis": "y",
    "axes.axisbelow": True,
    "grid.color": GRID,
    "grid.linewidth": 0.6,
    "grid.linestyle": "-",
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "xtick.labelcolor": INK_2,
    "ytick.labelcolor": INK_2,
    "legend.frameon": False,
    "lines.linewidth": 1.5,
    "svg.fonttype": "none",
})


def save(fig, name: str) -> None:
    fig.savefig(FIGURES / name, format="svg", bbox_inches="tight")
    preview = os.environ.get("EDA_PREVIEW_DIR")  # optional PNG copies for visual review
    if preview:
        fig.savefig(Path(preview) / name.replace(".svg", ".png"), format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)


def write_csv(name: str, rows: list[dict]) -> None:
    # utf-8-sig so Excel shows the "·" in lecture names correctly
    with (TABLES / name).open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def short_label(item: dict) -> str:
    """Reader-facing lecture name, e.g. 'Python · Lecture 1 (Bell)'."""
    return item["display_name"]


# --------------------------------------------------
# Audio
# --------------------------------------------------

def container_info(path: Path) -> dict:
    with av.open(str(path)) as container:
        stream = container.streams.audio[0]
        ctx = stream.codec_context
        channels = getattr(getattr(ctx, "layout", None), "nb_channels", None) or getattr(ctx, "channels", "")
        duration = container.duration / av.time_base if container.duration else float("nan")
        return {
            "container": path.suffix.lstrip(".").lower(),
            "audio_codec": ctx.name,
            "sample_rate_hz": ctx.sample_rate,
            "channels": channels,
            "audio_bitrate_kbps": round((stream.bit_rate or 0) / 1000, 1),
            "container_duration_s": round(duration, 2),
        }


def audio_metrics(samples: np.ndarray) -> dict:
    frame = int(FRAME_S * SAMPLE_RATE)
    n_frames = len(samples) // frame
    frames = samples[: n_frames * frame].reshape(n_frames, frame)
    frame_db = 20 * np.log10(np.sqrt(np.mean(frames ** 2, axis=1)) + 1e-10)

    noise_floor = float(np.percentile(frame_db, 10))
    active = frame_db > noise_floor + ACTIVE_MARGIN_DB

    chunk = int(5 * SAMPLE_RATE)
    n_chunks = math.ceil(len(samples) / chunk)
    chunk_db = np.empty(n_chunks)
    chunk_active = np.empty(n_chunks)
    frames_per_chunk = chunk // frame
    for i in range(n_chunks):
        piece = samples[i * chunk:(i + 1) * chunk]
        chunk_db[i] = 20 * np.log10(np.sqrt(np.mean(piece ** 2)) + 1e-10)
        chunk_active[i] = active[i * frames_per_chunk:(i + 1) * frames_per_chunk].mean() if i * frames_per_chunk < n_frames else 0.0

    return {
        "frame_db": frame_db,
        "chunk_db": chunk_db,
        "chunk_active": chunk_active,
        "noise_floor_dbfs": noise_floor,
        "p90_frame_dbfs": float(np.percentile(frame_db, 90)),
        "snr_proxy_db": float(np.percentile(frame_db, 90) - noise_floor),
        "clipped_sample_pct": float(np.mean(np.abs(samples) >= CLIP_LEVEL) * 100),
        "active_frame_pct": float(active.mean() * 100),
    }


# --------------------------------------------------
# Captions
# --------------------------------------------------

@dataclass
class Cue:
    start: float
    end: float
    raw: str
    text: str = ""
    annotations: int = 0
    speaker_labels: int = 0
    boilerplate: bool = False


def to_seconds(stamp: str) -> float:
    hours, minutes, rest = stamp.strip().split(":")
    seconds, millis = rest.replace(".", ",").split(",")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


def parse_srt(path: Path) -> list[Cue]:
    blocks = re.split(r"\r?\n\s*\r?\n", path.read_text(encoding="utf-8-sig").strip())
    cues = []
    for block in blocks:
        lines = block.strip().splitlines()
        timing = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing is None:
            continue
        start, end = (to_seconds(part) for part in lines[timing].split("-->"))
        raw = " ".join(lines[timing + 1:]).strip()
        cue = Cue(start, end, raw)
        cue.annotations = len(ANNOTATION.findall(raw))
        cue.speaker_labels = len(SPEAKER_LABEL.findall("\n".join(lines[timing + 1:])))
        text = SPEAKER_LABEL.sub(" ", "\n".join(lines[timing + 1:]))
        cue.text = " ".join(ANNOTATION.sub(" ", text).split())
        cues.append(cue)

    # OCW lectures open with a fixed Creative Commons notice ending in "ocw.mit.edu".
    for i, cue in enumerate(cues):
        if cue.start > 60:
            break
        if BOILERPLATE_END.search(cue.raw):
            for earlier in cues[: i + 1]:
                earlier.boilerplate = True
            break
    return cues


def word_spans(cues: list[Cue]) -> list[tuple[float, float, str]]:
    """Spread each cue's words evenly over the cue (an estimate; no word timestamps)."""
    spans = []
    for cue in cues:
        if cue.boilerplate:
            continue
        words = TOKEN.findall(cue.text.lower())
        if not words:
            continue
        step = (cue.end - cue.start) / len(words)
        for i, word in enumerate(words):
            spans.append((cue.start + i * step, cue.start + (i + 1) * step, word))
    return spans


def mattr(tokens: list[str], window: int) -> float:
    if len(tokens) < window:
        return len(set(tokens)) / max(len(tokens), 1)
    counts = Counter(tokens[:window])
    total = len(counts)
    for i in range(window, len(tokens)):
        counts[tokens[i]] += 1
        counts[tokens[i - window]] -= 1
        if counts[tokens[i - window]] == 0:
            del counts[tokens[i - window]]
        total += len(counts)
    return total / ((len(tokens) - window + 1) * window)


def transcript_metrics(cues: list[Cue], duration: float) -> dict:
    content = [c for c in cues if not c.boilerplate and c.text]
    spans = word_spans(cues)
    tokens = [w for _, _, w in spans]
    speech_start = content[0].start if content else 0.0
    speech_end = content[-1].end if content else 0.0

    window_counts = Counter(int(((s + e) / 2) // WINDOW_S) for s, e, _ in spans)
    first_full = math.ceil(speech_start / WINDOW_S)
    last_full = int(speech_end // WINDOW_S) - 1
    wpm = np.array([window_counts.get(w, 0) * 60 / WINDOW_S for w in range(first_full, last_full + 1)])

    chunk_words, boundary_cut_pct = {}, {}
    for size in CHUNK_OPTIONS_S:
        counts = Counter(int(((s + e) / 2) // size) for s, e, _ in spans)
        n_chunks = math.ceil(duration / size)
        chunk_words[size] = np.array([counts.get(i, 0) for i in range(n_chunks)])
        cut = sum(1 for s, e, _ in spans if math.floor((s + 1e-6) / size) != math.floor((e - 1e-6) / size))
        boundary_cut_pct[size] = 100 * cut / max(len(spans), 1)

    # Consecutive speech cues usually touch (gap 0). A positive gap only appears where
    # an empty or annotation-only cue marks silence/noise, so these are silent intervals.
    gaps = np.array([b.start - a.end for a, b in zip(content, content[1:])])
    overlaps = int(np.sum(gaps < -0.001)) if len(gaps) else 0
    pauses = gaps[gaps > 0.05] if len(gaps) else gaps
    covered = sum(c.end - c.start for c in content)
    content_words = [t for t in tokens if t not in STOPWORDS and not t.isdigit() and len(t) > 2]

    return {
        "cues": len(cues),
        "empty_cues": sum(1 for c in cues if not c.text and not c.boilerplate),
        "boilerplate_s": round(max((c.end for c in cues if c.boilerplate), default=0.0), 2),
        "annotations": sum(c.annotations for c in cues),
        "annotation_examples": sorted({m.upper() for c in cues for m in ANNOTATION.findall(c.raw)})[:8],
        "speaker_labels": sum(c.speaker_labels for c in cues),
        "overlapping_cues": overlaps,
        "words": len(tokens),
        "types": len(set(tokens)),
        "ttr": len(set(tokens)) / max(len(tokens), 1),
        "mattr": mattr(tokens, MATTR_WINDOW),
        "digit_token_pct": 100 * sum(1 for t in tokens if any(ch.isdigit() for ch in t)) / max(len(tokens), 1),
        "speech_start_s": speech_start,
        "speech_end_s": speech_end,
        "caption_coverage_pct": 100 * covered / duration,
        "tail_gap_s": duration - speech_end,
        "wpm": wpm,
        "pauses": pauses,
        "contiguous_pct": float(np.mean(gaps <= 0.05) * 100) if len(gaps) else 0.0,
        "long_pauses": int(np.sum(pauses > LONG_PAUSE_S)) if len(pauses) else 0,
        "chunk_words": chunk_words,
        "boundary_cut_pct": boundary_cut_pct,
        "top_terms": Counter(content_words).most_common(15),
    }


# --------------------------------------------------
# Figures
# --------------------------------------------------

def fig_durations(items: list[dict]) -> None:
    fig, ax = plt.subplots(figsize=(6.4, 2.6))
    labels = [short_label(i) for i in items]
    minutes = [i["duration_s"] / 60 for i in items]
    ax.barh(labels, minutes, color=SERIES[0], height=0.55)
    for y, (value, item) in enumerate(zip(minutes, items)):
        note = "" if item["has_transcript"] else " · no captions"
        ax.text(value + 0.6, y, f"{value:.1f} min{note}", va="center", color=INK_2, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Duration (minutes)")
    ax.set_xlim(0, max(minutes) * 1.2)
    ax.grid(axis="x")
    ax.grid(axis="y", visible=False)
    ax.set_title("Lecture durations")
    save(fig, "dataset_durations.svg")


def fig_loudness(items: list[dict]) -> None:
    fig, axes = plt.subplots(len(items), 2, figsize=(9, 1.55 * len(items)),
                             gridspec_kw={"width_ratios": [1, 2.4]}, squeeze=False)
    bins = np.arange(-80, 1, 2.5)
    for row, item in zip(axes, items):
        db = item["audio"]["chunk_db"]
        row[0].hist(db, bins=bins, color=SERIES[0])
        row[0].axvline(SILENCE_DBFS, color=MUTED, linewidth=0.8)
        row[0].set_ylabel(short_label(item), rotation=0, ha="right", va="center", color=INK)
        row[0].set_xlim(-80, 0)
        t = np.arange(len(db)) * 5 / 60
        row[1].plot(t, db, color=SERIES[0], linewidth=0.9)
        row[1].axhline(SILENCE_DBFS, color=MUTED, linewidth=0.8)
        row[1].set_ylim(-80, 0)
    axes[0][0].set_title("Distribution of 5 s chunk loudness")
    axes[0][1].set_title("Loudness over the lecture")
    axes[0][1].text(1, SILENCE_DBFS + 2, f"silence threshold {SILENCE_DBFS:.0f} dBFS", color=MUTED, fontsize=7)
    axes[-1][0].set_xlabel("RMS level (dBFS)")
    axes[-1][1].set_xlabel("Lecture time (minutes)")
    fig.tight_layout()
    save(fig, "dataset_loudness.svg")


def fig_wpm(items: list[dict]) -> None:
    with_text = [i for i in items if i["has_transcript"]]
    fig, axes = plt.subplots(len(with_text), 1, figsize=(8, 1.5 * len(with_text)), sharex=True, squeeze=False)
    for ax, item in zip(axes[:, 0], with_text):
        tm = item["transcript"]
        wpm = tm["wpm"]
        t = (np.arange(len(wpm)) + math.ceil(tm["speech_start_s"] / WINDOW_S) + 0.5) * WINDOW_S / 60
        ax.plot(t, wpm, color=SERIES[0], linewidth=1.2)
        median = float(np.median(wpm))
        ax.axhline(median, color=MUTED, linewidth=0.8)
        ax.text(1.01, median, f"median {median:.0f}", color=INK_2, fontsize=7, va="center",
                transform=ax.get_yaxis_transform())
        ax.set_ylabel(short_label(item), rotation=0, ha="right", va="center", color=INK)
        ax.set_ylim(0, 260)
    axes[0, 0].set_title("Speaking rate per 30 s window (words per minute, from captions)")
    axes[-1, 0].set_xlabel("Lecture time (minutes)")
    fig.tight_layout()
    save(fig, "dataset_speaking_rate.svg")


def fig_words_per_chunk(items: list[dict]) -> None:
    with_text = [i for i in items if i["has_transcript"]]
    fig, axes = plt.subplots(1, 2, figsize=(8, 2.6), squeeze=False)
    for ax, size, color in zip(axes[0], CHUNK_OPTIONS_S, SERIES):
        pooled = np.concatenate([i["transcript"]["chunk_words"][size] for i in with_text])
        ax.hist(pooled, bins=np.arange(0, pooled.max() + 2) - 0.5, color=color)
        ax.set_title(f"Words per {size} s chunk (all captioned lectures)")
        ax.set_xlabel("Words in chunk")
        ax.text(0.98, 0.92, f"median {np.median(pooled):.0f} · zero-word {100 * np.mean(pooled == 0):.1f}%",
                transform=ax.transAxes, ha="right", color=INK_2, fontsize=8)
    axes[0][0].set_ylabel("Chunks")
    fig.tight_layout()
    save(fig, "dataset_words_per_chunk.svg")


def fig_boundary_cuts(items: list[dict]) -> None:
    with_text = [i for i in items if i["has_transcript"]]
    x = np.arange(len(with_text))
    width = 0.36
    fig, ax = plt.subplots(figsize=(6.4, 2.6))
    for k, (size, color) in enumerate(zip(CHUNK_OPTIONS_S, SERIES)):
        values = [i["transcript"]["boundary_cut_pct"][size] for i in with_text]
        bars = ax.bar(x + (k - 0.5) * (width + 0.02), values, width, color=color, label=f"{size} s chunks")
        for bar, value in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, value + 0.15, f"{value:.1f}%",
                    ha="center", color=INK_2, fontsize=7)
    ax.set_xticks(x, [short_label(i).replace(" · ", "\n") for i in with_text], fontsize=8)
    ax.set_ylabel("Words split by a chunk boundary (%)")
    ax.set_title("Estimated words cut at chunk boundaries")
    ax.set_ylim(0, max(i["transcript"]["boundary_cut_pct"][CHUNK_OPTIONS_S[0]] for i in with_text) * 1.4)
    ax.legend(loc="upper left", ncol=2, fontsize=8)
    save(fig, "dataset_boundary_cuts.svg")


def fig_pauses(items: list[dict]) -> None:
    pooled = np.concatenate([i["transcript"]["pauses"] for i in items if i["has_transcript"]])
    fig, ax = plt.subplots(figsize=(6.4, 2.4))
    bins = np.logspace(np.log10(0.05), np.log10(max(pooled.max(), 10)), 30)
    ax.hist(pooled, bins=bins, color=SERIES[0])
    ax.set_xscale("log")
    ax.axvline(LONG_PAUSE_S, color=MUTED, linewidth=0.8)
    ax.text(LONG_PAUSE_S * 0.92, ax.get_ylim()[1] * 0.88, f"{LONG_PAUSE_S:.0f} s", color=MUTED, fontsize=7, ha="right")
    ax.set_xlabel("Silent interval between captioned speech (seconds, log scale)")
    ax.set_ylabel("Intervals")
    ax.set_title("Silent intervals between captioned speech (all lectures)")
    save(fig, "dataset_pauses.svg")


def fig_top_terms(items: list[dict]) -> None:
    with_text = [i for i in items if i["has_transcript"]]
    fig, axes = plt.subplots(1, len(with_text), figsize=(2.6 * len(with_text), 3.4), squeeze=False)
    for ax, item in zip(axes[0], with_text):
        terms = item["transcript"]["top_terms"][:12][::-1]
        ax.barh([t for t, _ in terms], [c for _, c in terms], color=SERIES[0], height=0.6)
        ax.set_title(short_label(item), fontsize=9)
        ax.grid(axis="x")
        ax.grid(axis="y", visible=False)
        ax.tick_params(axis="y", labelsize=8)
    axes[0][0].set_xlabel("Occurrences")
    fig.suptitle("Most frequent content words (stopwords removed)", color=INK, fontsize=10, fontweight="semibold")
    fig.tight_layout()
    save(fig, "dataset_top_terms.svg")


# --------------------------------------------------
# Main
# --------------------------------------------------

def main() -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    TABLES.mkdir(parents=True, exist_ok=True)

    with MANIFEST.open(encoding="utf-8-sig") as handle:
        items = list(csv.DictReader(handle))

    for item in items:
        media = DATA / item["media_file"]
        print(f"[{item['item_id']}] decoding {media.name}")
        item.update(container_info(media))
        samples = decode_audio(str(media), sampling_rate=SAMPLE_RATE)
        item["duration_s"] = len(samples) / SAMPLE_RATE
        item["audio"] = audio_metrics(samples)
        item["has_transcript"] = bool(item["transcript_file"])
        if item["has_transcript"]:
            item["transcript"] = transcript_metrics(parse_srt(DATA / item["transcript_file"]), item["duration_s"])
        del samples

    # ---- tables -----------------------------------------------------------
    write_csv("dataset_inventory.csv", [{
        "item_id": i["item_id"], "lecture": i["display_name"], "title": i["title"], "speaker": i["speaker"], "split": i["split"],
        "container": i["container"], "audio_codec": i["audio_codec"], "sample_rate_hz": i["sample_rate_hz"],
        "channels": i["channels"], "audio_bitrate_kbps": i["audio_bitrate_kbps"],
        "decoded_duration_s": round(i["duration_s"], 2), "container_duration_s": i["container_duration_s"],
        "media_mb": round(int(i["media_bytes"]) / 1e6, 1), "transcript_format": i["transcript_format"],
    } for i in items])

    write_csv("dataset_audio_quality.csv", [{
        "item_id": i["item_id"], "lecture": i["display_name"],
        "chunk_dbfs_median": round(float(np.median(i["audio"]["chunk_db"])), 1),
        "chunk_dbfs_p10": round(float(np.percentile(i["audio"]["chunk_db"], 10)), 1),
        "chunk_dbfs_p90": round(float(np.percentile(i["audio"]["chunk_db"], 90)), 1),
        "silent_chunk_pct": round(float(np.mean(i["audio"]["chunk_db"] < SILENCE_DBFS) * 100), 2),
        "low_activity_chunk_pct": round(float(np.mean(i["audio"]["chunk_active"] < 0.1) * 100), 2),
        "noise_floor_dbfs": round(i["audio"]["noise_floor_dbfs"], 1),
        "snr_proxy_db": round(i["audio"]["snr_proxy_db"], 1),
        "active_frame_pct": round(i["audio"]["active_frame_pct"], 1),
        "clipped_sample_pct": round(i["audio"]["clipped_sample_pct"], 4),
    } for i in items])

    captioned = [i for i in items if i["has_transcript"]]
    write_csv("dataset_transcript_stats.csv", [{
        "item_id": i["item_id"], "lecture": i["display_name"],
        "words": i["transcript"]["words"], "types": i["transcript"]["types"],
        "ttr": round(i["transcript"]["ttr"], 3), f"mattr_{MATTR_WINDOW}": round(i["transcript"]["mattr"], 3),
        "wpm_median": round(float(np.median(i["transcript"]["wpm"])), 1),
        "wpm_p10": round(float(np.percentile(i["transcript"]["wpm"], 10)), 1),
        "wpm_p90": round(float(np.percentile(i["transcript"]["wpm"], 90)), 1),
        "windows_wpm_below_40_pct": round(float(np.mean(i["transcript"]["wpm"] < 40) * 100), 2),
        "contiguous_cue_pct": round(i["transcript"]["contiguous_pct"], 1),
        "silent_intervals": len(i["transcript"]["pauses"]),
        "silent_interval_median_s": round(float(np.median(i["transcript"]["pauses"])), 2),
        "silent_interval_p90_s": round(float(np.percentile(i["transcript"]["pauses"], 90)), 2),
        "silent_intervals_over_2s": i["transcript"]["long_pauses"],
        "silent_time_pct": round(float(i["transcript"]["pauses"].sum() / i["duration_s"] * 100), 1),
        "digit_token_pct": round(i["transcript"]["digit_token_pct"], 2),
    } for i in captioned])

    write_csv("dataset_chunk_stats.csv", [{
        "item_id": i["item_id"], "lecture": i["display_name"], "chunk_s": size,
        "chunks": len(i["transcript"]["chunk_words"][size]),
        "words_per_chunk_median": float(np.median(i["transcript"]["chunk_words"][size])),
        "zero_word_chunk_pct": round(float(np.mean(i["transcript"]["chunk_words"][size] == 0) * 100), 2),
        "boundary_cut_word_pct": round(i["transcript"]["boundary_cut_pct"][size], 2),
    } for i in captioned for size in CHUNK_OPTIONS_S])

    write_csv("dataset_data_quality.csv", [{
        "item_id": i["item_id"], "lecture": i["display_name"], "cues": i["transcript"]["cues"], "empty_cues": i["transcript"]["empty_cues"],
        "boilerplate_s": i["transcript"]["boilerplate_s"], "annotations": i["transcript"]["annotations"],
        "annotation_examples": "; ".join(i["transcript"]["annotation_examples"]),
        "speaker_labels": i["transcript"]["speaker_labels"],
        "overlapping_cues": i["transcript"]["overlapping_cues"],
        "speech_start_s": round(i["transcript"]["speech_start_s"], 2),
        "speech_end_s": round(i["transcript"]["speech_end_s"], 2),
        "tail_after_last_caption_s": round(i["transcript"]["tail_gap_s"], 2),
        "caption_coverage_pct": round(i["transcript"]["caption_coverage_pct"], 1),
        "duration_mismatch_s": round(i["duration_s"] - float(i["container_duration_s"]), 2),
    } for i in captioned])

    write_csv("dataset_top_terms.csv", [
        {"item_id": i["item_id"], "lecture": i["display_name"], "rank": r + 1, "term": t, "count": c}
        for i in captioned for r, (t, c) in enumerate(i["transcript"]["top_terms"])
    ])

    median_wpm_all = float(np.median(np.concatenate([i["transcript"]["wpm"] for i in captioned])))
    projection = []
    for i in items:
        wpm = float(np.median(i["transcript"]["wpm"])) if i["has_transcript"] else median_wpm_all
        windows = math.ceil(i["duration_s"] / WINDOW_S)
        calls = math.ceil(windows / NOTE_EVERY_N_WINDOWS)
        words_per_call = wpm * WINDOW_S * NOTE_EVERY_N_WINDOWS / 60
        tokens_per_call = words_per_call * TOKENS_PER_WORD + PROMPT_OVERHEAD_TOKENS + OUTPUT_TOKENS
        row = {"item_id": i["item_id"], "lecture": i["display_name"], "duration_min": round(i["duration_s"] / 60, 1),
               "wpm_used": round(wpm, 1), "windows_30s": windows, "llm_calls": calls,
               "tokens_per_call_est": round(tokens_per_call), "tokens_total_est": round(calls * tokens_per_call)}
        for size in CHUNK_OPTIONS_S:
            chunks = math.ceil(i["duration_s"] / size)
            message = 4 * math.ceil(SAMPLE_RATE * 2 * size / 3) + JSON_OVERHEAD_BYTES
            row[f"chunks_{size}s"] = chunks
            row[f"message_kb_{size}s"] = round(message / 1000, 1)
            row[f"video_audio_mb_{size}s"] = round(chunks * message / 1e6, 1)
        projection.append(row)
    write_csv("dataset_pipeline_projection.csv", projection)

    # ---- figures ----------------------------------------------------------
    fig_durations(items)
    fig_loudness(items)
    fig_wpm(items)
    fig_words_per_chunk(items)
    fig_boundary_cuts(items)
    fig_pauses(items)
    fig_top_terms(items)

    summary = {
        "lectures": len(items),
        "captioned_lectures": len(captioned),
        "total_hours": round(sum(i["duration_s"] for i in items) / 3600, 2),
        "captioned_hours": round(sum(i["duration_s"] for i in captioned) / 3600, 2),
        "words_total": sum(i["transcript"]["words"] for i in captioned),
        "median_wpm_all": round(median_wpm_all, 1),
        "silence_dbfs": SILENCE_DBFS,
        "boundary_cut_pct_by_chunk": {
            str(size): round(float(np.mean([i["transcript"]["boundary_cut_pct"][size] for i in captioned])), 2)
            for size in CHUNK_OPTIONS_S
        },
    }
    (TABLES / "dataset_eda_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
