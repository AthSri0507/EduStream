"""N-2a: study-guide elements (NOTEBOOK_DESIGN §11.1-11.3): where an element was said, sentence-level grounding,
emphasis that must be earned, a glossary grounded by construction. Pure, no LLM."""

from collections import Counter

from agents import study_notes as sn

CHUNKS = [
    {"chunk_id": 0, "start_time": 0.0, "end_time": 10.0,
     "text": "A computer does two things. It performs calculations, a billion calculations per second."},
    {"chunk_id": 1, "start_time": 10.0, "end_time": 20.0,
     "text": "And it remembers the results of those calculations in memory for later."},
    {"chunk_id": 2, "start_time": 20.0, "end_time": 30.0,
     "text": "Declarative knowledge is statements of fact. The square root of x is y such that y times y is x."},
    {"chunk_id": 3, "start_time": 30.0, "end_time": 40.0,
     "text": "Imperative knowledge is a recipe or how-to. I want to stress this: a computer only does what you tell it."},
    {"chunk_id": 4, "start_time": 40.0, "end_time": 50.0,
     "text": "So I'm going to import random and use the rand int function between 16 and 272. It chose 75."},
]


def check(raw, known=(), live=False):
    flags, stats = [], Counter()
    return sn.validate(raw, CHUNKS, flags, stats, list(known), live), flags, stats


def test_a_paragraph_keeps_its_supported_sentences_and_its_place():
    el, flags, stats = check({"kind": "para", "lead": "What a computer does",
                              "text": "A computer performs calculations, a billion per second. It remembers the results "
                                      "in memory.", "quote": "It performs calculations, a billion calculations"})
    assert el["kind"] == "para" and el["t"] == 0.0 and len(el["sentences"]) == 2
    assert el["lead"] == "What a computer does" and "performs calculations" in el["said"]
    assert stats["sentences_kept"] == 2


def test_an_invented_sentence_is_removed_and_a_back_reference_after_it_too():
    el, flags, stats = check({"kind": "para", "lead": "Computers",
                              "text": "A computer performs a billion calculations per second. Quantum processors "
                                      "replaced transistors entirely in modern laptops. This makes them fast. "
                                      "The results are remembered in memory.",
                              "quote": "It performs calculations, a billion calculations per second"})
    assert el["sentences"] == ["A computer performs a billion calculations per second.",
                               "The results are remembered in memory."]
    assert stats["sentences_unsupported"] == 1 and stats["sentences_cascade"] == 1


def test_a_paragraph_that_loses_more_than_half_is_dropped():
    el, flags, _ = check({"kind": "para", "text": "A computer performs calculations. Quantum processors replaced "
                                                  "transistors entirely. Graphics cards mine cryptocurrency daily.",
                          "quote": "It performs calculations, a billion calculations"})
    assert el is None and any(f.startswith("paragraph_dropped") for f in flags)


def test_meta_sentences_about_the_talk_are_filler():
    el, flags, stats = check({"kind": "para", "text": "The lecturer explains what a computer does. A computer "
                                                      "performs a billion calculations per second.",
                              "quote": "It performs calculations, a billion calculations"})
    assert el["sentences"] == ["A computer performs a billion calculations per second."]
    assert stats["sentences_filler"] == 1


def test_a_repeat_of_the_notes_so_far_is_dropped():
    known = ["A computer performs a billion calculations per second."]
    el, flags, _ = check({"kind": "para", "text": "A computer performs a billion calculations per second. "
                                                  "The results of those calculations are remembered in memory.",
                          "quote": "It performs calculations, a billion calculations"}, known)
    assert el["sentences"] == ["The results of those calculations are remembered in memory."]


def test_near_verbatim_quote_places_the_element_and_unplaceable_ones_are_dropped():
    el, flags, _ = check({"kind": "para", "text": "Imperative knowledge is a recipe or how-to.",
                          "quote": "imperative knowledge is a recipe or a how to"})
    assert el["t"] == 30.0 and "quote_near_verbatim" in flags
    el, flags, _ = check({"kind": "para", "text": "Imperative knowledge is a recipe or how-to.", "quote": None})
    assert el["t"] == 30.0 and "located_by_support" in flags        # the line itself, not the first window around it
    el, flags, _ = check({"kind": "para", "text": "Rust guarantees memory safety without garbage collection.",
                          "quote": "rust has no garbage collector at all"})
    assert el is None and any(f.startswith("not_grounded") for f in flags)


def test_the_glossary_entry_is_the_notes_own_defining_sentence():
    el, flags, _ = check({"kind": "para", "lead": "Two kinds of knowledge",
                          "text": "Declarative knowledge is statements of fact. Imperative knowledge is a recipe or "
                                  "how-to.",
                          "terms": ["Declarative knowledge", "Imperative knowledge", "Recursion"],
                          "quote": "Declarative knowledge is statements of fact"})
    assert [t["term"] for t in el["terms"]] == ["Declarative knowledge", "Imperative knowledge"]
    assert el["terms"][0]["definition"] == "Declarative knowledge is statements of fact."
    assert "term_dropped_unsaid:'Recursion'" in flags               # never said, never explained


# Live run 29 Oct (Hypothesis Testing, 36:00-42:00): what speech recognition wrote, and notes the checks threw away.
QA = [{"chunk_id": 0, "start_time": 2130.0, "end_time": 2140.0,
       "text": "The company insists the mean. Netweight is the mean netweight is four hundred and fifty four grams"},
      {"chunk_id": 1, "start_time": 2140.0, "end_time": 2150.0,
       "text": "so h naught is mean weight is 454 grams and in alternate hypothesis the mean is not equal to 454"},
      {"chunk_id": 2, "start_time": 2150.0, "end_time": 2160.0,
       "text": "a type one error is rejecting h naught when it is true, a type two error is failing to reject it"},
      {"chunk_id": 3, "start_time": 2160.0, "end_time": 2170.0,
       "text": "the level of significance alpha is the maximum probability of a type one error, zero point zero five"},
      {"chunk_id": 4, "start_time": 2170.0, "end_time": 2180.0,
       "text": "if z falls in the rejection region in the two tails we reject h naught the critical values"}]


def qa(raw, known=()):
    flags, stats = [], Counter()
    return sn.validate(raw, QA, flags, stats, list(known), False), flags, stats


def test_notation_and_numbers_match_what_speech_recognition_wrote():
    el, flags, _ = qa({"kind": "para", "lead": "Hypotheses for the wafers",
                       "text": "The company claims a mean net weight of 454 g. H₀: μ = 454 g, while the alternative "
                               "hypothesis H₁ is μ ≠ 454 g.",
                       "quote": "the mean netweight is four hundred and fifty four grams"})
    assert el is not None and len(el["sentences"]) == 2, flags


def test_type_i_and_type_ii_are_different_sentences_not_repeats():
    el, flags, _ = qa({"kind": "para", "lead": "Errors",
                       "text": "A type I error is rejecting H₀ when it is true. A type II error is failing to reject H₀.",
                       "quote": "a type one error is rejecting h naught when it is true"})
    assert len(el["sentences"]) == 2 and not any(f.startswith("repeat") for f in flags)


def test_a_data_number_that_was_never_said_removes_its_sentence():
    el, flags, stats = qa({"kind": "para", "lead": "Wafers",
                           "text": "The company claims a mean net weight of 454 g. In the alternate hypothesis the "
                                   "mean weight is 449.5 grams.",
                           "quote": "the mean netweight is four hundred and fifty four grams"})
    assert el is None or el["sentences"] == ["The company claims a mean net weight of 454 g."]
    assert stats["sentences_number_unsaid"] == 1 and any(f.startswith("number_unsaid(449.5)") for f in flags)
    el, _, stats = qa({"kind": "para", "text": "The significance level alpha is 0.05.",
                       "quote": "the level of significance alpha is the maximum probability"})
    assert el is not None and stats["sentences_number_unsaid"] == 0          # "zero point zero five"


def test_definitions_in_the_shapes_notes_really_use_enter_the_glossary():
    el, flags, _ = qa({"kind": "para", "lead": "Errors and significance",
                       "text": "A type I error occurs when we reject H₀ while it is true. The level of significance "
                               "(α) is the maximum probability of a type I error.",
                       "terms": ["type I error", "level of significance", "alternative hypothesis"],
                       "quote": "a type one error is rejecting h naught when it is true"})
    assert [t["term"] for t in el["terms"]] == ["type I error", "level of significance"], flags
    assert "term_dropped_no_definition:'alternative hypothesis'" in flags     # said, but not explained here
    el, flags, _ = qa({"kind": "para", "lead": "Rejection region",
                       "text": "Reject H₀ when the test statistic z falls in the two tails beyond the critical values.",
                       "terms": ["rejection region", "z", "μ₀"],
                       "quote": "if z falls in the rejection region in the two tails"})
    assert el["terms"] == [{"term": "rejection region", "definition": el["sentences"][0]}]
    assert "term_dropped_symbol:'z'" in flags and "term_dropped_symbol:'μ₀'" in flags


def test_remember_needs_the_lecturer_to_stress_it():
    el, _, stats = check({"kind": "remember", "text": "A computer only does what you tell it.",
                          "quote": "a computer only does what you tell it"})
    assert el["kind"] == "remember" and stats["remember_verified"] == 1
    el, flags, stats = check({"kind": "remember", "text": "A computer performs a billion calculations per second.",
                              "quote": "It performs calculations, a billion calculations per second"})
    assert el["kind"] == "para" and stats["remember_demoted"] == 1   # the content stays, the claim of emphasis goes


def test_logistics_never_become_notes():
    el, flags, _ = check({"kind": "para", "text": "This lecture will be recorded for OCW.",
                          "quote": "A computer does two things"})
    assert el is None and any(f.startswith("logistics_paragraph") for f in flags)


def test_examples_code_steps_and_tables_are_checked_like_sentences():
    el, _, _ = check({"kind": "example", "title": "Picking a random responder",
                      "text": "random.randint(16, 272) chose 75.", "code": "import random\nrandom.randint(16, 272)",
                      "quote": "import random and use the rand int function"})
    assert el["kind"] == "example" and el["code"].startswith("import random") and el["t"] == 40.0
    el, flags, _ = check({"kind": "code", "caption": "Sorting", "code": "sorted(items, key=lambda x: x.price)",
                          "quote": "import random and use the rand int function"})
    assert el is None and any(f.startswith("code_unsupported") for f in flags)
    el, flags, _ = check({"kind": "table", "caption": "Two kinds of knowledge", "columns": ["Kind", "What it is"],
                          "rows": [["Declarative", "statements of fact"], ["Imperative", "a recipe or how-to"],
                                   ["Procedural", "compiled bytecode caches"]],
                          "quote": "Declarative knowledge is statements of fact"})
    assert [r[0] for r in el["rows"]] == ["Declarative", "Imperative"]
    el, flags, _ = check({"kind": "steps", "lead": "Steps", "items": ["import random"],
                          "quote": "import random and use the rand int function"})
    assert el is None and "steps_too_short" in flags


def test_continuations_fold_into_the_paragraph_they_extend():
    drafts: list[dict] = []
    first = {"id": "u0e0", "extends": None, "kind": "para", "t": 0.0, "said": "", "lead": "Computers",
             "sentences": ["A computer calculates."], "terms": [], "background": None}
    more = {"id": "u1e0", "extends": "u0e0", "kind": "para", "t": 90.0, "said": "", "lead": "",
            "sentences": ["It remembers results."], "terms": [{"term": "memory", "definition": "x"}], "background": None}
    sn.fold_draft(drafts, first, 0)
    sn.fold_draft(drafts, more, 1)
    assert len(drafts) == 1 and drafts[0]["sentences"] == ["A computer calculates.", "It remembers results."]
    assert drafts[0]["sentence_k"] == [0, 1] and drafts[0]["terms"][0]["term"] == "memory"
    assert "sentence_k" not in sn.published(drafts[0]) and "id" not in sn.published(drafts[0])


def test_spoken_order_keeps_an_example_with_its_idea():
    els = [{"kind": "para", "t": 30.0}, {"kind": "example", "t": 45.0}, {"kind": "para", "t": 0.0}]
    assert [e["t"] for e in sn.in_spoken_order(els)] == [0.0, 30.0, 45.0]
