package com.educationalstream;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.common.serialization.Serdes;
import org.apache.kafka.common.utils.Bytes;
import org.apache.kafka.streams.KafkaStreams;
import org.apache.kafka.streams.KeyValue;
import org.apache.kafka.streams.StreamsBuilder;
import org.apache.kafka.streams.StreamsConfig;
import org.apache.kafka.streams.kstream.*;
import org.apache.kafka.streams.processor.TimestampExtractor;

import java.time.Duration;
import java.util.Properties;

public class StreamProcessor {

    private static final String INPUT_TOPIC = "transcriptions";
    private static final String OUTPUT_TOPIC = "generated_notes";

    private static final ObjectMapper objectMapper = new ObjectMapper();

    public static void main(String[] args) {

        // --------------------------------------------------
        // 1. Kafka Streams configuration
        // --------------------------------------------------

        Properties props = new Properties();

        props.put(
                StreamsConfig.APPLICATION_ID_CONFIG,
                "educational-stream-processor"
        );

        props.put(
                StreamsConfig.BOOTSTRAP_SERVERS_CONFIG,
                "127.0.0.1:9092"
        );

        props.put(
                StreamsConfig.DEFAULT_KEY_SERDE_CLASS_CONFIG,
                Serdes.String().getClass()
        );

        props.put(
                StreamsConfig.DEFAULT_VALUE_SERDE_CLASS_CONFIG,
                Serdes.String().getClass()
        );

        // Process existing messages in the topic

props.put(
    ConsumerConfig.AUTO_OFFSET_RESET_CONFIG,
    "earliest"
);
        // --------------------------------------------------
        // 2. Create the stream builder
        // --------------------------------------------------

        StreamsBuilder builder = new StreamsBuilder();

        // --------------------------------------------------
        // 3. Read transcription events from Kafka
        // --------------------------------------------------

        KStream<String, String> transcriptions =
                builder.stream(
                        INPUT_TOPIC,
                        Consumed.with(
                                Serdes.String(),
                                Serdes.String()
                        ).withTimestampExtractor(
                                new TranscriptTimestampExtractor()
                        )
                );

        // --------------------------------------------------
        // 4. Extract video_id and make it the Kafka key
        // --------------------------------------------------

        KStream<String, String> keyedTranscriptions =
                transcriptions.selectKey(
                        (key, value) -> extractVideoId(value)
                );

        // --------------------------------------------------
        // 5. Extract only the transcript text
        // --------------------------------------------------

        KStream<String, String> textStream =
                keyedTranscriptions.mapValues(
                        StreamProcessor::extractText
                );

        // --------------------------------------------------
        // 6. Create 30-second windows
        // --------------------------------------------------

        KTable<Windowed<String>, String> aggregated =
                textStream
                        .groupByKey(
                                Grouped.with(
                                        Serdes.String(),
                                        Serdes.String()
                                )
                        )
                        .windowedBy(
                                TimeWindows.ofSizeAndGrace(
                                        Duration.ofSeconds(30),
                                        Duration.ofSeconds(5)
                                )
                        )
                        .reduce(
                                (oldText, newText) ->
                                        oldText + " " + newText
                        );

        // --------------------------------------------------
        // 7. Convert the window result into JSON
        // --------------------------------------------------

        aggregated
                .toStream()
                .map(
                        (windowedKey, text) -> {

                            String videoId =
                                    windowedKey.key();

                            long windowStart =
                                    windowedKey.window()
                                            .startTime()
                                            .toEpochMilli() / 1000;

                            long windowEnd =
                                    windowedKey.window()
                                            .endTime()
                                            .toEpochMilli() / 1000;

                            String outputJson =
                                    createOutputJson(
                                            videoId,
                                            windowStart,
                                            windowEnd,
                                            text
                                    );

                            return KeyValue.pair(
                                    videoId,
                                    outputJson
                            );
                        }
                )
                .to(
                        OUTPUT_TOPIC,
                        Produced.with(
                                Serdes.String(),
                                Serdes.String()
                        )
                );

        // --------------------------------------------------
        // 8. Build and start Kafka Streams
        // --------------------------------------------------

        KafkaStreams streams =
                new KafkaStreams(
                        builder.build(),
                        props
                );

        Runtime.getRuntime().addShutdownHook(
                new Thread(streams::close)
        );

        System.out.println(
                "Kafka Streams processor started..."
        );

        streams.start();
    }

    // ======================================================
    // Extract video_id from JSON
    // ======================================================

    private static String extractVideoId(String json) {

        try {

            JsonNode node =
                    objectMapper.readTree(json);

            return node
                    .get("video_id")
                    .asText();

        } catch (Exception e) {

            throw new RuntimeException(
                    "Invalid transcription JSON: " + json,
                    e
            );
        }
    }

    // ======================================================
    // Extract text from JSON
    // ======================================================

    private static String extractText(String json) {

        try {

            JsonNode node =
                    objectMapper.readTree(json);

            return node
                    .get("text")
                    .asText();

        } catch (Exception e) {

            throw new RuntimeException(
                    "Invalid transcription JSON: " + json,
                    e
            );
        }
    }

    // ======================================================
    // Create output JSON
    // ======================================================

    private static String createOutputJson(
            String videoId,
            long windowStart,
            long windowEnd,
            String text
    ) {

        try {

            return objectMapper
                    .createObjectNode()
                    .put("video_id", videoId)
                    .put("window_start", windowStart)
                    .put("window_end", windowEnd)
                    .put("transcript", text)
                    .toString();

        } catch (Exception e) {

            throw new RuntimeException(
                    "Could not create output JSON",
                    e
            );
        }
    }

    // ======================================================
    // Custom timestamp extractor
    // ======================================================

    public static class TranscriptTimestampExtractor
            implements TimestampExtractor {

        @Override
        public long extract(
                ConsumerRecord<Object, Object> record,
                long partitionTime
        ) {

            try {

                String json =
                        (String) record.value();

                JsonNode node =
                        objectMapper.readTree(json);

                long startTime =
                        node.get("start_time")
                                .asLong();

                // Convert seconds → milliseconds
                return startTime * 1000;

            } catch (Exception e) {

                return partitionTime >= 0
                        ? partitionTime
                        : System.currentTimeMillis();
            }
        }
    }
}