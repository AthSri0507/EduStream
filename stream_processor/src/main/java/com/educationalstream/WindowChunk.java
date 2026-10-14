package com.educationalstream;

import com.fasterxml.jackson.annotation.JsonInclude;

/** One transcribed chunk inside a window (window.v1 "chunks" item; also the aggregate's stored value). */
public record WindowChunk(
        int chunkId,
        double startTime,
        double endTime,
        String text,
        Double asrScore,
        Double compressionRatio,
        Integer srcPartition,
        Long srcOffset,
        @JsonInclude(JsonInclude.Include.NON_NULL) Double noSpeechProb) {

    static WindowChunk of(Transcript t) {
        return new WindowChunk(t.chunkId(), t.startTime(), t.endTime(), t.text() == null ? "" : t.text().strip(),
                t.asrScore(), t.compressionRatio(), t.srcPartition(), t.srcOffset(), t.noSpeechProb());
    }
}
