"""Loading and validation for multi-turn conversation scenarios.

A scenario is a short scripted exchange (bar, restaurant, pharmacy, ...):
the NPC speaks a line, the learner must produce Spanish that satisfies
`drill.grader.grade`, then the NPC's next line follows. Unlike a card
deck, a scenario is never scheduled or logged to the SRS -- see
`drill.cli.cmd_scene`.

`validate` catches the same self-rejection trap as
`tests/test_content.py` does for cards: a turn whose own first accept
form doesn't survive grading is unanswerable, and that's only supposed
to surface here, at content-authoring time, never mid-drill.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from drill.grader import grade


@dataclass(frozen=True)
class Turn:
    npc_es: str
    goal_en: str
    accept: tuple[str, ...]
    reject: tuple[str, ...]
    hint: str | None


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    title: str
    situation_en: str
    turns: tuple[Turn, ...]


_TURN_REQUIRED = ("npc_es", "goal_en", "accept")
_SCENARIO_REQUIRED = ("id", "title", "situation_en", "turns")


def _parse_turn(raw: dict) -> Turn:
    for field in _TURN_REQUIRED:
        if field not in raw:
            raise KeyError(field)
    return Turn(
        npc_es=raw["npc_es"],
        goal_en=raw["goal_en"],
        accept=tuple(raw["accept"]),
        reject=tuple(raw.get("reject", ())),
        hint=raw.get("hint"),
    )


def _parse_scenario(raw: dict) -> Scenario:
    for field in _SCENARIO_REQUIRED:
        if field not in raw:
            raise KeyError(field)
    turns = tuple(_parse_turn(t) for t in raw["turns"])
    return Scenario(
        scenario_id=raw["id"],
        title=raw["title"],
        situation_en=raw["situation_en"],
        turns=turns,
    )


def load(path: Path) -> tuple[list[Scenario], list[str]]:
    """Load scenarios from the JSONL file at `path`.

    Returns `(scenarios, errors)`. A malformed or incomplete line is
    collected into `errors` and skipped -- it never aborts the load, so
    one bad line in a scenario file can't take the whole set down.
    """
    scenarios: list[Scenario] = []
    errors: list[str] = []
    if not path.exists():
        return scenarios, [f"{path}: not found"]

    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{path.name}:{lineno}: invalid JSON: {exc}")
            continue
        try:
            scenario = _parse_scenario(raw)
        except (KeyError, TypeError) as exc:
            errors.append(f"{path.name}:{lineno}: missing/bad field {exc}")
            continue
        scenarios.append(scenario)

    return scenarios, errors


def validate(s: Scenario) -> list[str]:
    """Return a list of problems with `s`; empty means it's drillable.

    Catches: no turns; a turn with an empty `accept`; and a turn whose
    own first accept form fails `grade()` against its own accept/reject
    lists -- the same self-rejection trap that makes a card
    unanswerable.
    """
    problems: list[str] = []
    if not s.turns:
        problems.append(f"{s.scenario_id}: no turns")
        return problems

    for i, t in enumerate(s.turns, 1):
        if not t.accept:
            problems.append(f"{s.scenario_id} turn {i}: empty accept list")
            continue
        v = grade(t.accept[0], accept=t.accept, reject=t.reject)
        if not v.accepted:
            problems.append(
                f"{s.scenario_id} turn {i}: its own accept form {t.accept[0]!r} "
                f"is rejected ({v.layer}): {v.reason}"
            )
    return problems
