"""QA P1: ANSI escapes leak past `--no-color` and past a non-TTY.

Most `drill` output used to interpolate the raw `DIM`/`BOLD`/`RESET`/...
constants directly into f-strings, bypassing the `_color()`/`c()` gate --
so `--no-color` suppressed almost nothing, and piping to a file embedded
literal escape bytes. `stats`/`weak`/`export`/`add`/`import` also didn't
accept `--no-color` at all (argparse rejected it). See docs/qa/surfaces.md.

Also covers the two related QA findings fixed alongside it:
  - `--deck <nonexistent>` reused the generic "No cards yet" message even
    on a database holding hundreds of cards in other decks.
  - `import` of a missing file printed an error but exited 0, so a script
    could not detect the failure.

Every command is driven directly (`cli.cmd_*` / `argparse.Namespace`),
matching this test suite's existing convention (see test_scenario.py,
test_cli_validation.py, test_add.py) -- never subprocess, so stdin/speech
can be controlled deterministically and no real DB other than a tmp_path
one is ever touched.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from drill import cli, speech, store

NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


def _feed_input(monkeypatch, lines: list[str] | None = None) -> None:
    """Feed `input()` from `lines`, then EOF -- an empty/omitted list means
    "hit EOF (Ctrl-D) on the very first prompt", which every interactive
    command here already handles gracefully (prints one "stopping." line,
    exits cleanly) per the P0 fixes this suite guards elsewhere."""
    it = iter(lines or [])

    def fake_input(*a, **k):
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    monkeypatch.setattr("builtins.input", fake_input)


def _write_jsonl(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _card_line(**overrides) -> str:
    obj = {
        "id": "c-001",
        "deck": "hygiene",
        "kind": "production",
        "prompt_en": "the dog",
        "accept": ["el perro"],
        "reject": [],
        "note": None,
        "tags": [],
    }
    obj.update(overrides)
    return json.dumps(obj)


def _seed_due_cards(tmp_path: Path, db_path: Path, n: int = 3, deck: str = "hygiene") -> list[str]:
    """Import `n` fresh cards -- new cards are due immediately -- so
    review/daily/listen/export/weak have real, non-empty output to check,
    not just an early "nothing to do" branch (which is already ANSI-free
    trivially)."""
    # ids are namespaced by deck -- otherwise two decks seeded into the same
    # db would collide on id and the second import would silently rewrite
    # the first deck's cards in place instead of adding a second deck.
    ids = [f"{deck}-{i:03d}" for i in range(1, n + 1)]
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


def _mark_seen(db_path: Path, card_ids: list[str]) -> None:
    """Give each card a real review + non-'new' sched row, so sprint's
    "already seen" candidate query picks them up instead of taking the
    early, uncoloured "No seen cards yet" branch."""
    conn = store.connect(db_path)
    for cid in card_ids:
        store.record_review(
            conn, card_id=cid, reviewed_at=NOW, grade=3, latency_ms=500,
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


_SCENE_FIXTURE = (
    '{"id":"sc-x","title":"Escena de prueba","situation_en":"Testing.",'
    '"turns":['
    '{"npc_es":"¿Qué tal?","goal_en":"Say fine, thanks.",'
    '"accept":["bien, gracias"],"reject":[],"hint":null}'
    ']}'
)


def _no_color_args(command: str, tmp_path: Path, db_path: Path, monkeypatch) -> argparse.Namespace:
    """Build the argparse.Namespace `cli.cmd_<command>` needs, matching
    `build_parser()`'s defaults, with `no_color=True` and stdin/speech
    wired so every command runs to completion deterministically."""
    if command == "stats":
        return argparse.Namespace(db=db_path, deck=None, no_color=True)

    if command == "weak":
        return argparse.Namespace(db=db_path, deck=None, days=None, limit=10, no_color=True)

    if command == "export":
        return argparse.Namespace(
            db=db_path, deck=None, out=tmp_path / "out.md", limit=60,
            min_attempts=0, no_color=True,
        )

    if command == "add":
        return argparse.Namespace(
            db=db_path, prompt="a hygiene test", accept=["una prueba"], reject=None,
            note=None, tags=None, deck="hygiene", file=tmp_path / "mine.jsonl",
            no_color=True,
        )

    if command == "import":
        deck_path = tmp_path / "import_me.jsonl"
        _write_jsonl(deck_path, [_card_line(id="im-001")])
        return argparse.Namespace(db=db_path, paths=[str(deck_path)], no_color=True)

    if command == "daily":
        _feed_input(monkeypatch)
        return argparse.Namespace(db=db_path, deck=None, new=None, max=40, no_color=True)

    if command == "review":
        _feed_input(monkeypatch)
        return argparse.Namespace(db=db_path, deck=None, limit=20, no_color=True)

    if command == "listen":
        _feed_input(monkeypatch)
        monkeypatch.setattr(speech, "is_available", lambda: True)
        monkeypatch.setattr(speech, "speak", lambda *a, **k: True)
        return argparse.Namespace(
            db=db_path, deck=None, limit=20, rate=180, replays=3, no_color=True,
        )

    if command == "sprint":
        _feed_input(monkeypatch)
        return argparse.Namespace(
            db=db_path, deck=None, count=10, rounds=2, start=8.0, step=2.0,
            seed=1234, no_color=True,
        )

    if command == "scene":
        _feed_input(monkeypatch)
        scenario_path = tmp_path / "scenarios.jsonl"
        _write_jsonl(scenario_path, [_SCENE_FIXTURE])
        return argparse.Namespace(
            id=None, list=False, speak=False, max_attempts=3, file=scenario_path,
            no_color=True,
        )

    raise ValueError(command)


ALL_COMMANDS = [
    "stats", "weak", "daily", "review", "listen", "sprint", "scene",
    "export", "add", "import",
]


@pytest.mark.parametrize("command", ALL_COMMANDS)
def test_no_ansi_with_no_color(tmp_path, monkeypatch, capsys, command):
    db_path = tmp_path / "drill.db"
    _seed_due_cards(tmp_path, db_path)

    args = _no_color_args(command, tmp_path, db_path, monkeypatch)
    func = getattr(cli, f"cmd_{command}")
    func(args)

    out = capsys.readouterr().out
    assert "\x1b" not in out, out


# --- --no-color must be accepted by every subcommand -------------------------


_PARSE_ARGV: dict[str, list[str]] = {
    "import": ["import", "x.jsonl"],
    "review": ["review"],
    "add": ["add", "--prompt", "p", "--accept", "a"],
    "stats": ["stats"],
    "gui": ["gui"],
    "export": ["export"],
    "weak": ["weak"],
    "daily": ["daily"],
    "listen": ["listen"],
    "sprint": ["sprint"],
    "scene": ["scene"],
}


@pytest.mark.parametrize("command", sorted(_PARSE_ARGV))
def test_no_color_accepted_after_subcommand(command):
    """Regression for the argparse `unrecognized arguments: --no-color`
    rejection QA found on stats/weak/export/add/import."""
    argv = [*_PARSE_ARGV[command], "--no-color"]
    args = cli.build_parser().parse_args(argv)
    assert args.no_color is True


@pytest.mark.parametrize("command", sorted(_PARSE_ARGV))
def test_no_color_accepted_before_subcommand(command):
    """The flag is also global on the top-level parser now, so it works
    positioned before the subcommand name too."""
    argv = ["--no-color", *_PARSE_ARGV[command]]
    args = cli.build_parser().parse_args(argv)
    assert args.no_color is True


# --- misleading empty message for a nonexistent --deck -----------------------


def test_nonexistent_deck_names_the_real_decks(tmp_path, capsys):
    db_path = tmp_path / "drill.db"
    _seed_due_cards(tmp_path, db_path, deck="peninsular_contrast")
    _seed_due_cards(tmp_path, db_path, deck="travel_production")

    args = argparse.Namespace(db=db_path, deck="totally_bogus_deck", limit=20, no_color=True)
    rc = cli.cmd_review(args)
    assert rc == 0

    out = capsys.readouterr().out
    assert "No cards yet" not in out
    assert "totally_bogus_deck" in out
    assert "peninsular_contrast" in out
    assert "travel_production" in out


def test_genuinely_empty_db_still_gets_the_generic_message(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "drill.db"
    store.connect(db_path).close()

    # cmd_review auto-bootstraps the bundled decks from the repo's own
    # data/ dir on a zero-card DB (a separate, deliberate convenience --
    # see `_bootstrap_if_empty`), which would otherwise make "genuinely
    # empty" unreachable in this test environment. Disable it here so this
    # test isolates the "0 cards, no bundled decks either" message.
    monkeypatch.setattr(cli, "_bootstrap_if_empty", lambda conn: None)

    args = argparse.Namespace(db=db_path, deck="anything", limit=20, no_color=True)
    rc = cli.cmd_review(args)
    assert rc == 0

    out = capsys.readouterr().out
    assert "No cards yet" in out
    assert "python3 -m drill import" in out


# --- import of a missing file must exit non-zero ------------------------------


def test_import_missing_file_exits_nonzero(tmp_path, capsys):
    db_path = tmp_path / "drill.db"
    missing = tmp_path / "does_not_exist.jsonl"

    args = argparse.Namespace(db=db_path, paths=[str(missing)], no_color=True)
    rc = cli.cmd_import(args)
    assert rc != 0

    err = capsys.readouterr().err
    assert "missing" in err.lower()


def test_import_missing_plus_real_file_still_imports_real_and_still_fails(tmp_path, capsys):
    db_path = tmp_path / "drill.db"
    missing = tmp_path / "does_not_exist.jsonl"
    real = tmp_path / "real.jsonl"
    _write_jsonl(real, [_card_line(id="rc-001")])

    args = argparse.Namespace(db=db_path, paths=[str(missing), str(real)], no_color=True)
    rc = cli.cmd_import(args)
    assert rc != 0

    conn = store.connect(db_path)
    total = conn.execute("SELECT COUNT(*) FROM card").fetchone()[0]
    conn.close()
    assert total == 1
