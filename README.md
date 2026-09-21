# drill — Peninsular Spanish production practice

A local spaced-repetition tool for getting rusty Spanish back before a trip to Spain.
Python stdlib only. No account, no network, nothing to install.

```bash
python3 -m drill import data/*.jsonl   # once — loads the decks into ~/.langapp/drill.db
python3 -m drill daily                 # every day after that; this is the whole routine
python3 -m drill gui                   # same session in a window, or double-click bin/Drill.command
```

`daily` is the daily driver — due reviews first, then new cards at a derived rate. Every
other command is optional. Operational detail, including what to do when something breaks,
is in [`docs/RUNBOOK.md`](docs/RUNBOOK.md); the 13-day plan around it is in
[`docs/PROGRAM.md`](docs/PROGRAM.md).

There is a `pyproject.toml`, so `pip install -e .` gives you a `drill` console script if you
want one. Nothing here requires it, and every command in every doc is written as
`python3 -m drill ...` so it works from a clean checkout.

## What it does not do

No speaking practice with feedback. No live conversation. No listening comprehension
beyond dictation of sentences already on file. It grades **typed** production and enforces
Peninsular register — that is the whole scope. Speaking, unfamiliar speech and real
conversation are the tutor's job; this is the retrieval practice in between.

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
| `python3 -m drill daily` | Paced session: all due reviews + new cards, rate derived from days left |
| `python3 -m drill review` | Everything currently due, uncapped |
| `python3 -m drill gui` | Native desktop window (tkinter) |
| `python3 -m drill weak` | Weakest tags and most-missed cards |
| `python3 -m drill stats` | Card counts by state, and accuracy |
| `python3 -m drill listen` | Dictation — hear the Spanish, type it |
| `python3 -m drill scene` | Multi-turn conversation scenarios |
| `python3 -m drill sprint` | Timed rounds, 8s → 6s → 4s |
| `python3 -m drill add` | Capture a tutor correction |
| `python3 -m drill export` | Offline markdown of what you keep missing |
| `python3 -m drill import <files>` | Load or update decks; safe to re-run |

## Decks

460 cards in five decks, plus eight conversation scenarios.

| File | Cards | Covers |
|---|---|---|
| `data/travel_production.jsonl` | 100 | Full utterances: hotel, airport, restaurant, pharmacy, tickets, complaints |
| `data/numbers_listening.jsonl` | 85 | Cardinals, prices, time, dates, platforms, quantities |
| `data/peninsular_contrast.jsonl` | 120 | LatAm↔Spain lexicon, vosotros, false friends, colloquial |
| `data/cloze_grammar.jsonl` | 75 | Gap-fill: subjunctive triggers, irregulars, collocations |
| `data/grammar_repair.jsonl` | 80 | ser/estar, preterite vs imperfect, subjunctive, por/para, clitics, gustar |

Listed in the order new cards are introduced in. `data/scenarios.jsonl` holds the eight
scenarios; it is a different schema, not a card deck, and `import` skips it.

## The daily load, honestly

460 cards, none seen, 13 days left. `daily` divides one by the other and lands on about
**36 new cards a day** against a 40-card session cap — so a session is 30+ minutes, not 15,
and reviews start backing up on day two. The two honest options and what each costs are in
[`docs/PROGRAM.md`](docs/PROGRAM.md#a-note-on-the-daily-load).

## Adding cards

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
docs/           PROGRAM.md (the plan), RUNBOOK.md (operations), TUTOR.md (session briefs),
                SURVIVAL.md, 00-constraints.md
tests/          212 tests, including content validation over every deck
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
