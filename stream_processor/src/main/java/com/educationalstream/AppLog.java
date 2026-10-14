package com.educationalstream;

import java.io.IOException;
import java.io.Writer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.stream.Collectors;

/** JSON-lines log in run/logs/streams.log plus a short console line (same format as common/log.py). */
final class AppLog {

    private final String component;
    private final Writer file;

    AppLog(String component, String logDir) {
        this.component = component;
        Writer opened = null;
        try {
            Path dir = Path.of(logDir);
            Files.createDirectories(dir);
            opened = Files.newBufferedWriter(dir.resolve(component + ".log"), StandardCharsets.UTF_8,
                    StandardOpenOption.CREATE, StandardOpenOption.APPEND);
        } catch (IOException e) {
            System.err.println("[" + component + "] cannot open log file: " + e.getMessage());
        }
        this.file = opened;
    }

    void info(String event, Map<String, ?> fields) {
        write("info", event, fields);
    }

    void warn(String event, Map<String, ?> fields) {
        write("warn", event, fields);
    }

    void error(String event, Map<String, ?> fields) {
        write("error", event, fields);
    }

    private synchronized void write(String level, String event, Map<String, ?> fields) {
        Map<String, Object> record = new LinkedHashMap<>();
        record.put("ts", System.currentTimeMillis());
        record.put("component", component);
        record.put("level", level);
        record.put("event", event);
        record.putAll(fields);
        String detail = fields.entrySet().stream().map(e -> e.getKey() + "=" + e.getValue())
                .collect(Collectors.joining(" "));
        System.out.println("[" + component + "] " + level.toUpperCase() + " " + event + " " + detail);
        if (file != null) {
            try {
                file.write(Json.write(record));
                file.write(System.lineSeparator());
                file.flush();
            } catch (IOException e) {
                System.err.println("[" + component + "] log write failed: " + e.getMessage());
            }
        }
    }
}
