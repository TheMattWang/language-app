# Spanish — 13-day program (2026-09-20 → 2026-10-03)

Departure 2026-10-03. Target: Peninsular Spanish, rusty intermediate, production-focused.

This replaces a 19-day plan that opened 2026-09-15. None of it ran: no drill session has
been done (`stats` reports 460 new, 0 reviewed) and no tutor session has been booked. The
plan below is what is left, not what was hoped for.

**The one number that matters:** tutor half-hours produce ~15–50× more Spanish out of your
mouth than any app mechanic considered for this project. Everything below is arranged
around protecting that.

## Daily (non-negotiable core)

| Slot | Minutes | What |
|---|---|---|
| `drill` | 30+ | `python3 -m drill daily` — EN→ES production, typed. Say it aloud as you type. See the load note below; 30 is the honest number at the derived rate, not 15. |
| Tutor *(3×/wk)* | 30 | The volume driver. Spain-based tutor. Six sessions total — `docs/TUTOR.md`. |
| Voice roleplay *(off days)* | 20 | Claude/ChatGPT voice mode, same scenarios the tutor didn't reach |
| Passive media | 20 | During a chore. **Peninsular accents only** — RTVE, Spanish podcasts. |

Total ~70–80 min/day. If a day collapses, **the drill is the one that still happens.**

## Weekly shape

- **Tutor** — Sep 20, 22, 24, 27, 29, Oct 2 (the six sessions in `docs/TUTOR.md`)
- **Voice roleplay** — every day without a tutor session
- **Sun Sep 27 is a tutor day this time.** There is no rest day in thirteen; the review
  backlog does not pause.
- Run `python3 -m drill stats` and `python3 -m drill weak` before each tutor session.

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

- **Sep 24** — Are the tutor sessions actually happening? Two have already been missed. If S1–S3 haven't happened by this date, the program has failed for reasons no deck fixes. Escalate or change tutors **now**, not Oct 1.
- **Sep 30** — Review accuracy ≥85% on the contrast deck: `python3 -m drill stats --deck peninsular_contrast`.
- **Before departure** — *vosotros* produced spontaneously in an unscripted exchange. The clearest signal Peninsular register transferred.

## Taper: Sep 30 → Oct 3

Travel-scenario roleplay and high-frequency review only. **No new material after Oct 2** —
which, at the rates below, means accepting that whatever is still unseen on Oct 2 stays
unseen.

## The drill tool

Replaces Anki. Local, no account, nothing to install.

```bash
python3 -m drill import data/*.jsonl    # once, and after any deck edit
python3 -m drill daily                  # the daily driver: due reviews, then new cards
python3 -m drill daily --new 20         # the reduced-load option; see below
python3 -m drill stats
```

`daily` is the command. `review` exists and shows everything currently due, uncapped, with
no pacing and no new cards — use it to clear a backlog, not as the routine.
`docs/RUNBOOK.md` is the operational page: first run, daily use, offline use, and what to
do when something breaks.

**What it does not do:** no speaking practice with feedback, no live conversation, no
listening comprehension beyond dictation of sentences already on file. It grades typed
production and enforces register. The tutor covers the rest.

Two things it does that a generic SRS will not:

- **LatAm vocabulary is a hard reject that names the Spain alternative.** Type `el carro` and it tells you `el coche`, every time.
- **vosotros is enforced** by listing the `ustedes` form in a card's reject list, so `tienen` cannot pass where `tenéis` is wanted. This is the forcing function that survived the cancelled app.

Scheduling is SM-2 with a **departure clamp**: no card is ever scheduled past 2026-10-03,
because an interval landing after the flight is a card you never see. The clamp disengages
once the trip starts.

### A note on the daily load

The new-card rate is **derived, not fixed**: `daily` divides the cards you haven't seen by
the days left before Oct 3, and clamps the result to 40/day.

Right now that arithmetic is ugly. 460 unseen cards over 13 days is **~36 new cards a day**,
against a session cap of 40 (`--max`). So:

- A session is **30+ minutes**, not 15.
- Only about 4 slots per session are left for reviews. Everything else due goes to the
  backlog, and the backlog starts on day two and does not clear. `daily` prints the
  backlog count and you can run it again to work through it — at another 40 cards a sitting.
- The rate being near the 40 clamp is the tool saying the collection no longer fits before
  the flight.

Two honest options:

1. **Drill the full set.** ~36 new/day plus whatever backlog you clear. Realistically an
   hour a day on the tool, on top of the tutor. That is the price of seeing all 460 cards.
2. **`python3 -m drill daily --new 20`.** ~20–25 minutes, reviews mostly keep up, and about
   260 of the 460 cards get introduced before the flight. Roughly 200 cards are never seen.

Which 200 you lose is worth knowing. New cards are dealt round-robin across decks in
usefulness order — travel first, then numbers and contrast, then cloze, then grammar — so
the order decides who wins the last few slots of each day's batch, but the shortfall lands
across **every** deck, not only the last one. Option 2 does not mean "grammar and cloze go
unseen and nothing else"; it means every deck is partly introduced, with grammar and cloze
thinnest. If you want a deck finished, name it: `python3 -m drill daily --deck travel_production`.

Either way, do not switch between them daily. Pick one tonight.

### Desktop app

Double-click **`bin/Drill.command`** in Finder, or:

```bash
python3 -m drill gui
python3 -m drill gui --deck travel_production --limit 30
```

Native window, nothing to install, no account. **Enter does everything** — type, Enter to
answer, Enter for the next card; you never need the mouse. The **accent bar**
(`á é í ó ú ñ ü ¿ ¡`) is one click or `Ctrl-1..9`, because the grader never folds ñ and a US
keyboard makes that painful. Escape closes.

Feedback is colour-coded: green exact, amber accepted-with-a-wobble (accent slip or near
miss), red wrong — and a red answer always shows the Spain form you wanted.

### Decks

460 cards in five decks, listed in the order new cards are introduced in.

| File | Cards | What |
|---|---|---|
| `data/travel_production.jsonl` | 100 | Full utterances by scenario: hotel, airport, restaurant, bar, pharmacy, tickets, directions, shopping, problems, emergency |
| `data/numbers_listening.jsonl` | 85 | Cardinals, prices, time, dates, platform/floor numbers, quantities |
| `data/peninsular_contrast.jsonl` | 120 | LatAm↔Spain lexicon, vosotros, false friends, colloquial |
| `data/cloze_grammar.jsonl` | 75 | Gap-fill: subjunctive triggers, preterite/imperfect in context, irregulars, por/para, collocations |
| `data/grammar_repair.jsonl` | 80 | ser/estar, preterite vs imperfect, subjunctive, por/para, clitics, gustar-type, common learner errors |

`data/scenarios.jsonl` holds eight multi-turn conversations. Different schema, not a card
deck, not part of the 460, and `import` skips it.

```bash
python3 -m drill import data/*.jsonl
```

### Finding your weak spots

```bash
python3 -m drill weak              # weakest tags + most-missed cards
python3 -m drill weak --days 7     # just this week
```

Run it before each tutor session and bring the two tags it names — that is what the S3
checkpoint in `docs/TUTOR.md` asks for. It refuses to rank until it has ≥3 attempts per
tag, so early output saying "not enough history" is correct, not broken. With zero
sessions done, that is what it will say tonight.

### Listening

```bash
python3 -m drill listen              # hear the Spanish, type what you heard
python3 -m drill listen --rate 150   # slower
```

Uses the macOS `Mónica` voice (Peninsular). The English prompt appears only *after* you
answer — seeing it first turns dictation back into translation. Type `r` alone to replay,
up to three times, without it counting as an attempt. In the desktop app, `Ctrl-r` or the
speaker button replays the current card.

This is dictation of sentences already in the deck, not listening comprehension. It does
not prepare you for speech you have never seen. Pair it with
`data/numbers_listening.jsonl`: understanding *"cuarenta y siete con cincuenta"* at a till
is harder than any grammar in the program, and it's the thing you'll face on day one.

### Conversation scenarios

```bash
python3 -m drill scene --list
python3 -m drill scene --id sc-001 --speak
```

Eight multi-turn exchanges — bar, restaurant booking gone wrong, hotel problem, pharmacy,
train connection, directions, a return, meeting someone. A wrong answer re-prompts the same
turn: first miss shows the goal, second shows a hint, then it reveals the answer and moves
on. At the end it prints the dialogue as it should have gone.

Scripted, not live: the other side says the same thing every time. It is the closest
surviving piece of the original forcing-function idea — you cannot advance until you
produce the Spanish — but it is not conversation. Like `sprint`, it writes nothing to your
review history.

### Sprint — building speed, not knowledge

```bash
python3 -m drill sprint            # 10 cards x 3 rounds, 8s -> 6s -> 4s
```

The 4/3/2 technique from `research/01-pedagogy.md` §5 #9: the same cards, repeatedly, under
a shrinking clock. Everything else here is untimed, so nothing trains the thing that
actually fails at a bar counter — answering *fast enough*.

It picks your slowest, least accurate seen cards, and **writes nothing**: no review rows,
no schedule changes. An 8-second timeout marking a card you know perfectly well as
forgotten would corrupt the scheduler, so a sprint is practice, never assessment. It needs
cards you have already seen, so it does nothing useful until a few `daily` sessions are in.
