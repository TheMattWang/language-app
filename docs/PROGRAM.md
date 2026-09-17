# Spanish — 19-day program (2026-09-15 → 2026-10-03)

Departure ~Oct 3. Target: Peninsular Spanish, rusty intermediate, production-focused.

**The one number that matters:** tutor half-hours produce ~15–50× more Spanish out of your mouth than any app mechanic considered for this project. Everything below is arranged around protecting that.

## Daily (non-negotiable core)

| Slot | Minutes | What |
|---|---|---|
| `drill` | 15 | `python3 -m drill review` — EN→ES production, typed. Say it aloud as you type. |
| Tutor *(4×/wk)* | 30 | The volume driver. Spain-based tutor. |
| Voice roleplay *(off days)* | 20 | Claude/ChatGPT voice mode, same scenarios the tutor didn't reach |
| Passive media | 20 | During a chore. **Peninsular accents only** — RTVE, Spanish podcasts. |

Total ~55–65 min/day. If a day collapses, **the drill is the one that still happens.**

## Weekly shape

- **Mon/Tue/Thu/Fri** — tutor
- **Wed/Sat** — voice roleplay
- **Sun** — `python3 -m drill stats`, review the week's failures, no new material

## Tutor instructions (give these verbatim at the first session)

1. **"Háblame de tú, y usa vosotros cuando hables en plural."** A LatAm-trained ear defaults to *ustedes*; if the tutor doesn't force *vosotros*, you will never produce it.
2. **Roleplay, don't chat.** Named scenario each session: restaurant, pharmacy, hotel check-in, train tickets, a complaint.
3. **Correct register, not just grammar.** If *carro/celular/jugo* comes out, flag it — those mark you instantly.
4. **Don't let me escape into English.** Make me paraphrase around the gap instead of supplying the word.
5. Session 1 extra: **review the contrast deck** — `data/peninsular_contrast.jsonl`, 120 cards, ~10 min of their time. These are LLM-authored and need a native Spain speaker's eye. Ask specifically about pc-084..pc-093 (slang), which dates fastest.

## Scenario checklist — can you do these without English?

- [ ] Airport / transit
- [ ] Hotel check-in, problem with the booking
- [ ] Restaurant + tapas, dietary restriction
- [ ] Pharmacy, describe a symptom
- [ ] Buying train/metro tickets
- [ ] Asking directions *and understanding the answer*
- [ ] Shopping, sizes, returns
- [ ] **A complaint** — wrong order, wrong charge, lost booking

## Checkpoints

- **Sep 24** — Are the tutor sessions actually happening? If not, the program has failed for reasons no deck fixes. Escalate or change tutors **now**, not Oct 1.
- **Sep 30** — Review accuracy ≥85% on the contrast deck (`drill stats`).
- **Before departure** — *vosotros* produced spontaneously in an unscripted exchange. The clearest signal Peninsular register transferred.

## Taper: Sep 30 → Oct 3

Travel-scenario roleplay and high-frequency review only. **No new material after Oct 2.**

## The drill tool

Replaces Anki. Local, no account, no install beyond this repo.

```bash
python3 -m drill import data/peninsular_contrast.jsonl   # once, and after any edit
python3 -m drill review                                   # the daily 15 minutes
python3 -m drill review --deck peninsular_contrast --limit 30
python3 -m drill stats
```

Two things it does that a generic SRS will not:

- **LatAm vocabulary is a hard reject that names the Spain alternative.** Type `el carro` and it tells you `el coche`, every time.
- **vosotros is enforced** by listing the `ustedes` form in a card's reject list, so `tienen` cannot pass where `tenéis` is wanted. This is the forcing function that survived the cancelled app.

Scheduling is SM-2 with a **departure clamp**: no card is ever scheduled past 2026-10-03, because an interval landing after the flight is a card you never see. The clamp disengages once the trip starts.

### Desktop app

Double-click **`bin/Drill.command`** in Finder, or:

```bash
python3 -m drill gui
python3 -m drill gui --deck travel_production --limit 30
```

Native window, no install, no account. **Enter does everything** — type, Enter to answer, Enter for the next card; you never need the mouse. The **accent bar** (`á é í ó ú ñ ü ¿ ¡`) is one click or `Ctrl-1..9`, because the grader never folds ñ and a US keyboard makes that painful. Escape closes.

Feedback is colour-coded: green exact, amber accepted-with-a-wobble (accent slip or near miss), red wrong — and a red answer always shows the Spain form you wanted.

### Decks

| File | Cards | What |
|---|---|---|
| `data/peninsular_contrast.jsonl` | 120 | LatAm↔Spain lexicon, vosotros, false friends, colloquial |
| `data/travel_production.jsonl` | 100 | Full utterances by scenario: hotel, airport, restaurant, bar, pharmacy, tickets, directions, shopping, problems, emergency |
| `data/grammar_repair.jsonl` | 80 | ser/estar, preterite vs imperfect, subjunctive, por/para, clitics, gustar-type, common learner errors |

```bash
python3 -m drill import data/*.jsonl
```

### Finding your weak spots

```bash
python3 -m drill weak              # weakest tags + most-missed cards
python3 -m drill weak --days 7     # just this week
```

Run it before each tutor session and bring the two tags it names — that's what `docs/TUTOR.md` means by the Sep 24 checkpoint. It refuses to rank until it has ≥3 attempts per tag, so early output saying "not enough history" is correct, not broken.
