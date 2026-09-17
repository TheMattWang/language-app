"""Tests for `python -m drill add` (drill.cli.cmd_add).

Drives cmd_add by building an argparse.Namespace directly -- no shelling
out. Covers append/import wiring, id generation, and the refusal paths.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from drill import store
from drill.cli import cmd_add


def _ns(tmp_path: Path, **over) -> argparse.Namespace:
    base = dict(
        db=tmp_path / "drill.db",
        prompt="the car (Spain)",
        accept=["el coche"],
        reject=["carro"],
        note=None,
        tags=None,
        deck="mine",
        file=tmp_path / "mine.jsonl",
    )
    base.update(over)
    return argparse.Namespace(**base)


def _lines(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_card_is_appended_and_importable(tmp_path):
    args = _ns(tmp_path)
    rc = cmd_add(args)
    assert rc == 0

    lines = _lines(args.file)
    assert len(lines) == 1
    assert lines[0]["id"] == "mi-001"
    assert lines[0]["prompt_en"] == "the car (Spain)"
    assert lines[0]["accept"] == ["el coche"]
    assert lines[0]["reject"] == ["carro"]

    conn = store.connect(args.db)
    card = store.get_card(conn, "mi-001")
    conn.close()
    assert card is not None
    assert card.accept == ("el coche",)


def test_ids_increment_and_do_not_collide(tmp_path):
    args1 = _ns(tmp_path, prompt="one", accept=["uno"], reject=[])
    args2 = _ns(tmp_path, prompt="two", accept=["dos"], reject=[])
    args3 = _ns(tmp_path, prompt="three", accept=["tres"], reject=[])
    assert cmd_add(args1) == 0
    assert cmd_add(args2) == 0
    assert cmd_add(args3) == 0

    lines = _lines(args1.file)
    ids = [l["id"] for l in lines]
    assert ids == ["mi-001", "mi-002", "mi-003"]
    assert len(set(ids)) == 3


def test_reject_colliding_with_accept_is_refused(tmp_path, capsys):
    args = _ns(tmp_path, prompt="the car (Spain)", accept=["el coche"], reject=["coche"])
    rc = cmd_add(args)
    assert rc != 0
    assert not args.file.exists()

    err = capsys.readouterr().err
    assert "rejects its own answer" in err
    assert "coche" in err


def test_empty_prompt_is_refused(tmp_path, capsys):
    args = _ns(tmp_path, prompt="   ", accept=["el coche"])
    rc = cmd_add(args)
    assert rc != 0
    assert not args.file.exists()
    assert "prompt" in capsys.readouterr().err.lower()


def test_empty_accept_is_refused(tmp_path, capsys):
    args = _ns(tmp_path, accept=[])
    rc = cmd_add(args)
    assert rc != 0
    assert not args.file.exists()
    assert "accept" in capsys.readouterr().err.lower()


def test_accents_survive_file_and_db_round_trip(tmp_path):
    args = _ns(
        tmp_path,
        prompt="the mobile phone (Spain)",
        accept=["el móvil"],
        reject=["celular"],
        note="ojo con la tilde",
        tags="tech,lexicon",
    )
    assert cmd_add(args) == 0

    raw = args.file.read_text(encoding="utf-8")
    assert "el móvil" in raw
    assert "\\u" not in raw  # ensure_ascii=False keeps accents literal

    lines = _lines(args.file)
    assert lines[0]["accept"] == ["el móvil"]
    assert lines[0]["tags"] == ["tech", "lexicon"]

    conn = store.connect(args.db)
    card = store.get_card(conn, lines[0]["id"])
    conn.close()
    assert card.accept == ("el móvil",)
    assert card.note == "ojo con la tilde"


def test_target_file_created_when_absent(tmp_path):
    args = _ns(tmp_path, file=tmp_path / "nested" / "mine.jsonl")
    assert not args.file.parent.exists()
    rc = cmd_add(args)
    assert rc == 0
    assert args.file.exists()
    assert len(_lines(args.file)) == 1


def test_existing_lines_never_modified_by_later_add(tmp_path):
    args1 = _ns(tmp_path, prompt="one", accept=["uno"], reject=[], note="first")
    assert cmd_add(args1) == 0
    first_line = args1.file.read_text(encoding="utf-8").splitlines()[0]

    args2 = _ns(tmp_path, prompt="two", accept=["dos"], reject=[])
    assert cmd_add(args2) == 0

    lines_after = args1.file.read_text(encoding="utf-8").splitlines()
    assert lines_after[0] == first_line
    assert len(lines_after) == 2


def test_duplicate_prompt_warns_but_still_writes(tmp_path, capsys):
    args1 = _ns(tmp_path, prompt="the car (Spain)", accept=["el coche"], reject=[])
    assert cmd_add(args1) == 0
    capsys.readouterr()

    args2 = _ns(tmp_path, prompt="the car (Spain)", accept=["el carro (informal)"], reject=[])
    rc = cmd_add(args2)
    assert rc == 0

    err = capsys.readouterr().err
    assert "already exists" in err

    lines = _lines(args1.file)
    assert len(lines) == 2
    assert lines[0]["prompt_en"] == lines[1]["prompt_en"] == "the car (Spain)"
