"""Download the EduStream lecture dataset and write data/manifest.csv.

Reads tools/dataset_catalog.json, downloads each media and caption file
from archive.org into data/raw/<item_id>/, and verifies every file against
the SHA-1 published in the archive.org item metadata. Files that already
exist with the right checksum are not downloaded again.

Usage (from the repo root):
    .venv\\Scripts\\python tools\\fetch_dataset.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "tools" / "dataset_catalog.json"
RAW_DIR = ROOT / "data" / "raw"
MANIFEST = ROOT / "data" / "manifest.csv"

ARCHIVE_METADATA = "https://archive.org/metadata/{item}"
ARCHIVE_DOWNLOAD = "https://archive.org/download/{item}/{name}"
MAX_ATTEMPTS = 20

MANIFEST_FIELDS = [
    "item_id", "display_name", "title", "course", "speaker", "split",
    "media_file", "media_bytes", "media_sha1", "duration_s",
    "transcript_file", "transcript_format", "transcript_sha1",
    "source_url", "course_url", "licence",
]


# --------------------------------------------------
# archive.org helpers
# --------------------------------------------------

def fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def sha1_of(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(item: str, name: str, target: Path, expected_sha1: str, size: int) -> None:
    if target.exists() and sha1_of(target) == expected_sha1:
        print(f"  ok (cached)  {name}")
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    url = ARCHIVE_DOWNLOAD.format(item=item, name=name)
    print(f"  downloading  {name} ({size / 1e6:.1f} MB)", flush=True)

    # archive.org mirrors can stall; resume with HTTP Range requests and retry.
    for attempt in range(1, MAX_ATTEMPTS + 1):
        have = partial.stat().st_size if partial.exists() else 0
        if have >= size:
            break
        request = urllib.request.Request(url, headers={"Range": f"bytes={have}-"} if have else {})
        try:
            with urllib.request.urlopen(request, timeout=60) as response, partial.open("ab" if have else "wb") as out:
                if have and response.status != 206:
                    out.truncate(0)
                    have = 0
                next_report = have + 20_000_000
                while True:
                    block = response.read(1 << 20)
                    if not block:
                        break
                    out.write(block)
                    have += len(block)
                    if have >= next_report:
                        print(f"    {have / 1e6:6.1f} / {size / 1e6:.1f} MB", flush=True)
                        next_report += 20_000_000
        except (TimeoutError, OSError) as error:
            print(f"    attempt {attempt} interrupted at {have / 1e6:.1f} MB: {error}", flush=True)
            time.sleep(min(5 * attempt, 30))

    if not partial.exists() or partial.stat().st_size < size:
        raise RuntimeError(f"Gave up downloading {name} after {MAX_ATTEMPTS} attempts")

    actual = sha1_of(partial)
    if actual != expected_sha1:
        partial.unlink()
        raise RuntimeError(f"SHA-1 mismatch for {name}: {actual} != {expected_sha1}")
    partial.replace(target)
    print(f"  verified     {name}")


# --------------------------------------------------
# Main
# --------------------------------------------------

def main() -> int:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    metadata_cache: dict[str, dict] = {}
    rows = []

    for entry in catalog["items"]:
        item = entry["archive_item"]
        print(f"[{entry['item_id']}] {entry['title']}", flush=True)

        if item not in metadata_cache:
            metadata_cache[item] = fetch_json(ARCHIVE_METADATA.format(item=item))
        meta = metadata_cache[item]
        files = {f["name"]: f for f in meta["files"]}
        licence = meta.get("metadata", {}).get("licenseurl", "")

        media = files[entry["media_file"]]
        download(item, entry["media_file"], RAW_DIR / entry["item_id"] / entry["media_file"],
                 media["sha1"], int(media["size"]))

        transcript_sha1 = ""
        if entry["transcript_file"]:
            transcript = files[entry["transcript_file"]]
            download(item, entry["transcript_file"],
                     RAW_DIR / entry["item_id"] / entry["transcript_file"],
                     transcript["sha1"], int(transcript["size"]))
            transcript_sha1 = transcript["sha1"]

        rows.append({
            "item_id": entry["item_id"],
            "display_name": entry["display_name"],
            "title": entry["title"],
            "course": entry["course"],
            "speaker": entry["speaker"],
            "split": entry["split"],
            "media_file": f"raw/{entry['item_id']}/{entry['media_file']}",
            "media_bytes": media.get("size", ""),
            "media_sha1": media["sha1"],
            "duration_s": media.get("length", ""),
            "transcript_file": f"raw/{entry['item_id']}/{entry['transcript_file']}" if entry["transcript_file"] else "",
            "transcript_format": "srt" if entry["transcript_file"] else "none",
            "transcript_sha1": transcript_sha1,
            "source_url": f"https://archive.org/details/{item}",
            "course_url": entry["course_url"],
            "licence": licence,
        })

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {MANIFEST.relative_to(ROOT)} ({len(rows)} items)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
