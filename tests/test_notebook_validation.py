"""N-2: validation of the LLM's notebook delta and the extractive fallback (ARCHITECTURE §8.1.3-8.1.5)."""

from agents.notebook import Held, Memory, Window, build_update, extractive_delta, llm_delta
from common import schemas

TEXTS = [
    "So, fundamentally, it does two things. One, performs calculations.",
    "And it performs a lot of calculations. Computers these days are really, really fast.",
    "It performs these calculations and it has to store them somewhere, right? Store them in computer memory.",
    "So a computer also has to remember results, hundreds of gigabytes of storage.",
    "So the kinds of calculations that computers do, there are two kinds.",
    "One are calculations that are built into the language, addition, subtraction, multiplication.",
    "You as a programmer can put these types together and then define your own calculations.",
    "Computers only know what you tell them. They don't have a mind.",
    "The first type of knowledge is declarative knowledge, and those are statements of fact.",
]
CHUNKS = [{"chunk_id": 36 + i, "start_time": 360.0 + 10 * i, "end_time": 370.0 + 10 * i, "text": t}
          for i, t in enumerate(TEXTS)]


def memory_with_section(updates: int = 2) -> Memory:
    m = Memory("python_l1")
    for k in range(updates):
        m.apply({"update_index": k, "window_starts": [k], "section": {"id": 1, "title": "Course overview", "is_new": k == 0},
                 "points": [{"section_id": 1, "text": f"Earlier point number {k} about the course logistics.", "t": 10.0 * k,
                             "kind": "point", "quote": "x"}], "terms": []})
    return m


def point(text, quote, t="06:00", **extra):
    return {"text": text, "quote": quote, "t": t, "kind": "point", **extra}


def test_first_update_opens_section_1_and_ids_come_from_code():
    d = llm_delta(Memory("python_l1"), {"section": {"action": "continue"}, "points": []}, CHUNKS, 0)
    assert d["section"] == {"id": 1, "title": "Introduction", "is_new": True} and d["generator"] == "llm"
    d = llm_delta(memory_with_section(), {"section": {"action": "new", "title": "What a computer does", "id": 99}},
                  CHUNKS, 2)
    assert d["section"] == {"id": 2, "title": "What a computer does", "is_new": True}     # the LLM's id is ignored


def test_a_premature_new_section_is_turned_into_continue():
    d = llm_delta(memory_with_section(updates=1), {"section": {"action": "new", "title": "Too soon"}}, CHUNKS, 1)
    assert d["section"]["id"] == 1 and not d["section"]["is_new"]
    assert any(f.startswith("premature_new_section") for f in d["quality_flags"])


def test_points_before_starts_at_stay_in_the_previous_section():
    reply = {"section": {"action": "new", "title": "Types of calculation", "starts_at": "06:40"},
             "points": [point("A computer does two things: it performs calculations.",
                              "it does two things. One, performs calculations"),
                        point("Built-in calculations include addition, subtraction and multiplication.",
                              "built into the language, addition, subtraction, multiplication")]}
    d = llm_delta(memory_with_section(), reply, CHUNKS, 4)
    assert [p["section_id"] for p in d["points"]] == [1, 2]


def test_quotes_must_exist_and_support_the_point():
    reply = {"points": [
        point("Results are stored in computer memory.", "this sentence was never said in the lecture"),
        point("Python has built-in data types such as integers, floats, strings, lists and dictionaries.",
              "Computers these days are really, really fast"),                            # real quote, invented point
        point("Computers only know what you tell them; they have no mind.",
              "Computers only know what you tell them... They don't have a mind"),        # elided quote: fine
    ]}
    d = llm_delta(memory_with_section(), reply, CHUNKS, 4)
    assert [p["text"][:20] for p in d["points"]] == ["Computers only know "]
    assert d["points"][0]["t"] == 430.0                      # time of the quote's chunk, not the claimed 06:00
    assert "quote_not_found" in d["quality_flags"] and any(f.startswith("low_support") for f in d["quality_flags"])


def test_background_is_kept_separately():
    reply = {"points": [point("Computers perform a lot of calculations and are really fast.",
                              "it performs a lot of calculations",
                              background="A modern CPU runs billions of simple operations per second.")]}
    d = llm_delta(memory_with_section(), reply, CHUNKS, 4)
    assert d["points"][0]["background"].startswith("A modern CPU")


def test_duplicates_and_malformed_items_are_dropped():
    m = memory_with_section()
    m.points.append({"section_id": 1, "text": "Computers only know what you tell them; no mind.", "t": 430.0})
    reply = {"points": ["just a string",
                        point("Computers only know what you tell them, they have no mind.",
                              "Computers only know what you tell them"),
                        point("Results of calculations are stored in computer memory.",
                              "Store them in computer memory")]}
    d = llm_delta(m, reply, CHUNKS, 4)
    assert len(d["points"]) == 1 and {"malformed_point", "duplicate_point"} <= set(d["quality_flags"])


def test_terms_must_occur_and_unsupported_definitions_become_background():
    reply = {"points": [], "terms": [
        {"term": "declarative knowledge", "definition": "Knowledge made of statements of fact.", "t": "07:20",
         "quote": "declarative knowledge, and those are statements of fact", "source": "lecture"},
        {"term": "computer memory", "definition": "Volatile DRAM attached to the CPU over a bus.", "t": "06:20",
         "quote": "Store them in computer memory", "source": "lecture"},
        {"term": "recursion", "definition": "A function calling itself.", "t": "06:00", "quote": "x", "source": "lecture"},
    ]}
    d = llm_delta(memory_with_section(), reply, CHUNKS, 4)
    assert [(t["term"], t["source"]) for t in d["terms"]] == [("declarative knowledge", "lecture"),
                                                             ("computer memory", "background")]
    assert "term_not_in_transcript" in d["quality_flags"]


def test_when_every_point_is_dropped_the_extractive_fallback_is_used():
    reply = {"points": [point("Invented content with no support at all here.", "nothing like this was said ever")]}
    d = llm_delta(memory_with_section(), reply, CHUNKS, 4)
    assert d["generator"] == "extractive" and "llm_points_all_dropped" in d["quality_flags"]
    assert 1 <= len(d["points"]) <= 3 and all(p["quote"] == p["text"] for p in d["points"])


def test_extractive_skips_boilerplate_and_opens_parts():
    chunks = [{"chunk_id": 0, "start_time": 0.0, "end_time": 10.0,
               "text": "The following content is provided under a Creative Commons license."}] + CHUNKS
    d = extractive_delta(Memory("python_l1"), chunks, 0)
    assert d["section"]["title"] == "Part 1" and all("Creative Commons" not in p["text"] for p in d["points"])


def test_payloads_validate_and_memory_folds_them_once():
    m = Memory("python_l1")
    held = Held("python_l1", 4, [Window("python_l1", 1_792_051_560_000 + 30_000 * i, 1_792_051_590_000 + 30_000 * i,
                                        1_792_051_200_000, CHUNKS[3 * i:3 * i + 3], 0, i) for i in range(3)])
    reply = {"section": {"action": "new", "title": "What a computer does"},
             "points": [point("A computer performs calculations and remembers the results.",
                              "it does two things. One, performs calculations")],
             "terms": [{"term": "computer memory", "definition": "Where results are stored.", "quote":
                        "Store them in computer memory", "source": "lecture", "t": "06:20"}]}
    payload = build_update(m, held, llm_delta(m, reply, held.chunks(), 4), "openai/gpt-oss-120b", 812.0, 1)
    schemas.validate("notes.v2", payload)
    assert (payload["media_start"], payload["media_end"], len(payload["window_starts"])) == (360.0, 450.0, 3)
    m.apply(payload)
    m.apply(payload)                                       # a duplicate record changes nothing
    assert m.sent == {4} and len(m.points) == 1 and m.last_sent == 4 and set(m.terms) == {"computer memory"}
    assert held.windows[0].window_start in m.sent_windows
    schemas.validate("notes.v2", build_update(m, held, extractive_delta(m, held.chunks(), 4), None, 1.0, 1))
