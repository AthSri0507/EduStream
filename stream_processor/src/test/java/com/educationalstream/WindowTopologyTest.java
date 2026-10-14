package com.educationalstream;

import static com.educationalstream.TestData.NOW;
import static com.educationalstream.TestData.T0;
import static com.educationalstream.TestData.chunk;
import static com.educationalstream.TestData.flush;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import org.apache.kafka.common.Metric;
import org.apache.kafka.common.MetricName;
import org.apache.kafka.common.serialization.Serdes;
import org.apache.kafka.streams.KeyValue;
import org.apache.kafka.streams.StreamsConfig;
import org.apache.kafka.streams.TestInputTopic;
import org.apache.kafka.streams.TestOutputTopic;
import org.apache.kafka.streams.Topology;
import org.apache.kafka.streams.TopologyTestDriver;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/**
 * S-1 (ARCHITECTURE §10): window semantics on a fixed origin, in TopologyTestDriver.
 * The driver uses ONE partition (M2 J2), so partition isolation and stalls are tested on the
 * real broker instead (I-1, I-3); here every lecture shares one stream time, like S1 reuse.
 */
class WindowTopologyTest {

    private TopologyTestDriver driver;
    private TestInputTopic<String, String> in;
    private TestOutputTopic<String, String> windows;
    private TestOutputTopic<String, String> alerts;
    private TestOutputTopic<String, String> dlq;
    private Topology topology;

    @BeforeEach
    void setUp() {
        topology = WindowTopology.build(TestData.settings(), () -> NOW);
        Properties props = WindowTopology.properties(TestData.settings());
        props.put(StreamsConfig.STATE_DIR_CONFIG, "target/state-test");
        driver = new TopologyTestDriver(topology, props);
        in = driver.createInputTopic(Settings.TOPIC_TRANSCRIPTS, Serdes.String().serializer(), Serdes.String().serializer());
        windows = driver.createOutputTopic(Settings.TOPIC_WINDOWS, Serdes.String().deserializer(), Serdes.String().deserializer());
        alerts = driver.createOutputTopic(Settings.TOPIC_ALERTS, Serdes.String().deserializer(), Serdes.String().deserializer());
        dlq = driver.createOutputTopic(Settings.TOPIC_DLQ, Serdes.String().deserializer(), Serdes.String().deserializer());
    }

    @AfterEach
    void tearDown() {
        driver.close();
    }

    private List<KeyValue<String, JsonNode>> read(TestOutputTopic<String, String> topic) {
        return topic.readKeyValuesToList().stream().map(kv -> KeyValue.pair(kv.key, TestData.read(kv.value))).toList();
    }

    private double droppedRecords() {
        double total = 0;
        for (Map.Entry<MetricName, ? extends Metric> e : driver.metrics().entrySet()) {
            if (e.getKey().name().equals(LateDropMonitor.METRIC) && e.getKey().group().equals(LateDropMonitor.GROUP)) {
                total += ((Number) e.getValue().metricValue()).doubleValue();
            }
        }
        return total;
    }

    @Test
    void noRepartitionTopicAndNamedStores() {
        String description = topology.describe().toString();
        assertFalse(description.contains("repartition"), "the worker already keys by video_id (A4)");
        assertTrue(description.contains(WindowTopology.AGG_STORE));
        assertTrue(description.contains(WindowTopology.SUPPRESS_NAME));
    }

    @Test
    void oneOrderedDeduplicatedResultPerWindowOnlyAfterEndPlusGrace() {
        // 10 s chunks: window [0,30) holds chunks 0,1,2; it closes at stream time 30 + 10 = 40 s.
        in.pipeInput("python_l1", chunk("python_l1", 1, "second"));
        in.pipeInput("python_l1", chunk("python_l1", 0, "first"));
        in.pipeInput("python_l1", chunk("python_l1", 2, "third"));
        in.pipeInput("python_l1", chunk("python_l1", 0, "DUPLICATE redelivery"));   // at-least-once duplicate
        in.pipeInput("python_l1", chunk("python_l1", 3, "fourth"));                  // stream time 30 s
        assertTrue(windows.isEmpty(), "nothing may be emitted before end + grace");

        in.pipeInput("python_l1", chunk("python_l1", 4, "fifth"));                   // stream time 40 s
        List<KeyValue<String, JsonNode>> out = read(windows);
        assertEquals(1, out.size());
        JsonNode w = out.get(0).value;
        assertEquals("python_l1", out.get(0).key);
        assertEquals(T0, w.path("window_start").asLong());
        assertEquals("first second third", w.path("transcript").asText());
        assertEquals("[0,1,2]", w.path("chunk_ids").toString());
        assertEquals(T0, w.path("session_start").asLong());
        TestData.assertMatchesRequired(w.toString(), "window.v1");
        assertEquals(0.0, droppedRecords());
    }

    @Test
    void flushClosesExactlyTheLastWindowAndIsNeverEmittedItself() {
        for (int i = 0; i < 4; i++) {
            in.pipeInput("python_l1", chunk("python_l1", i, "chunk " + i));
        }
        assertTrue(windows.isEmpty());
        in.pipeInput("python_l1", flush("python_l1", T0, 3, 10));          // event_ts = T0 + 80 s
        List<KeyValue<String, JsonNode>> out = read(windows);
        assertEquals(2, out.size());
        assertEquals(T0 + 30_000, out.get(1).value.path("window_start").asLong());
        assertEquals("[3]", out.get(1).value.path("chunk_ids").toString());

        // Much later activity (another lecture's flush): the empty flush window of python_l1 never appears.
        in.pipeInput("algorithms_ku_l1", flush("algorithms_ku_l1", T0, 20, 10));
        assertTrue(windows.isEmpty());
        assertEquals(0.0, droppedRecords());
    }

    @Test
    void sequentialReuseOfAPartitionDropsNothing() {
        // T6 / S4: lecture A (60 s), then lecture B starting at the next window boundary after A's flush was sent.
        for (int i = 0; i < 6; i++) {
            in.pipeInput("lecture_a", chunk("lecture_a", i, "a" + i));
        }
        in.pipeInput("lecture_a", flush("lecture_a", T0, 5, 10));
        long flushTs = T0 + 6 * 10_000 + 40_000;
        long flushSentAt = flushTs + 10_000;
        long sessionB = (flushSentAt + 29_999) / 30_000 * 30_000;
        for (int i = 0; i < 3; i++) {
            in.pipeInput("lecture_b", TestData.chunk("lecture_b", sessionB, i, 10, "b" + i, 0.8, 1.2).toString());
        }
        in.pipeInput("lecture_b", flush("lecture_b", sessionB, 2, 10));

        List<KeyValue<String, JsonNode>> out = read(windows);
        assertEquals(List.of("lecture_a", "lecture_a", "lecture_b"), out.stream().map(kv -> kv.key).toList());
        assertEquals("b0 b1 b2", out.get(2).value.path("transcript").asText());
        assertEquals(0.0, droppedRecords(), "S4 guarantees no late records");
    }

    @Test
    void statsAreComputedPerWindow() {
        in.pipeInput("python_l1", TestData.chunk("python_l1", T0, 0, 10, "Recursion calls itself.", 0.7, 1.2).toString());
        in.pipeInput("python_l1", TestData.chunk("python_l1", T0, 1, 10, "", null, null).toString());
        in.pipeInput("python_l1", TestData.chunk("python_l1", T0, 2, 10, "Recursion needs a base case.", 0.5, 1.5).toString());
        in.pipeInput("python_l1", flush("python_l1", T0, 2, 10));

        JsonNode s = read(windows).get(0).value.path("stats");
        assertEquals(3, s.path("chunk_count").asInt());
        assertEquals(30.0, s.path("covered_s").asDouble());
        assertEquals(8, s.path("word_count").asInt());
        assertEquals(16.0, s.path("words_per_min").asDouble());
        assertEquals(0.6, s.path("score_avg").asDouble(), 1e-9);
        assertEquals(0.5, s.path("score_min").asDouble());
        assertEquals(0.7, s.path("score_max").asDouble());
        assertEquals(1.5, s.path("compression_ratio_max").asDouble());
        assertEquals("[[\"recursion\",2],[\"base\",1],[\"calls\",1],[\"case\",1],[\"itself\",1]]",
                s.path("top_terms").toString());
        // 16 wpm < 40 -> SILENCE; score 0.6 < 0.63 -> LOW_ASR_SCORE (both informational)
        List<KeyValue<String, JsonNode>> a = read(alerts);
        assertEquals(List.of("LOW_ASR_SCORE", "SILENCE"), a.stream().map(kv -> kv.value.path("type").asText()).toList());
        a.forEach(kv -> TestData.assertMatchesRequired(kv.value.toString(), "alert.v1"));
    }

    @Test
    void invalidRecordsGoToTheDlqAndTheStreamContinues() {
        String valid = chunk("python_l1", 0, "fine");
        in.pipeInput("python_l1", "not json {");
        in.pipeInput("python_l1", valid.replace("\"src_offset\":0,", ""));
        in.pipeInput("python_l1", valid.replace("\"asr_score\":0.75", "\"asr_score\":1.7"));
        in.pipeInput("other_key", valid);                                              // key != video_id
        in.pipeInput("python_l1", valid.replace("\"event_ts\":" + T0, "\"event_ts\":1000"));   // 1970
        in.pipeInput(null, valid);

        List<KeyValue<String, JsonNode>> dead = read(dlq);
        assertEquals(6, dead.size());
        for (int i = 0; i < dead.size(); i++) {
            JsonNode d = dead.get(i).value;
            assertEquals("streams", d.path("stage").asText());
            assertEquals(i, d.path("src_offset").asLong());
            TestData.assertMatchesRequired(d.toString(), "dlq.v1");
        }
        assertTrue(dead.get(1).value.path("error").asText().contains("src_offset"));
        assertTrue(dead.get(3).value.path("error").asText().contains("other_key"));
        assertTrue(dead.get(4).value.path("error").asText().contains("event_ts"));

        // Poison input did not move stream time: the lecture still windows normally from T0.
        for (int i = 0; i < 5; i++) {
            in.pipeInput("python_l1", chunk("python_l1", i, "w" + i));
        }
        List<KeyValue<String, JsonNode>> out = read(windows);
        assertEquals(1, out.size());
        assertEquals(T0, out.get(0).value.path("window_start").asLong());
        assertEquals(0.0, droppedRecords());
    }

    @Test
    void lateRecordIsDroppedAndTheMonitorAlertsOncePerIncrease() {
        LateDropMonitor monitor = new LateDropMonitor();
        for (int i = 0; i < 5; i++) {
            in.pipeInput("python_l1", chunk("python_l1", i, "w" + i));
        }
        assertEquals(List.of(), monitor.scan(driver.metrics(), NOW), "no drops, no alert");

        in.pipeInput("python_l1", chunk("python_l1", 1, "very late"));               // window [0,30) already closed
        assertEquals(1.0, droppedRecords());
        List<Alert> raised = monitor.scan(driver.metrics(), NOW);
        assertEquals(1, raised.size());
        assertEquals("LATE_DROP", raised.get(0).type());
        assertEquals("crit", raised.get(0).severity());
        assertEquals(1.0, raised.get(0).value());
        TestData.assertMatchesRequired(Json.write(raised.get(0)), "alert.v1");
        assertEquals(List.of(), monitor.scan(driver.metrics(), NOW), "unchanged count: no repeat alert");
        assertEquals(1, read(windows).size(), "the late record changed no output");
    }

    @Test
    void poisonWithAPlausibleEventTimeCannotCloseWindows() {
        // A key-mismatched record stamped far ahead (within the accepted range) must not close window [0,30).
        // It holds because poison is dead-lettered before the window processors, which keep their own
        // stream time (shown in M4: it still passes with the extractor's fallback removed).
        in.pipeInput("python_l1", chunk("python_l1", 0, "w0"));
        String ahead = TestData.chunk("python_l1", T0, 9, 10, "poison", 0.8, 1.2).toString();
        in.pipeInput("wrong_key", ahead);                         // event_ts T0 + 90 s, but dead-lettered
        in.pipeInput("python_l1", chunk("python_l1", 1, "w1"));
        assertEquals(1, read(dlq).size());
        assertTrue(windows.isEmpty(), "stream time is still 10 s, so window [0,30) is still open");
        assertEquals(0.0, droppedRecords());
    }

    @Test
    void restartedMonitorDoesNotAlertWithoutNewDrops() {
        // L2/L3: metrics start at 0 per process, so a new instance (new monitor, new driver) stays quiet.
        for (int i = 0; i < 5; i++) {
            in.pipeInput("python_l1", chunk("python_l1", i, "w" + i));
        }
        assertEquals(List.of(), new LateDropMonitor().scan(driver.metrics(), NOW));
    }
}
