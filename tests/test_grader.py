"""Tests for drill.grader.

This module decides whether the drill tool is usable at all: a grader that
false-rejects correct Spanish teaches the user the tool is broken. Every
layer is tested individually, plus an explicit false-reject budget test
against a table of realistically-varied correct answers.
"""

from __future__ import annotations

from drill.grader import grade
from drill.normalize import fold_accents, normalize


# --- L0: empty / too short --------------------------------------------------


def test_l0_empty_string_rejected() -> None:
    v = grade("", accept=["hola"])
    assert v.accepted is False
    assert v.layer == "L0_empty"


def test_l0_whitespace_only_rejected() -> None:
    v = grade("     ", accept=["hola"])
    assert v.accepted is False
    assert v.layer == "L0_empty"


def test_l0_single_character_rejected() -> None:
    v = grade("a", accept=["hola"])
    assert v.accepted is False
    assert v.layer == "L0_empty"


# --- L1: banned (LatAm) vocabulary -----------------------------------------


def test_l1_banned_carro_rejected_with_peninsular_alternative() -> None:
    v = grade("el carro es rojo", accept=["el coche es rojo", "coche"], reject=["carro"])
    assert v.accepted is False
    assert v.layer == "L1_banned"
    assert "coche" in (v.detail or "")


def test_l1_does_not_substring_match_inside_words() -> None:
    # "carrocería" contains "carro" as a substring but is a different word
    # entirely — must not be caught by the "carro" ban.
    v = grade("la carrocería es roja", accept=["la carrocería es roja"], reject=["carro"])
    assert v.accepted is True
    assert v.layer != "L1_banned"


def test_l1_reject_list_empty_never_fires() -> None:
    v = grade("el carro es rojo", accept=["el carro es rojo"])
    assert v.accepted is True


# --- ñ is never folded -------------------------------------------------------


def test_ene_tilde_never_folded_by_fold_accents() -> None:
    assert fold_accents(normalize("año")) == "año"
    assert fold_accents(normalize("ano")) == "ano"


def test_ano_and_anio_are_not_the_same_word() -> None:
    # "año" (year) vs "ano" (anus) must never be conflated, even though they
    # are one character apart and every other accent slip is forgiven.
    v = grade("ano", accept=["año"])
    assert v.accepted is False
    assert v.layer == "L5_reject"


def test_ano_and_anio_not_conflated_mid_sentence() -> None:
    v = grade("tengo un ano", accept=["tengo un año"])
    assert v.accepted is False


# --- L3: accent-only differences --------------------------------------------


def test_l3_accent_slip_accepted() -> None:
    v = grade("como estas", accept=["cómo estás"])
    assert v.accepted is True
    assert v.layer == "L3_accent"
    assert "tilde" in v.reason.lower()


def test_l3_accent_slip_accepted_single_word() -> None:
    # NOT "esta"/"está": those are different words (this / is), a tilde
    # diacrítica pair the grader must keep apart. A real accent slip is a
    # word that does not change identity when the accent is dropped.
    v = grade("cafe", accept=["café"])
    assert v.accepted is True
    assert v.layer == "L3_accent"


def test_diacritic_homograph_is_not_an_accent_slip() -> None:
    """esta/está, se/sé, el/él are different words, not typos of each other."""
    for attempt, target in (("esta", "está"), ("se", "sé"), ("el", "él"),
                            ("como", "cómo"), ("mi", "mí")):
        v = grade(attempt, accept=[target])
        assert not v.accepted, f"{attempt!r} wrongly accepted for {target!r} ({v.layer})"


# --- pro-drop: leading subject pronoun is optional --------------------------


def test_prodrop_pronoun_present_when_accept_has_none() -> None:
    v = grade("yo quiero café", accept=["quiero café"])
    assert v.accepted is True


def test_prodrop_pronoun_absent_when_accept_has_one() -> None:
    v = grade("quiero café", accept=["yo quiero café"])
    assert v.accepted is True


# --- politeness wrapping is ignorable ---------------------------------------


def test_politeness_leading_stripped() -> None:
    v = grade("por favor, quiero un café", accept=["quiero un café"])
    assert v.accepted is True


def test_politeness_trailing_stripped() -> None:
    v = grade("quiero un café, gracias", accept=["quiero un café"])
    assert v.accepted is True


def test_politeness_both_ends_stripped() -> None:
    v = grade("hola, quiero un café por favor", accept=["quiero un café"])
    assert v.accepted is True


# --- article variation at the start -----------------------------------------


def test_article_indefinite_vs_definite_accepted() -> None:
    v = grade("un coche", accept=["el coche"])
    assert v.accepted is True


def test_article_present_vs_absent_accepted() -> None:
    v = grade("el coche", accept=["coche"])
    assert v.accepted is True


# --- L4: close (typos, minor agreement) -------------------------------------


def test_l4_single_word_typo_accepted() -> None:
    v = grade("grasias", accept=["gracias"])
    assert v.accepted is True
    assert v.layer == "L4_close"


def test_l4_one_token_agreement_slip_accepted() -> None:
    v = grade("buenas días", accept=["buenos días"])
    assert v.accepted is True
    assert v.layer == "L4_close"


# --- L5: genuinely wrong ------------------------------------------------------


def test_l5_wrong_word_rejected_but_encouraging() -> None:
    v = grade("perro", accept=["gato"])
    assert v.accepted is False
    assert v.layer == "L5_reject"
    assert v.reason  # non-empty, and per design must not scold


# --- FALSE-REJECT BUDGET -----------------------------------------------------
#
# A table of (attempt, accept_forms) pairs a competent Spanish speaker would
# consider unambiguously correct. Varies: word order of politeness wrapping,
# pro-drop, accents, articles, politeness, and minor typos. The grader must
# accept at least 90% of these or the tool is unusable per prior review.

FALSE_REJECT_TABLE: list[tuple[str, list[str]]] = [
    ("hola, quiero un café", ["quiero un café"]),
    ("quiero un café por favor", ["quiero un café"]),
    ("yo quiero café", ["quiero café"]),
    ("quiero café", ["yo quiero café"]),
    ("cómo estás", ["como estas"]),
    ("como estas", ["cómo estás"]),
    ("el coche es rojo", ["un coche es rojo"]),
    ("un coche es rojo", ["el coche es rojo"]),
    ("gracias, dónde está el baño", ["dónde está el baño"]),
    ("dónde esta el baño", ["dónde está el baño"]),
    ("perdona, cuánto cuesta esto", ["cuánto cuesta esto"]),
    ("cuanto cuesta esto", ["cuánto cuesta esto"]),
    ("quiero reservar una mesa por favor", ["quiero reservar una mesa"]),
    ("nosotros queremos la cuenta", ["queremos la cuenta"]),
    ("queremos la cuenta", ["nosotros queremos la cuenta"]),
    ("puedo pagar con tarjeta", ["puedo pagar con tarjeta"]),
    ("hola buenas tardes", ["buenas tardes"]),
    ("buenas tardes", ["hola buenas tardes"]),
    ("necesito ayuda por favor", ["necesito ayuda"]),
    ("perdon, donde esta la estacion", ["dónde está la estación"]),
    ("el tren llega tarde", ["tren llega tarde"]),
    ("tren llega tarde", ["el tren llega tarde"]),
    ("quiero agua, porfa", ["quiero agua"]),
    ("ella tiene la llave", ["tiene la llave"]),
    ("tiene la llave", ["ella tiene la llave"]),
    ("quiero la cuanta", ["quiero la cuenta"]),  # typo: cuanta -> cuenta
    ("dos cervezas por favor", ["dos cervezas"]),
    ("una mesa para dos, gracias", ["una mesa para dos"]),
    ("por favor, quiero una mesa", ["quiero una mesa por favor"]),
    ("oye, cuánto es", ["cuánto es"]),
]


def test_false_reject_budget() -> None:
    failures: list[tuple[str, list[str], str, str]] = []
    for attempt, accept_forms in FALSE_REJECT_TABLE:
        v = grade(attempt, accept=accept_forms)
        if not v.accepted:
            failures.append((attempt, accept_forms, v.layer, v.reason))

    total = len(FALSE_REJECT_TABLE)
    accepted_count = total - len(failures)
    accept_rate = accepted_count / total

    if failures:
        lines = [
            f"  attempt={attempt!r} accept={accept_forms!r} -> layer={layer} reason={reason!r}"
            for attempt, accept_forms, layer, reason in failures
        ]
        failure_report = (
            f"False-reject rate too high: accepted {accepted_count}/{total} "
            f"({accept_rate:.1%}). Wrongly rejected:\n" + "\n".join(lines)
        )
    else:
        failure_report = ""

    assert accept_rate >= 0.90, failure_report
