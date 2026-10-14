"""Which Kafka partition does a video_id land on? (S1 planning; murmur2 = Java's partitioner, M2 K3/J1)

    .venv\\Scripts\\python -m tools.partition_of python_l1 algorithms_ku_l1 algorithms_demaine_l2
    .venv\\Scripts\\python -m tools.partition_of --suggest algorithms_l2 --want 2
"""

from __future__ import annotations

import argparse
import sys

from common.config import load
from common.partitioning import partition_for


def suggest(base: str, want: int, partitions: int, limit: int = 5) -> list[str]:
    """Readable variants of `base` that land on partition `want`."""
    found = []
    for suffix in [""] + [f"_{c}" for c in "abcdefghijklmnopqrstuvwxyz"] + [f"_{i}" for i in range(2, 100)]:
        candidate = base + suffix
        if partition_for(candidate, partitions) == want:
            found.append(candidate)
            if len(found) == limit:
                break
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video_ids", nargs="*")
    parser.add_argument("--partitions", type=int, default=None, help="default: EDU_PARTITIONS")
    parser.add_argument("--suggest", metavar="BASE")
    parser.add_argument("--want", type=int, default=0, help="target partition for --suggest")
    args = parser.parse_args(argv)
    partitions = args.partitions or load().partitions
    if args.suggest:
        print(f"video_ids based on {args.suggest!r} that land on partition {args.want} of {partitions}:")
        for candidate in suggest(args.suggest, args.want, partitions):
            print(f"  {candidate}")
        return 0
    seen: dict[int, list[str]] = {}
    for video_id in args.video_ids:
        partition = partition_for(video_id, partitions)
        seen.setdefault(partition, []).append(video_id)
        print(f"{video_id:28s} -> partition {partition} of {partitions}")
    clashes = {p: ids for p, ids in seen.items() if len(ids) > 1}
    if clashes:
        print(f"WARNING: S1 violated, several lectures share a partition: {clashes}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
