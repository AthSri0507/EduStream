package com.educationalstream;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

/** Shared test data on a fixed time origin (ARCHITECTURE §6.2 tests: session_start = 1_700_000_010_000). */
final class TestData {

    /** Aligned to 30 s. */
    static final long T0 = 1_700_000_010_000L;
    /** The tests' "now": one hour after T0, inside Transcript's accepted event_ts range. */
    static final long NOW = T0 + 3_600_000L;
    static final Path SCHEMAS = Path.of("..", "schemas");

    private TestData() {
    }

    static Settings settings() {
        return new Settings("dummy:9092", "edustream-streams-test", 1, 30, 10, 0.63, 15.0,
                "target/state-test", "target/logs-test");
    }

    static ObjectNode chunk(String videoId, long sessionStart, int chunkId, double chunkSeconds, String text,
                            Double asrScore, Double compressionRatio) {
        ObjectNode n = Json.MAPPER.createObjectNode()
                .put("schema", "transcript.v1").put("type", "chunk").put("video_id", videoId)
                .put("session_start", sessionStart).put("chunk_id", chunkId)
                .put("start_time", chunkId * chunkSeconds).put("end_time", (chunkId + 1) * chunkSeconds)
                .put("event_ts", sessionStart + Math.round(chunkId * chunkSeconds * 1000))
                .put("text", text).put("asr_score", asrScore).put("avg_logprob", -0.3)
                .put("no_speech_prob", 0.02).put("compression_ratio", compressionRatio).put("retried", false)
                .put("model", "base.en").put("worker_id", "w1").put("src_partition", 0).put("src_offset", chunkId)
                .put("transcribed_ts", sessionStart + Math.round((chunkId + 1) * chunkSeconds * 1000) + 900)
                .put("proc_ms", 900.0);
        return n;
    }

    static String chunk(String videoId, int chunkId, String text) {
        return chunk(videoId, T0, chunkId, 10, text, 0.75, 1.3).toString();
    }

    /** A5: event_ts = session_start + (last + 1) * chunk_wall + WINDOW + GRACE. */
    static String flush(String videoId, long sessionStart, int lastChunkId, double chunkSeconds) {
        long ts = sessionStart + Math.round((lastChunkId + 1) * chunkSeconds * 1000) + 40_000;
        return Json.MAPPER.createObjectNode().put("schema", "transcript.v1").put("type", "flush")
                .put("video_id", videoId).put("session_start", sessionStart).put("last_chunk_id", lastChunkId)
                .put("event_ts", ts).toString();
    }

    /** Flush with an explicit event time (used to probe the exact closing moment). */
    static String flushAt(String videoId, long sessionStart, int lastChunkId, long eventTs) {
        return Json.MAPPER.createObjectNode().put("schema", "transcript.v1").put("type", "flush")
                .put("video_id", videoId).put("session_start", sessionStart).put("last_chunk_id", lastChunkId)
                .put("event_ts", eventTs).toString();
    }

    /** Candidate "tight" A5: end of the (epoch-aligned) window holding the last chunk + GRACE. */
    static long tightFlushTs(long sessionStart, int lastChunkId, double chunkSeconds) {
        long lastTs = sessionStart + Math.round(lastChunkId * chunkSeconds * 1000);
        return lastTs - lastTs % 30_000 + 30_000 + 10_000;
    }

    static JsonNode read(String json) {
        try {
            return Json.MAPPER.readTree(json);
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    static JsonNode readFile(Path path) {
        try {
            return Json.MAPPER.readTree(path.toFile());
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    /**
     * C-1 (Java side, outputs): every field the shared JSON Schema requires is present, and the
     * schema name matches. Nested "stats" of window.v1 is checked too.
     */
    static void assertMatchesRequired(String json, String schemaName) {
        JsonNode payload = read(json);
        JsonNode schema = readFile(SCHEMAS.resolve(schemaName + ".schema.json"));
        assertEquals(schemaName, payload.path("schema").asText(), "schema name");
        assertHasAll(payload, schema.path("required"), schemaName);
        JsonNode statsRequired = schema.path("properties").path("stats").path("required");
        if (!statsRequired.isMissingNode()) {
            assertHasAll(payload.path("stats"), statsRequired, schemaName + ".stats");
        }
    }

    private static void assertHasAll(JsonNode payload, JsonNode required, String where) {
        List<String> missing = new ArrayList<>();
        required.forEach(field -> {
            if (!payload.has(field.asText())) {
                missing.add(field.asText());
            }
        });
        assertTrue(missing.isEmpty(), where + " is missing required fields " + missing + " in " + payload);
    }
}
