"""Progress view, view toggling and deck picker for the desktop app.

Same pattern as test_app.py: window withdrawn, widgets driven directly,
skip the whole module when no display is available.
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

CARDS_A = [
    {
        "id": "a1", "deck": "a", "kind": "contrast", "prompt_en": "the car (Spain)",
        "accept": ["el coche"], "reject": ["carro"], "note": None, "tags": ["lex"],
    },
    {
        "id": "a2", "deck": "a", "kind": "production", "prompt_en": "the juice (Spain)",
        "accept": ["el zumo"], "reject": ["jugo"], "note": None, "tags": ["lex"],
    },
]

CARDS_B = [
    {
        "id": "b1", "deck": "b", "kind": "production", "prompt_en": "hello",
        "accept": ["hola"], "reject": [], "note": None, "tags": ["greet"],
    },
]


def _make_root():
    try:
        root = tk.Tk()
    except tk.TclError:  # pragma: no cover - no display available
        pytest.skip("no display available for tkinter")
    root.withdraw()
    return root


@pytest.fixture()
def two_deck_db(tmp_path: Path) -> Path:
    deck_file = tmp_path / "cards.jsonl"
    rows = CARDS_A + CARDS_B
    deck_file.write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in rows), encoding="utf-8"
    )
    db_path = tmp_path / "t.db"
    conn = store.connect(db_path)
    store.import_jsonl(conn, deck_file)
    conn.close()
    return db_path


@pytest.fixture()
def app(two_deck_db: Path):
    root = _make_root()
    a = DrillApp(root, two_deck_db, deck=None, limit=10)
    yield a
    a.close()
    root.destroy()


def _answer(a: DrillApp, text: str) -> None:
    a.entry.delete(0, tk.END)
    a.entry.insert(0, text)
    a._on_enter()


# --- toggle -----------------------------------------------------------------


def test_tab_switches_to_progress_and_back(app: DrillApp) -> None:
    assert app.view == "drill"
    app._toggle_view()
    assert app.view == "progress"
    assert str(app.progress_frame.winfo_manager()) == "pack"
    app._toggle_view()
    assert app.view == "drill"
    assert str(app.drill_frame.winfo_manager()) == "pack"


def test_drill_state_survives_a_round_trip(app: DrillApp) -> None:
    app.entry.insert(0, "partial answer")
    card_before = app.queue[app.index][0]
    entry_before = app.entry.get()

    app._toggle_view()
    app._toggle_view()

    assert app.queue[app.index][0] is card_before
    assert app.entry.get() == entry_before
    assert app.awaiting_next is False


def test_tab_key_does_not_insert_a_tab_character(app: DrillApp) -> None:
    app.entry.insert(0, "abc")
    result = app._toggle_view()
    assert result == "break"
    assert "\t" not in app.entry.get()


# --- progress content ---------------------------------------------------


def test_progress_shows_honest_message_with_no_history(app: DrillApp) -> None:
    app._toggle_view()
    assert "no hay datos suficientes" in app.lbl_tags_empty.cget("text")
    for lbl in app.tag_rows:
        assert str(lbl.winfo_manager()) != "grid" or lbl.grid_info() == {}


def test_progress_shows_weakest_tag_with_seeded_history(app: DrillApp) -> None:
    for _ in range(4):
        store.record_review(
            app.conn, card_id="a1", reviewed_at=datetime.now(UTC), grade=1,
            latency_ms=500, raw_text="carro", accepted=False, layer=None,
            interval_before=0.0, interval_after=0.0,
        )
    app._toggle_view()
    assert app.lbl_tags_empty.cget("text") == ""
    texts = [lbl.cget("text") for lbl in app.tag_rows if lbl.grid_info()]
    assert any("lex" in t for t in texts)


def test_hardest_cards_appear_with_seeded_history(app: DrillApp) -> None:
    for accepted in (False, False, True):
        store.record_review(
            app.conn, card_id="a1", reviewed_at=datetime.now(UTC), grade=1,
            latency_ms=500, raw_text="x", accepted=accepted, layer=None,
            interval_before=0.0, interval_after=0.0,
        )
    app._toggle_view()
    texts = [lbl.cget("text") for lbl in app.card_rows if lbl.grid_info()]
    assert any("the car (Spain)" in t for t in texts)


# --- deck picker ----------------------------------------------------------


def test_deck_picker_lists_todas_and_seeded_decks(app: DrillApp) -> None:
    values = list(app.deck_picker["values"])
    assert values == ["Todas", "a", "b"]


def test_selecting_a_deck_reloads_the_filtered_queue(app: DrillApp) -> None:
    app.deck_picker.set("b")
    app._on_deck_change()
    assert app.deck == "b"
    assert len(app.queue) == 1
    assert app.queue[0][0].deck == "b"
    assert app.index == 0


def test_selecting_a_deck_preserves_session_counters(app: DrillApp) -> None:
    _answer(app, "el coche")
    assert app.correct == 1 and app.answered == 1

    app.deck_picker.set("b")
    app._on_deck_change()

    assert app.correct == 1
    assert app.answered == 1


# --- empty database ---------------------------------------------------------


def test_empty_database_does_not_raise(tmp_path: Path) -> None:
    store.connect(tmp_path / "empty.db").close()
    root = _make_root()
    a = DrillApp(root, tmp_path / "empty.db", deck=None, limit=10)
    assert list(a.deck_picker["values"]) == ["Todas"]
    a._toggle_view()
    assert "no hay datos suficientes" in a.lbl_tags_empty.cget("text")
    a._toggle_view()
    a.close()
    root.destroy()
