"""Checks on model-written Spanish before a learner sees it.

research/06-bench-local-baseline.md found that small local models leak
English, subtitle themselves with parenthetical translations, drift into
the wrong variety and leak reasoning text, whatever the prompt says. The
fix it recommended is enforcement outside the model: scan each reply and
regenerate on failure (there is latency headroom for one or two retries).

This module is that scan. It is deterministic and deliberately
conservative -- a false flag costs a regeneration, a missed one teaches
the learner something wrong, but flagging ordinary Spanish would make
every reply fail. It judges only the model's output, never the learner's
answer (that is drill.grader's job).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from drill import packs
from drill.normalize import fold_accents

__all__ = ["Issue", "check", "dialect_markers", "matches", "words"]


@dataclass(frozen=True)
class Issue:
    kind: str  # "empty" | "thinking" | "english" | "translation" | "dialect"
    detail: str


# English words that are not also Spanish words, so a hit means a leak.
# (No "a", "me", "no", "he", "son", "come", "pan", ...)
_ENGLISH = frozenset(
    """
    the and you your yours what where when which with without this that these those
    is are was were be been being have has had do does did don't can't won't i'm it's
    please thanks thank sorry hello hi yes yeah would could should will shall
    my our their they them we us he's she's there here how why who whom
    of for from into about just very really also only than then
    help speak english translate translation meaning means directions table
    """.split()
)
_WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?", re.UNICODE)
_PAREN = re.compile(r"\(([^)]*)\)")
_THINKING = re.compile(r"<\s*/?\s*think|^\s*(okay|alright|let me|first,|so,)\b", re.I | re.M)

# Fragments rejected for Spain that are also ordinary Peninsular words or
# carry another meaning there, so finding them in a reply proves nothing:
# camión (lorry), papa (the Pope), pana (corduroy), plata (silver), ...
_AMBIGUOUS_IN_SPAIN = frozenset(
    """
    auto banana camión departamento derecho cheque nota plata lana lentes malla
    medias mozo padre pana papa pasaje petaca timbre torta manejar fila
    """.split()
)
# Words only Spain uses for addressing a group (vosotros); the -áis/-éis
# verb endings are matched separately.
_VOSOTROS_WORDS = frozenset({"vosotros", "vosotras", "vuestro", "vuestra", "vuestros", "vuestras", "os"})
_NUMBERS_IN_EIS = frozenset({"seis", "dieciseis", "veintiseis"})


def words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


@lru_cache(maxsize=None)
def _latam_markers(pack_path: str) -> frozenset[str]:
    """Single-word Latin American forms, from the pack's `why:region` rejects."""
    markers: set[str] = set()
    for path in sorted(Path(pack_path).glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            card = json.loads(line)
            if "why:region" not in card.get("tags", []):
                continue
            for fragment in card.get("reject", []):
                ws = words(fragment)
                # Whole-sentence rejects are grammar (hoy comí), not lexicon.
                if len(ws) > 2:
                    continue
                head = fold_accents(ws[-1])
                if head not in {fold_accents(a) for a in _AMBIGUOUS_IN_SPAIN}:
                    markers.add(head)
    return frozenset(markers)


def matches(word: str, markers: frozenset[str] | set[str]) -> bool:
    """`word` (accent-folded) is a marker, or a marker's plural."""
    return (
        word in markers
        or (word.endswith("s") and word[:-1] in markers)
        or (word.endswith("es") and word[:-2] in markers)
    )


def dialect_markers(variety: str) -> frozenset[str]:
    """Accent-folded words that mark the *other* variety in a reply."""
    if variety == "es-ES":
        return _latam_markers(str(packs.load().path))
    return frozenset(_VOSOTROS_WORDS)


def check(text: str, variety: str = "es-ES") -> list[Issue]:
    """Problems with a model reply meant to be `variety` Spanish; [] = fine."""
    if not text.strip():
        return [Issue("empty", "no reply")]
    issues: list[Issue] = []

    if _THINKING.search(text):
        issues.append(Issue("thinking", "reasoning text leaked into the reply"))

    for inside in _PAREN.findall(text):
        if sum(w in _ENGLISH for w in words(inside)) >= 2:
            issues.append(Issue("translation", f"parenthetical translation: ({inside.strip()})"))

    english = sorted({w for w in words(_PAREN.sub(" ", text)) if w in _ENGLISH})
    if english:
        issues.append(Issue("english", "English: " + ", ".join(english)))

    markers = dialect_markers(variety)
    folded = [fold_accents(w) for w in words(text)]
    wrong = sorted({w for w in folded if matches(w, markers)})
    if variety != "es-ES":
        wrong += sorted({
            w for w in folded
            if w.endswith(("ais", "eis")) and len(w) > 4 and w not in _NUMBERS_IN_EIS
            and not matches(w, markers)
        })
    if wrong:
        other = "Latin American" if variety == "es-ES" else "Spain-only"
        issues.append(Issue("dialect", f"{other} form(s): " + ", ".join(wrong)))
    return issues
