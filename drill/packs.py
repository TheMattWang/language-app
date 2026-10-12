"""Language packs: the bundled content for one language, under data/<lang>/.

A pack is a folder of card decks plus `manifest.json`, which names the
language, its varieties (e.g. es-ES / es-419) and which variety each deck
is for. Adding a language is adding a folder; nothing here is Spanish-
specific. A deck missing from the manifest -- or a folder with no manifest
at all -- is treated as serving every variety, so a hand-dropped deck still
imports.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["DEFAULT_LANGUAGE", "Pack", "default_root", "load"]

DEFAULT_LANGUAGE = "es"
_MANIFEST = "manifest.json"
_DEFAULT_SCENARIOS = "scenarios.jsonl"


def default_root() -> Path:
    """The bundled `data/` directory, resolved from the package, not the CWD."""
    return Path(__file__).resolve().parent.parent / "data"


@dataclass(frozen=True)
class Pack:
    language: str
    path: Path
    varieties: dict[str, str] = field(default_factory=dict)
    deck_varieties: dict[str, tuple[str, ...]] = field(default_factory=dict)
    scenarios_file: str = _DEFAULT_SCENARIOS

    @property
    def scenarios_path(self) -> Path:
        return self.path / self.scenarios_file

    def deck_paths(self, variety: str | None = None) -> list[Path]:
        """Card deck files in this pack, optionally only those for `variety`."""
        paths = sorted(
            p for p in self.path.glob("*.jsonl") if p.name != self.scenarios_file
        )
        if variety is None:
            return paths
        return [p for p in paths if self.serves(p.stem, variety)]

    def serves(self, deck: str, variety: str) -> bool:
        wanted = self.deck_varieties.get(deck)
        return wanted is None or variety in wanted


def load(language: str = DEFAULT_LANGUAGE, root: Path | None = None) -> Pack:
    """Load the pack for `language`. A missing manifest yields an
    all-varieties pack over whatever decks the folder holds."""
    path = (root or default_root()) / language
    manifest = path / _MANIFEST
    if not manifest.is_file():
        return Pack(language=language, path=path)
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    return Pack(
        language=raw.get("language", language),
        path=path,
        varieties=dict(raw.get("varieties", {})),
        deck_varieties={
            name: tuple(spec.get("varieties", ()))
            for name, spec in raw.get("decks", {}).items()
        },
        scenarios_file=raw.get("scenarios", _DEFAULT_SCENARIOS),
    )
