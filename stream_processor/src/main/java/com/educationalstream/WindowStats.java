package com.educationalstream;

import java.util.List;

/**
 * Per-window statistics (window.v1 "stats"). Covers the CIE lab programs "word count"
 * (word_count, top_terms) and "min/max/avg" (score_min/max/avg, words_per_min).
 * Score fields are null when no chunk in the window contained speech.
 */
public record WindowStats(
        int chunkCount,
        double coveredS,
        int wordCount,
        double wordsPerMin,
        Double scoreAvg,
        Double scoreMin,
        Double scoreMax,
        Double noSpeechAvg,
        Double compressionRatioMax,
        List<List<Object>> topTerms) {
}
