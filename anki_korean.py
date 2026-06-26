#!/usr/bin/env -S uv run
"""
korean-anki: manage a Korean vocabulary Anki deck from the command line.

Usage:
  uv run anki_korean.py parse lesson.txt   # parse a chat export
  uv run anki_korean.py add "야근=overwork" # manually add a word
  uv run anki_korean.py build              # generate korean_deck.apkg
  uv run anki_korean.py list               # show all words
  uv run anki_korean.py list --search 사람
  uv run anki_korean.py list --deck reference
  uv run anki_korean.py remove "이야기"
"""

import argparse
import hashlib
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

try:
    import genanki
except ImportError:
    print("Run with: uv run anki_korean.py")
    sys.exit(1)

HERE = Path(__file__).parent
DB_FILE = HERE / "words.db"
OUTPUT_FILE = HERE / "korean_deck.apkg"

VOCAB_DECK_ID    = 1_953_742_187
VOCAB_MODEL_ID   = 1_607_392_319
REF_DECK_ID      = 1_953_742_188
REF_MODEL_ID     = 1_607_392_320

# ── Anki models ───────────────────────────────────────────────────────────────

CARD_CSS = """
.card {
    font-family: 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif;
    text-align: center;
    color: #1a1a1a;
    background: #fafafa;
    padding: 24px;
}
.korean  { font-size: 44px; font-weight: bold; color: #1a237e; }
.back    { font-size: 26px; color: #333; margin-top: 14px; white-space: pre-line; }
.label   { font-size: 11px; color: #aaa; margin-top: 18px; letter-spacing: 1px; text-transform: uppercase; }
hr       { border: none; border-top: 1px solid #e0e0e0; margin: 16px 0; }
"""

vocab_model = genanki.Model(
    VOCAB_MODEL_ID,
    "Korean Vocabulary",
    fields=[{"name": "Korean"}, {"name": "Back"}, {"name": "DateAdded"}],
    templates=[
        {
            "name": "Korean → Meaning",
            "qfmt": "<div class='korean'>{{Korean}}</div>",
            "afmt": "<div class='korean'>{{Korean}}</div><hr><div class='back'>{{Back}}</div><div class='label'>{{DateAdded}}</div>",
        },
        {
            "name": "Meaning → Korean",
            "qfmt": "<div class='back'>{{Back}}</div>",
            "afmt": "<div class='back'>{{Back}}</div><hr><div class='korean'>{{Korean}}</div><div class='label'>{{DateAdded}}</div>",
        },
    ],
    css=CARD_CSS,
)

ref_model = genanki.Model(
    REF_MODEL_ID,
    "Korean Reference",
    fields=[{"name": "Korean"}, {"name": "DateAdded"}],
    templates=[{
        "name": "Korean (reference)",
        "qfmt": "<div class='korean'>{{Korean}}</div><div class='label'>reference</div>",
        "afmt": "<div class='korean'>{{Korean}}</div><hr><div class='label'>no translation · {{DateAdded}}</div>",
    }],
    css=CARD_CSS,
)

# ── Korean/English detection ──────────────────────────────────────────────────

def is_korean(text: str) -> bool:
    return bool(re.search(r'[가-힣ᄀ-ᇿ㄰-㆏]', text))

def has_latin(text: str) -> bool:
    return bool(re.search(r'[a-zA-Z]', text))

def split_at_english(text: str) -> tuple[str, str | None]:
    """Split 'Korean term English meaning' at the first Latin word."""
    words = text.split()
    for i, word in enumerate(words):
        clean = word.strip('.,!?()[]')
        if has_latin(clean) and not is_korean(clean):
            korean_part = ' '.join(words[:i]).strip().rstrip(',')
            english_part = ' '.join(words[i:]).strip()
            return korean_part, english_part
    return text.strip(), None

def split_at_korean(text: str) -> tuple[str, str | None]:
    """Split 'English meaning Korean term' at the first Korean word."""
    words = text.split()
    for i, word in enumerate(words):
        if is_korean(word):
            korean_part = ' '.join(words[i:]).strip()
            english_part = ' '.join(words[:i]).strip() or None
            return korean_part, english_part
    return text.strip(), None

# ── Line parsing ──────────────────────────────────────────────────────────────

def parse_line(line: str) -> list[tuple[str, str, str]]:
    """
    Returns list of (korean, back, deck_type) tuples.
    deck_type is 'vocab' or 'reference'.
    """
    line = line.strip()
    if not is_korean(line):
        return []

    if '→' in line:
        parts = [p.strip() for p in line.split('→', 1)]
        if len(parts) == 2:
            a, b = parts
            if is_korean(a) and b:
                return [(a, b, 'vocab')]
            elif is_korean(b) and a:
                return [(b, a, 'vocab')]
            elif is_korean(a):
                return [(a, '', 'reference')]
        return []

    if '=' in line:
        parts = [p.strip() for p in line.split('=')]
        if len(parts) >= 3:
            # A = B = C  →  front=A, back="B\nC"
            front = parts[0]
            back = '\n'.join(parts[1:])
            return [(front, back, 'vocab')]
        elif len(parts) == 2:
            a, b = parts
            return [(a, b, 'vocab')]

    # No '=' — try comma-separated Korean terms with shared English
    if ',' in line:
        segments = [s.strip() for s in line.split(',')]
        korean_terms: list[str] = []
        english: str | None = None

        for seg in segments:
            k, e = split_at_english(seg)
            if k:
                korean_terms.append(k)
            if e:
                english = e

        if not korean_terms:
            return []
        if english:
            return [(k, english, 'vocab') for k in korean_terms]
        else:
            return [(k, '', 'reference') for k in korean_terms]

    # Simple "Korean English", "English Korean", or "Korean only"
    korean, english = split_at_english(line)
    if not korean:
        korean, english = split_at_korean(line)
    if not korean:
        return []
    if english:
        return [(korean, english, 'vocab')]
    return [(korean, '', 'reference')]

# ── Storage ───────────────────────────────────────────────────────────────────

_CREATE_TABLE = """
    CREATE TABLE IF NOT EXISTS words (
        korean     TEXT PRIMARY KEY,
        back       TEXT NOT NULL DEFAULT '',
        deck_type  TEXT NOT NULL,
        date_added TEXT NOT NULL
    )
"""

def load_words() -> dict[str, dict]:
    con = sqlite3.connect(DB_FILE)
    con.execute(_CREATE_TABLE)
    rows = con.execute("SELECT korean, back, deck_type, date_added FROM words").fetchall()
    con.close()
    return {r[0]: {'back': r[1], 'deck_type': r[2], 'date_added': r[3]} for r in rows}

def save_words(words: dict[str, dict]) -> None:
    con = sqlite3.connect(DB_FILE)
    con.execute(_CREATE_TABLE)
    con.execute("DELETE FROM words")
    con.executemany(
        "INSERT INTO words (korean, back, deck_type, date_added) VALUES (?, ?, ?, ?)",
        [(k, d['back'], d['deck_type'], d['date_added']) for k, d in words.items()],
    )
    con.commit()
    con.close()


def stable_guid(korean: str) -> int:
    return int(hashlib.md5(korean.encode()).hexdigest(), 16) % (10 ** 10)

# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_parse(args):
    path = Path(args.file)
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    words = load_words()
    today = str(date.today())
    added_vocab = added_ref = skipped = 0
    unrecognized: list[str] = []

    for line in path.read_text(encoding='utf-8').splitlines():
        entries = parse_line(line)
        if not entries:
            # Log non-empty Korean lines we couldn't parse (shouldn't happen often)
            stripped = line.strip()
            if stripped and is_korean(stripped) and stripped not in words:
                unrecognized.append(stripped)
            continue
        for korean, back, deck_type in entries:
            if korean in words:
                skipped += 1
            else:
                words[korean] = {'back': back, 'deck_type': deck_type, 'date_added': today}
                if deck_type == 'vocab':
                    added_vocab += 1
                    print(f"  + [{deck_type}] {korean} → {back}")
                else:
                    added_ref += 1
                    print(f"  + [reference] {korean}")

    save_words(words)
    print(f"\n{added_vocab} vocab, {added_ref} reference added · {skipped} duplicate(s) skipped.")
    if unrecognized:
        print(f"\nCouldn't classify ({len(unrecognized)}):")
        for u in unrecognized:
            print(f"  ? {u}")


def cmd_add(args):
    words = load_words()
    today = str(date.today())
    added = skipped = 0

    for pair in args.pairs:
        entries = parse_line(pair)
        if not entries:
            print(f"  skip (unrecognized format): {pair}")
            continue
        for korean, back, deck_type in entries:
            if korean in words:
                print(f"  ~ {korean} (already exists)")
                skipped += 1
            else:
                words[korean] = {'back': back, 'deck_type': deck_type, 'date_added': today}
                print(f"  + {korean} → {back or '[reference]'}")
                added += 1

    if added:
        save_words(words)
    print(f"\n{added} added, {skipped} skipped.")


def cmd_build(args):
    words = load_words()
    if not words:
        print("No words yet. Use 'parse' or 'add' first.")
        sys.exit(1)

    vocab_deck = genanki.Deck(VOCAB_DECK_ID, "Korean - Vocabulary")
    ref_deck   = genanki.Deck(REF_DECK_ID,   "Korean - Reference")

    for korean, d in words.items():
        if d['deck_type'] == 'vocab':
            note = genanki.Note(
                model=vocab_model,
                fields=[korean, d['back'], d['date_added']],
                guid=stable_guid(korean),
            )
            vocab_deck.add_note(note)
        else:
            note = genanki.Note(
                model=ref_model,
                fields=[korean, d['date_added']],
                guid=stable_guid(korean),
            )
            ref_deck.add_note(note)

    genanki.Package([vocab_deck, ref_deck]).write_to_file(str(OUTPUT_FILE))
    vocab_count = sum(1 for d in words.values() if d['deck_type'] == 'vocab')
    ref_count   = sum(1 for d in words.values() if d['deck_type'] == 'reference')
    print(f"Built {OUTPUT_FILE}")
    print(f"  Korean - Vocabulary : {vocab_count} card(s)")
    print(f"  Korean - Reference  : {ref_count} card(s)")
    print("\nImport into Anki: File → Import, then choose 'Update existing notes when first field matches'.")


def cmd_list(args):
    words = load_words()
    if not words:
        print("No words yet.")
        return

    deck_filter = args.deck
    query = args.search.lower() if args.search else None

    results = [
        (k, v) for k, v in sorted(words.items())
        if (not deck_filter or v['deck_type'] == deck_filter)
        and (not query or query in k.lower() or query in v['back'].lower())
    ]

    if not results:
        print("No matches.")
        return

    print(f"{'Korean':<24} {'Back':<36} {'Type':<10} {'Added'}")
    print('─' * 78)
    for korean, d in results:
        back = d['back'][:34] + '…' if len(d['back']) > 35 else d['back']
        print(f"{korean:<24} {back:<36} {d['deck_type']:<10} {d['date_added']}")
    print(f"\n{len(results)} word(s).")


def cmd_remove(args):
    words = load_words()
    removed = []
    for korean in args.words:
        if korean in words:
            del words[korean]
            removed.append(korean)
        else:
            print(f"  Not found: {korean}")
    if removed:
        save_words(words)
        print(f"Removed: {', '.join(removed)}")

# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(prog='anki_korean', description='Manage your Korean Anki deck.')
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('parse', help='Parse a chat export and add new words')
    p.add_argument('file', metavar='FILE')
    p.set_defaults(func=cmd_parse)

    p = sub.add_parser('add', help='Manually add word(s)')
    p.add_argument('pairs', nargs='+', metavar='WORD=MEANING')
    p.set_defaults(func=cmd_add)

    p = sub.add_parser('build', help='Generate the .apkg file for Anki')
    p.set_defaults(func=cmd_build)

    p = sub.add_parser('list', help='List words')
    p.add_argument('--search', '-s', metavar='QUERY')
    p.add_argument('--deck', choices=['vocab', 'reference'])
    p.set_defaults(func=cmd_list)

    p = sub.add_parser('remove', help='Remove word(s)')
    p.add_argument('words', nargs='+', metavar='KOREAN')
    p.set_defaults(func=cmd_remove)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
