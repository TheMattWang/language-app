"""Tests for `drill.cloze`: parsing/rendering helpers that make
`kind="cloze"` cards actually render differently from production cards.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from drill import cloze, store
from drill.grader import grade

# --- parsing -----------------------------------------------------------


def test_parse_with_em_dash_meaning() -> None:
    c = cloze.parse("No creo que ___ la respuesta. — I don't think he knows the answer.")
    assert c.sentence_es == "No creo que ___ la respuesta."
    assert c.meaning_en == "I don't think he knows the answer."
    assert c.gap_count == 1


def test_parse_with_hyphen_meaning() -> None:
    c = cloze.parse("Quiero que ___ conmigo. - I want you to come with me.")
    assert c.sentence_es == "Quiero que ___ conmigo."
    assert c.meaning_en == "I want you to come with me."
    assert c.gap_count == 1


def test_parse_prefers_em_dash_over_hyphen() -> None:
    c = cloze.parse("El anti-héroe ___ gana. — the anti-hero wins.")
    assert c.sentence_es == "El anti-héroe ___ gana."
    assert c.meaning_en == "the anti-hero wins."


def test_parse_without_meaning() -> None:
    c = cloze.parse("No creo que ___ la respuesta.")
    assert c.sentence_es == "No creo que ___ la respuesta."
    assert c.meaning_en is None
    assert c.gap_count == 1


def test_parse_without_gap_never_raises() -> None:
    c = cloze.parse("Ya lo sé. — I already know it.")
    assert c.sentence_es == "Ya lo sé."
    assert c.meaning_en == "I already know it."
    assert c.gap_count == 0


def test_parse_with_multiple_gaps() -> None:
    c = cloze.parse("___ que ___ la verdad. — that he knows the truth.")
    assert c.gap_count == 2


def test_parse_strips_whitespace() -> None:
    c = cloze.parse("  Quiero que ___ .  —   I want that.  ")
    assert c.sentence_es == "Quiero que ___ ."
    assert c.meaning_en == "I want that."


def test_parse_empty_string_never_raises() -> None:
    c = cloze.parse("")
    assert c.sentence_es == ""
    assert c.meaning_en is None
    assert c.gap_count == 0


def test_is_cloze() -> None:
    assert cloze.is_cloze("cloze") is True
    assert cloze.is_cloze("production") is False
    assert cloze.is_cloze("contrast") is False


# --- rendering -----------------------------------------------------------


def test_render_question_shows_gap() -> None:
    c = cloze.parse("No creo que ___ la respuesta. — I don't think he knows.")
    assert cloze.render_question(c) == "No creo que ___ la respuesta."


def test_render_question_with_no_gap_renders_as_itself() -> None:
    c = cloze.parse("Ya lo sé. — I already know it.")
    assert cloze.render_question(c) == "Ya lo sé."


def test_render_filled_replaces_gap() -> None:
    c = cloze.parse("No creo que ___ la respuesta. — I don't think he knows.")
    assert cloze.render_filled(c, "sepa") == "No creo que sepa la respuesta."


def test_render_filled_only_replaces_first_gap() -> None:
    c = cloze.parse("___ que ___ la verdad. — that he knows the truth.")
    assert cloze.render_filled(c, "sé") == "sé que ___ la verdad."


def test_render_filled_with_no_gap_is_unchanged() -> None:
    c = cloze.parse("Ya lo sé. — I already know it.")
    assert cloze.render_filled(c, "sepa") == "Ya lo sé."


# --- grading integration --------------------------------------------------


def test_cloze_card_grades_on_gap_text_only() -> None:
    verdict = grade("sepa", accept=["sepa"], reject=[])
    assert verdict.accepted is True

    verdict = grade(
        "No creo que sepa la respuesta", accept=["sepa"], reject=[]
    )
    assert verdict.accepted is False, "grading a cloze card must be against the gap fill, not the sentence"


# --- store import (kind is accepted, unaffected by cloze helpers) --------


def test_cloze_card_imports_via_store(tmp_path: Path) -> None:
    card = {
        "id": "cz-001", "deck": "cloze_grammar", "kind": "cloze",
        "prompt_en": "No creo que ___ la respuesta. — I don't think he knows the answer.",
        "accept": ["sepa"], "reject": [], "note": "no creer + subjunctive",
        "tags": ["subjunctive"],
    }
    deck_file = tmp_path / "cloze.jsonl"
    deck_file.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
    conn = store.connect(tmp_path / "t.db")
    result = store.import_jsonl(conn, deck_file)
    assert result.added == 1
    row = conn.execute("SELECT kind FROM card WHERE card_id='cz-001'").fetchone()
    assert row["kind"] == "cloze"
    conn.close()


# --- GUI ------------------------------------------------------------------

tk = pytest.importorskip("tkinter")

from drill.app import DrillApp  # noqa: E402


def _make_root():
    try:
        root = tk.Tk()
    except tk.TclError:  # pragma: no cover - no display available
        pytest.skip("no display available for tkinter")
    root.withdraw()
    return root


def test_gui_shows_gapped_sentence_and_filled_sentence(tmp_path: Path) -> None:
    cards = [
        {
            "id": "cz-001", "deck": "cz", "kind": "cloze",
            "prompt_en": "No creo que ___ la respuesta. — I don't think he knows the answer.",
            "accept": ["sepa"], "reject": [], "note": None, "tags": [],
        },
    ]
    deck_file = tmp_path / "cz.jsonl"
    deck_file.write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in cards), encoding="utf-8"
    )
    conn = store.connect(tmp_path / "t.db")
    store.import_jsonl(conn, deck_file)
    conn.close()

    root = _make_root()
    app = DrillApp(root, tmp_path / "t.db", deck=None, limit=10)
    try:
        assert app.lbl_prompt.cget("text") == "No creo que ___ la respuesta."
        assert "I don't think he knows the answer." in app.lbl_meaning.cget("text")

        app.entry.insert(0, "sepa")
        app._on_enter()

        all_labels_text = " ".join(
            [
                app.lbl_prompt.cget("text"),
                app.lbl_verdict.cget("text"),
                app.lbl_target.cget("text"),
                app.lbl_note.cget("text"),
                app.lbl_meaning.cget("text"),
            ]
        )
        assert "No creo que sepa la respuesta." in all_labels_text
    finally:
        app.close()
        root.destroy()


def test_gui_non_cloze_card_display_is_unchanged(tmp_path: Path) -> None:
    cards = [
        {
            "id": "p1", "deck": "p", "kind": "production",
            "prompt_en": "the juice (Spain)",
            "accept": ["el zumo"], "reject": ["jugo"], "note": None, "tags": [],
        },
    ]
    deck_file = tmp_path / "p.jsonl"
    deck_file.write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in cards), encoding="utf-8"
    )
    conn = store.connect(tmp_path / "t.db")
    store.import_jsonl(conn, deck_file)
    conn.close()

    root = _make_root()
    app = DrillApp(root, tmp_path / "t.db", deck=None, limit=10)
    try:
        assert app.lbl_prompt.cget("text") == "the juice (Spain)"
        assert app.lbl_meaning.cget("text") == ""

        app.entry.insert(0, "jugo")
        app._on_enter()

        assert app.lbl_target.cget("text") == "el zumo"
    finally:
        app.close()
        root.destroy()
