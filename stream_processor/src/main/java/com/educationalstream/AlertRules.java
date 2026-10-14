package com.educationalstream;

import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.ArrayList;
import java.util.List;

/**
 * Window threshold alerts (ARCHITECTURE §7; CIE lab program "threshold alerts").
 *
 * <ul>
 *   <li>LOW_ASR_SCORE, <b>informational only</b>: (score_avg &lt; T_SCORE or compression_ratio_max &gt; 2.4,
 *       i.e. a repetition loop survived the A13 retry) and covered_s &ge; MIN_COVERED_S.
 *       M2 calibration: asr_score is a weak signal (catches ~1 in 4 bad windows), so nothing acts on it.</li>
 *   <li>SILENCE, informational: covered_s &ge; MIN_COVERED_S and (words_per_min &lt; 40 or no_speech_avg &gt; 0.6).</li>
 * </ul>
 * The guard is in seconds of audio, not chunk counts, so it behaves the same at 5 s and 10 s chunks.
 */
public final class AlertRules {

    static final double LOOP_COMPRESSION_RATIO = 2.4;   // same threshold as the A13 retry rule
    static final double SILENCE_WPM = 40.0;
    static final double SILENCE_NO_SPEECH = 0.6;

    private AlertRules() {
    }

    public static List<Alert> evaluate(WindowSummary w, Settings settings, long nowMs) {
        List<Alert> alerts = new ArrayList<>();
        WindowStats s = w.stats();
        if (s.coveredS() < settings.minCoveredS()) {
            return alerts;   // e.g. a lecture's short final window: too little audio to judge
        }

        boolean lowScore = s.scoreAvg() != null && s.scoreAvg() < settings.tScore();
        boolean loop = s.compressionRatioMax() != null && s.compressionRatioMax() > LOOP_COMPRESSION_RATIO;
        if (lowScore || loop) {
            ArrayNode flagged = Json.MAPPER.createArrayNode();
            for (WindowChunk c : w.chunks()) {
                boolean chunkLow = c.asrScore() != null && c.asrScore() < settings.tScore();
                boolean chunkLoop = c.compressionRatio() != null && c.compressionRatio() > LOOP_COMPRESSION_RATIO;
                if (chunkLow || chunkLoop) {
                    flagged.addObject().put("chunk_id", c.chunkId())
                            .put("asr_score", c.asrScore()).put("compression_ratio", c.compressionRatio());
                }
            }
            ObjectNode details = Json.MAPPER.createObjectNode()
                    .put("reason", lowScore && loop ? "low_score+residual_loop" : lowScore ? "low_score" : "residual_loop")
                    .put("informational", true);
            details.set("chunks", flagged);
            alerts.add(Alert.forWindow("LOW_ASR_SCORE", "info", w, s.scoreAvg(), settings.tScore(), details, nowMs));
        }

        boolean slow = s.wordsPerMin() < SILENCE_WPM;
        boolean quiet = s.noSpeechAvg() != null && s.noSpeechAvg() > SILENCE_NO_SPEECH;
        if (slow || quiet) {
            ObjectNode details = Json.MAPPER.createObjectNode()
                    .put("reason", slow && quiet ? "slow_and_no_speech" : slow ? "slow_speech" : "no_speech")
                    .put("no_speech_avg", s.noSpeechAvg());
            alerts.add(Alert.forWindow("SILENCE", "info", w, s.wordsPerMin(), SILENCE_WPM, details, nowMs));
        }
        return alerts;
    }
}
