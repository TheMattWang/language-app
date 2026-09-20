"""Offline markdown export: the learner's own weak material, readable on
paper or a phone screen with no laptop and no signal.

`docs/SURVIVAL.md` is the generic phrasebook; this is the personalised one,
built from what the learner actually keeps getting wrong -- weak tags,
hardest cards, and register traps (reject-list misses). No colour codes:
this is a file, not a terminal.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from drill import cloze, store

__all__ = ["build_markdown"]

# 2026-10-03: the flight date this whole tool exists for.
TRAVEL_DATE = date(2026, 10, 3)

_MIN_TAG_ATTEMPTS = 3  # same floor `cmd_weak` uses
_MAX_TAGS_SHOWN = 10


@dataclass(frozen=True)
class _FailingCard:
    card: store.Card
    attempts: int
    misses: int


def _row_to_card(row: sqlite3.Row) -> store.Card:
    """Same shape as `store._row_to_card`, kept local since export needs its
    own queries (a configurable `min_attempts` floor, a reject-list filter)
    that store's public helpers don't expose -- `store.py` is not to be
    touched for this feature."""
    import json

    return store.Card(
        card_id=row["card_id"],
        deck=row["deck"],
        kind=row["kind"],
        prompt_en=row["prompt_en"],
        accept=tuple(json.loads(row["accept_json"])),
        reject=tuple(json.loads(row["reject_json"])),
        note=row["note"],
        tags=tuple(json.loads(row["tags_json"])),
    )


def _spanish_form(card: store.Card) -> tuple[str, str | None]:
    """Return (spanish, english) for a card -- the filled sentence for a
    cloze card (never a `___` gap; unreadable on paper with no way to
    check), else the first accept form and the English prompt."""
    if cloze.is_cloze(card.kind):
        cz = cloze.parse(card.prompt_en)
        filled = cloze.render_filled(cz, card.accept[0] if card.accept else "")
        return filled, cz.meaning_en
    accept = card.accept[0] if card.accept else ""
    return accept, card.prompt_en


def _weak_tags(conn: sqlite3.Connection, deck: str | None) -> list[store.TagStat]:
    tag_stats = store.tag_performance(conn, deck=deck)
    eligible = [t for t in tag_stats if t.attempts >= _MIN_TAG_ATTEMPTS]
    return eligible[:_MAX_TAGS_SHOWN]


def _failing_cards(
    conn: sqlite3.Connection, deck: str | None, limit: int, min_attempts: int
) -> list[_FailingCard]:
    """Cards actually missed at least once, worst-misses-first, with at
    least `min_attempts` attempts. Deliberately excludes zero-miss cards --
    "las que fallas" means cards you get wrong, not just any drilled card."""
    query = (
        "SELECT card.*, COUNT(review.review_id) AS attempts, "
        "SUM(CASE WHEN review.accepted = 0 THEN 1 ELSE 0 END) AS misses "
        "FROM card JOIN review ON card.card_id = review.card_id"
    )
    params: list = []
    if deck is not None:
        query += " WHERE card.deck = ?"
        params.append(deck)
    query += (
        " GROUP BY card.card_id"
        " HAVING COUNT(review.review_id) >= ? AND SUM(CASE WHEN review.accepted = 0 THEN 1 ELSE 0 END) >= 1"
        " ORDER BY misses DESC, (CAST(attempts - misses AS REAL) / attempts) ASC, card.card_id ASC"
        " LIMIT ?"
    )
    params.append(min_attempts)
    params.append(limit)

    out: list[_FailingCard] = []
    for row in conn.execute(query, params).fetchall():
        out.append(_FailingCard(card=_row_to_card(row), attempts=row["attempts"], misses=row["misses"]))
    return out


def _trampas_cards(conn: sqlite3.Connection, deck: str | None) -> list[store.Card]:
    """Every card with a non-empty reject list that's been missed at least
    once -- the register material (LatAm vs peninsular forms, etc)."""
    query = "SELECT * FROM card WHERE reject_json != '[]'"
    params: list = []
    if deck is not None:
        query += " AND deck = ?"
        params.append(deck)
    reject_cards = [_row_to_card(row) for row in conn.execute(query, params).fetchall()]
    if not reject_cards:
        return []

    ids = [c.card_id for c in reject_cards]
    placeholders = ",".join("?" * len(ids))
    missed_ids = {
        r["card_id"]
        for r in conn.execute(
            f"SELECT DISTINCT card_id FROM review WHERE accepted = 0 AND card_id IN ({placeholders})",
            ids,
        ).fetchall()
    }
    return [c for c in reject_cards if c.card_id in missed_ids]


def _fmt_generated(now: datetime) -> str:
    return now.strftime("%Y-%m-%d")


def _days_until_flight(now: datetime) -> int:
    return (TRAVEL_DATE - now.date()).days


def build_markdown(
    conn: sqlite3.Connection,
    *,
    deck: str | None = None,
    limit: int = 60,
    min_attempts: int = 2,
    now: datetime,
) -> str:
    lines: list[str] = []

    days_left = _days_until_flight(now)
    if days_left > 0:
        countdown = f"{days_left} día(s) para el vuelo (2026-10-03)"
    elif days_left == 0:
        countdown = "¡El vuelo es hoy! (2026-10-03)"
    else:
        countdown = f"vuelo hace {-days_left} día(s) (2026-10-03)"

    lines.append("# Mis fallos — repaso de español")
    lines.append("")
    lines.append(f"Generado: {_fmt_generated(now)} -- {countdown}")
    if deck:
        lines.append(f"Mazo: `{deck}`")
    lines.append("")

    # 2. Tus puntos debiles
    lines.append("## Tus puntos débiles")
    lines.append("")
    weak = _weak_tags(conn, deck)
    if not weak:
        lines.append(
            "No hay suficiente historial todavía para clasificar puntos débiles "
            f"(se necesitan al menos {_MIN_TAG_ATTEMPTS} intentos por etiqueta). "
            "Sigue practicando y vuelve a generar este archivo más tarde."
        )
    else:
        for t in weak:
            acc_pct = f"{t.accuracy * 100:.0f}%"
            lines.append(f"- **{t.tag}** -- {acc_pct} ({t.correct}/{t.attempts}), {t.cards} carta(s)")
    lines.append("")

    # 3. Las que fallas
    lines.append("## Las que fallas")
    lines.append("")
    failing = _failing_cards(conn, deck, limit, min_attempts)
    if not failing:
        lines.append(
            "Todavía no hay suficiente historial de fallos "
            f"(se necesitan al menos {min_attempts} intento(s) por carta, con al menos un fallo). "
            "Nada que mostrar aquí todavía -- eso es mejor que inventar una lista."
        )
    else:
        by_deck: dict[str, list[_FailingCard]] = {}
        for fc in failing:
            by_deck.setdefault(fc.card.deck, []).append(fc)
        for deck_name in sorted(by_deck):
            lines.append(f"### {deck_name}")
            lines.append("")
            for fc in by_deck[deck_name]:
                spanish, english = _spanish_form(fc.card)
                lines.append(f"**{spanish}** ({fc.misses}/{fc.attempts} fallos)")
                if english:
                    lines.append(f"> {english}")
                if fc.card.note:
                    lines.append(f"> _{fc.card.note}_")
                lines.append("")
    lines.append("")

    # 4. Trampas
    lines.append("## Trampas")
    lines.append("")
    trampas = _trampas_cards(conn, deck)
    if not trampas:
        lines.append("Ninguna todavía -- ninguna carta de registro (LatAm vs. peninsular) se ha fallado aún.")
    else:
        for card in trampas:
            correct, _ = _spanish_form(card)
            for bad in card.reject:
                lines.append(f"- ✗ {bad} → ✓ {correct}")
            if card.note:
                lines.append(f"  _{card.note}_")
    lines.append("")

    # 5. Closing
    lines.append("---")
    lines.append("")
    lines.append(
        "Para regenerar este archivo con tu progreso más reciente: "
        "`python3 -m drill export`"
    )
    lines.append("")

    return "\n".join(lines)
