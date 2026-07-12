from korean_anki.config import REF_DECK_NAME, VOCAB_DECK_NAME
from korean_anki.sync import (
    back_field_conflicts,
    deck_model_for,
    escape_anki_query_value,
    fields_for,
    html_to_text,
)


def test_html_to_text_converts_br_and_div_to_newlines():
    assert html_to_text("line1<br>line2") == "line1\nline2"


def test_html_to_text_unescapes_entities():
    assert html_to_text("A &amp; B") == "A & B"


def test_html_to_text_strips_leading_and_trailing_blank_lines():
    assert html_to_text("<br><br>hello<br><br>") == "hello"


def test_escape_anki_query_value_escapes_double_quotes():
    assert escape_anki_query_value('say "hi"') == 'say \\"hi\\"'


def test_deck_model_for_vocab():
    assert deck_model_for("vocab") == (VOCAB_DECK_NAME, "Korean Vocabulary")


def test_deck_model_for_reference():
    assert deck_model_for("reference") == (REF_DECK_NAME, "Korean Reference")


def test_fields_for_vocab_includes_back():
    data = {"deck_type": "vocab", "back": "meaning", "date_added": "2026-01-01"}
    assert fields_for("단어", data) == {
        "Korean": "단어",
        "Back": "meaning",
        "DateAdded": "2026-01-01",
    }


def test_fields_for_reference_omits_back():
    data = {"deck_type": "reference", "back": "", "date_added": "2026-01-01"}
    assert fields_for("단어", data) == {"Korean": "단어", "DateAdded": "2026-01-01"}


def test_back_field_conflicts_true_when_vocab_back_differs():
    data = {"deck_type": "vocab", "back": "old meaning"}
    assert back_field_conflicts(data, "new meaning") is True


def test_back_field_conflicts_false_when_back_matches():
    data = {"deck_type": "vocab", "back": "same"}
    assert back_field_conflicts(data, "same") is False


def test_back_field_conflicts_false_for_reference_type():
    data = {"deck_type": "reference", "back": ""}
    assert back_field_conflicts(data, "anything") is False
