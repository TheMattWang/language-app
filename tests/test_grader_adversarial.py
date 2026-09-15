"""Independent adversarial budget for the grader.

`tests/test_grader.py` was written alongside the grader and measures a
false-reject rate against its own table. This file is the counterweight:
the cases were chosen against the implementation, and it budgets BOTH
directions, because the two errors have different costs.

  A false reject annoys the learner and they stop trusting the tool.
  A false accept silently teaches them wrong Spanish.

The second is worse, so the false-accept budget here is the tighter one.
"""

from __future__ import annotations

import pytest

from drill.grader import grade

# --- answers a competent Spanish speaker would call correct ----------------
# (attempt, accept forms)
SHOULD_ACCEPT: list[tuple[str, list[str]]] = [
    ("quiero un cafe con leche", ["quiero un café con leche"]),      # missing accent
    ("Quiero un café con leche.", ["quiero un café con leche"]),     # caps + period
    ("  quiero un café con leche  ", ["quiero un café con leche"]),  # whitespace
    ("por favor, quiero un café con leche", ["quiero un café con leche"]),
    ("quiero un café con leche por favor", ["quiero un café con leche"]),
    ("yo quiero un café con leche", ["quiero un café con leche"]),   # pro-drop restored
    ("quiero café con leche", ["quiero un café con leche"]),         # dropped article
    ("la cuenta por favor", ["la cuenta"]),
    ("¿dónde está el baño?", ["dónde está el baño"]),
    ("donde esta el bano", ["dónde está el baño"]),                  # no accents at all
    ("tengo una reserva", ["tengo una reserva", "tengo reserva"]),   # second accept form
    ("vosotros tenéis", ["tenéis", "vosotros tenéis"]),
    ("me gustaria pagar con tarjeta", ["me gustaría pagar con tarjeta"]),
    ("perdona, dónde está la estación", ["dónde está la estación"]),
    ("el ordenador", ["el ordenador"]),
    ("ordenador", ["el ordenador"]),                                  # bare noun
    ("quiero reservar una mesa", ["quiero reservar una mesa"]),
    ("quiero reservar la mesa", ["quiero reservar una mesa"]),        # article swap
    ("hola, una caña por favor", ["una caña"]),
    ("no funciona la ducha", ["no funciona la ducha"]),
    ("estoy cansado", ["estoy cansado"]),
    ("estoy cansada", ["estoy cansado"]),                             # gender inflection
    ("me duele la cabeza", ["me duele la cabeza"]),
    ("¿me pone una caña?", ["me pone una caña"]),
    ("gracias, hasta luego", ["hasta luego"]),
]

# --- answers that are wrong and must NOT be accepted -----------------------
# (attempt, accept forms, why it matters)
SHOULD_REJECT: list[tuple[str, list[str], str]] = [
    ("tengo sed", ["tengo hambre"], "opposite need"),
    ("quiero la cuenta", ["quiero la carta"], "the bill vs the menu"),
    ("soy aburrido", ["estoy aburrido"], "ser/estar flips the meaning"),
    ("soy cansado", ["estoy cansado"], "ser/estar again"),
    ("el coche", ["la casa"], "unrelated noun"),
    ("tengo veinte", ["tengo veinte años"], "dropped the content word"),
    ("quiero pagar", ["quiero pagar con tarjeta"], "dropped the method"),
    ("no funciona", ["no funciona la ducha"], "dropped the subject"),
    ("buenos dias", ["buenas noches"], "wrong time of day"),
    ("la derecha", ["la izquierda"], "opposite direction"),
    ("puedo fumar", ["puedo pagar"], "different verb entirely"),
    ("hablo espanol", ["hablo ingles"], "different language"),
]


def test_false_reject_budget() -> None:
    """At most 10% of genuinely-correct answers may be rejected."""
    wrong = [
        (att, acc, v.layer, v.reason)
        for att, acc in SHOULD_ACCEPT
        for v in [grade(att, accept=acc)]
        if not v.accepted
    ]
    rate = len(wrong) / len(SHOULD_ACCEPT)
    assert rate <= 0.10, (
        f"false-reject rate {rate:.0%} exceeds 10% budget; "
        f"wrongly rejected {len(wrong)}/{len(SHOULD_ACCEPT)}:\n"
        + "\n".join(f"  {a!r} vs {acc} -> {layer}: {reason}" for a, acc, layer, reason in wrong)
    )


def test_false_accept_budget() -> None:
    """No wrong answer may be accepted. This budget is zero, by design.

    A false accept in a learning tool is not a tolerable error rate -- it
    is the tool actively teaching the wrong thing.
    """
    wrong = [
        (att, acc, why, v.layer)
        for att, acc, why in SHOULD_REJECT
        for v in [grade(att, accept=acc)]
        if v.accepted
    ]
    assert not wrong, "wrongly ACCEPTED (these teach bad Spanish):\n" + "\n".join(
        f"  {a!r} accepted for {acc} via {layer} -- {why}" for a, acc, why, layer in wrong
    )


@pytest.mark.parametrize(
    "attempt,accept,reject",
    [
        ("quiero el carro", ["quiero el coche"], ["carro"]),
        ("el celular", ["el móvil"], ["celular"]),
        ("tomo el jugo", ["tomo el zumo"], ["jugo"]),
        ("la papa", ["la patata"], ["papa"]),
        ("manejo el coche", ["conduzco el coche"], ["manejo"]),
    ],
)
def test_latam_vocabulary_is_hard_rejected(attempt, accept, reject) -> None:
    """The one thing this grader exists to catch."""
    v = grade(attempt, accept=accept, reject=reject)
    assert not v.accepted
    assert v.layer == "L1_banned"
    assert v.detail and accept[0].split()[-1] in v.detail


def test_reject_matches_whole_tokens_only() -> None:
    """`carro` must not fire inside `carrocería`."""
    v = grade("la carrocería", accept=["la carrocería"], reject=["carro"])
    assert v.accepted, f"substring false-positive: {v.layer} {v.reason}"


def test_ene_never_folded() -> None:
    """año/ano must never be conflated, at any layer."""
    v = grade("tengo veinte anos", accept=["tengo veinte años"])
    assert not v.accepted or v.layer != "L4_close", (
        "ñ/n confusion was fuzzy-accepted; this is the one folding that is never safe"
    )
