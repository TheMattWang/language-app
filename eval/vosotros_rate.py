"""How often does a model address a group with vosotros? (research/11 experiment 1)

research/11 showed regeneration can only *filter* replies, never create
vosotros: reaching 90% within 2 retries needs a per-sample rate >= ~0.54.
This measures that rate per model, at two temperatures, zero-shot and
with three in-variety examples (the cheapest no-training fix).

Each reply is classified by how it addresses the group:
  vos      vosotros forms only
  mixed    vosotros plus ustedes/tú forms (inconsistent address)
  ustedes  ustedes forms (wrong for Spain)
  tu       singular tú to a group (wrong)
  neutral  no second-person address at all (dodged)

    python3 eval/vosotros_rate.py MODEL [MODEL ...] [--samples 2] [--backend ollama]

Writes eval/results/vosotros_rate-<date>.json and prints a table.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from drill import llm, register  # noqa: E402
from drill.normalize import fold_accents  # noqa: E402

SCENES = {
    "bar": "Eres Mateo, camarero en un bar de tapas en Madrid.",
    "hotel": "Eres Lucía, recepcionista de un hotel en Sevilla.",
    "tienda": "Eres Marta, dependienta en una tienda de ropa en Barcelona.",
    "guia": "Eres Javier, guía turístico en Granada.",
    "farmacia": "Eres Carmen, farmacéutica en Valencia.",
}
RULES = (
    " Hablas solo en español de España. Los clientes son un grupo y los tratas siempre de "
    "vosotros (queréis, tenéis, os, vuestro). Respuestas cortas, de una o dos frases. "
    "Nunca hables inglés. Nunca rompas el personaje."
)

# Customer turns that are unambiguously plural and invite a second-person reply.
PROMPTS = {
    "bar": [
        "Somos dos. ¿Qué nos recomiendas para compartir?",
        "Hola, somos cuatro. ¿Tienes mesa?",
        "Mi amiga y yo queremos algo de beber. ¿Qué tenéis?",
        "Somos tres y tenemos mucha hambre. ¿Qué nos traes?",
        "¿Nos puedes traer la carta? Somos dos.",
        "Queremos pedir. ¿Qué es lo más típico de aquí?",
        "Ya hemos terminado. ¿Nos cobras?",
        "Somos vegetarianos los dos. ¿Qué podemos comer?",
    ],
    "hotel": [
        "Hola, tenemos una reserva para dos noches. Somos los Wang.",
        "Mi marido y yo queremos saber a qué hora es el desayuno.",
        "Somos tres. ¿Nos podéis guardar las maletas hasta la tarde?",
        "Acabamos de llegar. ¿Qué nos recomiendas visitar hoy?",
        "Nuestra habitación no tiene agua caliente.",
        "Nos vamos mañana temprano. ¿Cómo hacemos el check-out?",
        "¿Nos puedes pedir un taxi al aeropuerto? Somos dos.",
        "Somos una familia de cuatro. ¿Hay piscina?",
    ],
    "tienda": [
        "Hola, mi hermana y yo buscamos un regalo.",
        "Estamos mirando, gracias. ¿Hasta qué hora abrís?",
        "¿Tenéis esta camiseta en otra talla? Es para las dos.",
        "Queremos devolver esto. Lo compramos ayer.",
        "Somos turistas. ¿Nos hacéis el tax free?",
        "Nos gustan estas dos chaquetas. ¿Cuál nos recomiendas?",
        "¿Podemos pagar por separado?",
        "Mi novio y yo buscamos zapatos cómodos para caminar.",
    ],
    "guia": [
        "Somos cinco. ¿Cuánto dura la visita a la Alhambra?",
        "Hola, venimos al tour de las diez.",
        "Mis amigos y yo no tenemos entradas. ¿Qué hacemos?",
        "¿Dónde nos vemos al final de la visita?",
        "Somos estudiantes. ¿Hay descuento para nosotros?",
        "Llegamos tarde, perdona. ¿Nos hemos perdido mucho?",
        "¿Qué nos recomiendas ver después del tour?",
        "Somos dos y no hablamos muy bien español.",
    ],
    "farmacia": [
        "Hola, mi amigo y yo tenemos dolor de garganta.",
        "Nos han picado muchos mosquitos. ¿Qué nos das?",
        "Somos dos y necesitamos crema solar.",
        "Mi hijo y yo tenemos tos. ¿Qué nos recomiendas?",
        "Nos vamos de viaje. ¿Qué necesitamos llevar para el mareo?",
        "Venimos con receta, ¿la tenéis?",
        "¿Nos puedes explicar cómo tomar esto?",
        "Somos alérgicos los dos al polen.",
    ],
}

# Three in-variety exchanges, used as prior turns in the few-shot condition.
SHOTS = [
    ("Somos dos. ¿Qué tal está el gazpacho?", "Buenísimo, os va a encantar. ¿Queréis también algo para picar?"),
    ("Venimos a recoger unas entradas.", "Perfecto. ¿Me decís a qué nombre están?"),
    ("Mi amigo y yo estamos perdidos.", "Tranquilos, os lo explico. ¿Adónde vais?"),
]

_NUMBERS = {"seis", "dieciseis", "veintiseis"}
_VOS = {"vosotros", "vosotras", "os", "vuestro", "vuestra", "vuestros", "vuestras", "sois", "vais"}
_UST = {"ustedes", "les", "pueden", "quieren", "desean", "prefieren", "necesitan"}
_TU = {"te", "tu", "contigo", "tienes", "quieres", "puedes", "prefieres", "necesitas", "deseas"}


def classify(text: str) -> str:
    words = [fold_accents(w) for w in register.words(text)]
    vos = any(
        w in _VOS or (w.endswith(("ais", "eis")) and len(w) > 4 and w not in _NUMBERS)
        for w in words
    )
    ust = any(w in _UST for w in words)
    tu = any(w in _TU for w in words)
    if vos:
        return "mixed" if (ust or tu) else "vos"
    if ust:
        return "ustedes"
    if tu:
        return "tu"
    return "neutral"


def messages(scene: str, prompt: str, few_shot: bool) -> list[dict]:
    msgs = [{"role": "system", "content": SCENES[scene] + RULES}]
    if few_shot:
        for user, assistant in SHOTS:
            msgs += [{"role": "user", "content": user}, {"role": "assistant", "content": assistant}]
    msgs.append({"role": "user", "content": prompt})
    return msgs


def run_model(model: str, backend: str, samples: int) -> dict:
    out: dict = {}
    for temp in (0.7, 0.3):
        for few_shot in (False, True):
            key = f"T={temp} {'3-shot' if few_shot else '0-shot'}"
            rows = []
            for scene, prompts in PROMPTS.items():
                for prompt in prompts:
                    for _ in range(samples):
                        r = llm.chat(
                            messages(scene, prompt, few_shot),
                            backend=backend, model=model, temperature=temp, max_tokens=80,
                        )
                        rows.append({"scene": scene, "prompt": prompt, "reply": r.text,
                                     "class": classify(r.text), "seconds": r.seconds})
            out[key] = rows
    return out


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    counts = {c: sum(r["class"] == c for r in rows) for c in ("vos", "mixed", "ustedes", "tu", "neutral")}
    addressed = n - counts["neutral"]
    return {
        "n": n,
        **{c: counts[c] / n for c in counts},
        # The rate research/11's regeneration math needs: of replies that
        # address the group at all, how many do it consistently right.
        "vos_given_addressed": counts["vos"] / addressed if addressed else 0.0,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+")
    ap.add_argument("--backend", default="ollama")
    ap.add_argument("--samples", type=int, default=2)
    args = ap.parse_args()

    results = {}
    for model in args.models:
        try:
            results[model] = run_model(model, args.backend, args.samples)
        except llm.LLMUnavailable as exc:
            print(f"{model}: {exc}", file=sys.stderr)

    out_dir = ROOT / "eval" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"vosotros_rate-{date.today()}.json"
    path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"{'model':<28}{'condition':<16}{'n':>4}{'vos':>7}{'mixed':>7}{'ust':>7}{'tu':>7}{'neutral':>9}{'vos|addr':>10}")
    for model, conds in results.items():
        for cond, rows in conds.items():
            s = summarize(rows)
            print(f"{model:<28}{cond:<16}{s['n']:>4}{s['vos']:>7.0%}{s['mixed']:>7.0%}{s['ustedes']:>7.0%}"
                  f"{s['tu']:>7.0%}{s['neutral']:>9.0%}{s['vos_given_addressed']:>10.0%}")
    print(f"\nraw replies: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
