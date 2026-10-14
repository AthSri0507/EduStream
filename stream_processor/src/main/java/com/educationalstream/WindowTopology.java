package com.educationalstream;

import java.time.Duration;
import java.util.Map;
import java.util.Properties;
import java.util.function.LongSupplier;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.apache.kafka.common.serialization.Serdes;
import org.apache.kafka.streams.KeyValue;
import org.apache.kafka.streams.StreamsBuilder;
import org.apache.kafka.streams.StreamsConfig;
import org.apache.kafka.streams.Topology;
import org.apache.kafka.streams.errors.LogAndContinueExceptionHandler;
import org.apache.kafka.streams.errors.LogAndContinueProcessingExceptionHandler;
import org.apache.kafka.streams.kstream.Branched;
import org.apache.kafka.streams.kstream.Consumed;
import org.apache.kafka.streams.kstream.Grouped;
import org.apache.kafka.streams.kstream.KStream;
import org.apache.kafka.streams.kstream.Materialized;
import org.apache.kafka.streams.kstream.Named;
import org.apache.kafka.streams.kstream.Produced;
import org.apache.kafka.streams.kstream.Suppressed;
import org.apache.kafka.streams.kstream.TimeWindows;
import org.apache.kafka.streams.processor.TimestampExtractor;
import org.apache.kafka.streams.processor.api.FixedKeyProcessor;
import org.apache.kafka.streams.processor.api.FixedKeyProcessorContext;
import org.apache.kafka.streams.processor.api.FixedKeyRecord;
import org.apache.kafka.streams.processor.api.RecordMetadata;
import org.apache.kafka.streams.state.Stores;

/**
 * The EduStream topology (docs/ARCHITECTURE.md §6.1):
 * <pre>
 * transcriptions --parse/validate--+--invalid--> dlq
 *                                  +--valid--> groupByKey (no repartition: the worker already keys by video_id)
 *   --> 30 s tumbling windows, 10 s grace --> aggregate (TreeMap by chunk_id; in-memory store "window-agg-store")
 *   --> suppress until the window closes ("window-final") --> drop empty (flush-only) windows
 *   --> window.v1 --> window_summaries
 *                 \-> AlertRules --> alerts
 * </pre>
 */
public final class WindowTopology {

    static final String AGG_STORE = "window-agg-store";
    static final String SUPPRESS_NAME = "window-final";

    private WindowTopology() {
    }

    public static Topology build(Settings settings, LongSupplier clock) {
        Duration window = Duration.ofSeconds(settings.windowSeconds());
        Duration grace = Duration.ofSeconds(settings.graceSeconds());
        Duration retention = Duration.ofMillis(Math.max(Duration.ofMinutes(10).toMillis(), window.plus(grace).toMillis()));

        StreamsBuilder builder = new StreamsBuilder();
        KStream<String, Parsed> parsed = builder
                .stream(Settings.TOPIC_TRANSCRIPTS, Consumed.with(Serdes.String(), Serdes.String())
                        .withTimestampExtractor(new EventTimeExtractor(clock))
                        .withName("transcriptions-source"))
                .processValues(() -> new ParseProcessor(clock), Named.as("parse-validate"));

        Map<String, KStream<String, Parsed>> branches = parsed.split(Named.as("contract-"))
                .branch((key, p) -> p.transcript() == null, Branched.as("invalid"))
                .defaultBranch(Branched.as("valid"));

        branches.get("contract-invalid")
                .mapValues(Parsed::dlqJson, Named.as("dlq-json"))
                .to(Settings.TOPIC_DLQ, Produced.with(Serdes.String(), Serdes.String()).withName("dlq-sink"));

        KStream<String, WindowSummary> summaries = branches.get("contract-valid")
                .mapValues(Parsed::transcript, Named.as("transcript"))
                .groupByKey(Grouped.with("by-video", Serdes.String(), Json.serde(Transcript.class)))
                .windowedBy(TimeWindows.ofSizeAndGrace(window, grace))
                .aggregate(WindowAgg::new, (videoId, transcript, agg) -> agg.add(transcript), Named.as("window-agg"),
                        Materialized.<String, WindowAgg>as(Stores.inMemoryWindowStore(AGG_STORE, retention, window, false))
                                .withKeySerde(Serdes.String())
                                .withValueSerde(Json.serde(WindowAgg.class))
                                // Without this, updates reach suppress only when the record cache
                                // flushes (up to commit.interval.ms later); suppress already de-duplicates.
                                .withCachingDisabled())
                .suppress(Suppressed.untilWindowCloses(Suppressed.BufferConfig.unbounded()).withName(SUPPRESS_NAME))
                .toStream(Named.as("closed-windows"))
                .filter((w, agg) -> agg != null && agg.chunkCount() > 0, Named.as("drop-empty-windows"))
                .map((w, agg) -> KeyValue.pair(w.key(),
                        agg.summarize(w.key(), w.window().start(), w.window().end(), clock.getAsLong())),
                        Named.as("summarize"));

        summaries.mapValues(Json::write, Named.as("window-json"))
                .to(Settings.TOPIC_WINDOWS, Produced.with(Serdes.String(), Serdes.String()).withName("window-sink"));

        summaries.flatMapValues(w -> AlertRules.evaluate(w, settings, clock.getAsLong()), Named.as("alert-rules"))
                .mapValues(Json::write, Named.as("alert-json"))
                .to(Settings.TOPIC_ALERTS, Produced.with(Serdes.String(), Serdes.String()).withName("alert-sink"));

        return builder.build();
    }

    public static Properties properties(Settings settings) {
        Properties p = new Properties();
        p.put(StreamsConfig.APPLICATION_ID_CONFIG, settings.applicationId());
        p.put(StreamsConfig.BOOTSTRAP_SERVERS_CONFIG, settings.bootstrap());
        p.put(StreamsConfig.PROCESSING_GUARANTEE_CONFIG, StreamsConfig.AT_LEAST_ONCE);   // EOS is extension E1
        p.put(StreamsConfig.REPLICATION_FACTOR_CONFIG, settings.replicationFactor());
        p.put(StreamsConfig.STATE_DIR_CONFIG, settings.stateDir());
        p.put(StreamsConfig.DEFAULT_KEY_SERDE_CLASS_CONFIG, Serdes.StringSerde.class);
        p.put(StreamsConfig.DEFAULT_VALUE_SERDE_CLASS_CONFIG, Serdes.StringSerde.class);
        // Commit every 2 s (default 30 s): bounds how much is replayed after a crash.
        p.put(StreamsConfig.COMMIT_INTERVAL_MS_CONFIG, 2000);
        // Windowed changelog retention = store retention + this. The default (+1 day) would delete
        // changelog segments the day after a rehearsal, and on Windows a delete can crash the broker (M2).
        p.put(StreamsConfig.WINDOW_STORE_CHANGE_LOG_ADDITIONAL_RETENTION_MS_CONFIG, Duration.ofDays(7).toMillis());
        p.put(StreamsConfig.PROCESSING_EXCEPTION_HANDLER_CLASS_CONFIG, LogAndContinueProcessingExceptionHandler.class);
        p.put("processing.exception.handler.global.enabled", true);   // recommended by 4.3 (default in 5.0)
        p.put(StreamsConfig.DESERIALIZATION_EXCEPTION_HANDLER_CLASS_CONFIG, LogAndContinueExceptionHandler.class);
        p.put(StreamsConfig.consumerPrefix(ConsumerConfig.SESSION_TIMEOUT_MS_CONFIG), 10_000);
        p.put(StreamsConfig.consumerPrefix(ConsumerConfig.HEARTBEAT_INTERVAL_MS_CONFIG), 3_000);
        p.put(StreamsConfig.producerPrefix(ProducerConfig.ACKS_CONFIG), "all");
        return p;
    }

    /** Result of parse/validate: exactly one of transcript (valid) or dlqJson (invalid) is set. */
    record Parsed(Transcript transcript, String dlqJson) {
    }

    /** Validates each record; invalid ones become dlq.v1 JSON stamped with the current time. */
    static final class ParseProcessor implements FixedKeyProcessor<String, String, Parsed> {

        private final LongSupplier clock;
        private FixedKeyProcessorContext<String, Parsed> context;

        ParseProcessor(LongSupplier clock) {
            this.clock = clock;
        }

        @Override
        public void init(FixedKeyProcessorContext<String, Parsed> context) {
            this.context = context;
        }

        @Override
        public void process(FixedKeyRecord<String, String> record) {
            long now = clock.getAsLong();
            try {
                Transcript t = Transcript.parse(record.value(), now);
                if (!t.videoId().equals(record.key())) {
                    // groupByKey relies on key == video_id (A4); a mismatch would aggregate under the wrong lecture
                    throw new ContractException("record key " + record.key() + " != video_id " + t.videoId());
                }
                context.forward(record.withValue(new Parsed(t, null)));
            } catch (ContractException e) {
                RecordMetadata md = context.recordMetadata().orElse(null);
                DlqRecord dlq = DlqRecord.of(md == null ? Settings.TOPIC_TRANSCRIPTS : md.topic(),
                        md == null ? 0 : md.partition(), md == null ? 0 : md.offset(),
                        record.key(), record.value(), e.getMessage(), now);
                // DLQ output gets the current time, never the (possibly bogus) record timestamp:
                // the broker rejects timestamps outside its accepted range.
                context.forward(record.withValue(new Parsed(null, Json.write(dlq))).withTimestamp(now));
            }
        }
    }

    /**
     * Event time = transcript.v1 {@code event_ts} (ARCHITECTURE A3). A record that fails the
     * contract check (same check and clock as the parse step, plus key == video_id) keeps the
     * current partition time instead of its producer timestamp.
     *
     * <p>Defence in depth only: M4 showed (mutation check) that the windowed aggregate and suppress
     * track their own stream time from the records that reach them, and dead-lettered records never
     * do, so poison cannot close windows either way. This keeps the task-level stream time honest too.
     */
    static final class EventTimeExtractor implements TimestampExtractor {

        private final LongSupplier clock;

        EventTimeExtractor(LongSupplier clock) {
            this.clock = clock;
        }

        @Override
        public long extract(ConsumerRecord<Object, Object> record, long partitionTime) {
            long fallback = Math.max(partitionTime, 0);
            if (!(record.value() instanceof String value)) {
                return fallback;
            }
            try {
                Transcript t = Transcript.parse(value, clock.getAsLong());
                return t.videoId().equals(record.key()) ? t.eventTs() : fallback;
            } catch (ContractException e) {
                return fallback;
            }
        }
    }
}
