import pytest

import korean_anki.sync as sync


class FakeAnkiConnect:
    """Records calls and answers the subset of AnkiConnect actions run_sync uses."""

    def __init__(self, notes_info=None):
        self.notes_info = notes_info or {}
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, action, **params):
        self.calls.append((action, params))
        if action == "notesInfo":
            return [self.notes_info[n] for n in params["notes"] if n in self.notes_info]
        if action in ("updateNoteFields", "addNote", "deleteNotes", "sync"):
            return None
        raise AssertionError(f"unexpected AnkiConnect action in test: {action}")

    def calls_for(self, action):
        return [params for a, params in self.calls if a == action]


def note_info(note_id: int, korean: str, back: str | None = None) -> dict:
    fields = {"Korean": {"value": korean, "order": 0}}
    if back is not None:
        fields["Back"] = {"value": back, "order": 1}
    return {"noteId": note_id, "fields": fields}


def word(korean_back: str, deck_type: str, note_id: int) -> dict:
    return {
        "back": korean_back,
        "deck_type": deck_type,
        "date_added": "2026-01-01",
        "anki_note_id": note_id,
        "synced_at": None,
        "pending_delete": 0,
    }


@pytest.fixture
def sync_env(monkeypatch):
    monkeypatch.setattr(sync, "check_ankiconnect", lambda fail_hard=True: True)
    monkeypatch.setattr(sync, "ensure_deck_and_model", lambda *a, **k: None)
    saved: dict[str, dict] = {}
    monkeypatch.setattr(sync, "save_words", lambda words: saved.update(words=dict(words)))
    return saved


def _make_interactive(monkeypatch, answer: bool):
    monkeypatch.setattr(sync.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sync, "prompt_yes_no", lambda *a, **k: answer)


def test_front_edit_accepted_renames_word_in_db(monkeypatch, sync_env):
    words = {"안뇽": word("hi", "vocab", 111)}
    monkeypatch.setattr(sync, "load_words", lambda: words)
    fake = FakeAnkiConnect(notes_info={111: note_info(111, "안녕", "hi")})
    monkeypatch.setattr(sync, "anki_connect", fake)
    _make_interactive(monkeypatch, answer=True)

    ok = sync.run_sync(no_ankiweb_sync=True, no_interactive=False, fail_hard=False)

    assert ok is True
    assert "안녕" in sync_env["words"]
    assert "안뇽" not in sync_env["words"]
    assert sync_env["words"]["안녕"]["anki_note_id"] == 111
    assert sync_env["words"]["안녕"]["back"] == "hi"


def test_front_edit_declined_keeps_db_value_and_pushes_it_back(monkeypatch, sync_env):
    words = {"안뇽": word("hi", "vocab", 111)}
    monkeypatch.setattr(sync, "load_words", lambda: words)
    fake = FakeAnkiConnect(notes_info={111: note_info(111, "안녕", "hi")})
    monkeypatch.setattr(sync, "anki_connect", fake)
    _make_interactive(monkeypatch, answer=False)

    ok = sync.run_sync(no_ankiweb_sync=True, no_interactive=False, fail_hard=False)

    assert ok is True
    assert "안뇽" in sync_env["words"]
    assert "안녕" not in sync_env["words"]
    updates = fake.calls_for("updateNoteFields")
    assert any(u["note"]["fields"]["Korean"] == "안뇽" for u in updates)


def test_front_edit_non_interactive_is_reported_as_conflict(monkeypatch, sync_env):
    words = {"안뇽": word("hi", "vocab", 111)}
    monkeypatch.setattr(sync, "load_words", lambda: words)
    fake = FakeAnkiConnect(notes_info={111: note_info(111, "안녕", "hi")})
    monkeypatch.setattr(sync, "anki_connect", fake)

    ok = sync.run_sync(no_ankiweb_sync=True, no_interactive=True, fail_hard=False)

    assert ok is False
    assert "안뇽" in sync_env["words"]
    assert not fake.calls_for("updateNoteFields")


def test_front_edit_colliding_with_existing_word_is_rejected(monkeypatch, sync_env):
    words = {
        "안뇽": word("hi", "vocab", 111),
        "안녕": word("hello", "vocab", 222),
    }
    monkeypatch.setattr(sync, "load_words", lambda: words)
    fake = FakeAnkiConnect(
        notes_info={
            111: note_info(111, "안녕", "hi"),  # edited to collide with the other word
            222: note_info(222, "안녕", "hello"),
        }
    )
    monkeypatch.setattr(sync, "anki_connect", fake)
    _make_interactive(monkeypatch, answer=True)

    ok = sync.run_sync(no_ankiweb_sync=True, no_interactive=False, fail_hard=False)

    assert ok is True
    assert set(sync_env["words"]) == {"안뇽", "안녕"}
    assert sync_env["words"]["안뇽"]["anki_note_id"] == 111
    assert sync_env["words"]["안녕"]["anki_note_id"] == 222


def test_front_edit_to_empty_string_is_rejected(monkeypatch, sync_env):
    words = {"안뇽": word("hi", "vocab", 111)}
    monkeypatch.setattr(sync, "load_words", lambda: words)
    fake = FakeAnkiConnect(notes_info={111: note_info(111, "", "hi")})
    monkeypatch.setattr(sync, "anki_connect", fake)
    _make_interactive(monkeypatch, answer=True)

    ok = sync.run_sync(no_ankiweb_sync=True, no_interactive=False, fail_hard=False)

    assert ok is True
    assert set(sync_env["words"]) == {"안뇽"}


def test_forked_note_type_aborts_sync_before_any_write(monkeypatch, sync_env):
    """ensure_deck_and_model's fork guard must stop the run, not crash it."""
    words = {"안녕": word("hi", "vocab", 111)}
    monkeypatch.setattr(sync, "load_words", lambda: words)
    fake = FakeAnkiConnect(notes_info={111: note_info(111, "안녕", "hi")})
    monkeypatch.setattr(sync, "anki_connect", fake)

    def boom(*a, **k):
        raise sync.AnkiConnectError('Anki has both "X" and "X+" note types.')

    monkeypatch.setattr(sync, "ensure_deck_and_model", boom)

    assert sync.run_sync(no_ankiweb_sync=True, no_interactive=True, fail_hard=False) is False
    assert fake.calls_for("updateNoteFields") == []
    assert fake.calls_for("addNote") == []


def test_front_field_html_noise_is_not_a_conflict(monkeypatch, sync_env):
    """Anki stores field HTML; whitespace/markup in Korean isn't a front-field edit."""
    words = {"학식": word("학생식당", "vocab", 111)}
    monkeypatch.setattr(sync, "load_words", lambda: words)
    fake = FakeAnkiConnect(notes_info={111: note_info(111, "\n학식", "학생식당")})
    monkeypatch.setattr(sync, "anki_connect", fake)

    assert sync.run_sync(no_ankiweb_sync=True, no_interactive=True, fail_hard=False) is True
    pushed = fake.calls_for("updateNoteFields")
    assert len(pushed) == 1
    # the normalized value is pushed back, healing the stored field
    assert pushed[0]["note"]["fields"]["Korean"] == "학식"
    assert sync_env["words"]["학식"]["anki_note_id"] == 111
