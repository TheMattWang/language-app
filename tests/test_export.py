from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from drill import cli, export, store

NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _write_jsonl(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _card_line(**overrides) -> str:
    obj = {
        "id": "c-001",
        "deck": "trip",
        "kind": "production",
        "prompt_en": "the car",
        "accept": ["el coche"],
        "reject": [],
        "note": None,
        "tags": [],
    }
    obj.update(overrides)
    return json.dumps(obj)


def _record(conn, card_id: str, *, accepted: bool, n: int = 1, latency_ms: int = 1000) -> None:
    for i in range(n):
        store.record_review(
            conn,
            card_id=card_id,
            reviewed_at=NOW - timedelta(minutes=i),
            grade=3 if accepted else 0,
            latency_ms=latency_ms,
            raw_text="x",
            accepted=accepted,
            layer="L2_exact" if accepted else None,
            interval_before=0.0,
            interval_after=1.0,
        )


def _seed(conn, jsonl_path: Path) -> None:
    _write_jsonl(
        jsonl_path,
        [
            # subjunctive: weak tag, will get missed a lot
            _card_line(id="sub-001", prompt_en="I hope you come", accept=["espero que vengas"], tags=["subjunctive"]),
            _card_line(id="sub-002", prompt_en="I want you to eat", accept=["quiero que comas"], tags=["subjunctive"]),
            _card_line(id="sub-003", prompt_en="I doubt he knows", accept=["dudo que sepa"], tags=["subjunctive"]),
            # ser_estar: strong tag
            _card_line(id="se-001", prompt_en="the pharmacy is open", accept=["la farmacia esta abierta"], tags=["ser_estar"]),
            _card_line(id="se-002", prompt_en="it is closed", accept=["esta cerrado"], tags=["ser_estar"]),
            _card_line(id="se-003", prompt_en="he is tall", accept=["es alto"], tags=["ser_estar"]),
            # a thin card, under min_attempts
            _card_line(id="thin-001", prompt_en="the dog", accept=["el perro"], tags=["subjunctive"]),
            # a register trap (LatAm reject) missed once
            _card_line(id="reg-001", deck="trip", prompt_en="the car", accept=["el coche"], reject=["el carro"], tags=["lexicon"]),
            # a register trap never missed -- should not appear in trampas
            _card_line(id="reg-002", deck="trip", prompt_en="the phone", accept=["el movil"], reject=["el celular"], tags=["lexicon"]),
            # cloze card, missed several times
            _card_line(
                id="cz-001",
                deck="grammar",
                kind="cloze",
                prompt_en="No creo que ___ la respuesta. — I don't think he knows the answer.",
                accept=["sepa"],
                reject=[],
                tags=["subjunctive"],
            ),
        ],
    )
    store.import_jsonl(conn, jsonl_path)

    # subjunctive: mostly wrong (weak)
    _record(conn, "sub-001", accepted=False, n=3)
    _record(conn, "sub-001", accepted=True, n=1)
    _record(conn, "sub-002", accepted=False, n=2)
    _record(conn, "sub-003", accepted=False, n=4)  # most-missed card
    _record(conn, "thin-001", accepted=False, n=1)  # only 1 attempt -- thin

    # ser_estar: mostly right (strong)
    _record(conn, "se-001", accepted=True, n=3)
    _record(conn, "se-002", accepted=True, n=3)
    _record(conn, "se-003", accepted=True, n=3)

    # register trap: missed once
    _record(conn, "reg-001", accepted=False, n=1)
    _record(conn, "reg-001", accepted=True, n=1)
    # reg-002 attempted but never missed
    _record(conn, "reg-002", accepted=True, n=2)

    # cloze: missed twice
    _record(conn, "cz-001", accepted=False, n=2)


def test_weakest_tag_appears(tmp_path: Path) -> None:
    conn = store.connect(tmp_path / "drill.db")
    _seed(conn, tmp_path / "cards.jsonl")
    doc = export.build_markdown(conn, now=NOW)
    assert "subjunctive" in doc
    assert "ser_estar" in doc


def test_more_misses_sorts_before_fewer_misses(tmp_path: Path) -> None:
    conn = store.connect(tmp_path / "drill.db")
    _seed(conn, tmp_path / "cards.jsonl")
    doc = export.build_markdown(conn, now=NOW, min_attempts=2)
    # sub-003 (4 misses) must appear before sub-002 (2 misses)
    pos_003 = doc.index("dudo que sepa")
    pos_002 = doc.index("quiero que comas")
    assert pos_003 < pos_002


def test_min_attempts_excludes_thin_cards(tmp_path: Path) -> None:
    conn = store.connect(tmp_path / "drill.db")
    _seed(conn, tmp_path / "cards.jsonl")
    doc = export.build_markdown(conn, now=NOW, min_attempts=2)
    assert "el perro" not in doc  # thin-001 has only 1 attempt


def test_cloze_exports_as_filled_sentence(tmp_path: Path) -> None:
    conn = store.connect(tmp_path / "drill.db")
    _seed(conn, tmp_path / "cards.jsonl")
    doc = export.build_markdown(conn, now=NOW, min_attempts=2)
    assert "No creo que sepa la respuesta." in doc
    assert "___" not in doc


def test_trampas_renders_reject_arrow_for_missed_card(tmp_path: Path) -> None:
    conn = store.connect(tmp_path / "drill.db")
    _seed(conn, tmp_path / "cards.jsonl")
    doc = export.build_markdown(conn, now=NOW)
    assert "✗ el carro → ✓ el coche" in doc
    # reg-002 was never missed -- must not appear in trampas
    assert "el celular" not in doc


def test_no_ansi_escapes_anywhere(tmp_path: Path) -> None:
    conn = store.connect(tmp_path / "drill.db")
    _seed(conn, tmp_path / "cards.jsonl")
    doc = export.build_markdown(conn, now=NOW)
    assert not _ANSI_RE.search(doc)


def test_no_history_produces_honest_document(tmp_path: Path) -> None:
    conn = store.connect(tmp_path / "drill.db")
    jsonl_path = tmp_path / "cards.jsonl"
    _write_jsonl(jsonl_path, [_card_line(id="c-001")])
    store.import_jsonl(conn, jsonl_path)  # imported, but never reviewed

    doc = export.build_markdown(conn, now=NOW)
    assert "no hay suficiente" in doc.lower() or "todavía no hay" in doc.lower()
    # must not fabricate a ranking or a card entry
    assert "el coche" not in doc


def test_cmd_export_creates_file_and_parent_dir(tmp_path: Path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "drill.db"
    conn = store.connect(db_path)
    _seed(conn, tmp_path / "cards.jsonl")
    conn.close()

    out_path = tmp_path / "nested" / "dir" / "mis_fallos.md"
    assert not out_path.parent.exists()

    args = cli.build_parser().parse_args(
        ["--db", str(db_path), "export", "--out", str(out_path)]
    )
    rc = args.func(args)

    assert rc == 0
    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")
    assert "subjunctive" in content
    captured = capsys.readouterr()
    assert str(out_path) in captured.out
