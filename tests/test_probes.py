"""drill.probes, against a stub model -- no Ollama or MLX needed."""

from __future__ import annotations

import pytest

from drill import cli, llm, probes


def _stub(replies: dict[str, str]):
    def chat(messages, **_):
        return llm.Reply(text=replies[messages[-1]["content"]], seconds=0.1, backend="stub", model="stub")
    return chat


GOOD_ES = {
    p.user: {
        "vosotros": "Os recomiendo unas bravas y croquetas para compartir. ¿Qué queréis beber?",
        "l2_errors": "¿Queréis la tortilla? Marchando, que tenéis hambre.",
        "breakdown": "Tranquilo, despacio. ¿Quieres comer o beber algo?",
        "latam_trap": "Ahora te traigo la cuenta. El taxi lo coges en la esquina.",
        "recovery": "La cuenta, claro. Ahora mismo te la traigo.",
    }[p.name]
    for p in probes.PROBES
    if p.variety == "es-ES"
}


def test_clean_replies_pass_every_probe() -> None:
    results = probes.run(variety="es-ES", samples=2, chat=_stub(GOOD_ES))
    assert [r.probe.name for r in results] == ["vosotros", "l2_errors", "breakdown", "latam_trap", "recovery"]
    assert all(r.pass_rate == 1.0 for r in results), [r.failures for r in results]


@pytest.mark.parametrize(
    "name, reply, expect",
    [
        ("vosotros", "¿Qué te parece las croquetas?", "without vosotros"),  # gemma2:2b, research/06
        ("latam_trap", "Puedes agarrar un taxi en la esquina.", "echoed"),
        ("latam_trap", "En la puerta hay unos carros disponibles.", "echoed"),  # gemma2:2b, live
        ("breakdown", "Sure! What do you want to say?", "english"),
    ],
)
def test_known_failures_fail(name, reply, expect) -> None:
    probe = next(p for p in probes.PROBES if p.name == name and p.variety == "es-ES")
    assert any(expect in why for why in probes.evaluate(probe, reply))


def test_latam_group_probe_rejects_vosotros() -> None:
    probe = next(p for p in probes.PROBES if p.name == "group")
    assert probes.evaluate(probe, "Les recomiendo los tacos al pastor.") == []
    assert probes.evaluate(probe, "Os recomiendo los tacos al pastor.")


def test_probe_command_reports_unreachable_model(tmp_path, monkeypatch, capsys) -> None:
    def down(*_, **__):
        raise llm.LLMUnavailable("Can't reach Ollama.")
    monkeypatch.setattr(llm, "chat", down)
    code = cli.main(["--db", str(tmp_path / "d.db"), "probe", "--samples", "1"])
    assert code == 3
    assert "Can't reach Ollama" in capsys.readouterr().err
