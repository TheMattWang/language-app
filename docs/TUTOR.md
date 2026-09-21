# Tutor session briefs

Six 30-minute sessions, 2026-09-20 → 2026-10-02. One brief each. Send the tutor the
**Ask** line before the session; work the scenario live.

**Nothing is booked yet.** The original schedule opened 2026-09-17 and the first two
sessions passed unbooked, so this is the compressed version: six sessions in thirteen
days instead of eight in sixteen. There is no slack left in it. A session that slips is a
session lost, not a session moved — the topics below are already merged down to fit.

What the merge cost: pharmacy and health are now the back half of S4 rather than a session
of their own, and the unscripted conversation shares S6 with the taper. Those two are the
first things to expand back into if the tutor has an extra slot.

The tutor is the volume driver — roughly 15–50× more Spanish out of your mouth than the
drill produces. The drill's job is retrieval between sessions; the tutor's job is
production under real time pressure. Don't let a session become a grammar lecture:
**you should be talking at least 70% of the time.**

The drill does not cover any of this. It grades typed production and enforces Peninsular
register; it has no speaking feedback, no live conversation, and no listening beyond
dictation of sentences already on file. Everything not on that list is why these sessions
exist.

## Standing instructions — give these once, in session 1

> Háblame de tú, y usa **vosotros** cuando hables en plural.
> Quiero **roleplay**, no charla: dame una situación y hazme resolverla.
> Corrígeme el **registro**, no solo la gramática — si digo *carro*, *celular* o *jugo*, párame.
> **No me dejes escapar al inglés.** Si no sé una palabra, hazme explicarla en español.

That last one is the whole point. A comfortable tutor who supplies the word you're missing
is pleasant and teaches you nothing. Ask them to make you *talk around* the gap — that's
the skill you'll actually use in Spain.

---

## S1 · Sep 20 (tonight) — Placement + register audit

**Ask:** *"Evalúame. Habla conmigo 10 minutos y dime mi nivel y mis tres peores errores."*

- 10 min free conversation, no scaffolding — establishes the baseline
- Then: **review `data/peninsular_contrast.jsonl` together**, ~10 min. 115 cards, LLM-authored, never checked by a native. Ask specifically about `pc-084`–`pc-093` (slang), which dates fastest.
- Last 10 min: restaurant roleplay, cold

**You want to leave with:** a CEFR-ish level, three named errors, and a corrected card list.

## S2 · Sep 22 — Bar and restaurant

**Ask:** *"Soy un cliente. Tú eres el camarero. No me lo pongas fácil."*

- Ordering, `¿qué te pongo?`, tapas, the `carta` vs `menú` trap
- Dietary restriction mid-order (invent one)
- Ask for the bill, question a charge on it

**Target structures:** `quería` for polite requests, `me pone`, `lleva` for ingredients.

## S3 · Sep 24 — Getting around

**Ask:** *"Dame direcciones complicadas y hazme repetírtelas."*

- Buy tickets, ask about transbordo, miss a connection
- **Comprehension under pressure:** have them give directions fast, then you repeat back
- `todo recto` not `derecho`, `andando` not `caminando`

**This is the session where you'll want to quit.** Understanding fast directions is the
hardest thing on this list and the most useful.

**Mid-course checkpoint.** Run `python3 -m drill weak` before this session and bring the
two weakest tags. If S1 and S2 didn't happen, this is the point to change tutors — not
October.

## S4 · Sep 27 — Problems, complaints, pharmacy

Two halves; give the second Ask at the midpoint.

**Ask (first half):** *"Ponme problemas. Quiero quejarme sin ser grosero."*

- Wrong order, wrong charge, booking lost, room too noisy
- Politeness gradient: `perdona` → `oye` → `mira`
- `llevo media hora esperando`, `me han robado`, `hay un error`

**Ask (second half):** *"Estoy enfermo en Madrid. Ayúdame."*

- Describe symptoms, ask for a recommendation, `¿necesito receta?`
- `me duele`, `estoy constipado` (a cold, not constipated)
- Report a theft: `poner una denuncia`

## S5 · Sep 29 — Vosotros and social Spanish

**Ask:** *"Habla conmigo como si fuéramos amigos en un bar. Usa vosotros todo el rato."*

- Group conversation simulation — the tutor plays two people
- `vosotros` present, preterite, imperative, `os`, `vuestro`
- Slang check: `vale`, `venga`, `guay`, `majo`, `tío`, `qué rollo`

**This is the register session.** Vosotros produced spontaneously here is the single
clearest signal the Peninsular shift has landed.

## S6 · Oct 2 — Unscripted, then taper

Two halves; give the second Ask at the midpoint.

**Ask (first half):** *"Nada de roleplay. Solo hablemos. Cuéntame tu semana y hazme preguntas difíciles."*

- No scenario, no safety net — this is the closest thing to arriving
- Ask them to interrupt and change topic abruptly
- **Leave with:** their honest read on whether you'll cope

**Ask (second half):** *"Repasa conmigo solo lo que más voy a usar."*

- Fast drill of the 20 phrases you'll use daily
- No new material. No corrections beyond register.

---

## After every session

1. Note the three corrections that stung most.
2. Add them as cards — same JSONL format, then `python3 -m drill import data/<deck>.jsonl`.
3. `python3 -m pytest tests/test_content.py -q` to confirm the new cards are answerable.

A correction you don't turn into a card is a correction you'll make again in Spain.
