package com.educationalstream;

import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import org.apache.kafka.clients.producer.KafkaProducer;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.common.TopicPartition;
import org.apache.kafka.common.serialization.StringSerializer;
import org.apache.kafka.streams.KafkaStreams;
import org.apache.kafka.streams.Topology;
import org.apache.kafka.streams.errors.StreamsUncaughtExceptionHandler.StreamThreadExceptionResponse;
import org.apache.kafka.streams.processor.StateRestoreListener;

/**
 * Entry point of the EduStream Kafka Streams app (application.id edustream-streams).
 *
 * <pre>
 *   cd stream_processor && .\mvnw.cmd -q package
 *   java -Xmx512m -jar stream_processor\target\edustream-streams.jar      (from the repo root)
 * </pre>
 * Normally started by scripts\start_all.ps1 (restarted on error exits by run_component.ps1).
 */
public final class EduStreamsApp {

    private EduStreamsApp() {
    }

    public static void main(String[] args) throws InterruptedException {
        Settings settings = Settings.fromEnvironment();
        AppLog log = new AppLog("streams", settings.logDir());
        List<String> problems = settings.problems();
        if (!problems.isEmpty()) {
            log.error("config_invalid", Map.of("problems", problems));
            System.exit(2);
        }

        Topology topology = WindowTopology.build(settings, System::currentTimeMillis);
        System.out.println(topology.describe());
        KafkaStreams streams = new KafkaStreams(topology, WindowTopology.properties(settings));
        streams.setStateListener((now, before) -> {
            log.info("state", Map.of("from", before, "to", now));
            if (now == KafkaStreams.State.ERROR) {
                // All stream threads are gone: exit non-zero so run_component.ps1 restarts the process.
                new Thread(() -> System.exit(1), "exit-on-error").start();
            }
        });
        streams.setUncaughtExceptionHandler(e -> {
            log.error("stream_thread_failed", Map.of("error", String.valueOf(e)));
            return StreamThreadExceptionResponse.REPLACE_THREAD;
        });
        streams.setGlobalStateRestoreListener(new RestoreLogger(log));

        KafkaProducer<String, String> alertProducer = alertProducer(settings);
        LateDropMonitor monitor = new LateDropMonitor();
        ScheduledExecutorService ticker = Executors.newSingleThreadScheduledExecutor(r -> {
            Thread t = new Thread(r, "late-drop-monitor");
            t.setDaemon(true);
            return t;
        });
        CountDownLatch stopped = new CountDownLatch(1);
        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            log.info("stopping", Map.of());
            ticker.shutdownNow();
            streams.close(Duration.ofSeconds(10));
            alertProducer.close(Duration.ofSeconds(5));
            stopped.countDown();
        }, "shutdown"));

        log.info("starting", Map.of("application_id", settings.applicationId(), "bootstrap", settings.bootstrap(),
                "window_s", settings.windowSeconds(), "grace_s", settings.graceSeconds(),
                "t_score", settings.tScore(), "min_covered_s", settings.minCoveredS(), "state_dir", settings.stateDir()));
        streams.start();

        ticker.scheduleAtFixedRate(() -> {
            try {
                for (Alert alert : monitor.scan(streams.metrics(), System.currentTimeMillis())) {
                    log.warn("late_drop", Map.of("task", alert.details().path("task_id").asText(),
                            "dropped_since_start", alert.value()));
                    alertProducer.send(new ProducerRecord<>(Settings.TOPIC_ALERTS, "_system", Json.write(alert)),
                            (md, error) -> {
                                if (error != null) {
                                    log.error("late_drop_alert_failed", Map.of("error", String.valueOf(error)));
                                }
                            });
                }
            } catch (RuntimeException e) {
                log.error("late_drop_scan_failed", Map.of("error", String.valueOf(e)));
            }
        }, 10, 10, TimeUnit.SECONDS);

        stopped.await();
    }

    /** Separate non-transactional producer for LATE_DROP (duplicates collapse on alert_id). */
    private static KafkaProducer<String, String> alertProducer(Settings settings) {
        Properties p = new Properties();
        p.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, settings.bootstrap());
        p.put(ProducerConfig.CLIENT_ID_CONFIG, settings.applicationId() + "-late-drop");
        p.put(ProducerConfig.ACKS_CONFIG, "all");
        p.put(ProducerConfig.ENABLE_IDEMPOTENCE_CONFIG, true);
        p.put(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer.class);
        p.put(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, StringSerializer.class);
        return new KafkaProducer<>(p);
    }

    /** Logs state restoration from the changelog: the evidence for fault demo F-2b. */
    private record RestoreLogger(AppLog log) implements StateRestoreListener {

        @Override
        public void onRestoreStart(TopicPartition partition, String store, long startOffset, long endOffset) {
            log.info("restore_start", Map.of("store", store, "partition", partition.toString(),
                    "records_to_restore", endOffset - startOffset));
        }

        @Override
        public void onBatchRestored(TopicPartition partition, String store, long batchEndOffset, long numRestored) {
        }

        @Override
        public void onRestoreEnd(TopicPartition partition, String store, long totalRestored) {
            log.info("restore_end", Map.of("store", store, "partition", partition.toString(),
                    "records_restored", totalRestored));
        }
    }
}
