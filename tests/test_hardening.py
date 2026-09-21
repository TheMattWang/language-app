"""Regressions from the second QA sweep.

Each test here is a defect that shipped: found by an independent tester,
reproduced, fixed. Several are second attempts at a bug already "fixed"
once -- the concurrency one in particular, where the first fix (a
busy_timeout pragma) was never verified and did not work.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from drill import store
from drill.cli import _positive, main
from drill.export import _md

UTC = timezone.utc


def _card(i: int, **over) -> dict:
    c = {
        "id": f"c{i}", "deck": "d", "kind": "production", "prompt_en": f"p{i}",
        "accept": [f"a{i}"], "reject": [], "note": None, "tags": [],
    }
    c.update(over)
    return c


def _deck(tmp_path: Path, rows: list[dict], name: str = "deck.jsonl") -> Path:
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return p


# --- import robustness ------------------------------------------------------


def test_malformed_first_line_does_not_discard_the_whole_deck(tmp_path):
    """A bad row is a bad row; only a different *schema* aborts the file."""
    bad = _card(0)
    del bad["kind"]
    path = _deck(tmp_path, [bad, _card(1), _card(2), _card(3)])
    conn = store.connect(tmp_path / "a.db")
    res = store.import_jsonl(conn, path)
    assert res.added == 3, "one malformed line dropped every valid card in the file"
    assert len(res.errors) == 1
    conn.close()


def test_a_genuinely_different_schema_is_still_skipped(tmp_path):
    """The behaviour the first-line check exists for: scenarios.jsonl."""
    scenario = {"id": "s1", "title": "t", "situation_en": "x", "turns": []}
    conn = store.connect(tmp_path / "b.db")
    res = store.import_jsonl(conn, _deck(tmp_path, [scenario]))
    assert res.added == 0 and res.errors
    conn.close()


def test_non_utf8_is_reported_not_raised(tmp_path):
    path = tmp_path / "bin.jsonl"
    path.write_bytes(b'{"id":"x","deck":"d","kind":"production","prompt_en":"\xff\xfe","accept":["a"]}')
    conn = store.connect(tmp_path / "c.db")
    res = store.import_jsonl(conn, path)  # must not raise UnicodeDecodeError
    assert res.added == 0 and res.errors and "UTF-8" in res.errors[0]
    conn.close()


def test_concurrent_imports_both_land(tmp_path):
    """Two importers at once: the loser used to die on "database is locked".

    A deferred BEGIN takes its read snapshot at the first statement, so the
    two transactions conflict rather than queue -- and a conflict is not
    something busy_timeout can wait out. BEGIN IMMEDIATE takes the write
    lock up front instead.
    """
    db = tmp_path / "conc.db"
    store.connect(db).close()
    decks = [
        _deck(tmp_path, [_card(i, id=f"x{k}-{i}", deck=f"deck{k}") for i in range(80)], f"d{k}.jsonl")
        for k in range(2)
    ]
    errors: list[BaseException] = []

    def run(path: Path) -> None:
        try:
            conn = store.connect(db)
            store.import_jsonl(conn, path)
            conn.close()
        except BaseException as exc:  # noqa: BLE001 - recorded and re-raised below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(d,)) for d in decks]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent import raised: {errors!r}"
    conn = store.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM card").fetchone()[0] == 160
    conn.close()


# --- backups ----------------------------------------------------------------


def test_backup_does_not_claim_a_snapshot_it_pruned(tmp_path):
    db = tmp_path / "d.db"
    store.connect(db).close()
    assert store.backup_db(db, keep=0) is None, "returned a path to a file it had just deleted"
    kept = store.backup_db(db, keep=5)
    assert kept is not None and kept.exists()


# --- the daily budget's idea of "a day" -------------------------------------


def test_new_card_budget_rolls_over_at_local_midnight(tmp_path):
    """A Pacific-time evening is already the next UTC day.

    With a UTC boundary, drilling after 5pm local silently earned a second
    full allowance of new cards.
    """
    pacific = timezone(timedelta(hours=-7))
    conn = store.connect(tmp_path / "e.db")
    store.import_jsonl(conn, _deck(tmp_path, [_card(1)]))

    evening = datetime(2026, 9, 20, 18, 0, tzinfo=pacific)  # 01:00 UTC on the 21st
    store.record_review(
        conn, card_id="c1", reviewed_at=evening, grade=2, latency_ms=100,
        raw_text="a1", accepted=True, layer="L2_exact",
        interval_before=0.0, interval_after=1.0,
    )
    conn.commit()

    later = datetime(2026, 9, 20, 21, 0, tzinfo=pacific)  # same local day
    assert store.new_cards_introduced_today(conn, later) == 1, (
        "the evening's new card stopped counting once UTC rolled over"
    )
    conn.close()


# --- surfaces ---------------------------------------------------------------


def test_limit_is_bounded_above():
    """An int wider than 64 bits reached SQLite and raised OverflowError."""
    with pytest.raises(Exception) as exc:
        _positive("limit", 10**21)
    assert "<=" in str(exc.value)


def test_add_rejects_an_empty_deck_name(tmp_path, capsys):
    code = main(["--db", str(tmp_path / "f.db"), "add", "--deck", "",
                 "--prompt", "x", "--accept", "y"])
    assert code == 1
    assert "deck" in capsys.readouterr().err


def test_speech_terminates_option_parsing(monkeypatch):
    """Card text starting with "-" was parsed by `say` as a flag."""
    from drill import speech

    captured: dict = {}

    class FakePopen:
        def __init__(self, args, **kw):
            captured["args"] = args

    monkeypatch.setattr(speech.subprocess, "Popen", FakePopen)
    assert speech.speak("-rate trick", voice="Monica")
    args = captured["args"]
    assert args[-2] == "--" and args[-1] == "-rate trick"


@pytest.mark.parametrize(
    "raw,expected",
    [("*muy* bien", r"\*muy\* bien"), ("carta_del_día", r"carta\_del\_día"), ("a|b", r"a\|b")],
)
def test_markdown_metacharacters_in_card_text_are_escaped(raw, expected):
    assert _md(raw) == expected


def test_ordinary_spanish_is_not_littered_with_backslashes():
    """Escaping the full CommonMark set was worse than the bug."""
    assert _md("¿Dónde está el baño? Todo recto, a la derecha.") == (
        "¿Dónde está el baño? Todo recto, a la derecha."
    )
