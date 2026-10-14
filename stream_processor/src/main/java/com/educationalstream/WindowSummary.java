package com.educationalstream;

import com.fasterxml.jackson.annotation.JsonInclude;
import java.util.List;

/** One closed window (topic window_summaries, schema window.v1). Produced once per window (suppress). */
public record WindowSummary(
        String schema,
        String videoId,
        long windowStart,
        long windowEnd,
        int revision,
        @JsonInclude(JsonInclude.Include.NON_NULL) Long sessionStart,
        Double mediaStart,
        Double mediaEnd,
        List<Integer> chunkIds,
        String transcript,
        List<WindowChunk> chunks,
        WindowStats stats,
        Long emittedTs,
        String source) {
}
