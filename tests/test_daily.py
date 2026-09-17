from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from drill import store

DAY = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def _write_jsonl(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _card_line(**overrides) -> str:
    obj = {
        "id": "c001",
        "deck": "deck_a",
        "kind": "production",
        "prompt_en": "the car",
        "accept": ["el coche"],
        "reject": [],
        "note": None,
        "tags": [],
    }
    obj.update(overrides)
    return json.dumps(obj)


def _import_new_cards(conn, tmp_path: Path, n: int, *, deck: str = "deck_a", start: int = 1) -> list[str]:
    """Import n freshly-numbered 'new' cards, returning their ids in card_id order.

    `import_jsonl` stamps `due_at` with the real wall-clock time, which is
    unrelated to the fixed `DAY` these tests reason about -- so each card's
    due_at is pinned explicitly (still 'new', still a fresh card) to a time
    safely before `DAY`, the way an already-imported, already-due deck would
    look days later.
    """
    ids = [f"c{i:03d}" for i in range(start, start + n)]
    lines = [
        _card_line(id=cid, deck=deck, prompt_en=f"word {cid}", accept=[f"palabra{cid}"])
        for cid in ids
    ]
    path = tmp_path / f"{deck}-{start}.jsonl"
    _write_jsonl(path, lines)
    store.import_jsonl(conn, path)
    for cid in ids:
        store.save_sched(
            conn,
            store.SchedRow(
                card_id=cid,
                due_at=DAY - timedelta(days=2),
                interval_days=0.0,
                ease=2.5,
                reps=0,
                lapses=0,
                state="new",
                last_reviewed_at=None,
            ),
        )
    return ids


def _introduce(conn, card_id: str, *, reviewed_at: datetime, due_at: datetime) -> None:
    """Simulate a completed review that moves a card out of 'new' state, the way
    cmd_review's loop does (record_review + save_sched together)."""
    store.record_review(
        conn,
        card_id=card_id,
        reviewed_at=reviewed_at,
        grade=3,
        latency_ms=800,
        raw_text="x",
        accepted=True,
        layer="L2_exact",
        interval_before=0.0,
        interval_after=1.0,
    )
    store.save_sched(
        conn,
        store.SchedRow(
            card_id=card_id,
            due_at=due_at,
            interval_days=1.0,
            ease=2.5,
            reps=1,
            lapses=0,
            state="learning",
            last_reviewed_at=reviewed_at,
        ),
    )


def test_new_cards_capped_at_new_per_day(tmp_path: Path) -> None:
    conn = store.connect(tmp_path / "drill.db")
    _import_new_cards(conn, tmp_path, 20)

    queue = store.daily_queue(conn, DAY, new_per_day=15, max_cards=40)

    assert queue.due_reviews == 0
    assert queue.new_introduced == 15
    assert queue.new_remaining == 0
    assert len(queue.items) == 15
    # authored order
    assert [c.card_id for c, _ in queue.items] == [f"c{i:03d}" for i in range(1, 16)]


def test_already_introduced_today_counts_against_cap(tmp_path: Path) -> None:
    conn = store.connect(tmp_path / "drill.db")
    ids = _import_new_cards(conn, tmp_path, 20)

    earlier_today = DAY - timedelta(hours=3)
    for cid in ids[:5]:
        _introduce(conn, cid, reviewed_at=earlier_today, due_at=DAY + timedelta(days=1))

    assert store.new_cards_introduced_today(conn, DAY) == 5

    queue = store.daily_queue(conn, DAY, new_per_day=15, max_cards=40)

    # 15 - 5 already introduced = only 10 more new cards offered
    assert queue.new_introduced == 10
    assert queue.new_remaining == 0
    assert len(queue.items) == 10
    assert [c.card_id for c, _ in queue.items] == ids[5:15]


def test_reviews_are_never_displaced_by_new_cards(tmp_path: Path) -> None:
    conn = store.connect(tmp_path / "drill.db")
    ids = _import_new_cards(conn, tmp_path, 20)

    # Turn the first 5 into overdue "review" state cards.
    for cid in ids[:5]:
        store.save_sched(
            conn,
            store.SchedRow(
                card_id=cid,
                due_at=DAY - timedelta(hours=1),
                interval_days=1.0,
                ease=2.5,
                reps=1,
                lapses=0,
                state="review",
                last_reviewed_at=DAY - timedelta(days=1),
            ),
        )

    queue = store.daily_queue(conn, DAY, new_per_day=15, max_cards=40)

    assert queue.due_reviews == 5
    assert queue.new_introduced == 15  # full new_per_day budget, untouched by reviews
    assert queue.backlog == 0
    assert len(queue.items) == 20
    review_ids = {c.card_id for c, s in queue.items if s.state != "new"}
    assert review_ids == set(ids[:5])


def test_max_cards_truncates_reviews_and_reports_backlog(tmp_path: Path) -> None:
    conn = store.connect(tmp_path / "drill.db")
    ids = _import_new_cards(conn, tmp_path, 50)

    for cid in ids:
        store.save_sched(
            conn,
            store.SchedRow(
                card_id=cid,
                due_at=DAY - timedelta(hours=1),
                interval_days=1.0,
                ease=2.5,
                reps=1,
                lapses=0,
                state="review",
                last_reviewed_at=DAY - timedelta(days=1),
            ),
        )

    queue = store.daily_queue(conn, DAY, new_per_day=15, max_cards=40)

    assert queue.due_reviews == 50
    assert len(queue.items) == 40
    assert queue.backlog == 10
    assert queue.new_introduced == 0  # no room left for new cards at all


def test_cap_resets_on_next_utc_day(tmp_path: Path) -> None:
    conn = store.connect(tmp_path / "drill.db")
    ids = _import_new_cards(conn, tmp_path, 20)

    yesterday = DAY - timedelta(days=1)
    for cid in ids[:15]:
        _introduce(conn, cid, reviewed_at=yesterday, due_at=DAY + timedelta(days=30))

    assert store.new_cards_introduced_today(conn, yesterday) == 15
    assert store.new_cards_introduced_today(conn, DAY) == 0

    queue = store.daily_queue(conn, DAY, new_per_day=15, max_cards=40)
    assert queue.new_introduced == 5  # only the 5 still-new cards remain
    assert queue.new_remaining == 10


def test_review_on_previous_day_not_counted_today(tmp_path: Path) -> None:
    conn = store.connect(tmp_path / "drill.db")
    ids = _import_new_cards(conn, tmp_path, 1)

    _introduce(conn, ids[0], reviewed_at=DAY - timedelta(days=1), due_at=DAY + timedelta(days=30))

    assert store.new_cards_introduced_today(conn, DAY) == 0


def test_empty_deck_returns_empty_queue(tmp_path: Path) -> None:
    conn = store.connect(tmp_path / "drill.db")
    queue = store.daily_queue(conn, DAY, new_per_day=15, max_cards=40)

    assert queue.items == ()
    assert queue.due_reviews == 0
    assert queue.new_introduced == 0
    assert queue.new_remaining == 15
    assert queue.backlog == 0


def test_new_per_day_zero_returns_no_new_cards(tmp_path: Path) -> None:
    conn = store.connect(tmp_path / "drill.db")
    _import_new_cards(conn, tmp_path, 10)

    queue = store.daily_queue(conn, DAY, new_per_day=0, max_cards=40)

    assert queue.items == ()
    assert queue.new_introduced == 0
    assert queue.new_remaining == 0


def test_deck_filter_applies_to_daily_queue_and_introduced_today(tmp_path: Path) -> None:
    conn = store.connect(tmp_path / "drill.db")
    _import_new_cards(conn, tmp_path, 5, deck="deck_a", start=1)
    _import_new_cards(conn, tmp_path, 5, deck="deck_b", start=100)

    queue = store.daily_queue(conn, DAY, deck="deck_a", new_per_day=15, max_cards=40)
    assert len(queue.items) == 5
    assert all(c.deck == "deck_a" for c, _ in queue.items)
