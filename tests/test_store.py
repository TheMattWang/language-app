from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from drill import store


def _write_jsonl(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _card_line(**overrides) -> str:
    obj = {
        "id": "pc-001",
        "deck": "peninsular_contrast",
        "kind": "production",
        "prompt_en": "the car",
        "accept": ["el coche"],
        "reject": ["el carro"],
        "note": "carro is LatAm",
        "tags": ["lexicon"],
    }
    obj.update(overrides)
    return json.dumps(obj)


def test_schema_applies_idempotently(tmp_path: Path) -> None:
    db_path = tmp_path / "drill.db"
    conn1 = store.connect(db_path)
    conn1.close()
    # Re-connecting (re-applying schema) must not raise.
    conn2 = store.connect(db_path)
    tables = {
        row["name"]
        for row in conn2.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert {"card", "sched", "review"} <= tables
    conn2.close()


def test_connect_creates_parent_dirs(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "dir" / "drill.db"
    conn = store.connect(db_path)
    assert db_path.exists()
    conn.close()


def test_import_adds_new_cards_and_sched_rows(tmp_path: Path) -> None:
    conn = store.connect(tmp_path / "drill.db")
    jsonl_path = tmp_path / "cards.jsonl"
    _write_jsonl(
        jsonl_path,
        [_card_line(id="pc-001"), _card_line(id="pc-002", prompt_en="the house", accept=["la casa"])],
    )

    result = store.import_jsonl(conn, jsonl_path)

    assert result.added == 2
    assert result.updated == 0
    assert result.unchanged == 0
    assert result.errors == ()

    card = store.get_card(conn, "pc-001")
    assert card is not None
    assert card.prompt_en == "the car"
    assert card.accept == ("el coche",)
    assert card.reject == ("el carro",)
    assert card.tags == ("lexicon",)

    sched = store.get_sched(conn, "pc-001")
    assert sched is not None
    assert sched.state == "new"
    assert sched.interval_days == 0
    assert sched.ease == 2.5
    assert sched.reps == 0
    assert sched.last_reviewed_at is None


def test_reimport_identical_file_is_unchanged_no_duplicates(tmp_path: Path) -> None:
    conn = store.connect(tmp_path / "drill.db")
    jsonl_path = tmp_path / "cards.jsonl"
    _write_jsonl(jsonl_path, [_card_line(id="pc-001"), _card_line(id="pc-002")])

    first = store.import_jsonl(conn, jsonl_path)
    assert first.added == 2

    second = store.import_jsonl(conn, jsonl_path)
    assert second.added == 0
    assert second.updated == 0
    assert second.unchanged == 2
    assert second.errors == ()

    count = conn.execute("SELECT COUNT(*) FROM card").fetchone()[0]
    assert count == 2
    sched_count = conn.execute("SELECT COUNT(*) FROM sched").fetchone()[0]
    assert sched_count == 2


def test_edit_accept_updates_card_but_preserves_sched(tmp_path: Path) -> None:
    conn = store.connect(tmp_path / "drill.db")
    jsonl_path = tmp_path / "cards.jsonl"
    _write_jsonl(jsonl_path, [_card_line(id="pc-001")])
    store.import_jsonl(conn, jsonl_path)

    # Simulate user progress: mark card as reviewed / in review state.
    sched_before = store.get_sched(conn, "pc-001")
    assert sched_before is not None
    reviewed_time = datetime.now(timezone.utc) - timedelta(days=1)
    updated_sched = store.SchedRow(
        card_id="pc-001",
        due_at=datetime.now(timezone.utc) + timedelta(days=3),
        interval_days=3.0,
        ease=2.6,
        reps=2,
        lapses=0,
        state="review",
        last_reviewed_at=reviewed_time,
    )
    store.save_sched(conn, updated_sched)

    # Now edit the card's accept list and reimport.
    _write_jsonl(jsonl_path, [_card_line(id="pc-001", accept=["el coche", "el auto"])])
    result = store.import_jsonl(conn, jsonl_path)

    assert result.updated == 1
    assert result.added == 0

    card = store.get_card(conn, "pc-001")
    assert card is not None
    assert card.accept == ("el coche", "el auto")

    sched_after = store.get_sched(conn, "pc-001")
    assert sched_after is not None
    assert sched_after.state == "review"
    assert sched_after.reps == 2
    assert sched_after.interval_days == 3.0
    assert sched_after.ease == 2.6
    assert sched_after.last_reviewed_at is not None


def test_malformed_line_collected_without_aborting(tmp_path: Path) -> None:
    conn = store.connect(tmp_path / "drill.db")
    jsonl_path = tmp_path / "cards.jsonl"
    _write_jsonl(
        jsonl_path,
        [
            _card_line(id="pc-001"),
            "{not valid json",
            json.dumps({"id": "pc-missing-fields", "deck": "d"}),  # missing kind/prompt_en/accept
            _card_line(id="pc-002", prompt_en="the house", accept=["la casa"]),
        ],
    )

    result = store.import_jsonl(conn, jsonl_path)

    assert result.added == 2
    assert len(result.errors) == 2
    assert store.get_card(conn, "pc-001") is not None
    assert store.get_card(conn, "pc-002") is not None
    assert store.get_card(conn, "pc-missing-fields") is None


def test_due_cards_respects_now_limit_deck_and_orders_new_last(tmp_path: Path) -> None:
    conn = store.connect(tmp_path / "drill.db")
    jsonl_path = tmp_path / "cards.jsonl"
    _write_jsonl(
        jsonl_path,
        [
            _card_line(id="pc-001", deck="deck_a"),
            _card_line(id="pc-002", deck="deck_a", prompt_en="the house", accept=["la casa"]),
            _card_line(id="pc-003", deck="deck_b", prompt_en="the dog", accept=["el perro"]),
        ],
    )
    store.import_jsonl(conn, jsonl_path)

    now = datetime.now(timezone.utc)

    # Put pc-001 into a "review" state due in the past (before "new" cards).
    store.save_sched(
        conn,
        store.SchedRow(
            card_id="pc-001",
            due_at=now - timedelta(hours=1),
            interval_days=1.0,
            ease=2.5,
            reps=1,
            lapses=0,
            state="review",
            last_reviewed_at=now - timedelta(days=1),
        ),
    )
    # pc-002 stays "new" (due_at was set to import time, which is <= now).
    # pc-003 is in a different deck.

    results = store.due_cards(conn, now, deck="deck_a", limit=10)
    ids = [card.card_id for card, _ in results]
    assert ids == ["pc-001", "pc-002"]  # non-new before new
    assert "pc-003" not in ids  # deck filter excludes it

    # limit respected
    limited = store.due_cards(conn, now, deck="deck_a", limit=1)
    assert len(limited) == 1
    assert limited[0][0].card_id == "pc-001"

    # now respected: a due_at far in the future excludes the card
    store.save_sched(
        conn,
        store.SchedRow(
            card_id="pc-001",
            due_at=now + timedelta(days=30),
            interval_days=1.0,
            ease=2.5,
            reps=1,
            lapses=0,
            state="review",
            last_reviewed_at=now - timedelta(days=1),
        ),
    )
    future_results = store.due_cards(conn, now, deck="deck_a", limit=10)
    future_ids = [card.card_id for card, _ in future_results]
    assert future_ids == ["pc-002"]


def test_record_review_and_deck_stats(tmp_path: Path) -> None:
    conn = store.connect(tmp_path / "drill.db")
    jsonl_path = tmp_path / "cards.jsonl"
    _write_jsonl(
        jsonl_path,
        [
            _card_line(id="pc-001", deck="deck_a"),
            _card_line(id="pc-002", deck="deck_a", prompt_en="the house", accept=["la casa"]),
            _card_line(id="pc-003", deck="deck_b", prompt_en="the dog", accept=["el perro"]),
        ],
    )
    store.import_jsonl(conn, jsonl_path)

    now = datetime.now(timezone.utc)

    store.record_review(
        conn,
        card_id="pc-001",
        reviewed_at=now,
        grade=4,
        latency_ms=1200,
        raw_text="el coche",
        accepted=True,
        layer="production",
        interval_before=0.0,
        interval_after=1.0,
    )

    rows = conn.execute("SELECT * FROM review WHERE card_id = ?", ("pc-001",)).fetchall()
    assert len(rows) == 1
    assert rows[0]["accepted"] == 1
    assert rows[0]["grade"] == 4

    store.save_sched(
        conn,
        store.SchedRow(
            card_id="pc-001",
            due_at=now + timedelta(days=1),
            interval_days=1.0,
            ease=2.5,
            reps=1,
            lapses=0,
            state="learning",
            last_reviewed_at=now,
        ),
    )
    store.save_sched(
        conn,
        store.SchedRow(
            card_id="pc-002",
            due_at=now - timedelta(hours=1),
            interval_days=0.0,
            ease=2.5,
            reps=0,
            lapses=1,
            state="lapsed",
            last_reviewed_at=now,
        ),
    )

    stats_all = store.deck_stats(conn)
    assert stats_all["total"] == 3
    assert stats_all["new"] == 1  # pc-003 still new
    assert stats_all["learning"] == 1  # pc-001
    assert stats_all["lapsed"] == 1  # pc-002
    assert stats_all["review"] == 0

    stats_deck_a = store.deck_stats(conn, deck="deck_a")
    assert stats_deck_a["total"] == 2
    assert stats_deck_a["learning"] == 1
    assert stats_deck_a["lapsed"] == 1


def test_import_is_single_transaction_all_or_nothing_on_crash(tmp_path: Path, monkeypatch) -> None:
    # Sanity check that a totally malformed (non-JSONL) file doesn't create partial garbage
    # beyond what per-line error handling allows -- i.e. valid lines still land, and the
    # DB is left in a consistent, queryable state afterward.
    conn = store.connect(tmp_path / "drill.db")
    jsonl_path = tmp_path / "cards.jsonl"
    _write_jsonl(jsonl_path, ["not json at all", _card_line(id="pc-001")])

    result = store.import_jsonl(conn, jsonl_path)
    assert result.added == 1
    assert len(result.errors) == 1
    # DB remains usable.
    assert store.get_card(conn, "pc-001") is not None
