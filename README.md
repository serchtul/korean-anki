# korean-anki

A command-line tool to build and maintain an Anki deck from your Korean lesson chat exports. After each lesson, paste the chat into a text file, run one command to extract new vocabulary, and it's synced straight into your Anki collection (and from there, AnkiWeb).

Words are stored in a local SQLite database, which is always the source of truth for word content and existence.

## Requirements

- [uv](https://docs.astral.sh/uv/) — dependencies are managed via `pyproject.toml`, no manual setup needed.
- For `sync` (and `parse`'s auto-sync): [Anki desktop](https://apps.ankiweb.net/) open, with the [AnkiConnect](https://ankiweb.net/shared/info/2055492159) add-on installed (Tools → Add-ons → Get Add-ons... → code `2055492159`, then restart Anki).

## Workflow

```
# After each lesson:
uv run anki_korean.py parse lesson2.txt   # extract new words, then auto-sync into Anki + AnkiWeb
```

`parse` pushes new words directly into a running Anki desktop via AnkiConnect and triggers an AnkiWeb sync — no manual import needed day-to-day. If Anki isn't open when you run `parse`, the words are still saved locally; sync just gets skipped with a message, and you can push them later with `uv run anki_korean.py sync`.

### Fallback: building an `.apkg` for manual import

If you'd rather not use AnkiConnect (e.g. setting things up for the first time, or on a machine without Anki installed), `build` still works exactly as before:

```
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

Two decks are used, whether built as an `.apkg` or pushed live via `sync`:

- **Korean - Vocabulary** — standard cards with a Korean front and meaning/expansion on the back.
- **Korean - Reference** — cards with only a Korean front. Used for sentences or slang with no direct translation, for passive exposure during review.

## Commands

### `parse` — extract words from a chat export, then auto-sync

```
uv run anki_korean.py parse <file> [--no-sync] [--no-ankiweb-sync]
```

Reads a chat log, extracts all recognizable vocabulary, and adds new words to the local database. Already-known words are silently skipped. If any new words were added, it then runs the same push-to-Anki flow as `sync` (see below) — unless:

- `--no-sync` — only parse and save locally; don't touch Anki at all.
- `--no-ankiweb-sync` — push the new words into local Anki, but don't trigger the AnkiWeb sync step.

A failed auto-sync (Anki not open, AnkiConnect not installed, etc.) never fails the `parse` command itself — the words are already safely saved in the local database, and you'll see a message telling you to run `sync` manually later.

```
uv run anki_korean.py parse lesson3.txt
uv run anki_korean.py parse lesson3.txt --no-sync
```

---

### `sync` — push words directly into a running Anki, then AnkiWeb

```
uv run anki_korean.py sync [--no-ankiweb-sync] [--no-interactive]
```

Pushes every word in the local database into a live Anki collection via [AnkiConnect](https://ankiweb.net/shared/info/2055492159), creating the two decks/note types if they don't exist yet, then triggers Anki's own AnkiWeb sync so your account gets the update too. No AnkiWeb credentials are ever handled by this script — it just asks the already-running, already-logged-in Anki desktop app to do its normal sync.

**Requires Anki desktop to be open with the AnkiConnect add-on installed.** If it can't reach `http://127.0.0.1:8765`, you'll get a clear message telling you to open Anki / install the add-on, rather than a raw connection error.

Flags:
- `--no-ankiweb-sync` — push into local Anki only; skip the final AnkiWeb sync trigger.
- `--no-interactive` — never prompt on conflicts (see below); fail instead with a list of the words that need manual resolution. This is also auto-detected whenever `sync` isn't run from an interactive terminal (e.g. piped output, cron).

**Note:** `sync` only reports that the AnkiWeb sync was *requested* through AnkiConnect, not that it *completed* — that part is fire-and-forget on Anki's side. If it seems like nothing showed up on your other devices, check that you're logged into AnkiWeb in Anki desktop.

#### Assumptions and conflict handling

This tool treats `words.db` as the source of truth for which words exist and what their Korean (front) field says. It does **not** assume it's the only thing ever touching your Anki collection, so it has explicit, deliberate rules for what happens when the two sides disagree:

- **Deleting a word (`remove`) is a soft delete.** The word is marked for deletion locally, not wiped immediately — it's removed from Anki (and only then dropped from `words.db`) the *next* time you run `sync`. This gives you a window to notice a mistaken `remove` before it becomes permanent. Use `list --deleted` to see what's queued.
- **A card deleted directly in Anki is mirrored back, not resurrected.** If `sync` finds that a note it previously created no longer exists in Anki, it assumes that was deliberate — it marks the word for deletion in `words.db` too (flushed on the next sync) and always prints a log line about it. It will not silently recreate a card you deleted in Anki.
- **The Korean/front field is assumed to never be edited directly in Anki** — only the meaning/`Back` field is expected to change there. (`words.db` keys each word by its Korean text, so a front-field rename in Anki can't be reconciled automatically.) If `sync` detects the Korean field in Anki doesn't match what's in `words.db`, it prints a warning and skips that word rather than guessing what you meant.
- **A changed `Back` field in Anki triggers an interactive conflict prompt**, not a silent overwrite in either direction. `sync` does a best-effort conversion of Anki's stored HTML back to plain text, and if it differs from the database's stored value, you'll see:
  ```
  Conflict for 워라밸:
    DB value:   'working life balance'
    Anki value: 'work-life balance'
  Adopt Anki's edit for 워라밸? [Y/n]
  ```
  Press Enter or `y` to adopt the Anki edit into `words.db`. Type `n` to keep the database's value and overwrite the Anki card with it instead. With `--no-interactive` (or when not running in a terminal), conflicts are never auto-resolved — `sync` reports them and exits with an error, leaving both sides untouched until you resolve it interactively.

---

### `build` — generate an `.apkg` for manual import

```
uv run anki_korean.py build
```

Generates `korean_deck.apkg` from all (non-deleted) words in the local database. This is the original, Anki-desktop-independent workflow — useful for a first-time setup or a machine without Anki/AnkiConnect available. Kept unchanged alongside `sync`.

---

### `add` — manually add a word

```
uv run anki_korean.py add "korean=english" [...]
```

Accepts the same formats as the parser. Does not auto-sync — run `sync` afterward if you want it pushed to Anki right away.

```
uv run anki_korean.py add "수고하다=to work hard" "눈치=social awareness"
```

---

### `list` — review your vocabulary

```
uv run anki_korean.py list [--search QUERY] [--deck vocab|reference] [--deleted]
```

```
uv run anki_korean.py list
uv run anki_korean.py list --search 사람
uv run anki_korean.py list --deck reference
uv run anki_korean.py list --deleted   # words queued for deletion, not yet flushed by sync
```

---

### `remove` — delete a word

```
uv run anki_korean.py remove "korean" [...]
```

Marks the word for deletion — it's removed from Anki and the local database the next time you run `sync`.

```
uv run anki_korean.py remove "이야기"
```
