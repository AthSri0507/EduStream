"""Generate reproducible, schema-level EDA artifacts for the repository.

The repository does not contain a persisted dataset. The only concrete sample
available locally is the ten-message loop in producer/producer.py.
"""

from __future__ import annotations

import csv
import html
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent
FIGURES = OUT / "figures"
TABLES = OUT / "tables"


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def svg_document(width: int, height: int, body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        '<style>text{font-family:Arial,sans-serif;fill:#1f2937}'
        '.title{font-size:20px;font-weight:700}.label{font-size:13px}'
        '.small{font-size:11px}.axis{stroke:#6b7280;stroke-width:1}'
        '.grid{stroke:#e5e7eb;stroke-width:1}.bar{fill:#2563eb}'
        '.accent{fill:#0f766e}</style>'
        + body
        + "</svg>"
    )


def create_timeline_svg(path: Path) -> None:
    width, height = 900, 420
    left, right, top, bottom = 75, 30, 55, 70
    plot_w, plot_h = width - left - right, height - top - bottom
    max_seconds = 50
    body = ['<text x="30" y="32" class="title">Illustrative chunk timeline</text>']
    for tick in range(0, 51, 10):
        x = left + plot_w * tick / max_seconds
        body.append(f'<line x1="{x}" y1="{top}" x2="{x}" y2="{top + plot_h}" class="grid"/>')
        body.append(f'<text x="{x - 6}" y="{height - 42}" class="small">{tick}</text>')
    body.append(f'<line x1="{left}" y1="{top + plot_h}" x2="{width - right}" y2="{top + plot_h}" class="axis"/>')
    body.append(f'<text x="{width // 2 - 45}" y="{height - 18}" class="label">seconds</text>')
    for chunk_id in range(10):
        start = chunk_id * 5
        x = left + plot_w * start / max_seconds
        bar_w = plot_w * 5 / max_seconds - 2
        y = top + 18 + (chunk_id % 2) * 130
        body.append(f'<rect x="{x}" y="{y}" width="{bar_w}" height="70" rx="4" class="bar"/>')
        body.append(
            f'<text x="{x + bar_w / 2 - 15}" y="{y + 40}" class="small" '
            f'style="fill:white">c{chunk_id}</text>'
        )
    body.append('<text x="75" y="105" class="label">Chunks 0–4</text>')
    body.append('<text x="75" y="235" class="label">Chunks 5–9</text>')
    path.write_text(svg_document(width, height, "".join(body)), encoding="utf-8")


def create_pipeline_svg(path: Path) -> None:
    width, height = 1100, 300
    boxes = [
        ("Video/audio", "data/videos + WAV chunks"),
        ("video_audio", "Kafka input topic"),
        ("transcriptions", "Whisper output"),
        ("generated_notes", "30-sec windows"),
        ("final_notes", "extractive notes"),
    ]
    body = ['<text x="35" y="35" class="title">Repository data flow</text>']
    box_w, box_h, y, gap = 180, 110, 110, 35
    for index, (title, subtitle) in enumerate(boxes):
        x = 25 + index * (box_w + gap)
        body.append(f'<rect x="{x}" y="{y}" width="{box_w}" height="{box_h}" rx="8" class="accent"/>')
        body.append(
            f'<text x="{x + box_w / 2}" y="{y + 42}" text-anchor="middle" '
            f'style="fill:white;font-size:15px;font-weight:700">{html.escape(title)}</text>'
        )
        body.append(
            f'<text x="{x + box_w / 2}" y="{y + 68}" text-anchor="middle" '
            f'style="fill:white;font-size:11px">{html.escape(subtitle)}</text>'
        )
        if index < len(boxes) - 1:
            x1 = x + box_w
            x2 = x + box_w + gap - 8
            body.append(f'<line x1="{x1}" y1="{y + box_h / 2}" x2="{x2}" y2="{y + box_h / 2}" '
                        'stroke="#374151" stroke-width="3"/>')
            body.append(f'<polygon points="{x2},{y + box_h / 2} {x2 - 10},{y + box_h / 2 - 7} '
                        f'{x2 - 10},{y + box_h / 2 + 7}" fill="#374151"/>')
    path.write_text(svg_document(width, height, "".join(body)), encoding="utf-8")


def main() -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    TABLES.mkdir(parents=True, exist_ok=True)

    rows = [
        {
            "video_id": "lecture_01",
            "chunk_id": i,
            "timestamp_seconds": i * 5,
            "text": f"This is lecture audio chunk {i}",
            "text_word_count": 6,
        }
        for i in range(10)
    ]
    write_csv(
        TABLES / "illustrative_input_messages.csv",
        list(rows[0]),
        rows,
    )
    write_csv(
        TABLES / "field_dictionary.csv",
        ["stage", "field", "data_type", "required", "description", "source"],
        [
            {"stage": "producer sample", "field": "video_id", "data_type": "string", "required": "yes", "description": "Logical video identifier", "source": "producer/producer.py:20"},
            {"stage": "producer sample", "field": "chunk_id", "data_type": "integer", "required": "yes", "description": "Zero-based audio chunk identifier", "source": "producer/producer.py:21"},
            {"stage": "producer sample", "field": "timestamp", "data_type": "integer", "required": "yes", "description": "Chunk start time in seconds", "source": "producer/producer.py:22"},
            {"stage": "producer sample", "field": "text", "data_type": "string", "required": "yes", "description": "Text payload in the sample producer", "source": "producer/producer.py:23"},
            {"stage": "audio event", "field": "start_time", "data_type": "integer", "required": "yes", "description": "Chunk start time in seconds", "source": "producer/video_producer.py:58"},
            {"stage": "audio event", "field": "end_time", "data_type": "integer", "required": "yes", "description": "Chunk end time in seconds", "source": "producer/video_producer.py:59"},
            {"stage": "audio event", "field": "audio_path", "data_type": "string", "required": "yes", "description": "Local WAV path used by transcription", "source": "producer/video_producer.py:60"},
            {"stage": "transcript event", "field": "text", "data_type": "string", "required": "yes", "description": "Whisper transcript for an audio chunk", "source": "summarizer/transcription/transcription_worker.py:110"},
            {"stage": "notes event", "field": "window_start/window_end", "data_type": "integer", "required": "yes", "description": "30-second aggregation window", "source": "stream_processor/StreamProcessor.java:133-140"},
            {"stage": "notes event", "field": "notes", "data_type": "array[string]", "required": "yes", "description": "Up to five sentences of at least five words", "source": "summarizer/notes/note_generator.py:65-81"},
        ],
    )
    create_timeline_svg(FIGURES / "illustrative_chunk_timeline.svg")
    create_pipeline_svg(FIGURES / "repository_data_flow.svg")


if __name__ == "__main__":
    main()
