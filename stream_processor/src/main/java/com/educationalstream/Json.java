package com.educationalstream;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.json.JsonMapper;
import java.io.IOException;
import java.io.UncheckedIOException;
import org.apache.kafka.common.serialization.Serde;
import org.apache.kafka.common.serialization.Serdes;

/** One shared Jackson mapper (snake_case, like the Python side) and a JSON serde for state stores. */
public final class Json {

    public static final ObjectMapper MAPPER = JsonMapper.builder()
            .propertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE)
            .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
            .build();

    private Json() {
    }

    public static String write(Object value) {
        try {
            return MAPPER.writeValueAsString(value);
        } catch (JsonProcessingException e) {
            throw new UncheckedIOException(e);
        }
    }

    public static <T> Serde<T> serde(Class<T> type) {
        return Serdes.serdeFrom(
                (topic, value) -> {
                    try {
                        return value == null ? null : MAPPER.writeValueAsBytes(value);
                    } catch (JsonProcessingException e) {
                        throw new UncheckedIOException(e);
                    }
                },
                (topic, bytes) -> {
                    try {
                        return bytes == null ? null : MAPPER.readValue(bytes, type);
                    } catch (IOException e) {
                        throw new UncheckedIOException(e);
                    }
                });
    }
}
