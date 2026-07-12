import hashlib
import sqlite3

from korean_anki.config import DB_FILE

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
