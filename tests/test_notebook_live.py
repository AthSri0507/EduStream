"""N-2: the live stage (NOTEBOOK_DESIGN §11.4): a reply becomes notes.v3 elements with code-assigned ids, a paragraph
may continue the last one, the extractive fallback, and Memory folds the records (live and on rebuild alike)."""

from agents.notebook import Held, Memory, Window, build_update, extractive_live, live_delta
from common import schemas

S0 = 1_792_051_200_000
TEXTS = [
    "So, fundamentally, it does two things. One, performs calculations.",
    "And it performs a lot of calculations. Computers these days are really, really fast.",
    "It performs these calculations and it has to store them somewhere, right? Store them in computer memory.",
    "So a computer also has to remember results, hundreds of gigabytes of storage.",
    "So the kinds of calculations that computers do, there are two kinds.",
    "One are calculations that are built into the language, addition, subtraction, multiplication.",
    "You as a programmer can put these types together and then define your own calculations.",
    "Problem set zero is due on Thursday, so start early.",
    "The first type of knowledge is declarative knowledge, and those are statements of fact.",
]
CHUNKS = [{"chunk_id": 36 + i, "start_time": 360.0 + 10 * i, "end_time": 370.0 + 10 * i, "text": t}
          for i, t in enumerate(TEXTS)]


def held(k=4, chunks=CHUNKS) -> Held:
    return Held("python_l1", k, [Window("python_l1", S0 + k * 90_000, S0 + k * 90_000 + 30_000, S0, chunks, 0, k)])


def para(text, quote, lead="", cont=False, **extra):
    return {"kind": "para", "lead": lead, "text": text, "quote": quote, "continue": cont, **extra}


def test_elements_get_code_ids_and_the_record_validates():
    reply = {"elements": [para("A computer performs calculations and stores the results in memory.",
                               "Store them in computer memory", lead="What a computer does")],
             "info": {"text": "Problem set 0 is due on Thursday.", "quote": "Problem set zero is due on Thursday"}}
    m = Memory("python_l1")
    d = live_delta(m, reply, CHUNKS, 4)
    assert [e["id"] for e in d["elements"]] == ["u4e0"] and d["elements"][0]["extends"] is None
    assert d["info"] == {"text": "Problem set 0 is due on Thursday.", "t": 430.0}
    payload = build_update(held(), d, "openai/gpt-oss-120b", 1234.5, now_ms=S0)
    assert schemas.decode(schemas.encode("notes.v3", payload), "notes.v3") == payload
    assert payload["media_start"] == 360.0 and payload["media_end"] == 450.0 and len(payload["transcript"]) == 9


def test_a_continuation_extends_the_last_live_paragraph_until_it_is_long():
    m = Memory("python_l1")
    first = live_delta(m, {"elements": [para("A computer performs calculations.", "One, performs calculations",
                                             lead="Computers")]}, CHUNKS, 4)
    m.apply_update(build_update(held(), first, "m", 1.0, now_ms=S0))
    nxt = live_delta(m, {"elements": [para("It stores the results in computer memory.",
                                           "Store them in computer memory", lead="ignored", cont=True)]}, CHUNKS, 5)
    assert nxt["elements"][0]["extends"] == "u4e0" and nxt["elements"][0]["lead"] == ""
    m.apply_update(build_update(held(5), nxt, "m", 1.0, now_ms=S0))
    assert len(m.drafts) == 1 and m.drafts[0]["sentences"] == ["A computer performs calculations.",
                                                               "It stores the results in computer memory."]
    m.drafts[0]["sentences"] += ["x"] * 4                         # six sentences: a seventh starts a new paragraph
    late = live_delta(m, {"elements": [para("Declarative knowledge is statements of fact.",
                                            "declarative knowledge, and those are statements of fact", cont=True)]},
                      CHUNKS, 6)
    assert late["elements"][0]["extends"] is None and "continue_as_new_paragraph" in late["quality_flags"]


def test_at_most_two_elements_and_repeats_of_the_notes_are_dropped():
    m = Memory("python_l1")
    m.apply_update(build_update(held(3), live_delta(m, {"elements": [
        para("A computer performs calculations.", "One, performs calculations")]}, CHUNKS, 3), "m", 1.0, now_ms=S0))
    d = live_delta(m, {"elements": [
        para("A computer performs calculations.", "One, performs calculations"),
        para("Declarative knowledge is statements of fact.", "declarative knowledge, and those are statements of fact"),
        para("Built-in calculations include addition and subtraction.", "addition, subtraction, multiplication")]},
        CHUNKS, 4)
    assert "too_many_elements(3)" in d["quality_flags"]
    assert [e["sentences"] for e in d["elements"]] == [["Declarative knowledge is statements of fact."]]
    assert d["stats"]["sentences_repeat"] == 1


def test_a_reply_whose_elements_all_fail_is_an_empty_update_not_raw_transcript():
    d = live_delta(Memory("python_l1"), {"elements": [para("Rust has a borrow checker.", "rust borrow checker")]},
                   CHUNKS, 4)
    assert d["elements"] == [] and "all_elements_dropped" in d["quality_flags"] and d["generator"] == "llm"
    assert live_delta(Memory("python_l1"), {"elements": "nonsense", "info": 3}, CHUNKS, 4)["elements"] == []


def test_the_extractive_fallback_is_one_verbatim_paragraph():
    d = extractive_live(Memory("python_l1"), CHUNKS, 4, ["llm_unavailable:disabled"])
    assert d["generator"] == "extractive" and len(d["elements"]) == 1
    el = d["elements"][0]
    assert el["kind"] == "para" and all(s in " ".join(TEXTS) for s in el["sentences"])
    payload = build_update(held(), d, "ignored", 0.0, now_ms=S0)
    assert payload["model"] is None and schemas.validate("notes.v3", payload)


def test_memory_folds_records_once_and_keeps_the_transcript_since_the_last_pass():
    m = Memory("python_l1")
    payload = build_update(held(), extractive_live(m, CHUNKS, 4), None, 0.0, now_ms=S0)
    m.apply_update(payload, partition=2)
    m.apply_update(payload, partition=2)                          # a duplicate record changes nothing
    assert m.partition == 2 and m.sent == {4} and len(m.drafts) == 1 and m.media_end == 450.0
    assert [c["chunk_id"] for c in m.chunks(400.0)] == [36, 37, 38, 39]
    assert "Finished topics: (none yet)" in m.index()
