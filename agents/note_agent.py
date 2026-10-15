"""Note Agent (docs/ARCHITECTURE.md §8.1, rev 6): window_summaries -> one notebook per lecture -> final_notes.

  * Group note-agent, raw bytes, read_committed, one record per poll (§6.3).
  * Windows are HELD uncommitted per partition until their 90 s update is complete (agents/notebook.py),
    then one LLM call (or the extractive fallback) writes a notes.v2 delta, which is produced to the same
    partition number of final_notes; only then are the held offsets committed.
  * Memory (sections, points, terms, updates sent) is rebuilt from final_notes itself on EVERY partition
    assignment, so a restart or rebalance never repeats an LLM call or creates a duplicate update.
  * A lock file (run/locks/note-agent.lock) keeps a second instance from starting.
  * End of a lecture: lectures.flushed_ts / last_chunk_id from SQLite (read-only), checked every 5 s.
  * Produce failures exit with EXIT_PRODUCE_FAILED; scripts/run_component.ps1 restarts the process.

    .venv\\Scripts\\python -m agents.note_agent
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time

from kafka import ConsumerRebalanceListener, KafkaConsumer, TopicPartition
from kafka.errors import CommitFailedError
from kafka.structs import OffsetAndMetadata

from agents import llm
from agents.notebook import (SYSTEM_PROMPT, Grouper, Held, LectureEnd, Memory, Window, build_update,
                             extractive_delta, llm_delta, user_prompt)
from common import schemas
from common.config import GROUP_NOTES, RUN_DIR, TOPIC_NOTES, TOPIC_WINDOWS, load
from common.kafka_utils import (EXIT_PRODUCE_FAILED, ProduceFailed, make_consumer, make_producer, poll_one,
                                send_and_wait, send_to_dlq)
from common.log import JsonLog
from storage.db import connect_readonly, db_path

LOCK = RUN_DIR / "locks" / "note-agent.lock"
TIMER_EVERY_S = 5
EXIT_ALREADY_RUNNING = 2


# ----------------------------------------------------------------------------------------------- lock file
def _pid_alive(pid: int) -> bool:
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:          # pragma: no cover - psutil is in requirements
        return True


def acquire_lock(path=LOCK) -> bool:
    """True if this process now holds the lock; a stale lock (its pid is gone) is taken over."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            pid = int(path.read_text().strip() or 0)
        except ValueError:
            pid = 0
        if pid and pid != os.getpid() and _pid_alive(pid):
            return False
    path.write_text(str(os.getpid()))
    return True


def release_lock(path=LOCK) -> None:
    try:
        if path.read_text().strip() == str(os.getpid()):
            path.unlink()
    except OSError:
        pass


# ----------------------------------------------------------------------------------------------- the agent
class NoteAgent:
    def __init__(self, settings, log, client: llm.Client) -> None:
        self.settings, self.log, self.client = settings, log, client
        self.memories: dict[str, Memory] = {}
        self.groupers: dict[int, Grouper] = {}
        self.flush_seen: dict[str, float] = {}
        self.consumer: KafkaConsumer | None = None
        self.producer = None

    def memory(self, video_id: str) -> Memory:
        return self.memories.setdefault(video_id, Memory(video_id))

    def grouper(self, partition: int) -> Grouper:
        return self.groupers.setdefault(partition, Grouper(self.settings.note_update_s, self.settings.chunk_seconds))

    # ------------------------------------------------------------------ rebuild (§8.1.5)
    def rebuild(self, partitions: list[int]) -> None:
        """Fold every notes.v2 record of these final_notes partitions into memory (read up to the end)."""
        if not partitions:
            return
        reader = KafkaConsumer(bootstrap_servers=self.settings.kafka_bootstrap, client_id="note-agent-rebuild",
                               group_id=None, enable_auto_commit=False, isolation_level="read_committed")
        tps = [TopicPartition(TOPIC_NOTES, p) for p in partitions]
        try:
            reader.assign(tps)
            reader.seek_to_beginning(*tps)
            ends = reader.end_offsets(tps)
            seen: dict[str, Memory] = {}
            count = 0
            while any(reader.position(tp) < ends[tp] for tp in tps):
                for batch in reader.poll(timeout_ms=1000).values():
                    for r in batch:
                        try:
                            p = schemas.decode(r.value, "notes.v2")
                        except schemas.ContractError:
                            continue                       # notes.v1 or junk: not part of any notebook
                        seen.setdefault(p["video_id"], Memory(p["video_id"])).apply(p)
                        count += 1
            self.memories.update(seen)
            self.log.info("memory_rebuilt", partitions=partitions, records=count, lectures=sorted(seen))
        finally:
            reader.close()

    # ------------------------------------------------------------------ records
    def handle(self, record) -> None:
        try:
            payload = schemas.decode(record.value, "window.v1")
            if record.key is not None and record.key.decode("utf-8", "replace") != payload["video_id"]:
                raise schemas.ContractError("record key does not match video_id")
        except schemas.ContractError as exc:
            send_to_dlq(self.producer, "note-agent", record, str(exc), log=self.log)
            self._commit_if_free(record.partition, record.offset)
            return
        window = Window.from_payload(payload, record.partition, record.offset, time.time())
        memory = self.memory(window.video_id)
        if window.window_start in memory.sent_windows:      # replayed after a crash: already in an update
            self._commit_if_free(record.partition, record.offset)
            return
        for held, reason in self.grouper(record.partition).add(window, memory.last_sent):
            self.emit(held, reason)

    def timers(self, now: float) -> None:
        ends = self._lecture_ends({g.held.video_id for g in self.groupers.values() if g.held is not None})
        for partition, grouper in self.groupers.items():
            if grouper.held is None:
                continue
            reason = grouper.due(now, self.settings.note_max_hold_s, ends.get(grouper.held.video_id))
            if reason:
                self.emit(grouper.take(), reason)

    def _lecture_ends(self, video_ids: set[str]) -> dict[str, LectureEnd]:
        if not video_ids or not db_path().exists():
            return {}
        out = {}
        try:
            conn = connect_readonly()
            try:
                for vid in video_ids:
                    row = conn.execute("SELECT flushed_ts, last_chunk_id FROM lectures WHERE video_id = ?",
                                       (vid,)).fetchone()
                    if row and row["flushed_ts"] is not None and row["last_chunk_id"] is not None:
                        seen = self.flush_seen.setdefault(vid, time.time())
                        out[vid] = LectureEnd(row["last_chunk_id"], seen)
            finally:
                conn.close()
        except sqlite3.Error as exc:
            self.log.warn("lecture_end_check_failed", error=str(exc))
        return out

    # ------------------------------------------------------------------ one update
    def emit(self, held: Held, reason: str) -> None:
        memory = self.memory(held.video_id)
        if held.update_index in memory.sent:                 # skip-if-exists (rebuilt memory)
            self.commit(held.partition, held.last_offset)
            return
        chunks = held.chunks()
        started = time.perf_counter()
        result = self.client.complete_json(SYSTEM_PROMPT, user_prompt(memory, chunks))
        if result.ok:
            delta = llm_delta(memory, result.data, chunks, held.update_index)
        else:
            delta = extractive_delta(memory, chunks, held.update_index, [f"llm_unavailable:{result.reason}"])
        if reason != "complete":
            delta["quality_flags"].append(f"emitted_on:{reason}")
        payload = build_update(memory, held, delta, result.model, (time.perf_counter() - started) * 1000)
        send_and_wait(self.producer, TOPIC_NOTES, schemas.encode("notes.v2", payload), key=held.video_id,
                      partition=held.partition)
        memory.apply(payload)
        self.commit(held.partition, held.last_offset)
        self.log.info("update", video_id=held.video_id, update=held.update_index, windows=len(held.windows),
                      reason=reason, generator=payload["generator"], model=payload["model"],
                      points=len(payload["points"]), terms=len(payload["terms"]),
                      section=payload["section"]["id"], flags=len(payload["quality_flags"]),
                      agent_ms=payload["agent_ms"])

    # ------------------------------------------------------------------ commits
    def commit(self, partition: int, offset: int) -> None:
        try:
            self.consumer.commit({TopicPartition(TOPIC_WINDOWS, partition): OffsetAndMetadata(offset + 1, None, -1)})
        except CommitFailedError:
            self.log.warn("commit_failed_revoked", partition=partition, offset=offset)

    def _commit_if_free(self, partition: int, offset: int) -> None:
        """Commit a skipped record only if no held window on that partition sits below it."""
        if self.grouper(partition).held is None:
            self.commit(partition, offset)


class Rebalance(ConsumerRebalanceListener):
    def __init__(self, agent: NoteAgent) -> None:
        self.agent = agent

    def on_partitions_revoked(self, revoked):
        for tp in revoked:
            self.agent.groupers.pop(tp.partition, None)      # uncommitted: the new owner replays them

    def on_partitions_assigned(self, assigned):
        self.agent.rebuild(sorted(tp.partition for tp in assigned))


def main() -> int:
    settings = load()
    log = JsonLog("note-agent")
    if not acquire_lock():
        log.error("already_running", lock=str(LOCK))
        return EXIT_ALREADY_RUNNING
    client = llm.Client("notes", log=log)
    agent = NoteAgent(settings, log, client)
    agent.producer = make_producer(settings, client_id="note-agent")
    consumer = make_consumer(settings, GROUP_NOTES, None, client_id="note-agent")
    consumer.subscribe([TOPIC_WINDOWS], listener=Rebalance(agent))
    agent.consumer = consumer
    log.info("started", group=GROUP_NOTES, llm_enabled=client.enabled,
             models=[t.model for t in client.chain] if client.enabled else [])
    last_timer = 0.0
    try:
        while True:
            record = poll_one(consumer)
            if record is not None:
                agent.handle(record)
            now = time.time()
            if now - last_timer >= TIMER_EVERY_S:
                agent.timers(now)
                last_timer = now
    except ProduceFailed as exc:
        log.error("produce_failed_exiting", error=str(exc))
        agent.producer.close(timeout=0)
        return EXIT_PRODUCE_FAILED
    except KeyboardInterrupt:
        return 0
    finally:
        consumer.close()
        release_lock()


if __name__ == "__main__":
    sys.exit(main())
