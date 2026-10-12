from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from drill import cli, store
from drill.scenario import Scenario, Turn, load, validate

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "es" / "scenarios.jsonl"

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


def _feed_input(monkeypatch, lines: list[str]) -> None:
    it = iter(lines)

    def fake_input(*a, **k):
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    monkeypatch.setattr("builtins.input", fake_input)


def _write_jsonl(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _snapshot(conn) -> tuple[list[tuple], list[tuple]]:
    reviews = conn.execute("SELECT * FROM review ORDER BY review_id").fetchall()
    scheds = conn.execute("SELECT * FROM sched ORDER BY card_id").fetchall()
    return [tuple(r) for r in reviews], [tuple(r) for r in scheds]


def _scene_args(scenario_file: Path, monkeypatch, **overrides) -> argparse.Namespace:
    defaults = dict(
        id=None,
        list=False,
        speak=False,
        max_attempts=3,
        file=scenario_file,
        no_color=True,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


# --- load() -------------------------------------------------------------


def test_load_good_file(tmp_path: Path) -> None:
    path = tmp_path / "scenes.jsonl"
    _write_jsonl(
        path,
        [
            '{"id":"sc-t1","title":"Test","situation_en":"A test.",'
            '"turns":[{"npc_es":"Hola","goal_en":"Say hi back","accept":["hola"],"reject":[],"hint":null}]}'
        ],
    )
    scenarios, errors = load(path)
    assert errors == []
    assert len(scenarios) == 1
    assert scenarios[0].scenario_id == "sc-t1"
    assert scenarios[0].turns[0].npc_es == "Hola"


def test_load_malformed_line_collected_as_error_not_exception(tmp_path: Path) -> None:
    path = tmp_path / "scenes.jsonl"
    _write_jsonl(
        path,
        [
            "{not valid json",
            '{"id":"sc-t1","title":"Test","situation_en":"A test.",'
            '"turns":[{"npc_es":"Hola","goal_en":"Say hi back","accept":["hola"],"reject":[],"hint":null}]}',
            '{"id":"sc-t2","title":"Missing turns field","situation_en":"Oops"}',
        ],
    )
    scenarios, errors = load(path)  # must not raise
    assert len(errors) == 2
    assert len(scenarios) == 1
    assert scenarios[0].scenario_id == "sc-t1"


def test_load_missing_file(tmp_path: Path) -> None:
    scenarios, errors = load(tmp_path / "nope.jsonl")
    assert scenarios == []
    assert errors and "not found" in errors[0]


# --- validate() -----------------------------------------------------------


def test_validate_catches_no_turns() -> None:
    s = Scenario(scenario_id="sc-x", title="t", situation_en="s", turns=())
    problems = validate(s)
    assert problems
    assert "no turns" in problems[0]


def test_validate_catches_empty_accept() -> None:
    t = Turn(npc_es="Hola", goal_en="reply", accept=(), reject=(), hint=None)
    s = Scenario(scenario_id="sc-x", title="t", situation_en="s", turns=(t,))
    problems = validate(s)
    assert any("empty accept" in p for p in problems)


def test_validate_catches_self_rejecting_turn() -> None:
    # reject entry ("carro") is a subsequence of the turn's own first
    # accept form -- the card-unanswerable trap.
    t = Turn(
        npc_es="¿Cómo has venido?",
        goal_en="Say you came by car.",
        accept=("he venido en carro",),
        reject=("carro",),
        hint=None,
    )
    s = Scenario(scenario_id="sc-x", title="t", situation_en="s", turns=(t,))
    problems = validate(s)
    assert problems
    assert "sc-x" in problems[0]


def test_validate_passes_a_clean_scenario() -> None:
    t = Turn(
        npc_es="¿Qué te pongo?",
        goal_en="Order a small beer.",
        accept=("una caña", "una caña por favor"),
        reject=(),
        hint="caña = small draft beer",
    )
    s = Scenario(scenario_id="sc-x", title="t", situation_en="s", turns=(t,))
    assert validate(s) == []


@pytest.mark.parametrize(
    "s",
    load(DATA_FILE)[0],
    ids=lambda s: s.scenario_id,
)
def test_every_shipped_scenario_validates(s: Scenario) -> None:
    assert validate(s) == []


def test_shipped_scenarios_file_loads_without_errors() -> None:
    scenarios, errors = load(DATA_FILE)
    assert errors == []
    assert len(scenarios) >= 8


# --- cmd_scene() ------------------------------------------------------------


_FIXTURE = (
    '{"id":"sc-x","title":"Escena de prueba","situation_en":"Testing.",'
    '"turns":['
    '{"npc_es":"¿Qué tal?","goal_en":"Say fine, thanks.","accept":["bien, gracias","muy bien, gracias"],'
    '"reject":[],"hint":"use bien"},'
    '{"npc_es":"¿Y tú?","goal_en":"Say you are well too.","accept":["yo también bien"],'
    '"reject":[],"hint":null}'
    ']}'
)


def _write_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "scenarios.jsonl"
    _write_jsonl(path, [_FIXTURE])
    return path


def test_list_prints_ids_titles_and_turn_counts(tmp_path: Path, monkeypatch, capsys) -> None:
    path = _write_fixture(tmp_path)
    args = _scene_args(path, monkeypatch, list=True)
    rc = cli.cmd_scene(args)
    assert rc == 0
    out = _strip_ansi(capsys.readouterr().out)
    assert "sc-x" in out
    assert "Escena de prueba" in out
    assert "2 turn(s)" in out


def test_wrong_answer_reprompts_same_turn(tmp_path: Path, monkeypatch, capsys) -> None:
    path = _write_fixture(tmp_path)
    # turn 1: wrong then right; turn 2: right first try
    _feed_input(monkeypatch, ["mal", "bien, gracias", "yo también bien"])
    args = _scene_args(path, monkeypatch, id="sc-x", max_attempts=3)
    rc = cli.cmd_scene(args)
    assert rc == 0
    out = _strip_ansi(capsys.readouterr().out)
    # the miss on attempt 1 surfaces the English goal as a nudge
    assert "Say fine, thanks." in out
    assert "2/2 turn(s) passed" in out


def test_answer_revealed_after_max_attempts_and_turn_counts_as_failed(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    path = _write_fixture(tmp_path)
    # turn 1: exhaust both attempts with wrong answers; turn 2: right first try
    _feed_input(monkeypatch, ["mal", "todavia mal", "yo también bien"])
    args = _scene_args(path, monkeypatch, id="sc-x", max_attempts=2)
    rc = cli.cmd_scene(args)
    assert rc == 0
    out = _strip_ansi(capsys.readouterr().out)
    assert "use bien" in out  # hint shown on the 2nd (final) miss
    assert "bien, gracias" in out  # the answer is revealed
    assert "1/2 turn(s) passed" in out


def test_no_review_or_sched_rows_written(tmp_path: Path, monkeypatch, capsys) -> None:
    path = _write_fixture(tmp_path)
    db_path = tmp_path / "drill.db"
    conn = store.connect(db_path)
    before = _snapshot(conn)
    conn.close()

    _feed_input(monkeypatch, ["mal", "bien, gracias", "yo también bien"])
    args = _scene_args(path, monkeypatch, id="sc-x", max_attempts=3)
    cli.cmd_scene(args)

    conn2 = store.connect(db_path)
    after = _snapshot(conn2)
    conn2.close()

    assert before == after, "scene must never write review rows or change sched state"


def test_announces_it_writes_nothing(tmp_path: Path, monkeypatch, capsys) -> None:
    path = _write_fixture(tmp_path)
    _feed_input(monkeypatch, ["bien, gracias", "yo también bien"])
    args = _scene_args(path, monkeypatch, id="sc-x")
    cli.cmd_scene(args)
    out = capsys.readouterr().out
    assert "nothing" in out.lower()
