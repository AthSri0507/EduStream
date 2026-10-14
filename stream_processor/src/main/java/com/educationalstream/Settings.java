package com.educationalstream;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Configuration (docs/ARCHITECTURE.md §6.1, §7, §11).
 *
 * <p>Environment variables win; the repo's {@code .env} (read from the working directory)
 * only supplies defaults. This is the same rule as {@code common/config.py}, so the Python
 * and Java components always agree on WINDOW_SECONDS, GRACE_SECONDS and T_SCORE (S5).
 */
public record Settings(
        String bootstrap,
        String applicationId,
        int replicationFactor,
        int windowSeconds,
        int graceSeconds,
        double tScore,
        double minCoveredS,
        String stateDir,
        String logDir) {

    public static final String TOPIC_TRANSCRIPTS = "transcriptions";
    public static final String TOPIC_WINDOWS = "window_summaries";
    public static final String TOPIC_ALERTS = "alerts";
    public static final String TOPIC_DLQ = "dlq";

    public static Settings fromEnvironment() {
        Map<String, String> dotenv = readDotEnv(Path.of(".env"));
        int window = Integer.parseInt(get(dotenv, "WINDOW_SECONDS", "30"));
        return new Settings(
                get(dotenv, "KAFKA_BOOTSTRAP", "localhost:9092"),
                get(dotenv, "STREAMS_APP_ID", "edustream-streams"),
                Integer.parseInt(get(dotenv, "EDU_RF", "1")),
                window,
                Integer.parseInt(get(dotenv, "GRACE_SECONDS", "10")),
                Double.parseDouble(get(dotenv, "T_SCORE", "0.63")),
                Double.parseDouble(get(dotenv, "MIN_COVERED_S", String.valueOf(window / 2.0))),
                get(dotenv, "STATE_DIR", "run/state/streams"),
                get(dotenv, "LOG_DIR", "run/logs"));
    }

    /** Invariant violations; empty means usable (mirrors Settings.problems() in common/config.py). */
    public List<String> problems() {
        List<String> found = new ArrayList<>();
        if (windowSeconds <= 0 || graceSeconds <= 0) {
            found.add("WINDOW_SECONDS and GRACE_SECONDS must be > 0");
        }
        if (!(tScore > 0 && tScore < 1)) {
            found.add("T_SCORE=" + tScore + " must be in (0, 1)");
        }
        if (!(minCoveredS > 0 && minCoveredS <= windowSeconds)) {
            found.add("MIN_COVERED_S=" + minCoveredS + " must be in (0, WINDOW_SECONDS]");
        }
        if (replicationFactor < 1) {
            found.add("EDU_RF must be >= 1");
        }
        return found;
    }

    private static String get(Map<String, String> dotenv, String name, String fallback) {
        String value = System.getenv(name);
        if (value != null && !value.isBlank()) {
            return value.trim();
        }
        value = dotenv.get(name);
        return value != null && !value.isBlank() ? value : fallback;
    }

    static Map<String, String> readDotEnv(Path path) {
        Map<String, String> values = new HashMap<>();
        if (!Files.isRegularFile(path)) {
            return values;
        }
        try {
            for (String line : Files.readAllLines(path, StandardCharsets.UTF_8)) {
                String trimmed = line.trim();
                int eq = trimmed.indexOf('=');
                if (trimmed.isEmpty() || trimmed.startsWith("#") || eq <= 0) {
                    continue;
                }
                values.put(trimmed.substring(0, eq).trim(), trimmed.substring(eq + 1).trim());
            }
        } catch (IOException e) {
            // Unreadable .env: environment variables and built-in defaults still apply.
        }
        return values;
    }
}
