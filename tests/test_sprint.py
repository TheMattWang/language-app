from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from drill import cli, store

DAY = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(s: str) -> str:
    """DIM/RESET escape codes are emitted unconditionally by cli.py (see
    e.g. cmd_review) regardless of --no-color, which only gates the `c()`
    wrapper -- so tests that parse printed prompt text must strip ANSI
    first rather than relying on --no-color to suppress it."""
    return _ANSI_RE.sub("", s)


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
    import json

    return json.dumps(obj)


def _import_cards(conn, tmp_path: Path, n: int, *, deck: str = "deck_a") -> list[str]:
    ids = [f"c{i:03d}" for i in range(1, n + 1)]
    lines = [
        _card_line(id=cid, deck=deck, prompt_en=f"word {cid}", accept=[f"palabra{cid}"])
        for cid in ids
    ]
    path = tmp_path / f"{deck}.jsonl"
    _write_jsonl(path, lines)
    store.import_jsonl(conn, path)
    return ids


def _mark_seen(conn, card_id: str, *, accepted: bool = True, latency_ms: int = 1000, when=None) -> None:
    """Move a card out of 'new' and log one review, the way a real review does."""
    when = when or DAY
    store.record_review(
        conn,
        card_id=card_id,
        reviewed_at=when,
        grade=3 if accepted else 0,
        latency_ms=latency_ms,
        raw_text="x",
        accepted=accepted,
        layer="L2_exact" if accepted else "L5_reject",
        interval_before=0.0,
        interval_after=1.0,
    )
    store.save_sched(
        conn,
        store.SchedRow(
            card_id=card_id,
            due_at=when + timedelta(days=1),
            interval_days=1.0,
            ease=2.5,
            reps=1,
            lapses=0 if accepted else 1,
            state="learning",
            last_reviewed_at=when,
        ),
    )


def _snapshot(conn) -> tuple[list[tuple], list[tuple]]:
    reviews = conn.execute("SELECT * FROM review ORDER BY review_id").fetchall()
    scheds = conn.execute("SELECT * FROM sched ORDER BY card_id").fetchall()
    return [tuple(r) for r in reviews], [tuple(r) for r in scheds]


def _sprint_args(db_path: Path, monkeypatch, **overrides) -> argparse.Namespace:
    defaults = dict(
        db=db_path,
        deck=None,
        count=10,
        rounds=3,
        start=8.0,
        step=2.0,
        seed=1234,
        no_color=True,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _feed_input(monkeypatch, lines: list[str]) -> None:
    """Monkeypatch builtins.input to drain a scripted list of answers -- the
    non-TTY fallback path in `_read_with_deadline`, since stdin under pytest
    is never a TTY."""
    it = iter(lines)

    def fake_input(*a, **k):
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    monkeypatch.setattr("builtins.input", fake_input)


def test_refuses_gracefully_with_no_seen_cards(tmp_path: Path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "drill.db"
    conn = store.connect(db_path)
    _import_cards(conn, tmp_path, 5)  # all remain 'new'
    conn.close()

    args = _sprint_args(db_path, monkeypatch, count=3)
    rc = cli.cmd_sprint(args)

    assert rc == 0
    out = capsys.readouterr().out
    assert "No seen cards" in out


def test_runs_requested_rounds_over_same_card_set(tmp_path: Path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "drill.db"
    conn = store.connect(db_path)
    ids = _import_cards(conn, tmp_path, 4)
    for cid in ids:
        _mark_seen(conn, cid)
    conn.close()

    # 4 cards * 3 rounds = 12 prompts to answer; answer correctly each time.
    answers = ["palabra" + cid[1:] for cid in ids] * 3
    _feed_input(monkeypatch, answers)

    args = _sprint_args(db_path, monkeypatch, count=4, rounds=3)
    rc = cli.cmd_sprint(args)
    assert rc == 0

    out = capsys.readouterr().out
    assert out.count("Round 1") == 1
    assert out.count("Round 2") == 1
    assert out.count("Round 3") == 1
    # every round drills the same 4-card set
    for i in range(1, 4):
        assert out.count(f"[{i}/4]") == 3


def test_limit_shrinks_and_floors_at_two(tmp_path: Path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "drill.db"
    conn = store.connect(db_path)
    ids = _import_cards(conn, tmp_path, 2)
    for cid in ids:
        _mark_seen(conn, cid)
    conn.close()

    _feed_input(monkeypatch, ["x"] * 100)

    args = _sprint_args(db_path, monkeypatch, count=2, rounds=5, start=8.0, step=2.0)
    cli.cmd_sprint(args)

    out = capsys.readouterr().out
    # 8, 6, 4, 2, 2 (floored)
    assert "-- 8s per card" in out
    assert "-- 6s per card" in out
    assert "-- 4s per card" in out
    assert out.count("-- 2s per card") == 2


def test_no_review_or_sched_rows_written(tmp_path: Path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "drill.db"
    conn = store.connect(db_path)
    ids = _import_cards(conn, tmp_path, 3)
    for cid in ids:
        _mark_seen(conn, cid)
    before = _snapshot(conn)
    conn.close()

    # mix of correct, wrong, and a blank/miss answer, across 2 rounds
    _feed_input(monkeypatch, ["palabrac001", "nope", "", "x", "y", "z"])

    args = _sprint_args(db_path, monkeypatch, count=3, rounds=2, start=6.0, step=2.0)
    cli.cmd_sprint(args)

    conn2 = store.connect(db_path)
    after = _snapshot(conn2)
    conn2.close()

    assert before == after, "sprint must never write review rows or change sched state"


def test_wrong_answer_counts_as_miss_without_rescheduling(tmp_path: Path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "drill.db"
    conn = store.connect(db_path)
    ids = _import_cards(conn, tmp_path, 1)
    _mark_seen(conn, ids[0])
    before = _snapshot(conn)
    conn.close()

    _feed_input(monkeypatch, ["totally wrong"])

    args = _sprint_args(db_path, monkeypatch, count=1, rounds=1, start=6.0, step=2.0)
    cli.cmd_sprint(args)
    out = capsys.readouterr().out

    assert "0/1 correct" in out
    assert "miss" in out

    conn2 = store.connect(db_path)
    after = _snapshot(conn2)
    conn2.close()
    assert before == after


def test_shuffle_differs_between_rounds_same_seed_same_set(tmp_path: Path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "drill.db"
    conn = store.connect(db_path)
    ids = _import_cards(conn, tmp_path, 8)
    for cid in ids:
        _mark_seen(conn, cid)
    conn.close()

    _feed_input(monkeypatch, ["x"] * 100)

    # Run the whole sprint once, capturing the order cards are printed in
    # per round, via the prompt lines themselves.
    args = _sprint_args(db_path, monkeypatch, count=8, rounds=3, start=8.0, step=2.0, seed=42)
    cli.cmd_sprint(args)
    out = _strip_ansi(capsys.readouterr().out)

    rounds = out.split("Round ")[1:]
    prompt_orders = []
    for r in rounds:
        prompts = [line.split("] ", 1)[1] for line in r.splitlines() if line.strip().startswith("[")]
        prompt_orders.append(prompts)

    assert len(prompt_orders) == 3
    # same set each round
    for order in prompt_orders:
        assert sorted(order) == sorted(prompt_orders[0])
    # but not the same order -- a fixed seed still advances across rounds
    assert prompt_orders[0] != prompt_orders[1] or prompt_orders[1] != prompt_orders[2]


def test_reproducible_with_fixed_seed(tmp_path: Path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "drill.db"
    conn = store.connect(db_path)
    ids = _import_cards(conn, tmp_path, 6)
    for cid in ids:
        _mark_seen(conn, cid)
    conn.close()

    def run_once():
        _feed_input(monkeypatch, ["x"] * 100)
        args = _sprint_args(db_path, monkeypatch, count=6, rounds=2, start=8.0, step=2.0, seed=7)
        cli.cmd_sprint(args)
        return capsys.readouterr().out

    out1 = run_once()
    out2 = run_once()
    assert out1 == out2
