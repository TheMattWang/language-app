"""Drive the desktop app's widgets programmatically.

A GUI still has logic worth testing: that a submitted answer is graded,
persisted and rescheduled, that Enter advances, and that an empty deck
does not crash the window. The window is withdrawn so nothing flashes on
screen during a test run.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from drill import store  # noqa: E402
from drill.app import DrillApp  # noqa: E402

UTC = timezone.utc

CARDS = [
    {
        "id": "t1", "deck": "t", "kind": "contrast", "prompt_en": "the car (Spain)",
        "accept": ["el coche"], "reject": ["carro"], "note": "carro is LatAm",
        # `why:region` is what makes the regional wording correct here. Without
        # it the card falls back to the neutral message -- which is the point of
        # the default: an untagged card must not assert a regionalism.
        "tags": ["lex", "why:region"],
    },
    {
        "id": "t2", "deck": "t", "kind": "production", "prompt_en": "the juice (Spain)",
        "accept": ["el zumo"], "reject": ["jugo"], "note": None, "tags": [],  # untagged on purpose
    },
]


@pytest.fixture()
def app(tmp_path: Path):
    deck = tmp_path / "t.jsonl"
    deck.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in CARDS), encoding="utf-8")
    conn = store.connect(tmp_path / "t.db")
    store.import_jsonl(conn, deck)
    conn.close()

    try:
        root = tk.Tk()
    except tk.TclError:  # pragma: no cover - no display available
        pytest.skip("no display available for tkinter")
    root.withdraw()
    a = DrillApp(root, tmp_path / "t.db", deck=None, limit=10)
    yield a
    a.close()
    root.destroy()


def _answer(a: DrillApp, text: str) -> None:
    a.entry.delete(0, tk.END)
    a.entry.insert(0, text)
    a._on_enter()


def test_loads_due_cards(app: DrillApp) -> None:
    assert len(app.queue) == 2
    assert app.lbl_prompt.cget("text") == "the car (Spain)"


def test_correct_answer_scores_and_persists(app: DrillApp) -> None:
    _answer(app, "el coche")
    assert app.correct == 1 and app.answered == 1
    assert app.awaiting_next is True

    row = store.get_sched(app.conn, "t1")
    assert row.reps == 1, "review was not persisted"
    assert row.state != "new"


def test_latam_answer_is_rejected_with_guidance(app: DrillApp) -> None:
    _answer(app, "el carro")
    assert app.correct == 0 and app.answered == 1
    assert "coche" in app.lbl_target.cget("text")
    assert "Latinoamérica" in app.lbl_note.cget("text")


def test_enter_advances_to_next_card(app: DrillApp) -> None:
    _answer(app, "el coche")
    app._on_enter()  # second Enter advances
    assert app.index == 1
    assert app.lbl_prompt.cget("text") == "the juice (Spain)"
    assert app.entry.get() == "", "entry was not cleared for the next card"


def test_empty_submission_is_ignored(app: DrillApp) -> None:
    _answer(app, "   ")
    assert app.answered == 0, "whitespace counted as an attempt"
    assert app.awaiting_next is False


def test_finishing_the_queue_does_not_crash(app: DrillApp) -> None:
    for _ in range(len(app.queue)):
        _answer(app, "el coche")
        app._on_enter()
    assert "Hecho" in app.lbl_prompt.cget("text")


def test_accent_button_inserts_at_cursor(app: DrillApp) -> None:
    app.entry.insert(0, "manana")
    app.entry.icursor(3)
    app._insert("ñ")
    assert app.entry.get() == "manñana"


def test_empty_deck_shows_guidance(tmp_path: Path) -> None:
    store.connect(tmp_path / "empty.db").close()
    try:
        root = tk.Tk()
    except tk.TclError:  # pragma: no cover
        pytest.skip("no display")
    root.withdraw()
    a = DrillApp(root, tmp_path / "empty.db", deck=None, limit=10)
    assert "No hay tarjetas" in a.lbl_prompt.cget("text")
    a.close()
    root.destroy()


def test_gui_respects_the_daily_new_card_cap(tmp_path: Path) -> None:
    """Reopening the window must not introduce a fresh batch of new cards.

    The GUI originally called due_cards, which has no per-day cap, so every
    launch pulled another `limit` new cards regardless of how many had
    already been introduced that day.
    """
    rows = [
        {
            "id": f"c{i:03d}", "deck": "t", "kind": "production",
            "prompt_en": f"prompt {i}", "accept": [f"respuesta {i}"],
            "reject": [], "note": None, "tags": [],
        }
        for i in range(40)
    ]
    deck = tmp_path / "many.jsonl"
    deck.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    conn = store.connect(tmp_path / "many.db")
    store.import_jsonl(conn, deck)
    conn.close()

    try:
        root = tk.Tk()
    except tk.TclError:  # pragma: no cover
        pytest.skip("no display")
    root.withdraw()

    first = DrillApp(root, tmp_path / "many.db", deck=None, limit=40, new_per_day=5)
    assert len(first.queue) == 5, f"cap ignored on first open: {len(first.queue)}"
    for _ in range(5):
        first.entry.delete(0, tk.END)
        first.entry.insert(0, "respuesta 0")
        first._on_enter()
        first._on_enter()
    first.close()

    second = DrillApp(root, tmp_path / "many.db", deck=None, limit=40, new_per_day=5)
    assert second.plan is not None
    assert second.plan.new_introduced == 0, "reopening introduced more new cards"
    second.close()
    root.destroy()
