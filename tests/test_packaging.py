"""Packaging sanity checks.

Guards the project's hard rule -- no runtime dependencies -- and makes sure
the console entry point, package data, and RUNBOOK stay wired up correctly.
`tomllib` is stdlib from Python 3.11; on 3.10 (this project's floor) fall
back to the `tomli` backport, which parses identically.
"""

from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parent.parent


def _load_pyproject() -> dict:
    path = ROOT / "pyproject.toml"
    assert path.exists(), "pyproject.toml is missing"
    return tomllib.loads(path.read_text())


def test_pyproject_parses():
    data = _load_pyproject()
    assert data["project"]["name"] == "drill"


def test_no_runtime_dependencies():
    data = _load_pyproject()
    deps = data["project"].get("dependencies", [])
    assert deps == [], f"drill must have zero runtime dependencies, found: {deps}"


def test_console_script_points_at_cli_main():
    data = _load_pyproject()
    scripts = data["project"]["scripts"]
    assert scripts.get("drill") == "drill.cli:main"


def test_schema_sql_exists_and_is_packaged():
    schema = ROOT / "drill" / "schema.sql"
    assert schema.exists(), "drill/schema.sql must exist"

    data = _load_pyproject()
    package_data = data.get("tool", {}).get("setuptools", {}).get("package-data", {})
    drill_data = package_data.get("drill", [])
    assert "schema.sql" in drill_data, "schema.sql must be declared as package data"


def test_runbook_exists_and_documents_db_path():
    runbook = ROOT / "docs" / "RUNBOOK.md"
    assert runbook.exists(), "docs/RUNBOOK.md is missing"
    text = runbook.read_text()
    assert "~/.langapp/drill.db" in text
