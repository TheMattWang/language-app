"""Tests for the L1 reject-reason taxonomy in drill.grader.

Design: docs/DESIGN-reject-reasons.md. Scope: drill/grader.py only.
"""

from __future__ import annotations

from drill.grader import DEFAULT_REJECT_REASON, REJECT_REASONS, grade

# Captured from the pre-change code (the single fixed L1 message):
#   reason = f"En España no se dice «{reject_word}» — prueba con «{alt}»."
#   detail = f"«{reject_word}» es de Latinoamérica; en España: «{alt}»"
# This is the byte-for-byte "region" template's required output, for the
# specific accept/reject pair used below (alt == accept[0]).
_ORIGINAL_REASON = "En España no se dice «carro» — prueba con «el coche es rojo»."
_ORIGINAL_DETAIL = "«carro» es de Latinoamérica; en España: «el coche es rojo»"


def test_default_reject_reason_is_unspecified() -> None:
    assert DEFAULT_REJECT_REASON == "unspecified"
    assert "unspecified" not in REJECT_REASONS


def test_region_message_is_byte_identical_to_pre_change_output() -> None:
    v = grade(
        "el carro es rojo",
        accept=["el coche es rojo", "coche"],
        reject=["carro"],
        reject_reason="region",
    )
    assert v.layer == "L1_banned"
    assert v.reason == _ORIGINAL_REASON
    assert v.detail == _ORIGINAL_DETAIL
    assert v.reject_reason == "region"


def test_region_no_op_is_opt_in_not_the_default() -> None:
    # Same card, no reject_reason kwarg passed at all — the pre-existing
    # call-site shape. Explicitly requesting "region" still reproduces the
    # old text byte-for-byte, but the *default* (no kwarg) is deliberately
    # NOT region — see test_unspecified_message_default.
    v_default = grade(
        "el carro es rojo", accept=["el coche es rojo", "coche"], reject=["carro"]
    )
    v_region = grade(
        "el carro es rojo",
        accept=["el coche es rojo", "coche"],
        reject=["carro"],
        reject_reason="region",
    )
    assert v_region.reason == _ORIGINAL_REASON
    assert v_region.detail == _ORIGINAL_DETAIL
    assert v_default.reject_reason == "unspecified"
    assert v_default.reason != v_region.reason


def test_register_message() -> None:
    v = grade(
        "tienen razón",
        accept=["tenéis razón"],
        reject=["tienen"],
        reject_reason="register",
    )
    assert v.layer == "L1_banned"
    assert v.reason == "«tienen» es correcto, pero aquí toca vosotros — prueba con «tenéis razón»."
    assert "«tienen»" in v.detail
    assert "«tenéis razón»" in v.detail
    assert v.reject_reason == "register"


def test_meaning_message() -> None:
    v = grade(
        "está embarazada",
        accept=["está avergonzada"],
        reject=["embarazada"],
        reject_reason="meaning",
    )
    assert v.layer == "L1_banned"
    assert (
        v.reason
        == "«embarazada» es español correcto, pero significa otra cosa — aquí: «está avergonzada»."
    )
    assert "«embarazada»" in v.detail
    assert "«está avergonzada»" in v.detail
    assert v.reject_reason == "meaning"


def test_form_message() -> None:
    v = grade(
        "quiero que me llamas",
        accept=["quiero que me llames"],
        reject=["quiero que me llamas"],
        reject_reason="form",
    )
    assert v.layer == "L1_banned"
    assert (
        v.reason
        == "«quiero que me llamas» no es correcto en español — la forma es «quiero que me llames»."
    )
    assert "«quiero que me llamas»" in v.detail
    assert "«quiero que me llames»" in v.detail
    assert v.reject_reason == "form"


def test_unspecified_message_default() -> None:
    v = grade("carro rojo", accept=["coche rojo"], reject=["carro"])
    assert v.layer == "L1_banned"
    assert v.reason == "Aquí no vale «carro» — la respuesta es «coche rojo»."
    assert "«carro»" in v.detail
    assert "«coche rojo»" in v.detail
    assert v.reject_reason == "unspecified"
    # Must NOT be the region template.
    assert v.reason != _ORIGINAL_REASON.replace("carro", "carro")
    assert "España" not in v.reason
    assert "Latinoamérica" not in v.detail


def test_unknown_category_falls_back_to_unspecified_without_raising() -> None:
    v = grade(
        "carro rojo",
        accept=["coche rojo"],
        reject=["carro"],
        reject_reason="banana",
    )
    assert v.layer == "L1_banned"
    assert v.reason == "Aquí no vale «carro» — la respuesta es «coche rojo»."
    assert v.reject_reason == "unspecified"


def test_every_template_names_the_alternative() -> None:
    # Mirrors the existing invariant test_rejects_name_the_alternative:
    # detail must be non-empty and must contain the accepted alternative.
    for category in (*REJECT_REASONS, DEFAULT_REJECT_REASON, "garbage"):
        v = grade(
            "carro rojo",
            accept=["coche rojo"],
            reject=["carro"],
            reject_reason=category,
        )
        assert v.detail
        assert "«coche rojo»" in v.detail
        # First «...» in detail is the rejected form, per cli.py's
        # _offending_reject regex coupling.
        first_quoted = v.detail.split("«", 1)[1].split("»", 1)[0]
        assert first_quoted == "carro"


def test_verdict_reject_reason_none_for_accepted_answers() -> None:
    v = grade("hola", accept=["hola"])
    assert v.accepted is True
    assert v.reject_reason is None


def test_verdict_reject_reason_none_for_non_l1_rejections() -> None:
    v = grade("xyz completely wrong", accept=["hola"])
    assert v.accepted is False
    assert v.layer != "L1_banned"
    assert v.reject_reason is None


def test_meaning_vs_region_produce_different_explanations_for_same_form() -> None:
    # Regression shape of the real bug: gr-001/gr-002-style contradiction.
    # The same rejected form graded under two different reasons must not
    # collapse to the same (false, in one case) explanation.
    kwargs = dict(attempt="embarazada", accept=["avergonzada"], reject=["embarazada"])
    v_meaning = grade(**kwargs, reject_reason="meaning")
    v_region = grade(**kwargs, reject_reason="region")
    assert v_meaning.reason != v_region.reason
    assert v_meaning.detail != v_region.detail
    assert "España" not in v_meaning.reason
    assert "otra cosa" in v_meaning.reason
