"""The model-selection gate: adversarial probes against a local model.

Grown from eval/quality_probe.py (research/06-bench-local-baseline.md),
whose probes separated models that look the same on paper. Each probe is
one learner turn designed to trigger a known failure -- the wrong
variety, a break into English, a parenthetical subtitle -- and a reply
passes when `drill.register.check` finds nothing wrong, plus any
probe-specific check.

Replies are sampled (temperature > 0), so each probe runs several times
and the gate reports pass *rates*. Which rate is good enough to ship is
decided by measurement (research/11-ship-time-fine-tuning.md), not
asserted here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from drill import llm, register
from drill.normalize import fold_accents

__all__ = ["PROBES", "SYSTEM_PROMPTS", "Probe", "ProbeResult", "run"]

SYSTEM_PROMPTS = {
    "es-ES": (
        "Eres Mateo, camarero en un bar de tapas en Madrid. Hablas solo en español de España. "
        "A un grupo de clientes los tratas de vosotros. Respuestas cortas, de una o dos frases. "
        "Nunca hables inglés ni traduzcas al inglés. Nunca rompas el personaje. No corrijas al "
        "cliente explícitamente: reformula con naturalidad lo que ha querido decir."
    ),
    "es-419": (
        "Eres Mateo, mesero en una taquería en la Ciudad de México. Hablas solo en español de "
        "México. A un grupo de clientes los tratas de ustedes. Respuestas cortas, de una o dos "
        "frases. Nunca hables inglés ni traduzcas al inglés. Nunca rompas el personaje. No "
        "corrijas al cliente explícitamente: reformula con naturalidad lo que quiso decir."
    ),
}

_VOSOTROS_VERB_ENDINGS = ("ais", "eis")


def _uses_vosotros(text: str) -> bool:
    words = [fold_accents(w) for w in register.words(text)]
    return any(
        w in {"vosotros", "vosotras", "os", "vuestro", "vuestra", "vuestros", "vuestras", "sois", "vais"}
        or (w.endswith(_VOSOTROS_VERB_ENDINGS) and len(w) > 4 and w not in {"dieciseis", "veintiseis"})
        for w in words
    )


def _no_echo(*words: str) -> Callable[[str], str | None]:
    """Fail if the reply repeats any of the learner's wrong-variety words."""
    def check(text: str) -> str | None:
        said = {fold_accents(x) for x in register.words(text)}
        found = [w for w in words if any(register.matches(x, {w}) for x in said)]
        return f"echoed the learner's {', '.join(found)}" if found else None
    return check


def _requires_vosotros(text: str) -> str | None:
    return None if _uses_vosotros(text) else "addressed a group without vosotros"


@dataclass(frozen=True)
class Probe:
    name: str
    user: str
    variety: str
    # Extra check beyond drill.register; returns why it failed, or None.
    extra: Callable[[str], str | None] | None = None


PROBES: tuple[Probe, ...] = (
    Probe("vosotros", "Somos dos. ¿Qué nos recomiendas para compartir?", "es-ES", _requires_vosotros),
    Probe("l2_errors", "Yo quiero... eh... el, la, la tortilla? Y yo soy... no... yo tengo hambre mucho.", "es-ES"),
    Probe("breakdown", "Sorry, I don't know how to say this in Spanish. Can you help me?", "es-ES"),
    Probe("latam_trap", "¿Me traes la cuenta? ¿Y dónde puedo agarrar un carro para ir al hotel?", "es-ES",
          _no_echo("agarrar", "carro")),
    Probe("recovery", "eh... ¿cómo se dice... the bill? la... la cuenta, ¿sí?", "es-ES"),
    Probe("group", "Somos cuatro. ¿Qué nos recomiendas?", "es-419"),
    Probe("breakdown", "Sorry, I don't know how to say this in Spanish. Can you help me?", "es-419"),
    Probe("spain_trap", "¿Tenéis zumo de naranja? ¿Y dónde puedo coger un taxi?", "es-419",
          _no_echo("teneis", "zumo")),
    Probe("recovery", "eh... ¿cómo se dice... the bill? la... la cuenta, ¿sí?", "es-419"),
)


@dataclass
class ProbeResult:
    probe: Probe
    replies: list[str] = field(default_factory=list)
    failures: list[list[str]] = field(default_factory=list)  # per reply; [] = passed
    seconds: list[float] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return sum(not f for f in self.failures) / len(self.failures) if self.failures else 0.0


def evaluate(probe: Probe, text: str) -> list[str]:
    """Why `text` fails `probe`; [] when it passes."""
    reasons = [f"{i.kind}: {i.detail}" for i in register.check(text, probe.variety)]
    if probe.extra is not None:
        why = probe.extra(text)
        if why:
            reasons.append(why)
    return reasons


def run(
    *,
    variety: str = "es-ES",
    samples: int = 5,
    backend: str = llm.DEFAULT_BACKEND,
    model: str | None = None,
    chat: Callable[..., llm.Reply] | None = None,
) -> list[ProbeResult]:
    """Sample every probe for `variety` `samples` times. Raises LLMUnavailable."""
    chat = chat or llm.chat
    results = []
    for probe in (p for p in PROBES if p.variety == variety):
        result = ProbeResult(probe)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPTS[variety]},
            {"role": "user", "content": probe.user},
        ]
        for _ in range(samples):
            reply = chat(messages, backend=backend, model=model, max_tokens=80)
            result.replies.append(reply.text)
            result.seconds.append(reply.seconds)
            result.failures.append(evaluate(probe, reply.text))
        results.append(result)
    return results
