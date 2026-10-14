package com.educationalstream;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import java.util.regex.Pattern;

/**
 * One {@code transcript.v1} record (a transcribed chunk or a forwarded flush).
 *
 * <p>{@link #parse} is the Java side of the contract check (ARCHITECTURE §5): the same rules as
 * {@code schemas/transcript.v1.schema.json}, plus one Java-only guard: {@code event_ts} must lie
 * within the broker's accepted timestamp range (single.properties rejects records more than 1 day
 * old or 1 hour ahead). Window outputs carry their records' event time, so an out-of-range
 * {@code event_ts} would make the broker reject the output and stop the app (M2 finding).
 */
public record Transcript(
        String schema,
        String type,
        String videoId,
        Long sessionStart,
        Long eventTs,
        Integer chunkId,
        Double startTime,
        Double endTime,
        String text,
        Double asrScore,
        Double avgLogprob,
        Double noSpeechProb,
        Double compressionRatio,
        Boolean retried,
        String model,
        String workerId,
        Integer srcPartition,
        Long srcOffset,
        Long transcribedTs,
        Double procMs,
        Integer lastChunkId) {

    /** Margins inside the broker guard (log.message.timestamp.before/after.max.ms = 1 day / 1 hour). */
    static final long MAX_AGE_MS = 12L * 3600 * 1000;
    static final long MAX_AHEAD_MS = 30L * 60 * 1000;

    private static final Pattern VIDEO_ID = Pattern.compile("^[A-Za-z0-9_.-]{1,64}$");

    @JsonIgnore
    public boolean isFlush() {
        return "flush".equals(type);
    }

    /** Validates and parses a raw record value; throws {@link ContractException} with a readable reason. */
    public static Transcript parse(String raw, long nowMs) {
        if (raw == null) {
            throw new ContractException("transcript.v1: empty record value");
        }
        JsonNode node;
        try {
            node = Json.MAPPER.readTree(raw);
        } catch (JsonProcessingException e) {
            throw new ContractException("transcript.v1: not JSON (" + e.getOriginalMessage() + ")");
        }
        if (node == null || !node.isObject()) {
            throw new ContractException("transcript.v1: top level must be an object");
        }
        if (!"transcript.v1".equals(text(node, "schema"))) {
            throw new ContractException("transcript.v1 invalid at schema: must be 'transcript.v1'");
        }
        String type = text(node, "type");
        if (!type.equals("chunk") && !type.equals("flush")) {
            throw new ContractException("transcript.v1 invalid at type: must be 'chunk' or 'flush'");
        }
        if (!VIDEO_ID.matcher(text(node, "video_id")).matches()) {
            throw new ContractException("transcript.v1 invalid at video_id: must match " + VIDEO_ID.pattern());
        }
        integer(node, "session_start", 0);
        long eventTs = integer(node, "event_ts", 0);
        if (eventTs < nowMs - MAX_AGE_MS || eventTs > nowMs + MAX_AHEAD_MS) {
            throw new ContractException("transcript.v1 invalid at event_ts: " + eventTs
                    + " is outside the broker's accepted timestamp range (replays need scripts\\reset.ps1)");
        }
        if (type.equals("flush")) {
            integer(node, "last_chunk_id", -1);
        } else {
            integer(node, "chunk_id", 0);
            number(node, "start_time", 0);
            number(node, "end_time", 0);
            text(node, "text");
            nullableNumber(node, "asr_score", true, 0, 1);
            text(node, "model");
            integer(node, "src_partition", 0);
            integer(node, "src_offset", 0);
            for (String optional : new String[] {"avg_logprob", "no_speech_prob", "compression_ratio"}) {
                nullableNumber(node, optional, false, Double.NEGATIVE_INFINITY, Double.POSITIVE_INFINITY);
            }
        }
        try {
            return Json.MAPPER.treeToValue(node, Transcript.class);
        } catch (JsonProcessingException e) {
            throw new ContractException("transcript.v1: " + e.getOriginalMessage());
        }
    }

    private static String text(JsonNode node, String field) {
        JsonNode value = node.get(field);
        if (value == null || !value.isTextual()) {
            throw new ContractException("transcript.v1 invalid at " + field + ": required string");
        }
        return value.asText();
    }

    private static long integer(JsonNode node, String field, long min) {
        JsonNode value = node.get(field);
        if (value == null || !value.isIntegralNumber() || !value.canConvertToLong()) {
            throw new ContractException("transcript.v1 invalid at " + field + ": required integer");
        }
        if (value.asLong() < min) {
            throw new ContractException("transcript.v1 invalid at " + field + ": must be >= " + min);
        }
        return value.asLong();
    }

    private static double number(JsonNode node, String field, double min) {
        JsonNode value = node.get(field);
        if (value == null || !value.isNumber()) {
            throw new ContractException("transcript.v1 invalid at " + field + ": required number");
        }
        if (value.asDouble() < min) {
            throw new ContractException("transcript.v1 invalid at " + field + ": must be >= " + min);
        }
        return value.asDouble();
    }

    private static void nullableNumber(JsonNode node, String field, boolean required, double min, double max) {
        JsonNode value = node.get(field);
        if (value == null) {
            if (required) {
                throw new ContractException("transcript.v1 invalid at " + field + ": required (number or null)");
            }
            return;
        }
        if (value.isNull()) {
            return;
        }
        if (!value.isNumber() || value.asDouble() < min || value.asDouble() > max) {
            throw new ContractException("transcript.v1 invalid at " + field + ": must be a number in [" + min + ", " + max + "] or null");
        }
    }
}
