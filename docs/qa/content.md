# Spanish Content Audit

Scope: `data/peninsular_contrast.jsonl` (120), `data/travel_production.jsonl` (100),
`data/grammar_repair.jsonl` (80), `data/numbers_listening.jsonl` (85),
`data/cloze_grammar.jsonl` (75), `data/scenarios.jsonl` (8 multi-turn). 460 cards + 8 scenarios, all audited.

**Method:** full manual read of every card in all 6 files, plus programmatic sweeps for
(a) cross-deck accept/reject contradictions — built the true LatAm-lexicon reject-term set from
`peninsular_contrast` cards tagged `lexicon` (68 terms) and searched every `accept` string in
every deck and scenario turn for a leaked hit; (b) a broad independent LatAm-vocabulary watchlist
(~40 more terms not present in any reject list) run the same way; (c) an accent sweep on the
esta/está, que/qué, si/sí, mas/más, el/él, tu/tú, se/sé, como/cómo, donde/dónde family across every
`accept`/`prompt_en` field; (d) duplicate/near-duplicate detection on `prompt_en` and first-accept
answers; (e) ID-uniqueness and UTF-8/mojibake checks.

**Headline finding: the corpus is unusually clean.** No LatAm-leakage contradictions were found in
either sweep, no missing/wrong accents were found, no wrong-gender or wrong-conjugation errors were
found in ~1,600 individual Spanish strings read by hand, and no duplicate IDs or encoding corruption
exist. The issues below are the real, specific ones found — mostly P1/P2 polish, no P0s.

## Findings

| Card id | Deck | Problem | Current | Suggested fix | Severity |
|---|---|---|---|---|---|
| sc-005 turn3 | scenarios | Ungrammatical fragment offered as a valid spoken answer — "vuelta el domingo" drops the required article/verb; a native wouldn't produce this bare | `"ida y vuelta, vuelta el domingo"` | `"ida y vuelta, la vuelta el domingo"` (or drop this alt and keep only `"ida y vuelta, vuelvo el domingo"`) | P1 |
| sc-005 turn1 | scenarios | Scenario realism: a Renfe ticket-counter clerk asking how you *arrived at the station* (car vs. metro) is a non-sequitur — no real agent asks this before selling a ticket; breaks NPC-realism criterion | NPC: `"¿Has venido en coche o en metro?"` | Cut this turn, or replace with a relevant question (e.g. "¿cuántos billetes?" / "¿alguna preferencia de horario?") | P2 |
| pc-100 / tv-042 | peninsular_contrast, travel_production | Exact duplicate prompt across decks ("Can I pay by card?") with overlapping accept sets | — | Not harmful, but flag for dedup/consolidation | P2 |
| pc-120 / tv-076 | peninsular_contrast, travel_production | Exact duplicate prompt ("Could you speak more slowly, please?") | — | Consolidate | P2 |
| pc-077 / tv-065 | peninsular_contrast, travel_production | Near-duplicate prompt ("I have a cold" / "I've got a cold"), identical answer | — | Consolidate | P2 |
| pc-099 / tv-040 | peninsular_contrast, travel_production | Duplicate prompt ("the bill, please") | — | Consolidate | P2 |
| pc-113 / tv-054 | peninsular_contrast, travel_production | Duplicate prompt ("I'm just looking, thanks") | — | Consolidate | P2 |
| pc-116 / tv-073 | peninsular_contrast, travel_production | Duplicate prompt ("This isn't what I ordered") | — | Consolidate | P2 |
| pc-071 | peninsular_contrast | Minor register gap: gendered alt `"estoy avergonzada"` is missing (masculine `"estoy avergonzado"` given, but not the feminine form other cards in the same deck reliably pair, e.g. tv-035/tv-037/tv-066/gr-009) — low risk only because the gender-neutral `"me da vergüenza"` is also accepted as the first alt | `accept: ["me da vergüenza","estoy avergonzado"]` | Add `"estoy avergonzada"` | P2 |
| pc-090 | peninsular_contrast | Note is incomplete relative to its own reject list: explains `plata` as LatAm slang for money but doesn't mention `la lana` (also correctly rejected, also LatAm/Mexican slang) | `note: "plata is LatAm slang for money"` | `note: "plata/lana are LatAm slang for money"` | P2 |

## Cross-deck contradiction check (the highest-value check per the brief)

Ran programmatically: built the true LatAm-vocabulary reject-term list from `peninsular_contrast`'s
`lexicon`-tagged cards (68 dialectal terms — carro, celular, papa, jugo, manejar, estacionar,
departamento, camión-as-bus, lentes, refrigerador, mesero, alberca, durazno, chompa, vereda, rentar,
etc.) and searched every `accept` string in all 460 cards + 8 scenarios for a leaked hit.
**Zero contradictions found** — no LatAm term rejected on one card is ever accepted on another,
anywhere in the corpus. A second independent pass with a broader hand-built LatAm watchlist
(platicar, ahorita, mande, órale, palta, polera, comedor, etc., not already in any reject list)
also came back clean.

An initial naive word-level pass (before restricting to true lexicon terms) threw ~25 false
positives — e.g. flagging `tienen`/`son`/`están`/`han`/`vamos` as "banned" because they're the
*rejected* answer on a specific vosotros-vs-ustedes or ser-vs-estar conjugation drill (pc-041–044,
pc-085). Those are not LatAm-lexicon leaks; they're correct, context-specific conjugation contrasts,
verified individually and excluded.

## Notable things that are correct despite looking suspicious on first pass
- pc-073/pc-074 (`actualmente` rejected on one card, accepted on the reverse-direction card) and
  pc-078/pc-079 (`biblioteca`/`librería`) are intentional, correctly bidirectional false-friend pairs
  — not contradictions.
- Register (tú/vosotros/usted) is internally consistent within every scenario and matches the
  situation (informal tú for solo travelers with strangers/staff, vosotros for groups addressed by
  staff) — checked turn-by-turn across all 8 scenarios.
- The por/para, ser/estar, preterite/imperfect, and subjunctive-trigger cards in `grammar_repair`
  and `cloze_grammar` (155 cards) were read individually; all conjugations, moods, and explanatory
  notes are correct.
- `numbers_listening` (85 cards: numbers, prices, clock times, dates, addresses) is fully correct,
  including the trickier 24-hour timetable reading and "X menos cuarto" hour-rollover cases.
