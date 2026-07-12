import html
import re
import sys
from datetime import datetime

from korean_anki.ankiconnect import (
    AnkiConnectError,
    anki_connect,
    check_ankiconnect,
    ensure_deck_and_model,
)
from korean_anki.config import REF_DECK_NAME, VOCAB_DECK_NAME
from korean_anki.models import ref_model, vocab_model
from korean_anki.storage import active_words, load_words, save_words

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


def back_field_conflicts(data: dict, live_back: str) -> bool:
    return data['deck_type'] == 'vocab' and live_back != data['back']


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
                if back_field_conflicts(data, live_back):
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
