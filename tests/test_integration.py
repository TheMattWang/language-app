"""End-to-end wiring plus regressions for defects found in review.

Each test here corresponds to something that was actually broken when the
modules were first assembled, not to a hypothetical.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from drill import store
from drill.grader import grade
from drill.scheduler import Grade, SchedState, review as reschedule

UTC = timezone.utc


def _write(tmp_path, rows):
    p = tmp_path / "deck.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return p


def _card(**over):
    base = {
        "id": "c1",
        "deck": "d",
        "kind": "production",
        "prompt_en": "the car",
        "accept": ["el coche"],
        "reject": ["carro"],
        "note": "first note",
        "tags": ["lexicon"],
    }
    base.update(over)
    return base


# --- regression: note/tags were excluded from content_hash ------------------


def test_note_only_edit_persists(tmp_path):
    """A note-only edit used to hash identical and be silently discarded."""
    conn = store.connect(tmp_path / "a.db")
    store.import_jsonl(conn, _write(tmp_path, [_card()]))

    res = store.import_jsonl(conn, _write(tmp_path, [_card(note="corrected note")]))
    assert res.updated == 1, "note-only edit was treated as unchanged"
    assert store.get_card(conn, "c1").note == "corrected note"
    conn.close()


def test_tags_only_edit_persists(tmp_path):
    conn = store.connect(tmp_path / "b.db")
    store.import_jsonl(conn, _write(tmp_path, [_card()]))

    res = store.import_jsonl(conn, _write(tmp_path, [_card(tags=["lexicon", "vosotros"])]))
    assert res.updated == 1
    assert "vosotros" in store.get_card(conn, "c1").tags
    conn.close()


def test_edit_preserves_scheduling_progress(tmp_path):
    """Fixing a typo in a card must not reset what the learner has earned."""
    conn = store.connect(tmp_path / "c.db")
    store.import_jsonl(conn, _write(tmp_path, [_card()]))

    row = store.get_sched(conn, "c1")
    store.save_sched(conn, store.SchedRow(**{**row.__dict__, "reps": 7, "interval_days": 12.0}))

    store.import_jsonl(conn, _write(tmp_path, [_card(accept=["el coche", "coche"])]))
    after = store.get_sched(conn, "c1")
    assert after.reps == 7 and after.interval_days == 12.0
    conn.close()


# --- regression: due_at compared as strings, only valid in one offset -------


def test_non_utc_datetime_still_orders_correctly(tmp_path):
    """due_cards compares ISO strings; a non-UTC tz must not corrupt order."""
    conn = store.connect(tmp_path / "d.db")
    store.import_jsonl(conn, _write(tmp_path, [_card()]))

    row = store.get_sched(conn, "c1")
    # Same instant, expressed in Madrid time (+02:00). Naive string
    # comparison against a UTC-stamped "now" would sort this wrong.
    madrid = datetime(2026, 9, 20, 12, 0, tzinfo=ZoneInfo("Europe/Madrid"))
    store.save_sched(conn, store.SchedRow(**{**row.__dict__, "due_at": madrid}))

    just_after = madrid.astimezone(UTC) + timedelta(minutes=1)
    assert store.due_cards(conn, just_after), "card due in +02:00 was not seen as due"

    just_before = madrid.astimezone(UTC) - timedelta(minutes=1)
    assert not store.due_cards(conn, just_before), "card became due too early"
    conn.close()


# --- regression: ñ rejection gave no explanation ----------------------------


def test_ene_rejection_explains_itself():
    v = grade("donde esta el bano", accept=["dónde está el baño"])
    assert not v.accepted
    assert "ñ" in v.reason, f"unhelpful rejection: {v.reason!r}"


# --- end-to-end -------------------------------------------------------------


def test_import_review_reschedule_round_trip(tmp_path):
    conn = store.connect(tmp_path / "e.db")
    store.import_jsonl(conn, _write(tmp_path, [_card()]))
    now = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)
    # Pin due_at rather than inheriting import_jsonl's wall-clock stamp: with a
    # fixed `now`, a real clock later than it makes the card not-yet-due and
    # this test fails for reasons that have nothing to do with what it checks.
    conn.execute("UPDATE sched SET due_at = ?", (store._iso(now - timedelta(hours=1)),))
    conn.commit()

    queue = store.due_cards(conn, now)
    assert len(queue) == 1
    card, row = queue[0]

    verdict = grade("el coche", accept=card.accept, reject=card.reject)
    assert verdict.accepted

    state = SchedState(
        due_at=row.due_at,
        interval_days=row.interval_days,
        ease=row.ease,
        reps=row.reps,
        lapses=row.lapses,
        state=row.state,
        last_reviewed_at=row.last_reviewed_at,
    )
    nxt = reschedule(state, Grade.GOOD, now)
    store.save_sched(conn, store.SchedRow(card_id=card.card_id, **nxt.__dict__))
    store.record_review(
        conn,
        card_id=card.card_id,
        reviewed_at=now,
        grade=int(Grade.GOOD),
        latency_ms=1200,
        raw_text="el coche",
        accepted=True,
        layer=verdict.layer,
        interval_before=row.interval_days,
        interval_after=nxt.interval_days,
    )
    conn.commit()

    assert not store.due_cards(conn, now), "card still due immediately after a correct review"
    assert store.deck_stats(conn)["learning"] == 1
    conn.close()


def test_latam_answer_blocks_unlock_end_to_end(tmp_path):
    """The behaviour the whole tool exists for."""
    conn = store.connect(tmp_path / "f.db")
    store.import_jsonl(conn, _write(tmp_path, [_card()]))
    card, _ = store.due_cards(conn, datetime.now(UTC))[0]

    v = grade("el carro", accept=card.accept, reject=card.reject)
    assert not v.accepted and v.layer == "L1_banned"
    assert "coche" in (v.detail or "")
    conn.close()
