-- EduStream storage (docs/ARCHITECTURE.md §9). storage/db_sink.py is the ONLY writer;
-- the dashboard and the agents open the database read-only.
--
-- Write rules (implemented in storage/db_sink.py):
--   chunks, window_stats, notes, dlq : INSERT ... ON CONFLICT DO NOTHING   (first writer wins)
--   notebook (live_updates ... glossary): see the notebook block below
--   alerts                           : duplicates collapse on alert_id, keeping the larger value
--   lectures                         : monotonic updates (COALESCE / MAX)
--   notes_fts                        : rewritten only when a NEW notes row is the latest revision of its window
-- Apart from sink_ts / sampled_ts, every value comes from the message itself, so replaying the
-- same topics into an empty database produces identical tables (test D-1).

PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS lectures (
  video_id       TEXT PRIMARY KEY,
  title          TEXT,               -- from the first chunk (display name, e.g. "Python · Lecture 1 (Bell)")
  src_partition  INTEGER,
  session_start  INTEGER,            -- epoch ms
  first_event_ts INTEGER,
  last_seen_ts   INTEGER,            -- largest chunk event_ts seen (monotonic)
  last_chunk_id  INTEGER,            -- from the flush (NULL while the lecture is live)
  flushed_ts     INTEGER,            -- flush event_ts
  speedup        REAL                -- rev 6: playback speed (optional transcript field; NULL = 1)
);

CREATE TABLE IF NOT EXISTS chunks (
  video_id TEXT, chunk_id INTEGER, model TEXT,
  start_time REAL, end_time REAL, text TEXT,
  asr_score REAL, avg_logprob REAL, no_speech_prob REAL, compression_ratio REAL, retried INTEGER,
  worker_id TEXT, src_partition INTEGER, src_offset INTEGER,
  event_ts INTEGER, transcribed_ts INTEGER, proc_ms REAL, sink_ts INTEGER,
  PRIMARY KEY (video_id, chunk_id, model)
);

CREATE TABLE IF NOT EXISTS window_stats (
  video_id TEXT, window_start INTEGER, revision INTEGER,
  window_index INTEGER, window_end INTEGER, media_start REAL, media_end REAL,
  chunk_count INTEGER, covered_s REAL, word_count INTEGER, words_per_min REAL,
  score_avg REAL, score_min REAL, score_max REAL, no_speech_avg REAL, compression_ratio_max REAL,
  top_terms TEXT, chunk_ids TEXT, transcript TEXT, emitted_ts INTEGER, sink_ts INTEGER,
  PRIMARY KEY (video_id, window_start, revision)
);

CREATE TABLE IF NOT EXISTS notes (
  video_id TEXT, window_start INTEGER, revision INTEGER,
  window_index INTEGER, window_end INTEGER, media_start REAL, media_end REAL,
  summary TEXT, key_points TEXT, terms TEXT, questions TEXT,
  generator TEXT, quality_flag TEXT, model TEXT, agent_ms REAL, created_ts INTEGER, sink_ts INTEGER,
  PRIMARY KEY (video_id, window_start, revision)
);

CREATE TABLE IF NOT EXISTS alerts (
  alert_id TEXT PRIMARY KEY, type TEXT, severity TEXT, video_id TEXT, window_start INTEGER,
  revision INTEGER, value REAL, threshold REAL, details TEXT, source TEXT, created_ts INTEGER, sink_ts INTEGER
);

CREATE TABLE IF NOT EXISTS dlq (
  stage TEXT, source_topic TEXT, src_partition INTEGER, src_offset INTEGER,
  key TEXT, error TEXT, raw_value TEXT, failed_ts INTEGER, sink_ts INTEGER,
  PRIMARY KEY (source_topic, src_partition, src_offset, stage)
);

-- Notebook (NOTEBOOK_DESIGN §11), both on final_notes. Each record is written in ONE transaction and only if its
-- row in live_updates / passes is new (first writer wins), so a duplicate record changes nothing.
--   notes.v3          one live update per 90 s: its draft elements (and a course-info line)
--   consolidation.v1  one pass per ~6 min stretch: finished topics, their elements, glossary entries. Drafts before
--                     the pass's media_end are then hidden by readers (they stay here for audit) and leave the index.
-- Element bodies are JSON (the shape of agents/study_notes.py); `text` is their plain text for search.
CREATE TABLE IF NOT EXISTS live_updates (
  video_id TEXT, update_index INTEGER, media_start REAL, media_end REAL, window_starts TEXT,
  generator TEXT, model TEXT, quality_flags TEXT, agent_ms REAL, created_ts INTEGER, sink_ts INTEGER,
  PRIMARY KEY (video_id, update_index)
);

CREATE TABLE IF NOT EXISTS drafts (
  video_id TEXT, update_index INTEGER, seq INTEGER, draft_id TEXT, extends TEXT,
  root_t REAL,                        -- time of the paragraph it belongs to (a continuation: of the one it extends)
  kind TEXT, t REAL, text TEXT, body TEXT,
  PRIMARY KEY (video_id, update_index, seq)
);

CREATE TABLE IF NOT EXISTS course_info (
  video_id TEXT, update_index INTEGER, text TEXT, t REAL,
  PRIMARY KEY (video_id, update_index)
);

CREATE TABLE IF NOT EXISTS passes (
  video_id TEXT, pass_index INTEGER, media_start REAL, media_end REAL, final INTEGER,
  generator TEXT, model TEXT, quality_flags TEXT, agent_ms REAL, created_ts INTEGER, sink_ts INTEGER,
  PRIMARY KEY (video_id, pass_index)
);

CREATE TABLE IF NOT EXISTS topics (
  video_id TEXT, topic_n INTEGER, title TEXT, media_start REAL,
  media_end REAL,                     -- grows (MAX) when a later stretch continues the topic
  pass_index INTEGER, generator TEXT, question TEXT, answer TEXT,
  PRIMARY KEY (video_id, topic_n)
);

CREATE TABLE IF NOT EXISTS elements (
  video_id TEXT, pass_index INTEGER, seq INTEGER, topic_n INTEGER, kind TEXT, t REAL, text TEXT, body TEXT,
  PRIMARY KEY (video_id, pass_index, seq)
);

CREATE TABLE IF NOT EXISTS glossary (
  video_id TEXT, term TEXT COLLATE NOCASE, definition TEXT, t REAL, topic_n INTEGER,
  pass_index INTEGER,                 -- a later pass that explains the term again replaces the entry
  PRIMARY KEY (video_id, term)
);

-- Search over the notes for the Lecture Assistant: finished elements (ref p<pass>e<seq>) and live drafts
-- (ref = draft id, kind 'draft'), the latter removed when their stretch is consolidated.
CREATE VIRTUAL TABLE IF NOT EXISTS notebook_fts USING fts5(
  video_id UNINDEXED, ref UNINDEXED, t UNINDEXED, kind UNINDEXED, body
);

-- The student's additions (NOTEBOOK_DESIGN §13, addition.v1 on user_notes): figures from the Lecture Assistant the
-- student said yes to. First writer wins; a "remove" record only sets removed = 1 (nothing is deleted).
CREATE TABLE IF NOT EXISTS additions (
  video_id TEXT, addition_id TEXT PRIMARY KEY, shape TEXT, title TEXT,
  figure TEXT,                        -- JSON, agents/figures.py
  span_start REAL, span_end REAL,     -- NULL: beyond the lecture
  question TEXT, topic_override INTEGER, outside INTEGER, model TEXT,
  removed INTEGER DEFAULT 0, created_ts INTEGER, sink_ts INTEGER
);

-- Rev 6 (M6e): what was said, searchable by the Lecture Assistant (BM25). One row per stored chunk.
CREATE VIRTUAL TABLE IF NOT EXISTS transcript_fts USING fts5(
  video_id UNINDEXED, chunk_id UNINDEXED, start_time UNINDEXED, body
);

-- Consumer lag, refreshed every 5 s by the sink's lag thread (dashboard "Pipeline health").
CREATE TABLE IF NOT EXISTS lag (
  group_id TEXT, topic TEXT, partition INTEGER,
  committed INTEGER, end_offset INTEGER, lag INTEGER, lag_seconds REAL,
  owner TEXT,                         -- client id of the group member that owns the partition, if any
  sampled_ts INTEGER,
  PRIMARY KEY (group_id, topic, partition)
);

CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
  video_id UNINDEXED, window_start UNINDEXED, revision UNINDEXED, body
);

CREATE VIEW IF NOT EXISTS notes_latest AS
  SELECT n.* FROM notes n WHERE n.revision =
    (SELECT MAX(m.revision) FROM notes m WHERE m.video_id = n.video_id AND m.window_start = n.window_start);

CREATE VIEW IF NOT EXISTS window_latest AS
  SELECT w.* FROM window_stats w WHERE w.revision =
    (SELECT MAX(v.revision) FROM window_stats v WHERE v.video_id = w.video_id AND v.window_start = w.window_start);
