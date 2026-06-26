# korean-anki

A command-line tool to build and maintain an Anki deck from your Korean lesson chat exports. After each lesson, paste the chat into a text file, run one command to extract new vocabulary, then build and import into Anki.

Words are stored in a local SQLite database. Each `build` regenerates the `.apkg` with all accumulated vocabulary, so importing into Anki is always an update, never a duplicate.

## Requirements

- [uv](https://docs.astral.sh/uv/) — dependencies are managed via `pyproject.toml`, no manual setup needed.

## Workflow

```
# After each lesson:
uv run anki_korean.py parse lesson2.txt   # extract new words from chat export
uv run anki_korean.py build               # regenerate korean_deck.apkg
# → Import korean_deck.apkg into Anki
#   File → Import → "Update existing notes when first field matches"
```

## Supported word formats

The parser handles the formats your tutor typically uses. Any line without Korean characters (timestamps, names, image markers) is automatically ignored.

| Chat line | Cards created |
|---|---|
| `워라밸 = 워킹 라이프 밸런스 = working life balance` | 1 vocab card: front=워라밸, back=워킹 라이프 밸런스 / working life balance |
| `야근 overwork` | 1 vocab card: front=야근, back=overwork |
| `사랑 = love` | 1 vocab card: front=사랑, back=love |
| `칼퇴 = 칼같이 퇴근한다` | 1 vocab card (slang): front=칼퇴, back=칼같이 퇴근한다 |
| `몇몋 사람, 어떤 사람 some people` | 2 vocab cards sharing the same English meaning |
| `사랑 → love` or `love → 사랑` | 1 vocab card: front=사랑, back=love |
| `이야기` (Korean only, no translation) | 1 reference card (front only) |

## Anki decks

Two decks are created in a single `.apkg` file:

- **Korean - Vocabulary** — standard cards with a Korean front and meaning/expansion on the back.
- **Korean - Reference** — cards with only a Korean front. Used for sentences or slang with no direct translation, for passive exposure during review.

## Commands

### `parse` — extract words from a chat export

```
uv run anki_korean.py parse <file>
```

Reads a chat log, extracts all recognizable vocabulary, and adds new words to the local database. Already-known words are silently skipped.

```
uv run anki_korean.py parse lesson3.txt
```

---

### `build` — generate the Anki deck

```
uv run anki_korean.py build
```

Generates `korean_deck.apkg` from all words in the local database. Import this file into Anki after every session.

---

### `add` — manually add a word

```
uv run anki_korean.py add "korean=english" [...]
```

Accepts the same formats as the parser.

```
uv run anki_korean.py add "수고하다=to work hard" "눈치=social awareness"
```

---

### `list` — review your vocabulary

```
uv run anki_korean.py list [--search QUERY] [--deck vocab|reference]
```

```
uv run anki_korean.py list
uv run anki_korean.py list --search 사람
uv run anki_korean.py list --deck reference
```

---

### `remove` — delete a word

```
uv run anki_korean.py remove "korean" [...]
```

```
uv run anki_korean.py remove "이야기"
```
