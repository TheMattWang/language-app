"""Tests for the QA-report fixes in `drill/cli.py`: shared numeric-flag
validation across `review`/`daily`/`listen`/`sprint`/`weak`/`export`,
`sprint --rounds 0`/negative no longer crashing with `IndexError`, `add`
handling Ctrl-D/EOF gracefully, `stats` reporting accuracy, and the
first-run auto-import bootstrap. See docs/QA_REPORT.md.

Never touches ~/.langapp/drill.db -- every test uses tmp_path.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from drill import cli, store

NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)


def _write_jsonl(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _card_line(**overrides) -> str:
    obj = {
        "id": "c-001",
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


def _seed_due_cards(tmp_path: Path, db_path: Path, n: int = 3, deck: str = "deck_a") -> list[str]:
    """Import `n` fresh cards -- new cards are due immediately -- into `db_path`."""
    ids = [f"c-{i:03d}" for i in range(1, n + 1)]
    lines = [
        _card_line(id=cid, deck=deck, prompt_en=f"word {cid}", accept=[f"palabra{cid}"])
        for cid in ids
    ]
    path = tmp_path / f"{deck}.jsonl"
    _write_jsonl(path, lines)
    conn = store.connect(db_path)
    store.import_jsonl(conn, path)
    conn.close()
    return ids


def _card_deck_file(dir_path: Path, name: str, n: int = 2, deck: str | None = None) -> None:
    deck = deck or name
    lines = [
        _card_line(id=f"{name}-{i:03d}", deck=deck, prompt_en=f"{name} word {i}", accept=[f"{name}palabra{i}"])
        for i in range(1, n + 1)
    ]
    _write_jsonl(dir_path / f"{name}.jsonl", lines)


# --- 1. sprint --rounds 0 / negative: no more IndexError --------------------


def test_sprint_rounds_zero_exits_cleanly_via_main(tmp_path):
    db_path = tmp_path / "drill.db"
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--db", str(db_path), "sprint", "--rounds", "0"])
    assert exc_info.value.code == 2


def test_sprint_rounds_negative_exits_cleanly_via_main(tmp_path):
    db_path = tmp_path / "drill.db"
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--db", str(db_path), "sprint", "--rounds", "-1"])
    assert exc_info.value.code == 2


def test_cmd_sprint_rejects_bad_rounds_via_direct_namespace(tmp_path, capsys):
    """Guards the function itself, not just argparse's `type=`, since a
    hand-built Namespace (as much of this test suite constructs) skips
    argparse's own parsing entirely."""
    args = argparse.Namespace(
        db=tmp_path / "drill.db", deck=None, count=10, rounds=0,
        start=8.0, step=2.0, seed=1234, no_color=True,
    )
    rc = cli.cmd_sprint(args)
    assert rc == 2
    err = capsys.readouterr().err
    assert "--rounds" in err


# --- 2. add: EOF handled gracefully ------------------------------------------


def test_add_eof_exits_nonzero_prints_one_line_writes_nothing(tmp_path, monkeypatch, capsys):
    file_path = tmp_path / "mine.jsonl"
    args = argparse.Namespace(
        db=tmp_path / "drill.db",
        prompt=None, accept=None, reject=None, note=None, tags=None,
        deck="mine", file=file_path,
    )

    def fake_input(*a, **k):
        raise EOFError

    monkeypatch.setattr("builtins.input", fake_input)

    rc = cli.cmd_add(args)
    assert rc != 0
    assert not file_path.exists()

    out = capsys.readouterr().out
    printed_lines = [l for l in out.splitlines() if l.strip()]
    assert len(printed_lines) == 1
    assert "stopping" in printed_lines[0]


# --- 3. rejected numeric flags name the flag ---------------------------------


@pytest.mark.parametrize(
    "argv,expected_flag",
    [
        (["review", "--limit", "-5"], "--limit"),
        (["review", "--limit", "0"], "--limit"),
        (["listen", "--limit", "-1"], "--limit"),
        (["daily", "--max", "-5"], "--max"),
        (["sprint", "--count", "-3"], "--count"),
        (["sprint", "--count", "0"], "--count"),
        (["sprint", "--rounds", "0"], "--rounds"),
        (["sprint", "--rounds", "-1"], "--rounds"),
        (["weak", "--limit", "-1"], "--limit"),
        (["weak", "--days", "-5"], "--days"),
        (["export", "--limit", "-3"], "--limit"),
    ],
)
def test_rejected_numeric_flag_names_the_flag(tmp_path, capsys, argv, expected_flag):
    db_path = tmp_path / "drill.db"
    with pytest.raises(SystemExit) as exc_info:
        cli.build_parser().parse_args(["--db", str(db_path)] + argv)
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert expected_flag in err


def test_export_min_attempts_zero_is_legitimate_not_rejected(tmp_path):
    """min_attempts=0 is an explicitly justified exception (see the parser
    comment in cli.py) -- "no attempts floor", not "nothing to export"."""
    db_path = tmp_path / "drill.db"
    store.connect(db_path).close()
    args = cli.build_parser().parse_args(
        ["--db", str(db_path), "export", "--min-attempts", "0", "--out", str(tmp_path / "out.md")]
    )
    assert args.min_attempts == 0


# --- 4. --limit 0 must not claim "Nothing due" when cards are due -----------


def test_review_limit_zero_rejected_not_false_nothing_due(tmp_path, capsys):
    db_path = tmp_path / "drill.db"
    _seed_due_cards(tmp_path, db_path, n=5)

    args = argparse.Namespace(db=db_path, deck=None, limit=0, no_color=True)
    rc = cli.cmd_review(args)
    assert rc == 2

    out = capsys.readouterr().out
    assert "Nothing due" not in out


def test_sprint_count_zero_rejected_not_false_no_seen_cards(tmp_path, capsys):
    db_path = tmp_path / "drill.db"
    ids = _seed_due_cards(tmp_path, db_path, n=3)
    conn = store.connect(db_path)
    for cid in ids:
        store.record_review(
            conn, card_id=cid, reviewed_at=NOW, grade=3, latency_ms=1000,
            raw_text="x", accepted=True, layer="L2_exact",
            interval_before=0.0, interval_after=1.0,
        )
        store.save_sched(
            conn,
            store.SchedRow(
                card_id=cid, due_at=NOW, interval_days=1.0, ease=2.5,
                reps=1, lapses=0, state="learning", last_reviewed_at=NOW,
            ),
        )
    conn.commit()
    conn.close()

    args = argparse.Namespace(db=db_path, deck=None, count=0, rounds=3, start=8.0, step=2.0, seed=1, no_color=True)
    rc = cli.cmd_sprint(args)
    assert rc == 2
    out = capsys.readouterr().out
    assert "No seen cards" not in out


# --- 5. stats accuracy -------------------------------------------------------


def test_stats_accuracy_dash_on_empty_db(tmp_path, capsys):
    db_path = tmp_path / "drill.db"
    store.connect(db_path).close()

    args = argparse.Namespace(db=db_path, deck=None)
    rc = cli.cmd_stats(args)
    assert rc == 0

    out = capsys.readouterr().out
    assert "accuracy" in out
    assert "--" in out
    assert "0%" not in out


def test_stats_accuracy_real_percentage_after_reviews(tmp_path, capsys):
    db_path = tmp_path / "drill.db"
    ids = _seed_due_cards(tmp_path, db_path, n=4)
    conn = store.connect(db_path)
    for i, cid in enumerate(ids):
        accepted = i < 3  # 3/4 correct
        store.record_review(
            conn, card_id=cid, reviewed_at=NOW, grade=3 if accepted else 0,
            latency_ms=1000, raw_text="x", accepted=accepted,
            layer="L2_exact" if accepted else None,
            interval_before=0.0, interval_after=1.0,
        )
    conn.commit()
    conn.close()

    args = argparse.Namespace(db=db_path, deck=None)
    rc = cli.cmd_stats(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "75%" in out


# --- 6. first-run auto-import bootstrap --------------------------------------


def test_bootstrap_imports_card_decks_skips_scenarios_and_bad_schema(tmp_path, monkeypatch, capsys):
    pkg_root = tmp_path / "pkg"
    data_dir = pkg_root / "data" / "es"
    data_dir.mkdir(parents=True)

    _card_deck_file(data_dir, "valid_deck", n=3)

    # scenarios.jsonl: turn-based NPC dialogue, no deck/kind/accept -- must be skipped.
    scenario_obj = {
        "id": "sc-001", "title": "t", "situation_en": "s",
        "turns": [{"npc_es": "x", "goal_en": "y", "accept": ["a"], "reject": [], "hint": None}],
    }
    _write_jsonl(data_dir / "scenarios.jsonl", [json.dumps(scenario_obj)])

    # another file with an unrelated schema -- must also be skipped, silently.
    _write_jsonl(data_dir / "not_a_deck.jsonl", [json.dumps({"foo": "bar"})])

    monkeypatch.setattr(cli, "__file__", str(pkg_root / "drill" / "cli.py"))

    db_path = tmp_path / "drill.db"
    conn = store.connect(db_path)
    cli._bootstrap_if_empty(conn)

    total = conn.execute("SELECT COUNT(*) FROM card").fetchone()[0]
    assert total == 3

    scenario_cards = conn.execute("SELECT COUNT(*) FROM card WHERE card_id LIKE 'sc-%'").fetchone()[0]
    assert scenario_cards == 0

    decks = {r["deck"] for r in conn.execute("SELECT DISTINCT deck FROM card").fetchall()}
    assert decks == {"valid_deck"}
    conn.close()

    out = capsys.readouterr().out
    assert "valid_deck" in out
    assert "scenarios" not in out
    assert "not_a_deck" not in out


def test_bootstrap_missing_data_dir_prints_manual_command_no_crash(tmp_path, monkeypatch, capsys):
    pkg_root = tmp_path / "pkg_empty"
    monkeypatch.setattr(cli, "__file__", str(pkg_root / "drill" / "cli.py"))

    db_path = tmp_path / "drill2.db"
    conn = store.connect(db_path)
    cli._bootstrap_if_empty(conn)  # must not raise

    total = conn.execute("SELECT COUNT(*) FROM card").fetchone()[0]
    assert total == 0
    conn.close()

    out = capsys.readouterr().out
    assert "python3 -m drill import" in out


def test_bootstrap_skipped_when_db_already_has_cards(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "drill.db"
    _seed_due_cards(tmp_path, db_path, n=1)

    pkg_root = tmp_path / "pkg2"
    data_dir = pkg_root / "data" / "es"
    data_dir.mkdir(parents=True)
    _card_deck_file(data_dir, "other_deck", n=5)
    monkeypatch.setattr(cli, "__file__", str(pkg_root / "drill" / "cli.py"))

    conn = store.connect(db_path)
    cli._bootstrap_if_empty(conn)
    total = conn.execute("SELECT COUNT(*) FROM card").fetchone()[0]
    assert total == 1  # untouched -- db wasn't empty, so no auto-import happened
    conn.close()
