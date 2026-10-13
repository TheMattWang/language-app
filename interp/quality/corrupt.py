"""Controlled corruptions of correct Spanish: one known error per sentence.

Each function takes a clean sentence and returns a corrupted copy, or None
when the sentence offers nothing to corrupt. Clean and corrupted then form
a minimal pair, so any signal that ranks the clean one higher has detected
*that* error and nothing else.

Two families, because the conversation partner and translator fail in two
different ways (research/06, 13):
  form     the Spanish itself is broken: agreement, a non-word
  meaning  the Spanish is fine but no longer says what the source said
"""

from __future__ import annotations

import random
import re

_WORD = re.compile(r"\b\w+\b", re.UNICODE)

_ARTICLES = {"el": "la", "la": "el", "los": "las", "las": "los", "un": "una", "una": "un"}
_VERB_NUMBER = {
    "es": "son", "son": "es", "está": "están", "están": "está", "tiene": "tienen",
    "tienen": "tiene", "ha": "han", "han": "ha", "fue": "fueron", "fueron": "fue",
    "puede": "pueden", "pueden": "puede", "dijo": "dijeron", "dijeron": "dijo",
}


def _swap_first(text: str, table: dict[str, str]) -> str | None:
    for m in _WORD.finditer(text):
        w = m.group(0)
        if w.lower() in table:
            new = table[w.lower()]
            new = new.capitalize() if w[0].isupper() else new
            return text[: m.start()] + new + text[m.end():]
    return None


def gender(text: str, rng: random.Random) -> str | None:
    """el coche -> la coche: article/noun gender disagreement."""
    return _swap_first(text, _ARTICLES)


def verb_number(text: str, rng: random.Random) -> str | None:
    """el gobierno ha dicho -> el gobierno han dicho: subject/verb disagreement."""
    return _swap_first(text, _VERB_NUMBER)


def nonword(text: str, rng: random.Random) -> str | None:
    """gobierno -> gobeirno: a word that isn't Spanish (cf. 'ferranadisa')."""
    words = [m for m in _WORD.finditer(text) if len(m.group(0)) >= 7 and m.group(0).isalpha()]
    if not words:
        return None
    m = rng.choice(words)
    w = m.group(0)
    i = len(w) // 2
    new = w[:i - 1] + w[i] + w[i - 1] + w[i + 1:]
    return None if new == w else text[: m.start()] + new + text[m.end():]


def drop_clause(text: str, rng: random.Random) -> str | None:
    """Cut everything after the last comma past the first third: fluent but
    incomplete, the failure research/13 saw Opus-MT make."""
    cut = text.rfind(",")
    if cut < len(text) // 3:
        return None
    return text[:cut].rstrip() + "."


def swap_content(text: str, rng: random.Random, pool: list[str]) -> str | None:
    """Replace the longest word with the longest word of another sentence:
    the sentence now says something the source didn't."""
    words = [m for m in _WORD.finditer(text) if m.group(0).isalpha()]
    if not words:
        return None
    m = max(words, key=lambda x: len(x.group(0)))
    other = rng.choice(pool)
    donors = [w for w in _WORD.findall(other) if w.isalpha() and w.lower() != m.group(0).lower()]
    if not donors:
        return None
    donor = max(donors, key=len)
    return text[: m.start()] + donor + text[m.end():]


FORM = {"gender": gender, "verb_number": verb_number, "nonword": nonword}
MEANING = {"drop_clause": drop_clause, "swap_content": swap_content}
