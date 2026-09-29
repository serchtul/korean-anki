import pytest

import korean_anki.ankiconnect as ankiconnect
from korean_anki.ankiconnect import AnkiConnectError, ensure_deck_and_model
from korean_anki.models import vocab_model


class FakeAnkiConnect:
    """Answers the subset of actions ensure_deck_and_model uses."""

    def __init__(self, decks, models, templates=None):
        self.decks = decks
        self.models = models
        self.templates = templates or {}
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, action, **params):
        self.calls.append((action, params))
        if action == "deckNames":
            return self.decks
        if action == "modelNames":
            return self.models
        if action == "modelTemplates":
            return self.templates
        if action in ("createDeck", "createModel", "modelTemplateAdd"):
            return None
        raise AssertionError(f"unexpected AnkiConnect action in test: {action}")

    def actions(self):
        return [a for a, _ in self.calls]


@pytest.fixture
def fake(monkeypatch):
    def install(decks, models, templates=None):
        f = FakeAnkiConnect(decks, models, templates)
        monkeypatch.setattr(ankiconnect, "anki_connect", f)
        return f

    return install


def test_forked_note_type_raises_before_touching_templates(fake):
    f = fake(["Korean - Vocabulary"], ["Korean Vocabulary", "Korean Vocabulary+"])
    with pytest.raises(AnkiConnectError) as exc:
        ensure_deck_and_model("Korean - Vocabulary", "Korean Vocabulary", vocab_model)
    assert "Korean Vocabulary+" in str(exc.value)
    assert "modelTemplateAdd" not in f.actions()
    assert "modelTemplates" not in f.actions()


def test_missing_model_is_created_with_all_templates(fake):
    f = fake(["Korean - Vocabulary"], [])
    ensure_deck_and_model("Korean - Vocabulary", "Korean Vocabulary", vocab_model)
    created = [p for a, p in f.calls if a == "createModel"]
    assert len(created) == 1
    assert [t["Name"] for t in created[0]["cardTemplates"]] == [
        "Korean → Meaning",
        "Meaning → Korean",
    ]
    assert "modelTemplateAdd" not in f.actions()


def test_missing_deck_is_created(fake):
    f = fake([], ["Korean Vocabulary"], {"Korean → Meaning": {}, "Meaning → Korean": {}})
    ensure_deck_and_model("Korean - Vocabulary", "Korean Vocabulary", vocab_model)
    assert [p for a, p in f.calls if a == "createDeck"] == [{"deck": "Korean - Vocabulary"}]


def test_existing_model_backfills_only_missing_templates(fake):
    f = fake(["Korean - Vocabulary"], ["Korean Vocabulary"], {"Korean → Meaning": {}})
    ensure_deck_and_model("Korean - Vocabulary", "Korean Vocabulary", vocab_model)
    added = [p["template"]["Name"] for a, p in f.calls if a == "modelTemplateAdd"]
    assert added == ["Meaning → Korean"]


def test_existing_model_with_all_templates_is_a_noop(fake):
    f = fake(
        ["Korean - Vocabulary"],
        ["Korean Vocabulary"],
        {"Korean → Meaning": {}, "Meaning → Korean": {}},
    )
    ensure_deck_and_model("Korean - Vocabulary", "Korean Vocabulary", vocab_model)
    assert "modelTemplateAdd" not in f.actions()
    assert "createModel" not in f.actions()
