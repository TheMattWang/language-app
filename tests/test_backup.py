from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from drill import store


def _write_jsonl(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _card_line(**overrides) -> str:
    obj = {
        "id": "pc-001",
        "deck": "peninsular_contrast",
        "kind": "production",
        "prompt_en": "the car",
        "accept": ["el coche"],
        "reject": ["el carro"],
        "note": "carro is LatAm",
        "tags": ["lexicon"],
    }
    obj.update(overrides)
    return json.dumps(obj)


def _add_review(conn: sqlite3.Connection, card_id: str = "pc-001") -> None:
    store.record_review(
        conn,
        card_id=card_id,
        reviewed_at=datetime.now(timezone.utc),
        grade=3,
        latency_ms=500,
        raw_text="el coche",
        accepted=True,
        layer="l1",
        interval_before=0.0,
        interval_after=1.0,
    )


def test_backup_db_missing_source_returns_none(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.db"
    assert store.backup_db(missing) is None


def test_backup_db_creates_valid_copy_with_same_card_count(tmp_path: Path) -> None:
    db_path = tmp_path / "drill.db"
    conn = store.connect(db_path)
    jsonl_path = tmp_path / "cards.jsonl"
    _write_jsonl(
        jsonl_path,
        [_card_line(id="pc-001"), _card_line(id="pc-002", prompt_en="the house", accept=["la casa"])],
    )
    store.import_jsonl(conn, jsonl_path)
    conn.close()

    backup_path = store.backup_db(db_path)

    assert backup_path is not None
    assert backup_path.exists()
    assert backup_path.name.startswith("drill.db.bak.")

    backup_conn = sqlite3.connect(str(backup_path))
    count = backup_conn.execute("SELECT COUNT(*) FROM card").fetchone()[0]
    backup_conn.close()
    assert count == 2


def test_backup_db_prunes_to_keep_newest(tmp_path: Path) -> None:
    db_path = tmp_path / "drill.db"
    conn = store.connect(db_path)
    conn.close()

    written: list[Path] = []
    for _ in range(7):
        p = store.backup_db(db_path, keep=3)
        assert p is not None
        written.append(p)
        time.sleep(0.001)  # ensure distinct timestamps -> distinct filenames

    remaining = sorted(tmp_path.glob("drill.db.bak.*"))
    assert len(remaining) == 3
    # The newest 3 written backups should be the ones that remain.
    assert set(remaining) == set(sorted(written)[-3:])


def test_backup_db_unwritable_dir_returns_none(tmp_path: Path) -> None:
    db_path = tmp_path / "drill.db"
    conn = store.connect(db_path)
    conn.close()

    ro_dir = tmp_path / "readonly"
    ro_dir.mkdir()
    ro_db_path = ro_dir / "drill.db"
    ro_db_path.write_bytes(db_path.read_bytes())

    ro_dir.chmod(0o500)  # read + execute, no write
    try:
        result = store.backup_db(ro_db_path)
        assert result is None
    finally:
        ro_dir.chmod(0o700)  # restore so tmp_path cleanup can remove it


def test_import_backs_up_when_review_rows_exist(tmp_path: Path) -> None:
    db_path = tmp_path / "drill.db"
    conn = store.connect(db_path)
    jsonl_path = tmp_path / "cards.jsonl"
    _write_jsonl(jsonl_path, [_card_line(id="pc-001")])
    store.import_jsonl(conn, jsonl_path)
    _add_review(conn)

    store.import_jsonl(conn, jsonl_path)

    backups = list(tmp_path.glob("drill.db.bak.*"))
    assert len(backups) == 1


def test_import_does_not_back_up_on_fresh_database(tmp_path: Path) -> None:
    db_path = tmp_path / "drill.db"
    conn = store.connect(db_path)
    jsonl_path = tmp_path / "cards.jsonl"
    _write_jsonl(jsonl_path, [_card_line(id="pc-001")])

    store.import_jsonl(conn, jsonl_path)
    # Still no reviews after this import -- no backup should be produced.
    store.import_jsonl(conn, jsonl_path)

    backups = list(tmp_path.glob("drill.db.bak.*"))
    assert backups == []


def test_import_of_scenarios_schema_yields_single_clear_error(tmp_path: Path) -> None:
    conn = store.connect(tmp_path / "drill.db")
    scenarios_path = Path(__file__).parent.parent / "data" / "scenarios.jsonl"

    result = store.import_jsonl(conn, scenarios_path)

    assert result.added == 0
    assert result.updated == 0
    assert result.unchanged == 0
    assert len(result.errors) == 1
    assert "different schema" in result.errors[0]
