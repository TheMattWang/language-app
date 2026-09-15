"""Text normalization utilities for Spanish answer grading.

Pure stdlib. All functions are deterministic and side-effect free.
"""

from __future__ import annotations

import unicodedata

# Punctuation stripped by normalize(): inverted marks, terminal punctuation,
# and every quote/guillemet style (straight + curly).
_PUNCT_CHARS = "¿¡?!.,;:\"'“”‘’«»"
_PUNCT_TABLE = {ord(ch): None for ch in _PUNCT_CHARS}

_ACCENT_MAP = {
    "á": "a",
    "é": "e",
    "í": "i",
    "ó": "o",
    "ú": "u",
    "ü": "u",
}
# ñ is intentionally absent from _ACCENT_MAP: "año" and "ano" must never fold
# to the same token.


def normalize(s: str) -> str:
    """NFC-normalize, casefold, strip punctuation, collapse whitespace.

    Preserves accents and ñ.
    """
    text = unicodedata.normalize("NFC", s)
    text = text.casefold()
    text = text.translate(_PUNCT_TABLE)
    text = " ".join(text.split())
    return text.strip()


def fold_accents(s: str) -> str:
    """Fold á é í ó ú ü to their unaccented equivalents. ñ is never folded.

    Expects an already-normalized string (NFC + casefolded), but is safe to
    call on any string.
    """
    return "".join(_ACCENT_MAP.get(ch, ch) for ch in s)


def tokens(s: str) -> list[str]:
    """Normalize then split on whitespace."""
    normalized = normalize(s)
    if not normalized:
        return []
    return normalized.split(" ")


def edit_distance(a: str, b: str) -> int:
    """Standard Levenshtein distance between two strings.

    Iterative DP with O(min(len(a), len(b))) space.
    """
    if a == b:
        return 0
    # Ensure `a` is the shorter string so the rolling row is minimal width.
    if len(a) > len(b):
        a, b = b, a

    prev_row = list(range(len(a) + 1))
    for i, cb in enumerate(b, start=1):
        curr_row = [i] + [0] * len(a)
        for j, ca in enumerate(a, start=1):
            cost = 0 if ca == cb else 1
            curr_row[j] = min(
                prev_row[j] + 1,  # deletion
                curr_row[j - 1] + 1,  # insertion
                prev_row[j - 1] + cost,  # substitution
            )
        prev_row = curr_row
    return prev_row[len(a)]


def token_edit_distance(a: str, b: str) -> int:
    """Levenshtein distance over token lists rather than characters."""
    tokens_a = tokens(a)
    tokens_b = tokens(b)

    if tokens_a == tokens_b:
        return 0
    if len(tokens_a) > len(tokens_b):
        tokens_a, tokens_b = tokens_b, tokens_a

    prev_row = list(range(len(tokens_a) + 1))
    for i, tb in enumerate(tokens_b, start=1):
        curr_row = [i] + [0] * len(tokens_a)
        for j, ta in enumerate(tokens_a, start=1):
            cost = 0 if ta == tb else 1
            curr_row[j] = min(
                prev_row[j] + 1,
                curr_row[j - 1] + 1,
                prev_row[j - 1] + cost,
            )
        prev_row = curr_row
    return prev_row[len(tokens_a)]
