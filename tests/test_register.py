"""drill.register: the scan every model reply passes before a learner sees it.

The failing examples are the real replies recorded in
research/06-bench-local-baseline.md.
"""

from __future__ import annotations

import pytest

from drill.register import check, dialect_markers


def kinds(text: str, variety: str = "es-ES") -> set[str]:
    return {i.kind for i in check(text, variety)}


@pytest.mark.parametrize(
    "reply",
    [
        "¡Marchando! Una caña y unas bravas. ¿Algo más?",
        "Claro, ahora mismo os lo saco. ¿Queréis algo de beber?",
        "El camión de reparto llega a las seis.",  # camión = lorry in Spain
        "Son tres euros con cincuenta, por favor.",
        "Vale, ¿para tomar aquí o para llevar?",
    ],
)
def test_clean_peninsular_replies_pass(reply: str) -> None:
    assert check(reply, "es-ES") == []


def test_english_word_leak_is_caught() -> None:
    # llama3.2:3b in research/06
    assert kinds("¿Quieres que te dé directions?") == {"english"}


def test_parenthetical_translation_is_caught() -> None:
    # gemma2:2b in research/06
    found = kinds("¿Me puede decir en qué ayuda?\n\n(Can you tell me what you need help with?)")
    assert "translation" in found


def test_persona_break_into_english_is_caught() -> None:
    # qwen2.5:1.5b in research/06 offered to work in English
    assert "english" in kinds("Claro, puedo ayudarte. What would you like to say in English?")


def test_latam_lexicon_flagged_for_spain() -> None:
    issues = check("Puedes dejar el carro en el estacionamiento.", "es-ES")
    assert [i.kind for i in issues] == ["dialect"]
    assert "carro" in issues[0].detail and "estacionamiento" in issues[0].detail


def test_latam_lexicon_fine_for_latam() -> None:
    assert check("Puedes dejar el carro en el estacionamiento.", "es-419") == []


def test_vosotros_flagged_for_latam() -> None:
    issues = check("¿Qué queréis tomar? Os traigo la carta.", "es-419")
    assert [i.kind for i in issues] == ["dialect"]
    assert "quereis" in issues[0].detail and "os" in issues[0].detail


def test_numbers_and_pais_are_not_vosotros() -> None:
    assert check("Somos seis, venimos de otro país.", "es-419") == []


@pytest.mark.parametrize("reply", ["", "   ", "<think>the user wants</think>Hola", "Okay, so the user"])
def test_empty_and_thinking(reply: str) -> None:
    assert kinds(reply) & {"empty", "thinking"}


def test_markers_exclude_words_ordinary_in_spain() -> None:
    markers = dialect_markers("es-ES")
    assert {"carro", "celular", "computadora", "jugo"} <= markers
    assert not {"camion", "papa", "plata", "timbre"} & markers


def test_plurals_of_markers_are_caught() -> None:
    assert kinds("En la puerta hay unos carros disponibles.") == {"dialect"}
    assert kinds("Tenemos jugos naturales.") == {"dialect"}
