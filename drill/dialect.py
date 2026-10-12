"""Variety-aware card import: one deck, studied as Spain or Latin America.

Decks are authored for Spain (es-ES). A card's reject list holds forms
that are wrong *for Spain*, often as fragments (`celular`, `tienen`), and
its `why:` tag says why. Those fragments cannot simply be moved into the
accept list for a Latin American learner -- a bare `celular` would then
pass as the answer to a whole sentence. So the variety is resolved once,
at import time, from what the card states explicitly:

* `"varieties": [...]` limits a card to the listed varieties.
* `"variants": {"es-419": {"accept": [...], "reject": [...]}}` gives the
  answer lists for another variety.
* A card rejected for region or register (`why:region`, `why:register`)
  with no variant for the learner's variety is Spain-specific, and is
  skipped rather than graded against Spain's answers.

The grader never changes -- only which cards and lists it is given.
"""

from __future__ import annotations

from typing import Sequence

__all__ = ["AUTHORED_VARIETY", "VARIETY_REASONS", "resolve"]

AUTHORED_VARIETY = "es-ES"

# Reject reasons that depend on the variety rather than on the Spanish.
VARIETY_REASONS = frozenset({"region", "register"})


def resolve(
    obj: dict,
    accept: Sequence[str],
    reject: Sequence[str],
    variety: str,
) -> tuple[list[str], list[str]] | None:
    """The (accept, reject) lists for `variety`, or None to skip the card."""
    allowed = obj.get("varieties")
    if allowed is not None and variety not in allowed:
        return None
    if variety == AUTHORED_VARIETY:
        return list(accept), list(reject)

    variant = obj.get("variants", {}).get(variety)
    if variant is not None:
        return list(variant["accept"]), list(variant.get("reject", []))

    reasons = {t[len("why:"):] for t in obj.get("tags", []) if t.startswith("why:")}
    if reasons & VARIETY_REASONS:
        return None
    return list(accept), list(reject)
