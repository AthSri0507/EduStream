"""Send the scheduled flush (ARCHITECTURE A5) for a lecture whose source died before flushing.

Reads run/lectures/<video_id>.json (written by lecture_source.py), computes the A5
timestamp from the last chunk actually sent, waits until its send time, and sends it.

    .venv\\Scripts\\python -m tools.send_flush --video python_l1
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from common import schemas
from common.config import TOPIC_AUDIO, load
from common.kafka_utils import make_producer, send_and_wait
from producer.lecture_source import STATE_DIR, flush_event_ts, flush_send_at, write_state


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--video", required=True)
    args = parser.parse_args(argv)
    path = STATE_DIR / f"{args.video}.json"
    if not path.exists():
        print(f"no state file {path}; was the lecture started with producer/lecture_source.py?")
        return 1
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("status") == "flushed":
        print(f"{args.video} is already flushed")
        return 0
    last = state["last_chunk_sent"]
    if last < 0:
        print(f"{args.video} never sent a chunk; nothing to close")
        return 1
    ts = flush_event_ts(state["session_start"], last, state["chunk_wall_ms"], state["window_s"], state["grace_s"])
    send_at = flush_send_at(state["session_start"], last, state["chunk_wall_ms"], state["window_s"], state["grace_s"])
    wait_s = (send_at - time.time() * 1000) / 1000
    if wait_s > 0:
        print(f"waiting {wait_s:.0f} s until the flush's scheduled send time")
        time.sleep(wait_s)
    flush = {"schema": "audio_chunk.v1", "type": "flush", "video_id": args.video,
             "session_start": state["session_start"], "last_chunk_id": last, "event_ts": ts}
    producer = make_producer(load(), client_id="send-flush")
    md = send_and_wait(producer, TOPIC_AUDIO, schemas.encode("audio_chunk.v1", flush), key=args.video)
    producer.close()
    write_state(args.video, status="flushed", flush_event_ts=ts)
    print(f"flush sent for {args.video} (last chunk {last}) -> p{md.partition} off={md.offset}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
