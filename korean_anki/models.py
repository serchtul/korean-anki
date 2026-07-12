import sys

try:
    import genanki
except ImportError:
    print("Run with: uv run anki-kr")
    sys.exit(1)

from korean_anki.config import VOCAB_MODEL_ID, REF_MODEL_ID

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
