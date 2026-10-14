package com.educationalstream;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

/** An alert (topic alerts, schema alert.v1). alert_id is deterministic, so duplicates collapse at the sink. */
public record Alert(
        String schema,
        String alertId,
        String type,
        String severity,
        String videoId,
        Long windowStart,
        Integer revision,
        Double value,
        Double threshold,
        JsonNode details,
        String source,
        long createdTs) {

    static Alert forWindow(String type, String severity, WindowSummary w, Double value, double threshold,
                           ObjectNode details, long nowMs) {
        String id = type + ":" + w.videoId() + ":" + w.windowStart() + ":" + w.revision();
        return new Alert("alert.v1", id, type, severity, w.videoId(), w.windowStart(), w.revision(),
                value, threshold, details, "streams", nowMs);
    }

    /** LATE_DROP (ARCHITECTURE §7): one id per task per minute; value = drops seen by this instance. */
    static Alert lateDrop(String taskId, double droppedSinceStart, long nowMs) {
        ObjectNode details = Json.MAPPER.createObjectNode()
                .put("task_id", taskId)
                .put("meaning", "records arrived after their window closed (S1 violated?)");
        return new Alert("alert.v1", "LATE_DROP:" + taskId + ":" + nowMs / 60_000, "LATE_DROP", "crit",
                null, null, null, droppedSinceStart, 0.0, details, "streams-metrics", nowMs);
    }
}
