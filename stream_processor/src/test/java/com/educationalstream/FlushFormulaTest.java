package com.educationalstream;

import static com.educationalstream.TestData.NOW;
import static com.educationalstream.TestData.T0;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.apache.kafka.common.Metric;
import org.apache.kafka.common.MetricName;
import org.apache.kafka.common.serialization.Serdes;
import org.apache.kafka.streams.TestInputTopic;
import org.apache.kafka.streams.TestOutputTopic;
import org.apache.kafka.streams.TopologyTestDriver;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

/**
 * Candidate "tight" A5 flush (end of the last chunk's window + GRACE), checked against the real
 * topology before it may replace the legacy formula: just before / exactly on / just after a
 * window boundary, at 10 s and 5 s chunks, plus sequential reuse of the partition.
 */
class FlushFormulaTest {

    private TopologyTestDriver driver;
    private TestInputTopic<String, String> in;
    private TestOutputTopic<String, String> windows;

    @BeforeEach
    void setUp() {
        driver = new TopologyTestDriver(WindowTopology.build(TestData.settings(), () -> NOW),
                WindowTopology.properties(TestData.settings()));
        in = driver.createInputTopic(Settings.TOPIC_TRANSCRIPTS, Serdes.String().serializer(), Serdes.String().serializer());
        windows = driver.createOutputTopic(Settings.TOPIC_WINDOWS, Serdes.String().deserializer(), Serdes.String().deserializer());
    }

    @AfterEach
    void tearDown() {
        driver.close();
    }

    private List<JsonNode> emitted() {
        return windows.readValuesToList().stream().map(TestData::read).toList();
    }

    private double dropped() {
        double total = 0;
        for (Map.Entry<MetricName, ? extends Metric> e : driver.metrics().entrySet()) {
            if (e.getKey().name().equals(LateDropMonitor.METRIC) && e.getKey().group().equals(LateDropMonitor.GROUP)) {
                total += ((Number) e.getValue().metricValue()).doubleValue();
            }
        }
        return total;
    }

    @ParameterizedTest(name = "{3}: {1} chunks of {0} s")
    @CsvSource({
        "10, 14, 5, ends just before a boundary (140 s)",
        "10, 15, 5, ends exactly on a boundary (150 s)",
        "10, 16, 6, ends just after a boundary (160 s)",
        "5, 29, 5, ends just before a boundary (145 s)",
        "5, 30, 5, ends exactly on a boundary (150 s)",
        "5, 31, 6, ends just after a boundary (155 s)",
    })
    void tightFlushClosesTheLastWindowAtTheEarliestMoment(double chunkSeconds, int chunks, int expectedWindows,
                                                         String ignoredCase) {
        // "Just after" case: the last chunk alone starts a new window, so stream time stops at its start and the
        // previous window (end + grace still ahead) waits for the flush too. Both formulas behave like that.
        long lastTs = T0 + Math.round((chunks - 1) * chunkSeconds * 1000);
        long lastWindowStart = lastTs - lastTs % 30_000;
        for (int i = 0; i < chunks; i++) {
            in.pipeInput("python_l1", TestData.chunk("python_l1", T0, i, chunkSeconds, "c" + i, 0.8, 1.2).toString());
        }
        List<JsonNode> out = new ArrayList<>(emitted());
        assertFalse(out.stream().anyMatch(w -> w.path("window_start").asLong() == lastWindowStart));

        long tight = TestData.tightFlushTs(T0, chunks - 1, chunkSeconds);
        in.pipeInput("python_l1", TestData.flushAt("python_l1", T0, chunks - 1, tight - 1));
        out.addAll(emitted());
        assertFalse(out.stream().anyMatch(w -> w.path("window_start").asLong() == lastWindowStart),
                "1 ms before the formula's timestamp the last window must still be open (full grace period)");

        in.pipeInput("python_l1", TestData.flushAt("python_l1", T0, chunks - 1, tight));
        List<JsonNode> last = emitted();
        assertEquals(1, last.size(), "the tight flush closes exactly the window holding the last chunk");
        assertEquals(lastWindowStart, last.get(0).path("window_start").asLong());
        out.addAll(last);

        assertEquals(expectedWindows, out.size());
        assertEquals(expectedWindows, out.stream().map(w -> w.path("window_start").asLong()).distinct().count(),
                "each window emitted exactly once");
        List<Integer> ids = new ArrayList<>();
        out.forEach(w -> w.path("chunk_ids").forEach(id -> ids.add(id.asInt())));
        assertEquals(chunks, ids.size(), "each chunk in exactly one window");
        assertEquals(chunks, ids.stream().distinct().count());
        assertEquals(chunks - 1, last.get(0).path("chunk_ids").path(last.get(0).path("chunk_ids").size() - 1).asInt());
        assertEquals(0.0, dropped());
    }

    @Test
    void tightFlushDoesNotCloseTheNextLecturesWindowsEarly() {
        // Lecture A ends exactly on a boundary (the case the tight formula shortens most).
        for (int i = 0; i < 6; i++) {
            in.pipeInput("lecture_a", TestData.chunk("lecture_a", T0, i, 10, "a" + i, 0.8, 1.2).toString());
        }
        long flushA = TestData.tightFlushTs(T0, 5, 10);
        in.pipeInput("lecture_a", TestData.flushAt("lecture_a", T0, 5, flushA));
        assertEquals(2, emitted().size());

        // Lecture B reuses the partition (S4): starts at the next window boundary after A's flush was sent.
        long sessionB = (flushA + 10_000 + 29_999) / 30_000 * 30_000;
        assertTrue(sessionB >= flushA);
        for (int i = 0; i < 3; i++) {
            in.pipeInput("lecture_b", TestData.chunk("lecture_b", sessionB, i, 10, "b" + i, 0.8, 1.2).toString());
            assertTrue(windows.isEmpty(), "B's first window may only close after end + grace of B's own time");
        }
        in.pipeInput("lecture_b", TestData.chunk("lecture_b", sessionB, 3, 10, "b3", 0.8, 1.2).toString());
        assertTrue(windows.isEmpty(), "stream time sessionB + 30 s < sessionB + 40 s");
        in.pipeInput("lecture_b", TestData.flushAt("lecture_b", sessionB, 3, TestData.tightFlushTs(sessionB, 3, 10)));
        List<JsonNode> b = emitted();
        assertEquals(2, b.size());
        assertFalse(b.stream().anyMatch(w -> !w.path("video_id").asText().equals("lecture_b")));
        assertEquals(0.0, dropped());
    }
}
