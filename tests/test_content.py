"""Validation for the authored card decks in data/.

Content is the part of this project most likely to break silently: a card
whose reject list catches its own accept form is simply unanswerable, and
you would only find out mid-review. These run over every deck on disk, so
adding cards is covered automatically.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from drill.grader import DEFAULT_REJECT_REASON, REJECT_REASONS, grade, is_reason_tag
from drill.normalize import fold_accents, normalize

DATA = Path(__file__).resolve().parent.parent / "data" / "es"
# scenarios.jsonl is a different schema (multi-turn conversations, not
# single cards) -- it's validated separately in tests/test_scenario.py.
DECKS = sorted(p for p in DATA.glob("*.jsonl") if p.name != "scenarios.jsonl")
VALID_KINDS = {"production", "cloze", "contrast"}


def _load(path: Path) -> list[dict]:
    cards = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            cards.append(json.loads(line))
        except json.JSONDecodeError as exc:  # pragma: no cover - fails the test below
            pytest.fail(f"{path.name}:{lineno} invalid JSON: {exc}")
    return cards


def test_decks_exist() -> None:
    assert DECKS, "no decks found in data/"


@pytest.mark.parametrize("deck_path", DECKS, ids=lambda p: p.name)
def test_schema_and_ids(deck_path: Path) -> None:
    cards = _load(deck_path)
    seen: dict[str, int] = {}
    for i, c in enumerate(cards, 1):
        for field in ("id", "deck", "kind", "prompt_en", "accept"):
            assert field in c, f"{deck_path.name}:{i} missing {field!r}"
        assert c["kind"] in VALID_KINDS, f"{c['id']}: bad kind {c['kind']!r}"
        assert isinstance(c["accept"], list) and c["accept"], f"{c['id']}: empty accept"
        assert all(isinstance(a, str) and a.strip() for a in c["accept"]), c["id"]
        assert c["id"] not in seen, f"duplicate id {c['id']}"
        seen[c["id"]] = i


@pytest.mark.parametrize("deck_path", DECKS, ids=lambda p: p.name)
def test_every_accept_form_passes_its_own_card(deck_path: Path) -> None:
    """A card must accept the answer it teaches.

    The usual cause of failure is a reject entry that also appears in an
    accept form, which makes the card impossible to answer correctly.
    """
    broken = []
    for c in _load(deck_path):
        for form in c["accept"]:
            v = grade(form, accept=c["accept"], reject=c.get("reject", []))
            if not v.accepted:
                broken.append(f"  {c['id']}: {form!r} -> {v.layer} ({v.reason})")
    assert not broken, "cards that reject their own answer:\n" + "\n".join(broken)


@pytest.mark.parametrize("deck_path", DECKS, ids=lambda p: p.name)
def test_every_reject_form_is_caught(deck_path: Path) -> None:
    """A listed LatAm form must actually be flagged, or the card teaches nothing."""
    missed = []
    for c in _load(deck_path):
        for r in c.get("reject", []):
            v = grade(r, accept=c["accept"], reject=c["reject"])
            if v.layer != "L1_banned":
                missed.append(f"  {c['id']}: {r!r} slipped through as {v.layer}")
    assert not missed, "reject forms not caught:\n" + "\n".join(missed)


@pytest.mark.parametrize("deck_path", DECKS, ids=lambda p: p.name)
def test_rejects_name_the_alternative(deck_path: Path) -> None:
    """A rejection has to tell the learner what to say instead."""
    silent = []
    for c in _load(deck_path):
        for r in c.get("reject", []):
            v = grade(r, accept=c["accept"], reject=c["reject"])
            if v.layer == "L1_banned" and not v.detail:
                silent.append(f"  {c['id']}: {r!r} rejected with no guidance")
    assert not silent, "\n".join(silent)


@pytest.mark.parametrize("deck_path", DECKS, ids=lambda p: p.name)
def test_no_card_shows_its_own_answer(deck_path: Path) -> None:
    """A gap answerable by copying a visible word tests nothing.

    Whole-word match on the Spanish half only: the English gloss after the
    em dash is allowed to contain anything, and a substring hit ("es" inside
    "español") is not a leak.
    """
    import re

    leaks = []
    for c in _load(deck_path):
        spanish = c["prompt_en"].split("—")[0].lower()
        for form in c["accept"]:
            pattern = r"(?<![\wáéíóúñü])" + re.escape(form.lower()) + r"(?![\wáéíóúñü])"
            if re.search(pattern, spanish):
                leaks.append(f"  {c['id']}: prompt already contains {form!r}")
    assert not leaks, "cards revealing their own answer:\n" + "\n".join(leaks)


def _why_tags(card: dict) -> list[str]:
    return [t for t in card.get("tags", []) if is_reason_tag(t)]


@pytest.mark.parametrize("deck_path", DECKS, ids=lambda p: p.name)
def test_reason_tag_iff_reject_list(deck_path: Path) -> None:
    """A card has exactly one `why:` tag iff it has a non-empty `reject`.

    Catches drift in both directions: a reject-bearing card left on the
    bland default (missing tag) and a stray `why:` tag on a card that can
    never reach L1_banned (empty reject, so the tag is inert noise).
    """
    bad = []
    for c in _load(deck_path):
        whys = _why_tags(c)
        if c.get("reject"):
            if len(whys) != 1:
                bad.append(f"  {c['id']}: has reject but {len(whys)} why: tags {whys}")
        else:
            if whys:
                bad.append(f"  {c['id']}: no reject but has why: tag(s) {whys}")
    assert not bad, "\n".join(bad)


@pytest.mark.parametrize("deck_path", DECKS, ids=lambda p: p.name)
def test_reason_tag_is_valid(deck_path: Path) -> None:
    """Every `why:` tag value is one of the five valid reasons.

    Catches typos (`why:meaing`) that would otherwise silently degrade to
    the unspecified default at grade time instead of failing loudly here.
    """
    valid = set(REJECT_REASONS) | {DEFAULT_REJECT_REASON}
    bad = []
    for c in _load(deck_path):
        for tag in _why_tags(c):
            value = tag.split(":", 1)[1]
            if value not in valid:
                bad.append(f"  {c['id']}: invalid why: tag {tag!r}")
    assert not bad, "\n".join(bad)


def test_mirror_pairs_are_not_region_or_form() -> None:
    """The test that would have caught the original gr-001/gr-002 bug.

    Build an index of every `accept` form across all decks, folded and
    normalized. Any `reject` form that collides with an answer some other
    (or the same) card teaches as correct cannot honestly be explained as
    "not real Spanish" (`form`) or "not said in Spain" (`region`) -- it is
    demonstrably both real and Peninsular. Such a collision may only be
    tagged `meaning` (it means something else here) or `register` (it's
    the wrong person -- ustedes instead of vosotros).
    """

    def key(s: str) -> str:
        return fold_accents(normalize(s))

    accept_index: dict[str, list[str]] = {}
    for deck_path in DECKS:
        for c in _load(deck_path):
            for form in c["accept"]:
                accept_index.setdefault(key(form), []).append(c["id"])

    bad = []
    for deck_path in DECKS:
        for c in _load(deck_path):
            reason = None
            for tag in _why_tags(c):
                reason = tag.split(":", 1)[1]
            for r in c.get("reject", []):
                hits = accept_index.get(key(r))
                if not hits:
                    continue
                if reason not in ("meaning", "register"):
                    bad.append(
                        f"  {c['id']}: rejects {r!r}, which is accepted by "
                        f"{hits} elsewhere, but is tagged why:{reason}"
                    )
    assert not bad, "reject forms that contradict an accepted answer:\n" + "\n".join(bad)
