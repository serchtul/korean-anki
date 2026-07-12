"""
anki-kr: manage a Korean vocabulary Anki deck from the command line.

Usage:
  uv run anki-kr parse lesson.txt   # parse a chat export, then auto-sync new words
  uv run anki-kr parse lesson.txt --no-sync  # parse only, skip auto-sync
  uv run anki-kr add "야근=overwork" # manually add a word
  uv run anki-kr build              # generate korean_deck.apkg (manual import fallback)
  uv run anki-kr sync               # push directly into running Anki + AnkiWeb
  uv run anki-kr list               # show all words
  uv run anki-kr list --search 사람
  uv run anki-kr list --deck reference
  uv run anki-kr list --deleted     # show words queued for deletion
  uv run anki-kr remove "이야기"
"""

import argparse
import sys
from datetime import date
from pathlib import Path

import genanki

from korean_anki.config import (
    OUTPUT_FILE,
    REF_DECK_ID,
    REF_DECK_NAME,
    VOCAB_DECK_ID,
    VOCAB_DECK_NAME,
)
from korean_anki.models import ref_model, vocab_model
from korean_anki.parsing import is_korean, parse_line
from korean_anki.storage import active_words, load_words, save_words, stable_guid
from korean_anki.sync import run_sync

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
    parser = argparse.ArgumentParser(prog='anki-kr', description='Manage your Korean Anki deck.')
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
