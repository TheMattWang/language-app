"""New-card introduction order.

Added in review. The original implementation took new cards by card_id,
which had two consequences worth locking down: grammar (`gr-*`) was
introduced before travel (`tv-*`) purely because g sorts before t, and a
whole deck would be drained before the next one started -- leaving the
last deck introduced days before departure, where the horizon clamp gives
it almost no repetitions.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from drill import store

UTC = timezone.utc
NOW = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)


def _seed(tmp_path: Path, counts: dict[str, int]):
    rows = []
    for deck, n in counts.items():
        prefix = deck[:2]
        for i in range(1, n + 1):
            rows.append(
                {
                    "id": f"{prefix}-{i:03d}", "deck": deck, "kind": "production",
                    "prompt_en": f"{deck} {i}", "accept": [f"respuesta {i}"],
                    "reject": [], "note": None, "tags": [deck],
                }
            )
    p = tmp_path / "d.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    conn = store.connect(tmp_path / "d.db")
    store.import_jsonl(conn, p)
    # Pin due_at so the fixed NOW postdates card creation regardless of when
    # the suite actually runs.
    conn.execute("UPDATE sched SET due_at = ?", (store._iso(NOW - timedelta(days=1)),))
    conn.commit()
    return conn


def test_every_deck_starts_on_day_one(tmp_path: Path) -> None:
    conn = _seed(tmp_path, {"travel_production": 100, "peninsular_contrast": 120,
                            "grammar_repair": 80})
    q = store.daily_queue(conn, NOW, new_per_day=20)
    by_deck = Counter(card.deck for card, _ in q.items)
    assert len(by_deck) == 3, f"a deck was left out of day one: {by_deck}"
    assert min(by_deck.values()) >= 5, f"a deck barely appeared: {by_deck}"
    conn.close()


def test_travel_outranks_grammar_despite_alphabetical_id(tmp_path: Path) -> None:
    """`gr-` sorts before `tv-`; priority must win over the id."""
    conn = _seed(tmp_path, {"travel_production": 10, "grammar_repair": 10})
    q = store.daily_queue(conn, NOW, new_per_day=2)
    decks = [card.deck for card, _ in q.items]
    assert decks[0] == "travel_production", f"grammar led the queue: {decks}"
    conn.close()


def test_unknown_deck_sorts_between_known_ones(tmp_path: Path) -> None:
    conn = _seed(tmp_path, {"travel_production": 5, "zzz_custom": 5, "grammar_repair": 5})
    q = store.daily_queue(conn, NOW, new_per_day=3)
    decks = [card.deck for card, _ in q.items]
    assert decks.index("travel_production") < decks.index("zzz_custom")
    assert decks.index("zzz_custom") < decks.index("grammar_repair")
    conn.close()


def test_exhausted_deck_does_not_stall_the_round_robin(tmp_path: Path) -> None:
    """A deck running out must not cap the others below the daily budget."""
    conn = _seed(tmp_path, {"travel_production": 1, "peninsular_contrast": 50})
    q = store.daily_queue(conn, NOW, new_per_day=20)
    assert len(q.items) == 20, f"budget not filled after a deck ran dry: {len(q.items)}"
    conn.close()


def test_single_deck_still_works(tmp_path: Path) -> None:
    conn = _seed(tmp_path, {"peninsular_contrast": 30})
    q = store.daily_queue(conn, NOW, new_per_day=20)
    assert len(q.items) == 20
    assert [c.card_id for c, _ in q.items] == sorted(c.card_id for c, _ in q.items)
    conn.close()


def test_whole_collection_fits_before_departure(tmp_path: Path) -> None:
    """The whole collection over the 16 days remaining on 2026-09-17.

    Re-check this whenever a deck is added: every new deck makes the
    arithmetic tighter, and silently not reaching the last cards before the
    flight is the failure this asserts against.
    """
    conn = _seed(tmp_path, {"travel_production": 100, "peninsular_contrast": 120,
                            "grammar_repair": 80, "numbers_listening": 85,
                            "cloze_grammar": 75})
    introduced = 0
    day = NOW
    for _ in range(16):
        q = store.daily_queue(conn, day, new_per_day=30)
        introduced += q.new_introduced
        # mark them introduced so tomorrow offers the next batch
        for card, _row in q.items:
            store.record_review(
                conn, card_id=card.card_id, reviewed_at=day, grade=2, latency_ms=1,
                raw_text="x", accepted=True, layer="L2_exact",
                interval_before=0.0, interval_after=1.0,
            )
            conn.execute(
                "UPDATE sched SET state='review', due_at=? WHERE card_id=?",
                (store._iso(day + timedelta(days=90)), card.card_id),
            )
        conn.commit()
        day += timedelta(days=1)
    assert introduced >= 460, f"only {introduced}/460 cards would be seen before the flight"
    conn.close()


def test_daily_budget_is_global_not_per_deck(tmp_path: Path) -> None:
    """Filtering by deck must not grant a fresh daily allowance.

    The GUI's deck picker calls daily_queue with a deck, so a per-deck cap
    let the budget be spent once per deck: 20 on "all", then another batch
    on each individual deck. Deck says which cards may be offered, never how
    many count against today's cap.
    """
    conn = _seed(tmp_path, {"travel_production": 50, "peninsular_contrast": 50,
                            "grammar_repair": 50})
    q = store.daily_queue(conn, NOW, new_per_day=20)
    assert q.new_introduced == 20

    for card, _row in q.items:
        store.record_review(
            conn, card_id=card.card_id, reviewed_at=NOW, grade=2, latency_ms=1,
            raw_text="x", accepted=True, layer="L2_exact",
            interval_before=0.0, interval_after=1.0,
        )
    conn.commit()

    for deck in ("travel_production", "peninsular_contrast", "grammar_repair"):
        scoped = store.daily_queue(conn, NOW, deck=deck, new_per_day=20)
        assert scoped.new_introduced == 0, (
            f"filtering to {deck} handed out {scoped.new_introduced} extra new cards"
        )
    conn.close()
