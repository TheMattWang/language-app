"""Typo tolerance vs. word confusion -- the line L4 has to hold.

A grader that is too strict teaches the user the tool is broken; one that is
too loose teaches wrong Spanish. Both failures happened here, in that order:
an unbounded fuzzy layer accepted "soy" for "estoy", the fix gated on token
length, and the length gate then rejected 42% of ordinary single-letter
typos because Spanish function words are two and three letters long.

The rule these tests pin: forgiveness depends on whether what was typed is a
word, not on how long it is.
"""

from __future__ import annotations

import pytest

from drill.grader import grade


# --- slips: not Spanish words, so they can only be mistypings --------------

@pytest.mark.parametrize(
    "attempt,accept",
    [
        ("hoi", "hoy"),
        ("vou", "voy"),
        ("uon", "uno"),
        ("dks", "dos"),
        ("mol", "mil"),
        ("sde", "sed"),
    ],
)
def test_nonword_typo_on_a_short_word_is_forgiven(attempt: str, accept: str) -> None:
    v = grade(attempt, accept=[accept])
    assert v.accepted, f"{attempt!r} is not a Spanish word; it can only be a typo of {accept!r}"
    assert v.layer == "L4_close"


def test_one_key_slip_does_not_fail_a_whole_sentence() -> None:
    v = grade(
        "madrid está em el centro de españa",
        accept=["Madrid está en el centro de España"],
    )
    assert v.accepted, "a single mistyped preposition failed six correct words"


def test_mistyped_article_is_still_an_article() -> None:
    # "la" is stripped from the accept form, so a mistyped one has to be
    # stripped from the attempt too or the token counts never line up.
    assert grade("lc paella está rica", accept=["la paella está rica"]).accepted
    assert grade("ea coche", accept=["el coche"]).accepted


def test_mistyped_pronoun_is_still_a_pronoun() -> None:
    # Regression: this broke all 18 vosotros conjugation cards, in the one
    # deck where vosotros is the entire point.
    assert grade("vosoyros tenéis", accept=["vosotros tenéis"]).accepted


def test_content_word_colliding_with_politeness_is_compared_not_stripped() -> None:
    # "hora" mistyped as "hola" used to be swallowed as a greeting, leaving
    # the sentence a token short and failing on token count rather than on
    # the actual difference. It may still be refused -- "hola" is a real word
    # -- but it must be judged as a word, not vanish.
    v = grade("he estado esperando media hola", accept=["he estado esperando media hora"])
    assert v.layer in ("L4_close", "L5_reject")
    if not v.accepted:
        assert "hola" not in (v.matched or ""), "rejected for the wrong reason"


# --- confusions: real, different words, and the whole point of the card ----

@pytest.mark.parametrize(
    "attempt,accept",
    [
        ("por", "para"),
        ("para", "por"),
        ("papa", "para"),
        ("soy aburrido", "estoy aburrido"),
        ("estoy aburrido", "soy aburrido"),
        ("de qué andén sabe", "de qué andén sale"),
        ("este autobús va al aeropuerto", "esta autobús va al aeropuerto"),
        ("tengo sed", "tengo hambre"),
    ],
)
def test_a_different_real_word_is_never_a_typo(attempt: str, accept: str) -> None:
    assert not grade(attempt, accept=[accept]).accepted, (
        f"{attempt!r} is a real Spanish word, not a slip of {accept!r}"
    )


def test_lexicon_gap_degrades_to_leniency_not_to_a_wrong_rejection() -> None:
    """The lexicon is partial on purpose; a miss must fail open."""
    # "zzqx" is in no lexicon and is not a word: forgiven as a typo.
    assert grade("zzqx", accept=["zzqy"]).accepted
