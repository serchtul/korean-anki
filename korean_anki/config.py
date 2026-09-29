from pathlib import Path

# config.py lives at korean_anki/config.py; project root is one level up
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_FILE = PROJECT_ROOT / "words.db"
OUTPUT_FILE = PROJECT_ROOT / "korean_deck.apkg"

VOCAB_DECK_ID    = 1_953_742_187
# Anki forked the vocab note type on an .apkg import (the imported model declared
# the same id with a different template count), so the surviving studied note type
# carries this Anki-assigned id. Keep it in sync or `build` + import forks again.
VOCAB_MODEL_ID   = 1_782_698_471_296
REF_DECK_ID      = 1_953_742_188
REF_MODEL_ID     = 1_607_392_320

VOCAB_DECK_NAME  = "Korean - Vocabulary"
REF_DECK_NAME    = "Korean - Reference"

VOCAB_MODEL_NAME = "Korean Vocabulary"
REF_MODEL_NAME   = "Korean Reference"
