package com.educationalstream;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
import java.util.List;
import java.util.stream.Stream;
import org.junit.jupiter.api.DynamicTest;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestFactory;

/**
 * C-1, Java side (ARCHITECTURE §5): the same golden fixtures the Python tests use
 * (schemas/examples), so both languages agree on the contract.
 */
class ContractTest {

    private static final Path EXAMPLES = TestData.SCHEMAS.resolve("examples");
    /** Fixture time origin (schemas/examples use session_start 1_792_051_200_000). */
    private static final long FIXTURE_NOW = 1_792_051_200_000L + 3_600_000L;

    /** JSON trees equal, with numbers compared by value (3 == 3.0, int == long). */
    private static final Comparator<JsonNode> NUMERIC = (a, b) -> {
        if (a.equals(b)) {
            return 0;
        }
        if (a.isNumber() && b.isNumber()) {
            return Double.compare(a.asDouble(), b.asDouble());
        }
        return 1;
    };

    @TestFactory
    Stream<DynamicTest> transcriptFixturesParseExactlyAsNamed() throws IOException {
        List<Path> files = fixtures("transcript");
        assertFalse(files.isEmpty());
        return files.stream().map(path -> DynamicTest.dynamicTest(path.getFileName().toString(), () -> {
            String raw = Files.readString(path);
            if (path.getFileName().toString().startsWith("valid")) {
                assertDoesNotThrow(() -> Transcript.parse(raw, FIXTURE_NOW));
            } else {
                assertThrows(ContractException.class, () -> Transcript.parse(raw, FIXTURE_NOW));
            }
        }));
    }

    @Test
    void outOfRangeEventTimeIsRejectedBeforeTheBrokerCanRejectTheOutput() throws IOException {
        String raw = Files.readString(EXAMPLES.resolve("transcript").resolve("valid-chunk.json"));
        long fixtureEventTs = 1_792_051_260_000L;
        assertThrows(ContractException.class, () -> Transcript.parse(raw, fixtureEventTs + 13 * 3_600_000L));
        assertThrows(ContractException.class, () -> Transcript.parse(raw, fixtureEventTs - 31 * 60_000L));
    }

    @TestFactory
    Stream<DynamicTest> outputFixturesRoundTripThroughJavaModels() throws IOException {
        Stream<DynamicTest> windows = roundTrips("window", WindowSummary.class);
        Stream<DynamicTest> alerts = roundTrips("alert", Alert.class);
        Stream<DynamicTest> dlq = roundTrips("dlq", DlqRecord.class);
        return Stream.of(windows, alerts, dlq).flatMap(s -> s);
    }

    private static Stream<DynamicTest> roundTrips(String folder, Class<?> type) throws IOException {
        return fixtures(folder).stream()
                .filter(p -> p.getFileName().toString().startsWith("valid"))
                .map(path -> DynamicTest.dynamicTest(folder + "/" + path.getFileName(), () -> {
                    JsonNode expected = TestData.readFile(path);
                    Object model = Json.MAPPER.treeToValue(expected, type);
                    JsonNode actual = Json.MAPPER.valueToTree(model);
                    assertTrue(expected.equals(NUMERIC, actual),
                            "round trip changed the payload:\n expected " + expected + "\n actual   " + actual);
                }));
    }

    private static List<Path> fixtures(String folder) throws IOException {
        try (Stream<Path> files = Files.list(EXAMPLES.resolve(folder))) {
            return files.filter(p -> p.toString().endsWith(".json")).sorted().toList();
        }
    }
}
