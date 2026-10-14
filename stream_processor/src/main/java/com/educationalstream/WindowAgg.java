package com.educationalstream;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.DoubleSummaryStatistics;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.TreeMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/**
 * The windowed aggregate (ARCHITECTURE §6.1 step 5), stored as JSON in the in-memory window store.
 *
 * <p>Chunks live in a {@code TreeMap<chunk_id, chunk>}: output is ordered by chunk_id whatever the
 * arrival order (fixes D8), and a chunk redelivered by an at-least-once retry is ignored (first
 * writer wins). A flush record adds nothing; it only advances stream time so the window can close.
 */
public class WindowAgg {

    private static final Pattern TOKEN = Pattern.compile("[a-z0-9]+(?:'[a-z]+)?");
    private static final int TOP_TERMS = 5;
    private static final Set<String> STOPWORDS = Set.of(
            "about", "above", "after", "again", "against", "all", "also", "and", "any", "are", "aren't", "because",
            "been", "before", "being", "below", "between", "both", "but", "can", "can't", "cannot", "could",
            "did", "didn't", "does", "doesn't", "doing", "don't", "down", "during", "each", "few", "for", "from",
            "further", "get", "gets", "getting", "going", "gonna", "got", "had", "has", "have", "having", "he'd",
            "he'll", "he's", "her", "here", "hers", "him", "his", "how", "i'd", "i'll", "i'm", "i've", "into",
            "isn't", "it's", "its", "just", "kind", "know", "let", "let's", "like", "lot", "more", "most", "not",
            "now", "off", "okay", "once", "one", "only", "other", "our", "ours", "out", "over", "own", "really",
            "right", "same", "say", "says", "see", "she", "should", "some", "something", "sort", "such", "than",
            "that", "that's", "the", "their", "them", "then", "there", "there's", "these", "they", "they're",
            "thing", "things", "think", "this", "those", "through", "too", "two", "three", "under", "until",
            "very", "want", "was", "way", "we'll", "we're", "we've", "well", "were", "what", "what's", "when",
            "where", "which", "while", "who", "why", "will", "with", "won't", "would", "yeah", "yes", "you",
            "you'd", "you'll", "you're", "you've", "your", "yours", "actually", "basically", "maybe", "sure",
            "mean", "first", "second", "here's", "um", "uh");

    /** chunk_id -> chunk; public fields so Jackson can store the aggregate in the window store. */
    public TreeMap<Integer, WindowChunk> chunks = new TreeMap<>();
    public Long sessionStart;

    public WindowAgg add(Transcript t) {
        if (sessionStart == null) {
            sessionStart = t.sessionStart();
        }
        if (!t.isFlush()) {
            chunks.putIfAbsent(t.chunkId(), WindowChunk.of(t));
        }
        return this;
    }

    public int chunkCount() {
        return chunks.size();
    }

    /** Builds the window.v1 payload (ARCHITECTURE §6.1 step 7). Requires at least one chunk. */
    public WindowSummary summarize(String videoId, long windowStart, long windowEnd, long nowMs) {
        List<WindowChunk> list = new ArrayList<>(chunks.values());
        String transcript = list.stream().map(WindowChunk::text).filter(s -> s != null && !s.isBlank())
                .collect(Collectors.joining(" "));
        int words = transcript.isBlank() ? 0 : transcript.trim().split("\\s+").length;
        double covered = list.stream().mapToDouble(c -> Math.max(0, c.endTime() - c.startTime())).sum();
        DoubleSummaryStatistics scores = list.stream().map(WindowChunk::asrScore).filter(Objects::nonNull)
                .mapToDouble(Double::doubleValue).summaryStatistics();
        DoubleSummaryStatistics noSpeech = list.stream().map(WindowChunk::noSpeechProb).filter(Objects::nonNull)
                .mapToDouble(Double::doubleValue).summaryStatistics();
        DoubleSummaryStatistics ratios = list.stream().map(WindowChunk::compressionRatio).filter(Objects::nonNull)
                .mapToDouble(Double::doubleValue).summaryStatistics();

        WindowStats stats = new WindowStats(
                list.size(),
                round(covered, 3),
                words,
                covered > 0 ? round(words / covered * 60, 1) : 0.0,
                scores.getCount() > 0 ? round(scores.getAverage(), 4) : null,
                scores.getCount() > 0 ? round(scores.getMin(), 4) : null,
                scores.getCount() > 0 ? round(scores.getMax(), 4) : null,
                noSpeech.getCount() > 0 ? round(noSpeech.getAverage(), 4) : null,
                ratios.getCount() > 0 ? round(ratios.getMax(), 3) : null,
                topTerms(transcript));

        return new WindowSummary("window.v1", videoId, windowStart, windowEnd, 1, sessionStart,
                list.get(0).startTime(), list.stream().mapToDouble(WindowChunk::endTime).max().orElse(0),
                list.stream().map(WindowChunk::chunkId).toList(), transcript, list, stats, nowMs, "streams");
    }

    /** Top non-stopword terms, by count then alphabetically (deterministic). */
    static List<List<Object>> topTerms(String transcript) {
        Map<String, Integer> counts = new TreeMap<>();
        Matcher m = TOKEN.matcher(transcript.toLowerCase());
        while (m.find()) {
            String token = m.group();
            if (token.length() > 2 && !token.chars().allMatch(Character::isDigit) && !STOPWORDS.contains(token)) {
                counts.merge(token, 1, Integer::sum);
            }
        }
        return counts.entrySet().stream()
                .sorted(Map.Entry.<String, Integer>comparingByValue(Comparator.reverseOrder())
                        .thenComparing(Map.Entry.comparingByKey()))
                .limit(TOP_TERMS)
                .map(e -> List.<Object>of(e.getKey(), e.getValue()))
                .toList();
    }

    static double round(double value, int places) {
        double scale = Math.pow(10, places);
        return Math.round(value * scale) / scale;
    }
}
