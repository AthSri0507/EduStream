package com.educationalstream;

/** A dead-lettered input record (topic dlq, schema dlq.v1; ARCHITECTURE §4 DLQ path 1). */
public record DlqRecord(
        String schema,
        String stage,
        String sourceTopic,
        int srcPartition,
        long srcOffset,
        String key,
        String rawValue,
        String error,
        int attempts,
        long failedTs) {

    static final int RAW_LIMIT = 4096;

    static DlqRecord of(String sourceTopic, int partition, long offset, String key, String raw, String error, long nowMs) {
        String preview = raw == null ? "" : raw.length() > RAW_LIMIT ? raw.substring(0, RAW_LIMIT) : raw;
        String reason = error == null ? "unknown error" : error.length() > 1000 ? error.substring(0, 1000) : error;
        return new DlqRecord("dlq.v1", "streams", sourceTopic, Math.max(partition, 0), Math.max(offset, 0),
                key, preview, reason, 1, nowMs);
    }
}
