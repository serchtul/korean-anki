#!/usr/bin/env -S uv run
"""
korean-anki: manage a Korean vocabulary Anki deck from the command line.

Usage:
  uv run anki_korean.py parse lesson.txt   # parse a chat export, then auto-sync new words
  uv run anki_korean.py parse lesson.txt --no-sync  # parse only, skip auto-sync
  uv run anki_korean.py add "야근=overwork" # manually add a word
  uv run anki_korean.py build              # generate korean_deck.apkg (manual import fallback)
  uv run anki_korean.py sync               # push directly into running Anki + AnkiWeb
  uv run anki_korean.py list               # show all words
  uv run anki_korean.py list --search 사람
  uv run anki_korean.py list --deck reference
  uv run anki_korean.py list --deleted     # show words queued for deletion
  uv run anki_korean.py remove "이야기"
"""

import argparse
import hashlib
import html
import json
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any

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

VOCAB_DECK_NAME  = "Korean - Vocabulary"
REF_DECK_NAME    = "Korean - Reference"

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

_NEW_COLUMNS = [
    ("anki_note_id", "INTEGER"),
    ("synced_at", "TEXT"),
    ("pending_delete", "INTEGER NOT NULL DEFAULT 0"),
]

def _ensure_schema(con: sqlite3.Connection) -> None:
    con.execute(_CREATE_TABLE)
    for name, decl in _NEW_COLUMNS:
        try:
            con.execute(f"ALTER TABLE words ADD COLUMN {name} {decl}")
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise

def load_words() -> dict[str, dict]:
    con = sqlite3.connect(DB_FILE)
    _ensure_schema(con)
    rows = con.execute(
        "SELECT korean, back, deck_type, date_added, anki_note_id, synced_at, pending_delete FROM words"
    ).fetchall()
    con.close()
    return {
        r[0]: {
            'back': r[1],
            'deck_type': r[2],
            'date_added': r[3],
            'anki_note_id': r[4],
            'synced_at': r[5],
            'pending_delete': r[6] or 0,
        }
        for r in rows
    }

def save_words(words: dict[str, dict]) -> None:
    con = sqlite3.connect(DB_FILE)
    _ensure_schema(con)
    con.execute("DELETE FROM words")
    con.executemany(
        """INSERT INTO words
           (korean, back, deck_type, date_added, anki_note_id, synced_at, pending_delete)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                k,
                d['back'],
                d['deck_type'],
                d['date_added'],
                d.get('anki_note_id'),
                d.get('synced_at'),
                d.get('pending_delete', 0),
            )
            for k, d in words.items()
        ],
    )
    con.commit()
    con.close()


def stable_guid(korean: str) -> int:
    return int(hashlib.md5(korean.encode()).hexdigest(), 16) % (10 ** 10)


def active_words(words: dict[str, dict]) -> dict[str, dict]:
    return {k: d for k, d in words.items() if not d.get('pending_delete')}

# ── AnkiConnect client ──────────────────────────────────────────────────────

ANKICONNECT_URL = "http://127.0.0.1:8765"
MIN_ANKICONNECT_VERSION = 6


class AnkiConnectError(Exception):
    pass


def anki_connect(action: str, **params) -> Any:
    payload = json.dumps({"action": action, "version": MIN_ANKICONNECT_VERSION, "params": params}).encode("utf-8")
    req = urllib.request.Request(ANKICONNECT_URL, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise AnkiConnectError(
            f"Couldn't reach AnkiConnect at {ANKICONNECT_URL}. "
            "Make sure Anki desktop is open and the AnkiConnect add-on "
            "(Tools → Add-ons → code 2055492159) is installed."
        ) from e
    except json.JSONDecodeError as e:
        raise AnkiConnectError("AnkiConnect returned a response that wasn't valid JSON.") from e

    if not isinstance(body, dict) or "result" not in body or "error" not in body:
        raise AnkiConnectError(f"Unexpected AnkiConnect response shape: {body!r}")
    if body["error"] is not None:
        raise AnkiConnectError(f"AnkiConnect error for action '{action}': {body['error']}")
    return body["result"]


def check_ankiconnect(fail_hard: bool = True) -> bool:
    try:
        version = anki_connect("version")
    except AnkiConnectError as e:
        print(f"Cannot connect to Anki:\n  {e}")
        if fail_hard:
            sys.exit(1)
        return False

    if not isinstance(version, int):
        print(f"Cannot connect to Anki:\n  AnkiConnect returned an unexpected version value: {version!r}")
        if fail_hard:
            sys.exit(1)
        return False

    if version < MIN_ANKICONNECT_VERSION:
        print(
            f"AnkiConnect API version {version} is older than the version this tool expects "
            f"({MIN_ANKICONNECT_VERSION}+). Update the AnkiConnect add-on in Anki "
            "(Tools → Add-ons → Check for updates) and try again."
        )
        if fail_hard:
            sys.exit(1)
        return False

    return True


def ensure_deck_and_model(deck_name: str, model_name: str, model_def: genanki.Model) -> None:
    existing_decks = anki_connect("deckNames")
    if deck_name not in existing_decks:
        anki_connect("createDeck", deck=deck_name)

    existing_models = anki_connect("modelNames")
    if model_name not in existing_models:
        anki_connect(
            "createModel",
            modelName=model_name,
            inOrderFields=[f["name"] for f in model_def.fields],
            css=model_def.css,
            cardTemplates=[
                {"Name": t["name"], "Front": t["qfmt"], "Back": t["afmt"]}
                for t in model_def.templates
            ],
        )


_HTML_BLOCK_BOUNDARY = re.compile(r'<br\s*/?>|</div>|</p>', re.IGNORECASE)
_HTML_TAG = re.compile(r'<[^>]+>')


def html_to_text(value: str) -> str:
    """Best-effort conversion of Anki's stored field HTML to plain text."""
    text = _HTML_BLOCK_BOUNDARY.sub('\n', value)
    text = _HTML_TAG.sub('', text)
    text = html.unescape(text)
    lines = [line.strip() for line in text.splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return '\n'.join(lines)


def escape_anki_query_value(value: str) -> str:
    return value.replace('"', '\\"')


def deck_model_for(deck_type: str) -> tuple[str, str]:
    if deck_type == 'vocab':
        return VOCAB_DECK_NAME, "Korean Vocabulary"
    return REF_DECK_NAME, "Korean Reference"


def fields_for(korean: str, data: dict) -> dict:
    if data['deck_type'] == 'vocab':
        return {"Korean": korean, "Back": data['back'], "DateAdded": data['date_added']}
    return {"Korean": korean, "DateAdded": data['date_added']}


def prompt_yes_no(question: str, default_yes: bool = True) -> bool:
    suffix = "[Y/n]" if default_yes else "[y/N]"
    answer = input(f"{question} {suffix} ").strip().lower()
    if not answer:
        return default_yes
    return answer.startswith('y')


def run_sync(no_ankiweb_sync: bool, no_interactive: bool, fail_hard: bool = True) -> bool:
    if not check_ankiconnect(fail_hard=fail_hard):
        return False

    interactive = not no_interactive and sys.stdin.isatty()

    words = load_words()
    active = active_words(words)
    if not active:
        print("No words yet. Use 'parse' or 'add' first.")
        return False

    ensure_deck_and_model(VOCAB_DECK_NAME, "Korean Vocabulary", vocab_model)
    ensure_deck_and_model(REF_DECK_NAME, "Korean Reference", ref_model)

    # ── Flush soft-deletes ──────────────────────────────────────────────────
    pending = {k: d for k, d in words.items() if d.get('pending_delete')}
    if pending:
        note_ids = [d['anki_note_id'] for d in pending.values() if d.get('anki_note_id')]
        if note_ids:
            try:
                anki_connect("deleteNotes", notes=note_ids)
            except AnkiConnectError as e:
                print(f"Warning: failed to delete some notes from Anki: {e}")
        for k in pending:
            del words[k]
        print(f"{len(pending)} word(s) deleted from Anki and word list.")

    # ── Batch-fetch live state for remaining active words ──────────────────
    note_id_to_korean: dict[int, str] = {
        d['anki_note_id']: k for k, d in active.items() if d.get('anki_note_id')
    }
    notes_info_by_id: dict[int, dict] = {}
    if note_id_to_korean:
        try:
            infos = anki_connect("notesInfo", notes=list(note_id_to_korean.keys()))
            for info in infos:
                if info.get('noteId'):
                    notes_info_by_id[info['noteId']] = info
        except AnkiConnectError as e:
            print(f"Warning: failed to fetch live note info from Anki: {e}")

    added = updated = errors = 0
    newly_deleted = 0
    conflicts: list[str] = []
    now = datetime.now().isoformat(timespec='seconds')

    for korean, data in active.items():
        deck_name, model_name = deck_model_for(data['deck_type'])
        fields = fields_for(korean, data)
        note_id = data.get('anki_note_id')

        try:
            if not note_id:
                try:
                    new_id = anki_connect(
                        "addNote",
                        note={
                            "deckName": deck_name,
                            "modelName": model_name,
                            "fields": fields,
                            "options": {"allowDuplicate": False},
                        },
                    )
                    data['anki_note_id'] = new_id
                    data['synced_at'] = now
                    added += 1
                    print(f"  + {korean}")
                except AnkiConnectError as e:
                    if 'duplicate' not in str(e).lower():
                        raise
                    # Anki's duplicate check is scoped to the note type across the whole
                    # collection, not just this deck — e.g. the note may already exist from
                    # an earlier .apkg import. Look it up and link to it instead of erroring.
                    query = f'note:"{model_name}" Korean:"{escape_anki_query_value(korean)}"'
                    found = anki_connect("findNotes", query=query)
                    if not found:
                        raise
                    note_id = found[0]
                    anki_connect("updateNoteFields", note={"id": note_id, "fields": fields})
                    data['anki_note_id'] = note_id
                    data['synced_at'] = now
                    updated += 1
                    print(f"  = {korean} (linked to existing Anki note)")
                continue

            info = notes_info_by_id.get(note_id)
            if info is None:
                # Stale id — try to re-resolve by field lookup before assuming a real delete.
                query = f'deck:"{deck_name}" Korean:"{escape_anki_query_value(korean)}"'
                found = anki_connect("findNotes", query=query)
                if found:
                    note_id = found[0]
                    anki_connect("updateNoteFields", note={"id": note_id, "fields": fields})
                    data['anki_note_id'] = note_id
                    data['synced_at'] = now
                    updated += 1
                else:
                    data['pending_delete'] = 1
                    newly_deleted += 1
                    print(f"  ~ {korean}: deleted in Anki, removing from word list too (will flush on next sync)")
                continue

            live_fields = info.get('fields', {})
            live_korean = live_fields.get('Korean', {}).get('value', korean)
            if live_korean != korean:
                errors += 1
                print(f"  ! {korean}: Korean field in Anki doesn't match ('{live_korean}') — front-field edits aren't supported, skipping")
                continue

            if data['deck_type'] == 'vocab':
                live_back_raw = live_fields.get('Back', {}).get('value', '')
                live_back = html_to_text(live_back_raw)
                if live_back != data['back']:
                    if interactive:
                        print(f"\nConflict for {korean}:")
                        print(f"  DB value:   {data['back']!r}")
                        print(f"  Anki value: {live_back!r}")
                        if prompt_yes_no(f"Adopt Anki's edit for {korean}?", default_yes=True):
                            data['back'] = live_back
                            data['synced_at'] = now
                            updated += 1
                            continue
                        # else: fall through and push DB value to Anki below
                    else:
                        conflicts.append(korean)
                        continue

            anki_connect("updateNoteFields", note={"id": note_id, "fields": fields_for(korean, data)})
            data['synced_at'] = now
            updated += 1
        except AnkiConnectError as e:
            errors += 1
            print(f"  ! {korean}: {e}")

    words.update(active)
    save_words(words)

    print(f"\n{added} added, {updated} updated, {newly_deleted} deleted-in-Anki, {errors} error(s).")
    if errors:
        print("Some words failed to sync; re-run 'sync' to retry.")

    if conflicts:
        print(f"\n{len(conflicts)} word(s) have conflicting edits in Anki and require interactive resolution:")
        for k in conflicts:
            print(f"  - {k}")
        print("Re-run 'sync' from an interactive terminal (without --no-interactive) to resolve them.")
        return False

    if not no_ankiweb_sync:
        print("\nSyncing with AnkiWeb...")
        try:
            anki_connect("sync")
            print("AnkiWeb sync triggered. Check the Anki desktop window for completion status.")
        except AnkiConnectError as e:
            print(
                f"Local notes were synced to Anki, but triggering AnkiWeb sync failed: {e}\n"
                "Make sure you're logged into AnkiWeb in Anki desktop (Anki menu → Sync), "
                "or sync manually by clicking the Sync button in Anki."
            )

    return True

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
                words[korean] = {
                    'back': back,
                    'deck_type': deck_type,
                    'date_added': today,
                    'anki_note_id': None,
                    'synced_at': None,
                    'pending_delete': 0,
                }
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

    # Sync if this run added anything new, or if earlier runs (e.g. parse/add with
    # --no-sync) left words that were never pushed to Anki, or deletions never flushed.
    needs_sync = any(
        d.get('pending_delete') or not d.get('anki_note_id')
        for d in words.values()
    )
    if needs_sync and not args.no_sync:
        print("\nSyncing words to Anki...")
        if not run_sync(args.no_ankiweb_sync, no_interactive=False, fail_hard=False):
            print("Sync skipped or incomplete — words are saved locally; run 'sync' manually later.")


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
                words[korean] = {
                    'back': back,
                    'deck_type': deck_type,
                    'date_added': today,
                    'anki_note_id': None,
                    'synced_at': None,
                    'pending_delete': 0,
                }
                print(f"  + {korean} → {back or '[reference]'}")
                added += 1

    if added:
        save_words(words)
    print(f"\n{added} added, {skipped} skipped.")


def cmd_build(_args):
    words = active_words(load_words())
    if not words:
        print("No words yet. Use 'parse' or 'add' first.")
        sys.exit(1)

    vocab_deck = genanki.Deck(VOCAB_DECK_ID, VOCAB_DECK_NAME)
    ref_deck   = genanki.Deck(REF_DECK_ID,   REF_DECK_NAME)

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


def cmd_sync(args):
    if not run_sync(args.no_ankiweb_sync, args.no_interactive, fail_hard=True):
        sys.exit(1)


def cmd_list(args):
    words = load_words()
    if args.deleted:
        words = {k: d for k, d in words.items() if d.get('pending_delete')}
    else:
        words = active_words(words)

    if not words:
        print("No matches.")
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
        if korean in words and not words[korean].get('pending_delete'):
            words[korean]['pending_delete'] = 1
            removed.append(korean)
        elif korean not in words:
            print(f"  Not found: {korean}")
    if removed:
        save_words(words)
        print(f"Marked for deletion (removed from Anki + word list on next sync): {', '.join(removed)}")

# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(prog='anki_korean', description='Manage your Korean Anki deck.')
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('parse', help='Parse a chat export and add new words (auto-syncs to Anki)')
    p.add_argument('file', metavar='FILE')
    p.add_argument('--no-sync', action='store_true', help="Don't auto-sync new words to Anki")
    p.add_argument('--no-ankiweb-sync', action='store_true', help="Push to local Anki but don't trigger AnkiWeb sync")
    p.set_defaults(func=cmd_parse)

    p = sub.add_parser('add', help='Manually add word(s)')
    p.add_argument('pairs', nargs='+', metavar='WORD=MEANING')
    p.set_defaults(func=cmd_add)

    p = sub.add_parser('build', help='Generate the .apkg file for Anki')
    p.set_defaults(func=cmd_build)

    p = sub.add_parser('sync', help='Push words directly into a running Anki via AnkiConnect')
    p.add_argument('--no-ankiweb-sync', action='store_true', help="Don't trigger AnkiWeb sync after updating local Anki")
    p.add_argument('--no-interactive', action='store_true', help="Don't prompt on conflicts; fail instead")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser('list', help='List words')
    p.add_argument('--search', '-s', metavar='QUERY')
    p.add_argument('--deck', choices=['vocab', 'reference'])
    p.add_argument('--deleted', action='store_true', help='Show only words queued for deletion')
    p.set_defaults(func=cmd_list)

    p = sub.add_parser('remove', help='Remove word(s)')
    p.add_argument('words', nargs='+', metavar='KOREAN')
    p.set_defaults(func=cmd_remove)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
