"""Parsing/rendering helpers for `kind="cloze"` cards.

Card format (see docs at the call sites -- no schema migration): for a
cloze card, `prompt_en` holds the Spanish sentence with a `___` gap,
optionally followed by a separator and the English meaning:

    "No creo que ___ la respuesta. — I don't think he knows the answer."

`accept` on the card holds only what fills the gap, never the whole
sentence, so grading (`drill.grader.grade`) needs no changes at all --
these helpers only affect what gets displayed.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Cloze", "is_cloze", "parse", "render_question", "render_filled"]

GAP = "___"

# Prefer the em dash; a plain hyphen (surrounded by spaces, so it doesn't
# eat hyphenated words) is accepted too.
_EM_DASH_SEP = " — "
_HYPHEN_SEP = " - "


@dataclass(frozen=True)
class Cloze:
    sentence_es: str  # with the ___ gap intact
    meaning_en: str | None
    gap_count: int


def is_cloze(kind: str) -> bool:
    return kind == "cloze"


def parse(prompt_en: str) -> Cloze:
    """Tolerant: a prompt with no separator, or no gap at all, still
    parses -- it just comes back with `meaning_en=None` / `gap_count=0`.
    Never raises."""
    text = (prompt_en or "").strip()

    if _EM_DASH_SEP in text:
        sentence, meaning = text.split(_EM_DASH_SEP, 1)
    elif _HYPHEN_SEP in text:
        sentence, meaning = text.split(_HYPHEN_SEP, 1)
    else:
        sentence, meaning = text, None

    sentence = sentence.strip()
    meaning = meaning.strip() if meaning is not None else None
    return Cloze(sentence_es=sentence, meaning_en=meaning or None, gap_count=sentence.count(GAP))


def render_question(c: Cloze) -> str:
    """What the learner sees before answering: the Spanish sentence with
    its gap(s) intact -- a prompt with no gap renders as itself."""
    return c.sentence_es


def render_filled(c: Cloze, answer: str) -> str:
    """The sentence with the gap replaced by `answer`. Only the FIRST gap
    is filled when there are several; a sentence with no gap renders
    unchanged."""
    if GAP not in c.sentence_es:
        return c.sentence_es
    return c.sentence_es.replace(GAP, answer, 1)
