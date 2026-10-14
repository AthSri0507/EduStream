package com.educationalstream;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

/** S-1 alert boundaries (ARCHITECTURE §7): T_SCORE = 0.63, MIN_COVERED_S = 15, guards in seconds. */
class AlertRulesTest {

    private static final Settings S = TestData.settings();
    private static final String WORDS = "the scheduler picks the next ready process from the queue each time slice";

    /** A window built from chunks of `chunkSeconds`, with the given ids, all with the same score. */
    private static WindowSummary window(double chunkSeconds, int[] chunkIds, double score, Double ratio, String text) {
        WindowAgg agg = new WindowAgg();
        for (int id : chunkIds) {
            agg.add(Transcript.parse(TestData.chunk("python_l1", TestData.T0, id, chunkSeconds, text, score, ratio)
                    .toString(), TestData.NOW));
        }
        return agg.summarize("python_l1", TestData.T0, TestData.T0 + 30_000, TestData.NOW);
    }

    private static List<String> types(WindowSummary w) {
        return AlertRules.evaluate(w, S, TestData.NOW).stream().map(Alert::type).toList();
    }

    @Test
    void scoreBoundaryAtTScore() {
        assertEquals(List.of("LOW_ASR_SCORE"), types(window(10, new int[] {0, 1, 2}, 0.629, 1.3, WORDS)));
        assertEquals(List.of(), types(window(10, new int[] {0, 1, 2}, 0.631, 1.3, WORDS)));
    }

    @Test
    void coveredSecondsBoundary() {
        // 3 chunks of 5 s = 15.0 s covered -> judged; a chunk of 14.9 s -> not judged
        assertEquals(List.of("LOW_ASR_SCORE"), types(window(5, new int[] {0, 1, 2}, 0.5, 1.3, WORDS)));
        WindowAgg agg = new WindowAgg();
        agg.add(Transcript.parse(TestData.chunk("python_l1", TestData.T0, 0, 14.9, WORDS, 0.5, 1.3).toString(),
                TestData.NOW));
        assertEquals(List.of(), types(agg.summarize("python_l1", TestData.T0, TestData.T0 + 30_000, TestData.NOW)));
    }

    @ParameterizedTest(name = "{0} s chunks")
    @ValueSource(doubles = {5.0, 10.0})
    void fullWindowMissingOneChunkStillAlerts(double chunkSeconds) {
        // 5 s: 5 of 6 chunks (25 s); 10 s: 2 of 3 chunks (20 s). The old chunk_count >= 3 rule failed at 10 s.
        int[] ids = chunkSeconds == 5.0 ? new int[] {0, 1, 2, 4, 5} : new int[] {0, 2};
        assertEquals(List.of("LOW_ASR_SCORE"), types(window(chunkSeconds, ids, 0.5, 1.3, WORDS)));
    }

    @ParameterizedTest(name = "{0} s chunks")
    @ValueSource(doubles = {5.0, 10.0})
    void shortFinalWindowDoesNotAlert(double chunkSeconds) {
        int[] ids = chunkSeconds == 5.0 ? new int[] {0, 1} : new int[] {0};     // 10 s covered < 15 s
        assertEquals(List.of(), types(window(chunkSeconds, ids, 0.5, 1.3, "")));
    }

    @Test
    void residualLoopAlertsEvenWithAHighScore() {
        // M2: loop chunks scored 0.80-0.97, so the score alone misses them
        List<Alert> alerts = AlertRules.evaluate(window(10, new int[] {0, 1, 2}, 0.9, 3.1, WORDS), S, TestData.NOW);
        assertEquals(1, alerts.size());
        Alert a = alerts.get(0);
        assertEquals("LOW_ASR_SCORE", a.type());
        assertEquals("residual_loop", a.details().path("reason").asText());
        assertEquals("info", a.severity());                                  // informational only
        assertEquals("LOW_ASR_SCORE:python_l1:" + TestData.T0 + ":1", a.alertId());
        assertEquals(3, a.details().path("chunks").size());
        TestData.assertMatchesRequired(Json.write(a), "alert.v1");
    }

    @Test
    void silenceRule() {
        // no words at all in a fully covered window -> SILENCE (and no LOW_ASR_SCORE: the score is fine)
        assertEquals(List.of("SILENCE"), types(window(10, new int[] {0, 1, 2}, 0.8, 1.2, "")));
        // 1 word per chunk = 6 wpm -> SILENCE
        WindowSummary quiet = window(10, new int[] {0, 1, 2}, 0.8, 1.2, "so");
        assertTrue(quiet.stats().wordsPerMin() < AlertRules.SILENCE_WPM);
        assertEquals(List.of("SILENCE"), types(quiet));
        // normal speech (13 words per 10 s chunk = 78 wpm) -> nothing
        assertEquals(List.of(), types(window(10, new int[] {0, 1, 2}, 0.8, 1.2, WORDS)));
    }
}
