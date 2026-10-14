import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.TreeSet;

import org.apache.kafka.common.Metric;
import org.apache.kafka.common.MetricName;
import org.apache.kafka.common.serialization.Serdes;
import org.apache.kafka.common.utils.Utils;
import org.apache.kafka.streams.KeyValue;
import org.apache.kafka.streams.StreamsBuilder;
import org.apache.kafka.streams.StreamsConfig;
import org.apache.kafka.streams.TestInputTopic;
import org.apache.kafka.streams.TestOutputTopic;
import org.apache.kafka.streams.TopologyTestDriver;
import org.apache.kafka.streams.kstream.Consumed;
import org.apache.kafka.streams.kstream.Materialized;
import org.apache.kafka.streams.kstream.Produced;
import org.apache.kafka.streams.kstream.Suppressed;
import org.apache.kafka.streams.kstream.TimeWindows;
import org.apache.kafka.streams.processor.api.Processor;
import org.apache.kafka.streams.processor.api.ProcessorContext;
import org.apache.kafka.streams.processor.api.Record;
import org.apache.kafka.streams.state.Stores;

/**
 * M2 checks 2, 4 and 5 (docs/ARCHITECTURE.md §12), plus a dry run of the §6 window design.
 *
 *   J1  Java DefaultPartitioner murmur2 partition for each key (compared with Python by bench/m2_report.py)
 *   J2  TopologyTestDriver delivers every key on partition 0 (single-partition semantics)
 *   J3  KIP-1033 LogAndContinueProcessingExceptionHandler exists in Kafka Streams 4.3.1
 *   J4  suppress + in-memory window store: exactly one ordered result per window, only after end + grace
 *   J5  scheduled flush closes the last window, and the empty flush window is never emitted
 *   J6  a late record is dropped and counted in dropped-records-total (the LATE_DROP tripwire)
 *
 * Plain main() with PASS/FAIL lines (no JUnit); run by bench/run_java_checks.ps1.
 */
public class M2StreamsChecks {

    static final long T0 = 1_700_000_010_000L;   // fixed origin, aligned to 30 s (ARCHITECTURE §6.2 tests)
    static final int PARTITIONS = 3;
    static int failures = 0;

    static void check(String name, boolean ok, String detail) {
        System.out.printf("[%s] %s: %s%n", ok ? "PASS" : "FAIL", name, detail);
        if (!ok) failures++;
    }

    static Properties props(String app) {
        Properties p = new Properties();
        p.put(StreamsConfig.APPLICATION_ID_CONFIG, app);
        p.put(StreamsConfig.BOOTSTRAP_SERVERS_CONFIG, "dummy:9092");
        return p;
    }

    public static void main(String[] args) throws Exception {
        partitioner(args);
        driverPartitions();
        processingHandler();
        windows();
        System.out.println(failures == 0 ? "ALL JAVA CHECKS PASSED" : failures + " JAVA CHECK(S) FAILED");
        System.exit(failures == 0 ? 0 : 1);
    }

    // J1 -------------------------------------------------------------------
    static void partitioner(String[] keys) {
        StringBuilder json = new StringBuilder("{");
        for (int i = 0; i < keys.length; i++) {
            int p = Utils.toPositive(Utils.murmur2(keys[i].getBytes(java.nio.charset.StandardCharsets.UTF_8))) % PARTITIONS;
            json.append(i == 0 ? "" : ", ").append('"').append(keys[i]).append("\": ").append(p);
        }
        json.append("}");
        System.out.println("JAVA_PARTITIONS " + json);
        check("J1 Java murmur2 partitions computed", keys.length > 0, keys.length + " keys");
    }

    // J2 -------------------------------------------------------------------
    static void driverPartitions() {
        TreeSet<Integer> seen = new TreeSet<>();
        StreamsBuilder builder = new StreamsBuilder();
        builder.stream("in", Consumed.with(Serdes.String(), Serdes.String()))
               .process(() -> new Processor<String, String, Void, Void>() {
                   private ProcessorContext<Void, Void> ctx;
                   @Override public void init(ProcessorContext<Void, Void> context) { ctx = context; }
                   @Override public void process(Record<String, String> record) {
                       seen.add(ctx.recordMetadata().get().partition());
                   }
               });
        try (TopologyTestDriver driver = new TopologyTestDriver(builder.build(), props("m2-driver"))) {
            TestInputTopic<String, String> in = driver.createInputTopic("in", Serdes.String().serializer(), Serdes.String().serializer());
            for (String key : List.of("python_l1", "algorithms_l1", "algorithms_l2", "a", "b", "c", "video_07")) {
                in.pipeInput(key, "x");
            }
        }
        check("J2 TopologyTestDriver uses one partition", seen.equals(new TreeSet<>(List.of(0))),
              "partitions seen = " + seen + " -> partition-isolation tests must run on a real broker");
    }

    // J3 -------------------------------------------------------------------
    static void processingHandler() {
        String cls = "org.apache.kafka.streams.errors.LogAndContinueProcessingExceptionHandler";
        boolean found;
        try { Class.forName(cls); found = true; } catch (ClassNotFoundException e) { found = false; }
        check("J3 KIP-1033 processing handler exists", found, cls);
    }

    // J4-J6 ----------------------------------------------------------------
    static void windows() {
        StreamsBuilder builder = new StreamsBuilder();
        builder.stream("transcriptions", Consumed.with(Serdes.String(), Serdes.String()))
               .groupByKey()
               .windowedBy(TimeWindows.ofSizeAndGrace(Duration.ofSeconds(30), Duration.ofSeconds(10)))
               .aggregate(() -> "",
                          // keep chunk labels sorted (stand-in for the TreeMap<chunk_id, Chunk>); flush adds nothing
                          (key, value, agg) -> value.equals("FLUSH") ? agg : sortedJoin(agg, value),
                          Materialized.<String, String>as(Stores.inMemoryWindowStore(
                                  "window-agg-store", Duration.ofMinutes(10), Duration.ofSeconds(30), false))
                                  .withKeySerde(Serdes.String()).withValueSerde(Serdes.String()))
               .suppress(Suppressed.untilWindowCloses(Suppressed.BufferConfig.unbounded()).withName("window-final"))
               .toStream()
               .filter((windowedKey, agg) -> !agg.isEmpty())                // drop the empty flush window
               .map((w, agg) -> KeyValue.pair(w.key() + "@" + (w.window().start() - T0) / 1000, agg))
               .to("window_summaries", Produced.with(Serdes.String(), Serdes.String()));

        try (TopologyTestDriver driver = new TopologyTestDriver(builder.build(), props("m2-windows"))) {
            TestInputTopic<String, String> in = driver.createInputTopic("transcriptions",
                    Serdes.String().serializer(), Serdes.String().serializer());
            TestOutputTopic<String, String> out = driver.createOutputTopic("window_summaries",
                    Serdes.String().deserializer(), Serdes.String().deserializer());
            List<KeyValue<String, String>> emitted = new ArrayList<>();

            // Lecture with 12 chunks of 5 s (two windows), chunk 3 and 4 arrive out of order.
            int[] order = {0, 1, 2, 4, 3, 5, 6, 7};
            for (int c : order) in.pipeInput("lecA", "c" + c, Instant.ofEpochMilli(T0 + c * 5_000L));
            in.pipeInput("lecA", "c3", Instant.ofEpochMilli(T0 + 3 * 5_000L));      // at-least-once duplicate
            emitted.addAll(out.readKeyValuesToList());
            boolean nothingEarly = emitted.isEmpty();                               // stream time 35 s < 30 + 10

            in.pipeInput("lecA", "c8", Instant.ofEpochMilli(T0 + 8 * 5_000L));     // stream time 40 s = end + grace
            emitted.addAll(out.readKeyValuesToList());
            boolean firstClosed = emitted.size() == 1
                    && emitted.get(0).key.equals("lecA@0")
                    && emitted.get(0).value.equals("c0,c1,c2,c3,c4,c5");
            for (int c = 9; c < 12; c++) in.pipeInput("lecA", "c" + c, Instant.ofEpochMilli(T0 + c * 5_000L));
            emitted.addAll(out.readKeyValuesToList());
            boolean secondStillOpen = emitted.size() == 1;
            check("J4 one ordered, deduplicated result per window after end+grace",
                  nothingEarly && firstClosed && secondStillOpen,
                  "before close: " + (nothingEarly ? "none" : "EARLY") + "; window 0 = " +
                  (emitted.isEmpty() ? "-" : emitted.get(0).value) + "; window 1 still open = " + secondStillOpen);

            // Scheduled flush: event_ts = session_start + (last+1)*chunk + WINDOW + GRACE = T0 + 60 + 30 + 10 s
            long flushTs = T0 + (12 * 5_000L) + 30_000L + 10_000L;
            in.pipeInput("lecA", "FLUSH", Instant.ofEpochMilli(flushTs));
            emitted.addAll(out.readKeyValuesToList());
            boolean lastClosed = emitted.size() == 2
                    && emitted.get(1).key.equals("lecA@30")
                    && emitted.get(1).value.equals("c6,c7,c8,c9,c10,c11");
            // Advance far beyond the flush window to prove it is never emitted (it is empty -> filtered).
            in.pipeInput("lecB", "FLUSH", Instant.ofEpochMilli(flushTs + 120_000L));
            emitted.addAll(out.readKeyValuesToList());
            boolean flushWindowHidden = emitted.stream().noneMatch(kv -> kv.key.equals("lecA@90"))
                    && emitted.size() == 2;
            check("J5 flush closes last window; flush window not emitted", lastClosed && flushWindowHidden,
                  "emitted keys = " + emitted.stream().map(kv -> kv.key + "=" + kv.value).toList());

            // A record far behind stream time is late: dropped and counted.
            in.pipeInput("lecA", "c1", Instant.ofEpochMilli(T0 + 5_000L));
            emitted.addAll(out.readKeyValuesToList());
            double dropped = 0;
            String metricGroup = "-";
            for (Map.Entry<MetricName, ? extends Metric> e : driver.metrics().entrySet()) {
                if (e.getKey().name().equals("dropped-records-total")) {
                    dropped += ((Number) e.getValue().metricValue()).doubleValue();
                    metricGroup = e.getKey().group();
                }
            }
            check("J6 late record dropped and counted", dropped >= 1 && emitted.size() == 2,
                  "dropped-records-total = " + dropped + " (group " + metricGroup + ")");
        }
    }

    /** Joins chunk labels in numeric order, ignoring a label that is already present (dedupe). */
    static String sortedJoin(String agg, String value) {
        TreeSet<Integer> ids = new TreeSet<>();
        for (String part : (agg.isEmpty() ? new String[0] : agg.split(","))) ids.add(Integer.parseInt(part.substring(1)));
        ids.add(Integer.parseInt(value.substring(1)));
        return String.join(",", ids.stream().map(i -> "c" + i).toList());
    }
}
