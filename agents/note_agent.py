"""Note Agent (docs/ARCHITECTURE.md §8.1, docs/NOTEBOOK_DESIGN.md §11): window_summaries -> study notes -> final_notes.

Two stages, both written to final_notes (same partition number as the lecture):
  * Live: windows are HELD uncommitted per partition until their 90 s update is complete (agents/notebook.py),
    then one LLM call (or the extractive fallback) writes up to 2 study-guide elements as a notes.v3 record;
    only then are the held offsets committed.
  * Consolidation: every ~6 minutes of drafts, and at the lecture's end, one call turns the drafts and the
    transcript of the stretch into finished topics (agents/consolidation.py), a consolidation.v1 record. It runs
    from the 5 s timer, GAP_S after the lecture's last live call, so the two never share a minute of the free
    token limit. A failed pass is deferred (the drafts stay live); only at the lecture's end, with the LLM off, or
    after a long outage are the drafts published as they are. There is no separate end-of-lecture pass any more
    (decision 4): the last consolidation finishes the notebook.
  * Memory (drafts, topics, glossary, the transcript since the last pass, updates sent) is rebuilt from
    final_notes itself on EVERY partition assignment, so a restart never repeats a call or a record.
  * Group note-agent, raw bytes, read_committed, one record per poll (§6.3). A lock file
    (run/locks/note-agent.lock) keeps a second instance from starting.
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

from agents import consolidation, llm
from agents.notebook import (LIVE_MAX_TOKENS, LIVE_MODEL, LIVE_SYSTEM, Grouper, Held, LectureEnd, Memory, Window, build_update,
                             extractive_live, live_delta, live_user)
from common import schemas
from common.config import GROUP_NOTES, RUN_DIR, TOPIC_NOTES, TOPIC_WINDOWS, load
from common.kafka_utils import (EXIT_PRODUCE_FAILED, ProduceFailed, make_consumer, make_producer, poll_one,
                                send_and_wait, send_to_dlq)
from common.log import JsonLog
from storage.db import connect_readonly, db_path

LOCK = RUN_DIR / "locks" / "note-agent.lock"
TIMER_EVERY_S = 5
END_IDLE_S = 30                 # flushed, but the last chunk's window never came: finish anyway
EXIT_ALREADY_RUNNING = 2
STRONG_WAIT_S, REST_WAIT_S = 30, 10      # consolidation waits for the strong model first, briefly for the rest
NOTEBOOK_SCHEMAS = (b'"notes.v3"', b'"consolidation.v1"')


# ----------------------------------------------------------------------------------------------- lock file
def _pid_alive(pid: int) -> bool:
    """True only if that pid is a running Note Agent. Live run 28 Oct: Windows reused a stopped agent's pid for
    another process, so "the pid exists" kept every new agent out ("already_running") and no notes were written."""
    try:
        import psutil
        return any("agents.note_agent" in part for part in psutil.Process(pid).cmdline())
    except ImportError:          # pragma: no cover - psutil is in requirements
        return True
    except Exception:            # gone, or not ours to inspect: not a running agent
        return False


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
        self.last_update_at: dict[str, float] = {}
        self.strong_free_at = 0.0      # the next pass waits for this (passes one minute apart across lectures)
        self.consumer: KafkaConsumer | None = None
        self.producer = None

    def memory(self, video_id: str) -> Memory:
        return self.memories.setdefault(video_id, Memory(video_id))

    def grouper(self, partition: int) -> Grouper:
        return self.groupers.setdefault(partition, Grouper(self.settings.note_update_s, self.settings.chunk_seconds))

    # ------------------------------------------------------------------ rebuild (§8.1.5)
    def rebuild(self, partitions: list[int]) -> None:
        """Fold every notebook record of these final_notes partitions into memory (read up to the end)."""
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
                        name = notebook_schema(r.value)
                        try:
                            p = schemas.decode(r.value, name) if name else None
                        except schemas.ContractError:
                            p = None
                        if p is None:
                            continue                       # older notes.v1/v2 or junk: not part of any notebook
                        memory = seen.setdefault(p["video_id"], Memory(p["video_id"]))
                        if name == "notes.v3":
                            memory.apply_update(p, partition=r.partition)
                        else:
                            memory.apply_pass(p, partition=r.partition)
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
        held = {g.held.video_id for g in self.groupers.values() if g.held is not None}
        open_lectures = {v for v, m in self.memories.items() if m.sent and not m.finished}
        ends = self._lecture_ends(held | open_lectures)
        for partition, grouper in self.groupers.items():
            if grouper.held is None:
                continue
            reason = grouper.due(now, self.settings.note_max_hold_s, ends.get(grouper.held.video_id))
            if reason:
                self.emit(grouper.take(), reason)
        still_held = {g.held.video_id for g in self.groupers.values() if g.held is not None}
        # The most overdue lecture first; one pass per minute across lectures (dry run 28 Oct: two lectures due at
        # the same moment sent the second one's passes to the small model).
        # Rehearsal 28 Oct: by "most overdue, then name" a lecture whose attempts kept failing took every turn and
        # Python L1 never got one; now the lecture that has waited longest since its last attempt goes first.
        turn = sorted(open_lectures, key=lambda v: (self.memories[v].last_attempt_at,
                                                    self.memories[v].consolidated_to - self.memories[v].media_end, v))
        for vid in turn:
            memory = self.memories[vid]
            # A pass runs while the next update is being collected (live run 28 Oct: waiting for "nothing held"
            # delayed the first pass by 3 minutes); only the lecture's end waits for its last update.
            ended = vid not in still_held and self._ended(memory, ends.get(vid), now)
            plan = consolidation.due(memory, ended)
            if plan is not None and plan.ending and memory.ending_since is None:
                memory.ending_since = now                    # the grace runs from the end, not from a first turn
            if (plan is not None and now - memory.last_live_at >= consolidation.GAP_S and now >= memory.retry_at
                    and now >= self.strong_free_at):
                self.consolidate(memory, plan, now)

    def _ended(self, memory: Memory, end: LectureEnd | None, now: float) -> bool:
        """Flushed, and the notebook has caught up with the flush or nothing has arrived for END_IDLE_S (the last
        chunk's window may never come, e.g. its chunk went to the DLQ)."""
        if end is None:
            return False
        if memory.media_end >= (end.last_chunk_id + 1) * self.settings.chunk_seconds - 0.5:
            return True
        return now - max(end.flush_seen_at, self.last_update_at.get(memory.video_id, 0.0)) >= END_IDLE_S

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

    # ------------------------------------------------------------------ one live update (§11.4)
    def emit(self, held: Held, reason: str) -> None:
        memory = self.memory(held.video_id)
        if held.update_index in memory.sent:                 # skip-if-exists (rebuilt memory)
            self.commit(held.partition, held.last_offset)
            return
        chunks = held.chunks()
        started = time.perf_counter()
        result = self.client.complete_json(LIVE_SYSTEM, live_user(memory, chunks), max_tokens=LIVE_MAX_TOKENS,
                                           wait_s=20, prefer=LIVE_MODEL)
        memory.last_live_at = time.time()
        if result.ok:
            delta = live_delta(memory, result.data, chunks, held.update_index)
        else:
            delta = extractive_live(memory, chunks, held.update_index, [f"llm_unavailable:{result.reason}"])
        if reason != "complete":
            delta["quality_flags"].append(f"emitted_on:{reason}")
        payload = build_update(held, delta, result.model, (time.perf_counter() - started) * 1000)
        send_and_wait(self.producer, TOPIC_NOTES, schemas.encode("notes.v3", payload), key=held.video_id,
                      partition=held.partition)
        memory.apply_update(payload, partition=held.partition)
        self.last_update_at[held.video_id] = time.time()
        self.commit(held.partition, held.last_offset)
        self.log.info("update", video_id=held.video_id, update=held.update_index, windows=len(held.windows),
                      reason=reason, generator=payload["generator"], model=payload["model"],
                      elements=[e["kind"] + ("+" if e["extends"] else "") for e in payload["elements"]],
                      stats=delta["stats"], flags=len(payload["quality_flags"]), agent_ms=payload["agent_ms"])

    # ------------------------------------------------------------------ one consolidation pass (§4, §11.5)
    def consolidate(self, memory: Memory, plan: consolidation.Plan, now: float) -> None:
        if plan.ending and memory.ending_since is None:
            memory.ending_since = now
        memory.last_attempt_at = now
        chunks = memory.chunks(plan.end)
        if not chunks:                                       # nothing transcribed in the stretch: nothing to write
            self._publish_pass(memory, plan, consolidation.fallback(memory, plan, ["no_transcript"]), None, 0.0)
            return
        started = time.perf_counter()
        system = consolidation.system_prompt(memory, plan)
        user = consolidation.user_prompt(memory, chunks, consolidation.drafts_for(memory, plan))
        result = self.client.complete_json(system, user, max_tokens=consolidation.MAX_TOKENS, timeout_s=60,
                                           wait_s=STRONG_WAIT_S, first_only=True)
        if result.ok or any(reason not in ("local_budget", "provider_blocked") for _, reason in result.attempts or []):
            self.strong_free_at = now + consolidation.PASS_SPACING_S   # a request reached the strong model
        if not result.ok and len(self.client.chain) > 1 and result.reason not in consolidation.OFF_REASONS:
            later = self.client.complete_json(system, user, max_tokens=consolidation.MAX_TOKENS, timeout_s=60,
                                              wait_s=REST_WAIT_S)
            later.attempts = result.attempts + later.attempts
            result = later
        if result.ok:
            fields = consolidation.from_reply(memory, result.data, plan, chunks)
        elif (result.reason in consolidation.OFF_REASONS
              or (plan.ending and now - memory.ending_since >= consolidation.END_GRACE_S)
              or memory.media_end - plan.start >= consolidation.GIVE_UP_S):
            fields = consolidation.fallback(memory, plan, [f"llm_unavailable:{result.reason}"])
        else:                                                # §11.10 fix 2: defer, the drafts stay live
            memory.retry_at = now + (consolidation.RETRY_S if not plan.ending else consolidation.RETRY_S / 2)
            self.log.warn("consolidation_deferred", video_id=memory.video_id, start=plan.start, end=plan.end,
                          reason=result.reason, attempts=result.attempts)
            return
        self._publish_pass(memory, plan, fields, result.model, (time.perf_counter() - started) * 1000)

    def _publish_pass(self, memory: Memory, plan: consolidation.Plan, fields: dict, model: str | None,
                      agent_ms: float) -> None:
        payload = consolidation.build_pass(memory, fields, model, agent_ms)
        send_and_wait(self.producer, TOPIC_NOTES, schemas.encode("consolidation.v1", payload), key=memory.video_id,
                      partition=memory.partition)
        memory.apply_pass(payload, partition=memory.partition)
        self.log.info("consolidated", video_id=memory.video_id, pass_index=payload["pass_index"], mode=plan.mode,
                      final=payload["final"], start=payload["media_start"], cut=payload["media_end"],
                      generator=payload["generator"], model=payload["model"],
                      topics=[[t["n"], t["title"], t["new"]] for t in payload["topics"]],
                      elements=len(payload["elements"]), glossary=len(payload["glossary"]), stats=fields["stats"],
                      flags=len(payload["quality_flags"]), agent_ms=payload["agent_ms"])

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


def notebook_schema(value: bytes | None) -> str | None:
    """final_notes carries notes.v3 and consolidation.v1 (older runs: notes.v1/v2, no longer read)."""
    head = (value or b"")[:200]
    return next((n.strip(b'"').decode() for n in NOTEBOOK_SCHEMAS if n in head), None)


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
