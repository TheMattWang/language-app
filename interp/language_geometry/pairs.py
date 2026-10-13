"""Spain vs Latin American Spanish minimal pairs.

Each pair is one sentence frame filled two ways that differ ONLY in the
variety marker, so a direction that separates them is about variety,
not content, length or translator style (the confound NTREX's spa vs
spa-MX has: they are independent translations).

Two kinds of marker:
  lexical    coche / carro          (vocabulary)
  address    queréis / quieren      (vosotros vs ustedes: grammar)

Note `quieren` is also Spain's *formal* plural, so the address pairs are
"vosotros vs not-vosotros" more than "Spain vs Latin America".
"""

LEXICAL = [  # (Spain, Latin America), same grammatical gender where possible
    ("el coche", "el carro"), ("el móvil", "el celular"), ("el ordenador", "la computadora"),
    ("el zumo", "el jugo"), ("la patata", "la papa"), ("el billete", "el boleto"),
    ("el piso", "el departamento"), ("la nevera", "el refrigerador"), ("el ascensor", "el elevador"),
    ("el camarero", "el mesero"), ("la piscina", "la alberca"), ("el melocotón", "el durazno"),
    ("la maleta", "la valija"), ("el aparcamiento", "el estacionamiento"), ("el jersey", "el suéter"),
    ("el bocadillo", "el sándwich"),
]
LEXICAL_FRAMES = [
    "Mi hermana me pregunta por {} todos los días.",
    "No encuentro {} por ninguna parte.",
    "Mañana tengo que hablar con mi padre sobre {}.",
    "Todo el mundo en la oficina habla de {}.",
]

ADDRESS = [  # (vosotros, ustedes)
    ("queréis", "quieren"), ("tenéis", "tienen"), ("sabéis", "saben"), ("hacéis", "hacen"),
    ("necesitáis", "necesitan"), ("preferís", "prefieren"), ("conocéis", "conocen"),
    ("entendéis", "entienden"), ("veis", "ven"), ("coméis", "comen"), ("buscáis", "buscan"),
    ("pedís", "piden"),
]
ADDRESS_FRAMES = [
    "Chicos, ¿de verdad {} eso?",
    "Me han dicho que {} lo mismo que yo.",
    "Ya sé que {} muchas cosas.",
    "No entiendo por qué {} eso ahora.",
]


def pairs() -> list[dict]:
    """Every pair as {kind, item, spain, latam}; `item` groups a pair's frames
    so train/test splits can hold out whole words."""
    out = []
    for kind, items, frames in (("lexical", LEXICAL, LEXICAL_FRAMES), ("address", ADDRESS, ADDRESS_FRAMES)):
        for es, la in items:
            for frame in frames:
                out.append({"kind": kind, "item": es, "spain": frame.format(es), "latam": frame.format(la)})
    return out
