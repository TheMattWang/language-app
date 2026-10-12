"""Settings, the optional goal date, dialect resolution and `drill setup`."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from drill import cli, dialect, export, packs, store

UTC = timezone.utc
NOW = datetime(2026, 10, 12, tzinfo=UTC)
PACK = packs.load()


def _conn(tmp_path: Path):
    return store.connect(tmp_path / "drill.db")


# --- settings and goal date ----------------------------------------------------


def test_settings_roundtrip_and_delete(tmp_path) -> None:
    conn = _conn(tmp_path)
    assert store.get_setting(conn, "k") is None
    store.set_setting(conn, "k", "v1")
    store.set_setting(conn, "k", "v2")
    assert store.get_setting(conn, "k") == "v2"
    store.set_setting(conn, "k", None)
    assert store.get_setting(conn, "k", "dflt") == "dflt"


def test_goal_horizon_absent_or_malformed_is_none(tmp_path) -> None:
    conn = _conn(tmp_path)
    assert store.goal_horizon(conn) is None
    store.set_setting(conn, store.SETTING_GOAL_DATE, "not-a-date")
    assert store.goal_horizon(conn) is None
    store.set_setting(conn, store.SETTING_GOAL_DATE, "2026-12-20")
    assert store.goal_horizon(conn) == datetime(2026, 12, 20, tzinfo=UTC)


def test_no_goal_date_paces_at_sustainable_default(tmp_path) -> None:
    conn = _conn(tmp_path)
    for path in PACK.deck_paths():
        store.import_jsonl(conn, path)
    assert store.suggested_new_per_day(conn, NOW) == store.SUSTAINABLE_NEW_PER_DAY


def test_goal_date_paces_to_finish_in_time(tmp_path) -> None:
    conn = _conn(tmp_path)
    for path in PACK.deck_paths():
        store.import_jsonl(conn, path)
    horizon = datetime(2026, 10, 22, tzinfo=UTC)  # 10 days, 455 cards -> capped at 40
    assert store.suggested_new_per_day(conn, NOW, horizon=horizon) == 40


def test_unknown_dialect_setting_falls_back(tmp_path) -> None:
    conn = _conn(tmp_path)
    store.set_setting(conn, store.SETTING_DIALECT, "xx")
    assert store.get_dialect(conn) == store.DEFAULT_DIALECT


# --- dialect.resolve -----------------------------------------------------------


def test_spain_keeps_card_as_authored() -> None:
    obj = {"tags": ["why:region"]}
    assert dialect.resolve(obj, ["el coche"], ["carro"], "es-ES") == (["el coche"], ["carro"])


def test_region_card_without_variant_is_skipped_for_latam() -> None:
    # Moving the fragment `carro` into accept would let a bare fragment pass.
    assert dialect.resolve({"tags": ["why:region"]}, ["el coche"], ["carro"], "es-419") is None
    assert dialect.resolve({"tags": ["why:register"]}, ["tenéis"], ["tienen"], "es-419") is None


def test_variant_supplies_latam_lists() -> None:
    obj = {
        "tags": ["why:region"],
        "variants": {"es-419": {"accept": ["el carro", "el auto"]}},
    }
    assert dialect.resolve(obj, ["el coche"], ["carro"], "es-419") == (["el carro", "el auto"], [])


def test_meaning_and_form_rejects_survive_every_variety() -> None:
    obj = {"tags": ["why:meaning"]}
    assert dialect.resolve(obj, ["es aburrido"], ["está aburrido"], "es-419") == (
        ["es aburrido"], ["está aburrido"],
    )


def test_varieties_field_limits_card() -> None:
    obj = {"varieties": ["es-ES"]}
    assert dialect.resolve(obj, ["lleguéis"], [], "es-419") is None
    assert dialect.resolve(obj, ["lleguéis"], [], "es-ES") == (["lleguéis"], [])


def test_import_with_variety_reports_skipped(tmp_path) -> None:
    deck = tmp_path / "d.jsonl"
    rows = [
        {"id": "a", "deck": "d", "kind": "production", "prompt_en": "car",
         "accept": ["el coche"], "reject": ["carro"], "tags": ["why:region"]},
        {"id": "b", "deck": "d", "kind": "production", "prompt_en": "hello",
         "accept": ["hola"]},
    ]
    deck.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    conn = _conn(tmp_path)
    result = store.import_jsonl(conn, deck, variety="es-419")
    assert (result.added, result.skipped) == (1, ("a",))


# --- bundled pack ----------------------------------------------------------------


def test_bundled_pack_manifest_names_every_deck() -> None:
    names = {p.stem for p in PACK.deck_paths()}
    assert names == set(PACK.deck_varieties), "deck files and manifest disagree"
    assert PACK.scenarios_path.is_file()


def test_latam_pack_has_no_vosotros_answers(tmp_path) -> None:
    conn = _conn(tmp_path)
    for path in PACK.deck_paths("es-419"):
        store.remove_cards(conn, store.import_jsonl(conn, path, variety="es-419").skipped)
    accepts = [
        a for (raw,) in conn.execute("SELECT accept_json FROM card")
        for a in json.loads(raw)
    ]
    assert accepts
    numbers = ("seis", "dieciséis", "veintiséis")
    vosotros = [
        a for a in accepts
        for w in a.strip("¿?¡!.").split()
        if w in ("vosotros", "os") or (w.endswith(("áis", "éis")) and w not in numbers)
    ]
    assert not vosotros


# --- drill setup ----------------------------------------------------------------


def _setup(db: Path, *argv: str) -> int:
    return cli.main(["--db", str(db), "setup", *argv])


def test_setup_switching_dialect_reimports(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    db = tmp_path / "drill.db"
    assert _setup(db, "--dialect", "es-419") == 0
    conn = store.connect(db)
    assert store.get_dialect(conn) == "es-419"
    latam = conn.execute("SELECT COUNT(*) FROM card").fetchone()[0]
    assert conn.execute(
        "SELECT COUNT(*) FROM card WHERE deck = 'peninsular_contrast'"
    ).fetchone()[0] == 0
    conn.close()

    assert _setup(db, "--dialect", "es-ES") == 0
    conn = store.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM card").fetchone()[0] > latam


@pytest.mark.parametrize("bad", ["2020-01-01", "12/20/2026"])
def test_setup_rejects_bad_goal_dates(tmp_path, monkeypatch, bad) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert _setup(tmp_path / "drill.db", "--goal-date", bad) == 2


def test_setup_goal_date_set_and_cleared(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    db = tmp_path / "drill.db"
    assert _setup(db, "--goal-date", "2099-01-01") == 0
    assert store.goal_horizon(store.connect(db)) == datetime(2099, 1, 1, tzinfo=UTC)
    assert _setup(db, "--goal-date", "none") == 0
    assert store.goal_horizon(store.connect(db)) is None


# --- export ------------------------------------------------------------------------


def test_export_mentions_goal_only_when_set(tmp_path) -> None:
    conn = _conn(tmp_path)
    assert "meta" not in export.build_markdown(conn, now=NOW).splitlines()[2]
    store.set_setting(conn, store.SETTING_GOAL_DATE, "2026-10-22")
    assert "faltan 10 día(s) para tu meta" in export.build_markdown(conn, now=NOW)
