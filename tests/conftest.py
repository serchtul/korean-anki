import pytest

import korean_anki.storage as storage


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_FILE", tmp_path / "test_words.db")
