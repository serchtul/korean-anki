import json
import sys
import urllib.error
import urllib.request
from typing import Any

import genanki

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
