package com.educationalstream;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.apache.kafka.common.Metric;
import org.apache.kafka.common.MetricName;

/**
 * LATE_DROP tripwire (ARCHITECTURE §6.1 step 9, §7): watches the task metric
 * {@code dropped-records-total} (group {@code stream-task-metrics}, verified in M2 J6).
 *
 * <p>Kafka Streams metrics live in memory and start at 0 for every process and every newly
 * created task. So the monitor alerts on any increase over the last value it saw for a task,
 * and treats a decrease as a re-created task (reset). A restart or a task moving to another
 * instance therefore never raises a false alert, and drops in the first seconds are not missed.
 * In the supported model (S1) this should never fire.
 */
public final class LateDropMonitor {

    static final String METRIC = "dropped-records-total";
    static final String GROUP = "stream-task-metrics";

    private final Map<String, Double> lastSeen = new HashMap<>();

    public List<Alert> scan(Map<MetricName, ? extends Metric> metrics, long nowMs) {
        List<Alert> alerts = new ArrayList<>();
        for (Map.Entry<MetricName, ? extends Metric> entry : metrics.entrySet()) {
            MetricName name = entry.getKey();
            if (!METRIC.equals(name.name()) || !GROUP.equals(name.group())) {
                continue;
            }
            if (!(entry.getValue().metricValue() instanceof Number number)) {
                continue;
            }
            String task = name.tags().getOrDefault("task-id", "unknown");
            double value = number.doubleValue();
            if (value > lastSeen.getOrDefault(task, 0.0)) {
                alerts.add(Alert.lateDrop(task, value, nowMs));
            }
            lastSeen.put(task, value);
        }
        return alerts;
    }
}
