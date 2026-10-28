"""Offline replay of the notebook (docs/NOTEBOOK_DESIGN.md §11): the REAL Note Agent code on a recorded transcript,
without Kafka. Every 90 s block goes through NoteAgent.emit (live notes), consolidation runs as the agent's timer
would run it, every record is validated against its schema, stored by the real sink (storage/db_sink.py) in a
fresh SQLite file, and rendered with the dashboard's own query and HTML (dashboard/queries.py, notebook_html.py).

    .venv\\Scripts\\python bench\\replay_notebook.py                         (28 Oct live run, Python L1, 12.5 min)
    .venv\\Scripts\\python bench\\replay_notebook.py --chunks <M2 chunks .jsonl> --minutes 20 --out <name>

Writes bench/results/replay_<name>/: edustream.db, records.jsonl, view_live.html, view_finished.html, summary.json.
LLM replies are cached (LLM_CACHE=on), so a rerun costs nothing; uncached calls are paced like a live lecture
(a lecture spaces its calls 90 s apart, the replay does not). Keys are never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from common import config  # noqa: E402,F401  (loads .env)

os.environ.update(LLM_ENABLED="true", LLM_FORCE_FAIL="false", LLM_CACHE="on", LLM_NOTES_TPM_SHARE="1.0")

from agents import consolidation, llm  # noqa: E402
from agents import note_agent as na  # noqa: E402
from agents.notebook import Held, Window  # noqa: E402
from common import schemas  # noqa: E402
from common.log import JsonLog  # noqa: E402
from dashboard import notebook_html as nbh  # noqa: E402
from dashboard import queries  # noqa: E402
from storage.db import connect_readonly, connect_writer  # noqa: E402
from storage.db_sink import apply_batch  # noqa: E402

S0 = 1_792_051_200_000
DEFAULT = ROOT / "bench" / "results" / "chunks_live_python_l1_20261028.jsonl"


class Sent:
    """Stands in for Kafka: send_and_wait appends here; the records are stored by the real sink afterwards."""

    def __init__(self) -> None:
        self.records: list[dict] = []

    def __call__(self, producer, topic, value, key, partition=None, **_):
        self.records.append({"topic": topic, "value": value, "key": key})


def pace(client: llm.Client, before: int) -> None:
    """Wait in proportion to the tokens an uncached call just used (Groq: 8,000 tokens/minute per model)."""
    used = sum(n for q in client.budget.used.values() for _, n in q) - before
    if used > 0:
        time.sleep(min(60.0, used / 6000 * 60))


def used(client: llm.Client) -> int:
    return sum(n for q in client.budget.used.values() for _, n in q)


def transcript_record(c: dict, video_id: str, title: str) -> dict:
    return {"schema": "transcript.v1", "type": "chunk", "video_id": video_id, "session_start": S0,
            "chunk_id": c["chunk_id"], "start_time": c["start_time"], "end_time": c["end_time"],
            "event_ts": S0 + int(c["end_time"] * 1000), "text": c["text"], "asr_score": 0.9, "model": "base.en",
            "src_partition": 0, "src_offset": c["chunk_id"], **({"title": title} if c["chunk_id"] == 0 else {})}


def store(db: Path, items: list[tuple[str, dict]]) -> dict:
    recs = [SimpleNamespace(topic=t, value=json.dumps(p).encode(), partition=0, offset=i, key=b"replay")
            for i, (t, p) in enumerate(items)]
    conn = connect_writer(db)
    try:
        return apply_batch(conn, recs, now=S0, window_ms=30_000)
    finally:
        conn.close()


def page(db: Path, video_id: str, title: str, theme: str) -> str:
    """A static stand-in for the Streamlit layout: head, rail | topics (as <details>) + live box."""
    conn = connect_readonly(db)
    try:
        nb = queries.notebook(conn, video_id)
    finally:
        conn.close()
    topics = "".join(
        f'<details{" open" if nb["finished"] or i == len(nb["topics"]) - 1 else ""} style="border-top:1px solid '
        f'var(--border);padding:6px 0"><summary style="cursor:pointer;font-weight:600;font-size:17px;padding:6px 0">'
        f'{nbh.e(nbh.topic_label(t))}</summary>{nbh.topic_html(t)}</details>' for i, t in enumerate(nb["topics"]))
    live = "" if nb["finished"] else nbh.live_html(nb)
    bg = "#0e1117" if theme == "dark" else "#ffffff"
    body = (f'<h2 style="margin:0 0 4px">{nbh.e(title)}</h2>{nbh.head_html(nb)}<div style="display:grid;'
            f'grid-template-columns:200px minmax(0,1fr);gap:24px">{nbh.rail_html(nb)}<div>{topics}{live}</div></div>')
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,'
            f'initial-scale=1"><title>Notebook replay</title></head><body style="margin:0;background:{bg};'
            f'font-family:Segoe UI,system-ui,sans-serif"><div style="max-width:1100px;margin:0 auto;padding:16px">'
            f'{nbh.wrap(body, theme)}</div></body></html>')


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks", default=str(DEFAULT))
    ap.add_argument("--title", default="Python · Lecture 1 (Bell)")
    ap.add_argument("--video", default="python_l1")
    ap.add_argument("--minutes", type=float, default=12.5)
    ap.add_argument("--out", default="python_l1")
    ap.add_argument("--theme", default="dark")
    args = ap.parse_args()
    out = ROOT / "bench" / "results" / f"replay_{args.out}"
    out.mkdir(parents=True, exist_ok=True)
    db = out / "edustream.db"
    for f in out.glob("edustream.db*"):
        f.unlink()
    end_s = args.minutes * 60
    chunks = [json.loads(line) for line in Path(args.chunks).read_text(encoding="utf-8").splitlines()]
    chunks = [{**c, "text": c.get("text") or ""} for c in chunks if c["start_time"] < end_s]

    sent = Sent()
    na.send_and_wait = sent                                      # the agent "produces" into the list
    settings = config.load()
    client = llm.Client("notes", log=JsonLog("replay"))
    if not client.chain:
        sys.exit("No LLM provider configured in .env")
    agent = na.NoteAgent(settings, JsonLog("replay"), client)
    agent.consumer = SimpleNamespace(commit=lambda offsets: None)
    memory = agent.memory(args.video)
    stored: list[tuple[str, dict]] = []
    flush = {"schema": "transcript.v1", "type": "flush", "video_id": args.video, "session_start": S0,
             "last_chunk_id": chunks[-1]["chunk_id"], "event_ts": S0 + int(end_s * 1000)}
    n_updates = -(-int(end_s) // settings.note_update_s)
    views = {"live": round(n_updates * 0.6)}
    stored_upto = 0

    def flush_records(extra: list[tuple[str, dict]] = ()) -> None:
        nonlocal stored_upto
        for r in sent.records[stored_upto:]:
            payload = json.loads(r["value"])
            schemas.validate(payload["schema"], payload)         # encode() validated already; belt and braces
            stored.append(("final_notes", payload))
        stored_upto = len(sent.records)
        stored.extend(extra)

    for k in range(n_updates):
        part = [c for c in chunks if k * settings.note_update_s <= c["start_time"] < (k + 1) * settings.note_update_s]
        last = k == n_updates - 1
        transcript = [("transcriptions", transcript_record(c, args.video, args.title)) for c in part]
        held = Held(args.video, k, [Window(args.video, S0 + k * 90_000, S0 + (k + 1) * 90_000, S0, part, 0, k)])
        before = used(client)
        agent.emit(held, "complete" if not last else "lecture_end")
        pace(client, before)
        flush_records(transcript)
        while (plan := consolidation.due(memory, lecture_ended=last)) is not None:
            before = used(client)
            agent.consolidate(memory, plan, time.time())
            pace(client, before)
            if memory.retry_at > time.time():                    # deferred: a live lecture would retry later
                time.sleep(max(0.0, memory.retry_at - time.time()))
            flush_records()
            if not last:
                break
        if k + 1 == views["live"]:
            store(db, stored)
            (out / "view_live.html").write_text(page(db, args.video, args.title, args.theme), encoding="utf-8")
    flush_records([("transcriptions", flush)])
    print(store(db, stored))
    store(db, stored)                                            # replay: every record a duplicate, nothing changes
    (out / "view_finished.html").write_text(page(db, args.video, args.title, args.theme), encoding="utf-8")
    (out / "view_finished_light.html").write_text(page(db, args.video, args.title, "light"), encoding="utf-8")
    (out / "records.jsonl").write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for t, p in stored
                                               if t == "final_notes"), encoding="utf-8")
    passes = [p for t, p in stored if p.get("schema") == "consolidation.v1"]
    updates = [p for t, p in stored if p.get("schema") == "notes.v3"]
    elements = [el for p in passes for el in p["elements"]]
    words = sum(len(" ".join(el.get("sentences", [])).split()) for el in elements)
    summary = {
        "updates": len(updates), "updates_llm": sum(u["generator"] == "llm" for u in updates),
        "live_elements": sum(len(u["elements"]) for u in updates),
        "passes": [{"span": f"{p['media_start']:.0f}-{p['media_end']:.0f}", "final": p["final"],
                    "generator": p["generator"], "model": p["model"],
                    "topics": [f"{t['n']}{'' if t['new'] else '+'} {t['title']}" for t in p["topics"]],
                    "elements": len(p["elements"]), "flags": p["quality_flags"]} for p in passes],
        "final_elements": {k: sum(el["kind"] == k for el in elements) for k in {el["kind"] for el in elements}},
        "words_per_6_min": round(words / (end_s / 360)),
        "glossary": sorted({g["term"] for p in passes for g in p["glossary"]}),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
