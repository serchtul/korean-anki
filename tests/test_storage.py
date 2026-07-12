import pytest

from korean_anki.storage import active_words, load_words, save_words, stable_guid


@pytest.mark.usefixtures("isolated_db")
def test_save_and_load_round_trip():
    words = {
        "사랑": {
            "back": "love",
            "deck_type": "vocab",
            "date_added": "2026-01-01",
            "anki_note_id": None,
            "synced_at": None,
            "pending_delete": 0,
        }
    }
    save_words(words)
    assert load_words() == words


@pytest.mark.usefixtures("isolated_db")
def test_save_and_load_round_trip_with_synced_fields():
    words = {
        "이야기": {
            "back": "",
            "deck_type": "reference",
            "date_added": "2026-01-01",
            "anki_note_id": 12345,
            "synced_at": "2026-01-02T10:00:00",
            "pending_delete": 1,
        }
    }
    save_words(words)
    assert load_words() == words


@pytest.mark.usefixtures("isolated_db")
def test_load_words_on_fresh_db_is_empty():
    assert load_words() == {}


@pytest.mark.usefixtures("isolated_db")
def test_ensure_schema_is_idempotent_across_calls():
    assert load_words() == {}
    assert load_words() == {}
    save_words({})
    assert load_words() == {}


def test_active_words_filters_pending_delete():
    words = {
        "a": {"pending_delete": 0},
        "b": {"pending_delete": 1},
        "c": {},
    }
    assert active_words(words) == {"a": {"pending_delete": 0}, "c": {}}


def test_stable_guid_is_deterministic():
    assert stable_guid("사랑") == stable_guid("사랑")


def test_stable_guid_differs_for_different_input():
    assert stable_guid("사랑") != stable_guid("이야기")


def test_stable_guid_is_within_expected_range():
    guid = stable_guid("사랑")
    assert 0 <= guid < 10 ** 10
