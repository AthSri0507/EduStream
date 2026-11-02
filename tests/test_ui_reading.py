"""UI stages 3-4 (docs/UI_DESIGN.md): sentence-case titles, glossary terms that open their definition, the glossary at
the end, In class newest first with Earlier notes, and "While you were away" from the browser's away/back times."""

import pytest

from dashboard import live_panel
from dashboard import notebook_html as nbh
from dashboard import notebook_page

GLOSS = [("null hypothesis", "The claim of no effect, H₀."), ("critical value", "The edge of the rejection region.")]


@pytest.mark.parametrize("title, shown", [
    ("Hypothesis Statements and Decision Rule", "Hypothesis statements and decision rule"),
    ("Type I and Type II Errors", "Type I and type II errors"),
    ("Z‑score and Two‑Sided Rejection Rule", "Z‑score and two‑sided rejection rule"),
    ("IQ Test Using ANOVA", "IQ test using ANOVA"),
    ("Sampling Distribution Under H₀", "Sampling distribution under H₀"),
    ("Being a machine: following a recipe", "Being a machine: following a recipe"),   # already sentence case
    ("t-test for unknown σ", "t-test for unknown σ"),
])
def test_titles_are_shown_in_sentence_case(title, shown):
    assert nbh.sentence_case(title) == shown
    assert nbh.topic_label({"n": 1, "title": title, "start": 0.0, "end": 60.0}).startswith(f"1. {shown}")


def para(text, t=10.0, terms=()):
    return {"kind": "para", "t": t, "said": "", "lead": "", "sentences": [text],
            "terms": [{"term": x, "definition": "d"} for x in terms]}


def test_the_first_mention_of_a_glossary_term_opens_its_definition():
    topic = {"n": 1, "title": "T", "start": 0.0, "end": 60.0, "elements": [
        para("We test the null hypothesis against the data."),
        para("Again the null hypothesis, and the critical value 1.96.", t=20.0)]}
    html = nbh.topic_html(topic, gloss=GLOSS)
    assert html.count('class="gt"') == 2                       # each term once per topic
    assert '<b>null hypothesis</b>: The claim of no effect, H₀.' in html and 'role="tooltip"' in html
    own = {"n": 2, "title": "T", "start": 0.0, "end": 60.0,
           "elements": [para("The null hypothesis is the claim of no effect.", terms=["null hypothesis"])]}
    assert 'class="gt"' not in nbh.topic_html(own, gloss=GLOSS)   # defined right there: bold, no pop-up
    evil = [("<b>", "<script>x</script>")]
    assert "<script>" not in nbh.topic_html({**topic, "elements": [para("a &lt;b&gt; tag")]}, gloss=evil)


def test_in_class_shows_earlier_topics_in_one_fold_and_the_glossary_at_the_end():
    topics = [{"n": i, "title": f"Topic Number {i}", "start": i * 60.0, "end": i * 60.0 + 60, "elements": [para("x")]}
              for i in (1, 2)]
    html = nbh.earlier_html(topics)
    assert html.index("1. Topic number 1") < html.index("2. Topic number 2")
    end = nbh.glossary_end_html({"glossary": [{"term": "alpha", "definition": "the significance level"}]})
    assert "<dt>alpha</dt><dd>the significance level</dd>" in end
    live = nbh.live_html({"drafts": [], "latest_k": None, "since": 0.0, "now_text": "", "status": "",
                          "glossary": []}, board=True)
    assert 'class="live board"' in live                        # larger live lines on In class


@pytest.mark.parametrize("away, said, now, span", [
    (None, 900.0, 1_000_000, None),
    ({"left_ms": 1_000_000, "back_ms": 1_010_000}, 900.0, 1_010_000, None),           # 10 s: a glance
    ({"left_ms": 1_000_000, "back_ms": 1_120_000}, 900.0, 1_120_000, (780.0, 900.0)),  # 2 min away
    ({"left_ms": 1_000_000, "back_ms": 1_120_000}, 930.0, 1_150_000, (780.0, 900.0)),  # seen 30 s after coming back
])
def test_while_you_were_away_maps_the_gap_onto_lecture_time(away, said, now, span):
    assert notebook_page.away_span(away, said, now) == span


def test_away_strip_lists_what_was_added_and_is_labelled():
    html = nbh.away_html([para("first", t=790.0), para("second", t=850.0)], 780.0, 900.0)
    assert "While you were away (13:00–15:00)" in html and html.index("first") < html.index("second")
    assert "still being written" in nbh.away_html([], 780.0, 900.0)


def test_sound_level_bar():
    assert live_panel.sound_level(-80) == 0.0 and live_panel.sound_level(-35) == 0.5 and live_panel.sound_level(0) == 1.0


def test_the_longer_term_wins_and_no_match_inside_a_definition_box():
    # Live run 31 Oct: "hypothesis" was linked inside "null hypothesis".
    gloss = [("hypothesis", "A statement about a population parameter."), ("null hypothesis", "The default claim.")]
    topic = {"n": 1, "title": "T", "start": 0.0, "end": 60.0,
             "elements": [para("We reject the null hypothesis; a hypothesis is tested.")]}
    html = nbh.topic_html(topic, gloss=gloss)
    assert '<span class="gt" tabindex="0">null hypothesis<span' in html
    assert html.count('class="gt"') == 2 and '; a <span class="gt" tabindex="0">hypothesis<span' in html


def test_control_characters_from_model_text_are_dropped():
    # Live run 31 Oct: "\bar X" in a model's JSON became backspace + "ar X", drawn as a box.
    assert "\x08" not in nbh.e("Z=(\x08ar X-mu)/sigma") and nbh.e("a\x08b") == "ab"
