import pytest

from korean_anki.parsing import (
    has_latin,
    is_korean,
    parse_line,
    split_at_english,
    split_at_korean,
)


@pytest.mark.parametrize("text, expected", [
    ("사람", True),
    ("hello", False),
    ("123!?", False),
    ("hello 사람", True),
])
def test_is_korean(text, expected):
    assert is_korean(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("hello", True),
    ("사람", False),
    ("123", False),
    ("사람s", True),
])
def test_has_latin(text, expected):
    assert has_latin(text) == expected


def test_split_at_english_finds_first_latin_word():
    assert split_at_english("야근 overwork") == ("야근", "overwork")


def test_split_at_english_no_latin_word_returns_whole_text():
    assert split_at_english("이야기") == ("이야기", None)


def test_split_at_korean_finds_first_korean_word():
    assert split_at_korean("some people 어떤 사람") == ("어떤 사람", "some people")


def test_split_at_korean_no_korean_word_returns_whole_text():
    assert split_at_korean("hello world") == ("hello world", None)


@pytest.mark.parametrize("line, expected", [
    (
        "워라밸 = 워킹 라이프 밸런스 = working life balance",
        [("워라밸", "워킹 라이프 밸런스\nworking life balance", "vocab")],
    ),
    ("야근 overwork", [("야근", "overwork", "vocab")]),
    ("사랑 = love", [("사랑", "love", "vocab")]),
    (
        "몇몇 사람, 어떤 사람 some people",
        [("몇몇 사람", "some people", "vocab"), ("어떤 사람", "some people", "vocab")],
    ),
    ("사랑 → love", [("사랑", "love", "vocab")]),
    ("love → 사랑", [("사랑", "love", "vocab")]),
    ("이야기", [("이야기", "", "reference")]),
    ("10:32 AM Seoyeon", []),
    ("이야기, 사람", [("이야기", "", "reference"), ("사람", "", "reference")]),
    ("→ 사랑", []),
])
def test_parse_line(line, expected):
    assert parse_line(line) == expected
