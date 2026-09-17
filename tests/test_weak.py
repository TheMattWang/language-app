from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from drill import store


def _write_jsonl(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _card_line(**overrides) -> str:
    obj = {
        "id": "pc-001",
        "deck": "trip",
        "kind": "production",
        "prompt_en": "the car",
        "accept": ["el coche"],
        "reject": ["el carro"],
        "note": None,
        "tags": ["lexicon"],
    }
    obj.update(overrides)
    return json.dumps(obj)


def _record(
    conn,
    card_id: str,
    *,
    accepted: bool,
    reviewed_at: datetime,
    grade: int = 3,
    latency_ms: int | None = 1000,
) -> None:
    store.record_review(
        conn,
        card_id=card_id,
        reviewed_at=reviewed_at,
        grade=grade,
        latency_ms=latency_ms,
        raw_text="x",
        accepted=accepted,
        layer="L2_exact" if accepted else None,
        interval_before=0.0,
        interval_after=1.0,
    )


def _seed_deck(conn, jsonl_path: Path) -> None:
    _write_jsonl(
        jsonl_path,
        [
            # subjunctive: weak (1/4 correct), 2 cards
            _card_line(id="c1", prompt_en="I hope you come", accept=["espero que vengas"], tags=["subjunctive"]),
            _card_line(id="c2", prompt_en="I want you to eat", accept=["quiero que comas"], tags=["subjunctive"]),
            # ser_estar: strong (3/3 correct), 1 card, also tagged pharmacy
            _card_line(id="c3", prompt_en="the pharmacy is open", accept=["la farmacia esta abierta"], tags=["ser_estar", "pharmacy"]),
            # vosotros: only 2 attempts, should be hidden by the >=3 threshold
            _card_line(id="c4", prompt_en="you all eat", accept=["vosotros comeis"], tags=["vosotros"]),
        ],
    )
    store.import_jsonl(conn, jsonl_path)


def test_tag_performance_multi_tag_card_counts_toward_each_tag(tmp_path: Path) -> None:
    conn = store.connect(tmp_path / "drill.db")
    _seed_deck(conn, tmp_path / "cards.jsonl")
    now = datetime.now(timezone.utc)

    _record(conn, "c3", accepted=True, reviewed_at=now)

    stats = {s.tag: s for s in store.tag_performance(conn)}
    assert stats["ser_estar"].attempts == 1
    assert stats["ser_estar"].correct == 1
    assert stats["pharmacy"].attempts == 1
    assert stats["pharmacy"].correct == 1


def test_tag_performance_accuracy_ordering_and_threshold(tmp_path: Path) -> None:
    conn = store.connect(tmp_path / "drill.db")
    _seed_deck(conn, tmp_path / "cards.jsonl")
    now = datetime.now(timezone.utc)

    # subjunctive: 1/4 correct across two cards
    _record(conn, "c1", accepted=False, reviewed_at=now)
    _record(conn, "c1", accepted=False, reviewed_at=now)
    _record(conn, "c2", accepted=False, reviewed_at=now)
    _record(conn, "c2", accepted=True, reviewed_at=now)

    # ser_estar / pharmacy: 3/3 correct
    _record(conn, "c3", accepted=True, reviewed_at=now)
    _record(conn, "c3", accepted=True, reviewed_at=now)
    _record(conn, "c3", accepted=True, reviewed_at=now)

    # vosotros: only 2 attempts -- must be excluded by attempts >= 3 filtering
    _record(conn, "c4", accepted=False, reviewed_at=now)
    _record(conn, "c4", accepted=True, reviewed_at=now)

    stats = store.tag_performance(conn)
    by_tag = {s.tag: s for s in stats}

    assert by_tag["subjunctive"].attempts == 4
    assert by_tag["subjunctive"].correct == 1
    assert by_tag["subjunctive"].accuracy == 0.25
    assert by_tag["subjunctive"].cards == 2

    assert by_tag["ser_estar"].accuracy == 1.0
    assert by_tag["vosotros"].attempts == 2

    # weakest-first ordering (store returns all tags; CLI applies the
    # attempts>=3 threshold, but ordering must already be weakest-first).
    eligible = [s.tag for s in stats if s.attempts >= 3]
    assert eligible[0] == "subjunctive"
    assert "vosotros" not in eligible


def test_tag_performance_since_filters_older_reviews(tmp_path: Path) -> None:
    conn = store.connect(tmp_path / "drill.db")
    _seed_deck(conn, tmp_path / "cards.jsonl")
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=30)

    _record(conn, "c1", accepted=False, reviewed_at=old)
    _record(conn, "c1", accepted=False, reviewed_at=old)
    _record(conn, "c2", accepted=True, reviewed_at=now)

    recent = {s.tag: s for s in store.tag_performance(conn, since=now - timedelta(days=1))}
    assert recent["subjunctive"].attempts == 1
    assert recent["subjunctive"].correct == 1

    full_history = {s.tag: s for s in store.tag_performance(conn)}
    assert full_history["subjunctive"].attempts == 3


def test_tag_performance_deck_filter(tmp_path: Path) -> None:
    conn = store.connect(tmp_path / "drill.db")
    jsonl_path = tmp_path / "cards.jsonl"
    _write_jsonl(
        jsonl_path,
        [
            _card_line(id="c1", deck="trip", tags=["subjunctive"]),
            _card_line(id="c2", deck="other_deck", prompt_en="x", accept=["y"], tags=["subjunctive"]),
        ],
    )
    store.import_jsonl(conn, jsonl_path)
    now = datetime.now(timezone.utc)
    _record(conn, "c1", accepted=True, reviewed_at=now)
    _record(conn, "c2", accepted=False, reviewed_at=now)

    stats = {s.tag: s for s in store.tag_performance(conn, deck="trip")}
    assert stats["subjunctive"].attempts == 1
    assert stats["subjunctive"].correct == 1
    assert stats["subjunctive"].cards == 1


def test_tag_performance_empty_db_returns_empty_list(tmp_path: Path) -> None:
    conn = store.connect(tmp_path / "drill.db")
    assert store.tag_performance(conn) == []


def test_hardest_cards_ranks_by_misses(tmp_path: Path) -> None:
    conn = store.connect(tmp_path / "drill.db")
    _seed_deck(conn, tmp_path / "cards.jsonl")
    now = datetime.now(timezone.utc)

    # c1: 3 misses / 3 attempts
    _record(conn, "c1", accepted=False, reviewed_at=now)
    _record(conn, "c1", accepted=False, reviewed_at=now)
    _record(conn, "c1", accepted=False, reviewed_at=now)
    # c2: 1 miss / 2 attempts
    _record(conn, "c2", accepted=False, reviewed_at=now)
    _record(conn, "c2", accepted=True, reviewed_at=now)
    # c3: 0 misses / 2 attempts
    _record(conn, "c3", accepted=True, reviewed_at=now)
    _record(conn, "c3", accepted=True, reviewed_at=now)
    # c4: only 1 attempt -- must be excluded (needs >= 2)
    _record(conn, "c4", accepted=False, reviewed_at=now)

    results = store.hardest_cards(conn)
    ids = [card.card_id for card, _, _ in results]

    assert ids[0] == "c1"
    assert ids[1] == "c2"
    assert "c4" not in ids
    card1, attempts1, misses1 = results[0]
    assert attempts1 == 3
    assert misses1 == 3


def test_hardest_cards_empty_db_returns_empty_list(tmp_path: Path) -> None:
    conn = store.connect(tmp_path / "drill.db")
    assert store.hardest_cards(conn) == []
