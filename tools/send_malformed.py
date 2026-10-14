"""Inject poison messages for fault demo F4 (replaces producer/producer.py, whose old schema was itself one).

Each kind must end up in the dlq topic while the pipeline keeps running.

    .venv\\Scripts\\python -m tools.send_malformed                 # one of each kind
    .venv\\Scripts\\python -m tools.send_malformed --kind not-json
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from common.config import TOPIC_AUDIO, load
from common.kafka_utils import make_producer, send_and_wait

NOW = int(time.time() * 1000)
KINDS = {
    "not-json": b"this is not json {",
    # The old producer/producer.py schema (timestamp/text instead of audio) - defect D1
    "old-schema": json.dumps({"video_id": "python_l1", "chunk_id": 0, "timestamp": 0,
                              "text": "This is lecture audio chunk 0"}).encode(),
    "bad-base64": json.dumps({"schema": "audio_chunk.v1", "type": "chunk", "video_id": "python_l1",
                              "session_start": NOW, "chunk_id": 0, "start_time": 0, "end_time": 10,
                              "event_ts": NOW, "sample_rate": 16000, "encoding": "pcm_s16le",
                              "audio_b64": "%%%not-base64%%%"}).encode(),
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kind", choices=sorted(KINDS), action="append")
    parser.add_argument("--key", default="python_l1", help="key decides the partition (and which worker sees it)")
    args = parser.parse_args(argv)
    producer = make_producer(load(), client_id="send-malformed")
    for kind in args.kind or sorted(KINDS):
        md = send_and_wait(producer, TOPIC_AUDIO, KINDS[kind], key=args.key)
        print(f"sent {kind:11s} -> {TOPIC_AUDIO} p{md.partition} off={md.offset}  (expect it in dlq)")
    producer.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
