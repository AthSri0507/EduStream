"""A13 decoding rule, with a fake model (no Whisper needed)."""

import math
from types import SimpleNamespace

from summarizer.transcription import asr


def seg(text, start, end, logprob=-0.3, ratio=1.4, no_speech=0.01):
    return SimpleNamespace(text=text, start=start, end=end, avg_logprob=logprob, compression_ratio=ratio,
                           no_speech_prob=no_speech)


class FakeModel:
    def __init__(self, first, retry):
        self.first, self.retry, self.calls = first, retry, []

    def transcribe(self, audio, **options):
        self.calls.append(options)
        return (self.retry if "repetition_penalty" in options else self.first), None


def test_summary_is_duration_weighted():
    result = asr.summarize_segments([seg(" a ", 0, 3, logprob=-0.2), seg("b", 3, 4, logprob=-1.0)])
    assert result["text"] == "a b"
    assert math.isclose(result["avg_logprob"], (-0.2 * 3 - 1.0) / 4)
    assert math.isclose(result["asr_score"], math.exp((-0.2 * 3 - 1.0) / 4))


def test_no_speech_gives_empty_text_and_null_score():
    assert asr.summarize_segments([]) == {"text": "", "asr_score": None, "avg_logprob": None,
                                          "no_speech_prob": None, "compression_ratio": None}


def test_good_chunk_is_decoded_once_at_temperature_0():
    model = FakeModel([seg("fine", 0, 10)], retry=None)
    result = asr.transcribe(model, audio=None)
    assert result["retried"] is False and len(model.calls) == 1
    assert model.calls[0]["temperature"] == 0.0


def test_loop_triggers_one_repetition_penalty_retry():
    loop = [seg("4, " * 100, 0, 10, ratio=11.5, logprob=-0.1)]      # asr_score high, ratio flags it (M2)
    model = FakeModel(loop, retry=[seg("This is true for k equals 1, 2, 3.", 0, 10)])
    result = asr.transcribe(model, audio=None)
    assert result["retried"] is True and result["text"].startswith("This is true")
    assert len(model.calls) == 2
    assert model.calls[1]["repetition_penalty"] == 1.3 and model.calls[1]["temperature"] == 0.0


def test_low_logprob_also_triggers_retry():
    assert asr.needs_retry({"compression_ratio": 1.2, "avg_logprob": -1.3})
    assert not asr.needs_retry({"compression_ratio": 2.4, "avg_logprob": -1.0})      # boundaries excluded
    assert not asr.needs_retry({"compression_ratio": None, "avg_logprob": None})
