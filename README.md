# drill — Peninsular Spanish production practice

A local spaced-repetition tool for getting rusty Spanish back before a trip to Spain.
Python stdlib only. No account, no install step, no network.

```bash
python3 -m drill import data/*.jsonl
python3 -m drill daily          # the 15 minutes that matter
python3 -m drill gui            # or double-click bin/Drill.command
```

## What makes it different from a flashcard app

It grades **production**, and it enforces **register**. Type `el carro` and it stops you:

```
the car (Spain)
  > el carro
  ✗ En España no se dice «carro» — prueba con «el coche».
    «carro» es de Latinoamérica; en España: «el coche»
```

`vosotros` is enforced the same way — a card wanting `tenéis` lists `tienen` as a
rejected form, so the LatAm default cannot pass. A generic SRS has no notion of an
answer that is *wrong for where you are going*.

Grading is deterministic and layered: exact match, accent-tolerant match (accent slips
never block), then a narrow fuzzy layer for typos and inflections. It deliberately does
**not** use an LLM judge — for a tool that decides whether you were right, a confident
wrong answer is worse than no answer.

## Commands

| Command | What |
|---|---|
| `drill daily` | Paced session: all due reviews + up to 15 new cards |
| `drill review` | Everything currently due, uncapped |
| `drill gui` | Native desktop window (tkinter) |
| `drill weak` | Weakest tags and most-missed cards |
| `drill stats` | Card counts by state |
| `drill listen` | Dictation — hear the Spanish, type it |
| `drill scene` | Multi-turn conversation scenarios |
| `drill sprint` | Timed rounds, 8s → 6s → 4s |
| `drill add` | Capture a tutor correction |
| `drill export` | Offline markdown of what you keep missing |
| `drill import <files>` | Load or update decks; safe to re-run |

## Decks

| File | Cards | Covers |
|---|---|---|
| `data/peninsular_contrast.jsonl` | 120 | LatAm↔Spain lexicon, vosotros, false friends, colloquial |
| `data/travel_production.jsonl` | 100 | Full utterances: hotel, airport, restaurant, pharmacy, tickets, complaints |
| `data/grammar_repair.jsonl` | 80 | ser/estar, preterite vs imperfect, subjunctive, por/para, clitics, gustar |
| `data/numbers_listening.jsonl` | 85 | Cardinals, prices, time, dates, platforms, quantities |
| `data/cloze_grammar.jsonl` | 75 | Gap-fill: subjunctive triggers, irregulars, collocations |
| `data/scenarios.jsonl` | 8 | Multi-turn conversations (different schema) |

Cards are JSONL. Add your own — especially corrections from a tutor, which are the
highest-value cards you will ever write:

```json
{"id":"my-001","deck":"mine","kind":"production","prompt_en":"The bill, please.",
 "accept":["la cuenta por favor"],"reject":[],"note":null,"tags":["bar"]}
```

Then `python3 -m drill import data/mine.jsonl` and
`python3 -m pytest tests/test_content.py -q` to confirm the new cards are answerable.

## Layout

```
drill/          the tool (store, scheduler, grader, cli, tkinter app)
data/           card decks, JSONL
docs/           PROGRAM.md (the 19-day plan), TUTOR.md (session briefs), SURVIVAL.md
tests/          98+ tests, including content validation over every deck
research/       historical; the original research corpus
```

## Scheduling

SM-2, with one non-standard rule: **no card is ever scheduled past 2026-10-03**.
An interval landing after departure is a card you will never see, so intervals are
clamped to roughly half the remaining runway. The clamp disengages once the trip starts.

## History

This started as something else — a macOS app that would flip Chrome and Brave into
Spanish and refuse to restore English until you produced the right sentence. That was
planned in detail, reviewed by three adversarial agents, and then killed on its first
test: the per-app `AppleLanguages` override did not change Chrome's UI.

`docs/00-constraints.md` records what was tried, the precise finding (the Spanish
assets *are* on disk, at `Google Chrome Framework.framework/.../es.lproj/locale.pak`),
and the diagnostic ladder that was deliberately not run. The review also established
that the lock would have produced 15–50× less spoken Spanish than simply booking
tutor sessions — so the program is now tutor-led, and this tool does the retrieval
practice in between.
