import re

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
