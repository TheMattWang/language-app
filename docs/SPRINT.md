# Sprint — one day, 2026-09-20

13 days to departure (2026-10-03). 25 commits, 314 tests green, 455 cards, 0 reviews.

## Sprint goal

**End today with the tutor booked, the first real drill session on the clock, and the one
defect that teaches false Spanish fixed — and nothing else in the codebase touched.**

## The judgement call, up front

**More engineering is the wrong use of today.** The numbers in this repo say so:

| Number | Where from | What it means |
|---|---|---|
| `review: 0` / 455 new | `drill stats` | The tool has never been used. Every defect found so far was found by an agent, not by a learner. |
| 15–50× | `docs/00-constraints.md`, `docs/PROGRAM.md` | Tutor half-hours out-produce any app mechanic by this factor. This was settled on day 0 and killed the previous product. |
| ~36 new cards/day | `PROGRAM.md` §load | One day spent not drilling ≈ 36 cards that are never introduced before the flight. |
| 6 sessions, 0 booked, S1 is tonight | `docs/TUTOR.md` | Two sessions were already lost to the earlier schedule. The Sep 24 checkpoint says a third miss means the program has failed *for reasons no deck fixes*. |
| 2 of 2 | `docs/qa/grader.md`, `docs/qa/grader_regression.md` | Both previous grader hardening passes introduced a new P0. Sweep 1's false-accept fix added `_SUB_MIN_LEN = 4`, which became the sweep-2 false-reject P0. Touching the grader is not free. |

So the bar for shipping code today is not "is this a real defect" — all six backlog items
are real. The bar is **"does this teach the learner something false, in a deck he will
actually see before Oct 3?"** Exactly one item clears it (#3 below). Everything else waits
until the tool has a human user, which is a state it has never been in.

The minimum correctness bar before the tool should simply be used as-is: **the grader must
not assert something false about Spanish.** It may be terse, undiscoverable, or awkward on
Ctrl-D. It may not say `está aburrido` is Latin American.

## Ordered backlog

### 1 · Book all six tutor sessions — P0, size S, no code

*Rationale:* the program's entire thesis is that this is the volume driver; S1 is tonight
and nothing is booked. Two sessions are already gone. A day of engineering that leaves
this undone is a day that made the program worse.

**Acceptance criteria**
- Six confirmed bookings with a named Spain-based tutor at the `TUTOR.md` dates: Sep 20,
  22, 24, 27, 29, Oct 2. Confirmations exist outside this repo (email/platform), not as an
  intention.
- `docs/TUTOR.md`'s "**Nothing is booked yet.**" paragraph is replaced with the tutor's
  name, platform, and the six confirmed times in ISO form.
- The four standing instructions from `TUTOR.md` have been sent to the tutor before S1.
- If fewer than six slots exist with one tutor, a second tutor covers the remainder, or the
  count is explicitly reduced in `TUTOR.md` with the dropped topics named.

### 2 · Run the first real `daily` session — P0, size S, no code

*Rationale:* 314 tests and two QA sweeps have not told us the one thing a single human
session will: whether the load is bearable and whether the cards are answerable by a
person rather than by `test_content.py`. This is also the decision point `PROGRAM.md`
demands ("Pick one tonight").

**Acceptance criteria**
- `python3 -m drill stats` reports `review:` ≥ 20 and `new:` < 455 against
  `~/.langapp/drill.db`.
- The load option is chosen and recorded: `PROGRAM.md` §"A note on the daily load" is
  edited from two options to the one selected, with the discarded option moved to a single
  "rejected because" line.
- Any card that was wrong-but-arguably-right during the session is written down (id +
  what was typed). That list is the input to any future grader work; today it is only
  collected, not acted on.

### 3 · Rejection explanations must be true — P1, size M, strings only

*Rationale:* `grade()` emits one hardcoded regionalism template for every L1 rejection.
Measured across the shipped decks: **193 cards carry a reject list; on 150 of them (78%)
the explanation is false.** That is wider than the brief's 77 `grammar_repair` cards — it
also hits **56 `peninsular_contrast` cards** (vosotros drills tell you `tienen` is "not
said in Spain"), 15 `travel_production` and 2 `numbers_listening`. Only the 43
`lexicon`-tagged contrast cards are genuinely regional. The contrast deck is the deck the
Sep 30 checkpoint measures and the deck the tutor audits tonight in S1, so these cards
*will* be seen. The mirror pairs (gr-001/gr-002) assert flatly contradictory facts.

Mitigating fact, already true: `card.note` is printed directly beneath the reason on both
surfaces (`cli.py:436`, `cli.py:608`, `app.py:357`) and those notes are correct. The
learner sees truth and falsehood stacked. That is why this is P1 and not P0 — but it is
also why the fix is cheap: the right explanation already exists on the card.

**Scope: the L1 branch of `grade()` (`grader.py:302-316`) and its call sites. No change to
matching, normalisation, `_OPTIONAL_TOKENS`, or any layer's accept/reject logic.**

**Acceptance criteria**
- `grade()` accepts new optional context (e.g. `regional: bool = False` or the card's
  note/tags) with a default that preserves today's strings; `cli.py`, `app.py` and
  `scenario.py` pass it from the `Card`.
- **Verdict invariance (the gate):** a sweep feeding every `accept` and every `reject`
  string of all 455 cards through `grade()` produces byte-identical `(accepted, layer,
  matched)` before and after. Only `reason`/`detail` may differ. If this does not hold,
  the change is reverted, not debugged.
- For the 43 `lexicon`-tagged `peninsular_contrast` cards, `reason` and `detail` are
  unchanged verbatim.
- For the other 150 reject-bearing cards, neither `reason` nor `detail` contains
  `no se dice`, `en España`, or `Latinoamérica`.
- gr-001 typed as `está aburrido` and gr-002 typed as `es aburrido` both reject, and
  neither output claims the form is not used in Spain.
- If the new `reason` would duplicate `card.note`, it is printed once, not twice.
- All 314 existing tests pass with **no expected `accepted`/`layer` value edited**; new
  tests cover one grammar card, one lexicon card, one vosotros card.
- **Timebox: 90 minutes.** At 90 minutes it is abandoned and reverted, not finished late.
  Items 1 and 2 are not negotiable against it.

### 4 · Decide the clitic policy — P2, size S, decision only

*Rationale:* articles and clitics are both in `_OPTIONAL_TOKENS`, so `la tiene` passes for
`lo tiene`. Article gender is noise; clitic gender is a real distinction. But only 8
`grammar_repair` cards are clitic-tagged, and removing clitics from the optional set makes
every long sentence in every deck hard-fail on a dropped `me`/`le` — the exact class of
false reject that `docs/qa/grader_regression.md` calls a P0.

**Decision: keep clitics optional. Do not change the grader.** 8 cards of extra strictness
is not worth a new false-reject surface across 455, with the grader's regression record.
Clitic gender is a *tutor* correction, not a grader one — it goes on the S2 Ask line.

**Acceptance criteria:** this paragraph exists (done), and `_OPTIONAL_TOKENS` is unchanged
at the end of the day.

## Explicitly out of scope

Cut, with the reason:

- **Discoverability of `scene`/`sprint`/`weak`/`export` (backlog #2).** There is one user
  and he wrote the docs. `README.md` and `PROGRAM.md` both document all four; `PROGRAM.md`
  already instructs running `weak` before each tutor session. This is a defect for a second
  user, and there is no second user before Oct 3.
- **Misleading `N/M correct` on EOF before the first card (backlog #3).** Cosmetic, on an
  abort path, visible only to someone who quits before answering anything. Zero learning
  impact.
- **Schema-migration path (backlog #4).** Latent by construction: it fires on the *next*
  schema change, and this sprint plan forbids schema changes. One user, one DB, 13 days,
  and `backup_db` exists. Revisit if the tool outlives the trip.
- **P2 residue in `docs/qa/*.md`** — id-rename orphans, duplicate-id last-wins, the
  `--deck nonexistent` message, `import` exit code, ANSI leaking past `--no-color`, the GUI
  entry-not-repacked bug (`app.py:272-299`). All real, none of them teaches false Spanish or
  blocks a session. The GUI bug is the closest call: it needs a finish-then-deck-switch,
  which the single-deck `daily` routine never does. Workaround if hit: restart the app.
- **Content P2s from `docs/qa/content.md`** — six duplicate prompts across
  `peninsular_contrast`/`travel_production`, `pc-071` missing the feminine form, `sc-005`
  turn 3. Duplicates cost ~6 of 455 slots; the audit's headline is that the corpus is
  clean. The tutor's S1 pass over the contrast deck is the higher-value content review and
  it is already booked as item 1.
- **Anything that adds a card, a deck, or a feature.** At ~36 new/day the collection
  already does not fit before the flight; `PROGRAM.md` says ~200 cards go unseen under the
  lighter option. Adding content makes the shortfall worse. The only new cards permitted
  are tutor corrections, per the `TUTOR.md` after-session ritual.

## Definition of done

1. Six tutor sessions booked and `docs/TUTOR.md` updated to say so.
2. `drill stats` shows `review:` ≥ 20 — a human has used the tool.
3. Either item 3 is merged with the verdict-invariance sweep passing and 314+ tests green,
   **or** it was abandoned at the timebox and reverted cleanly (`git status` clean).
4. The load option is chosen and `PROGRAM.md` reflects one option, not two.
5. No other file under `drill/` has changed.

## Risks

| Risk | Mitigation |
|---|---|
| The grader fix introduces a regression, as both previous grader passes did (2 for 2). | Strings-only diff in one branch; the verdict-invariance sweep over all 455 cards is a merge gate, not a nice-to-have; revert rather than debug. |
| Engineering eats the evening and item 2 never happens. | 90-minute timebox on item 3, started **after** items 1 and 2. Items 1 and 2 are done before any editor opens. |
| No tutor has a slot today. | Book the latest available slot tonight on an instant-booking platform; if nothing by 18:00, do 20 min of voice roleplay tonight, book S1 for Sep 21, and cut the program to five sessions with the dropped topic named in `TUTOR.md` — do not silently carry six. |
| The 36/day load proves unbearable at the first real session and the habit dies on day 2. | Pick `--new 20` and hold it; `PROGRAM.md` already warns against switching daily. A finished 20-card session beats an abandoned 36-card one. |
| The 115 LLM-authored contrast cards contain errors no test can catch, and drilling them installs bad Spanish. | Already mitigated in the S1 brief: ~10 min of native review of `peninsular_contrast`, `pc-084`–`pc-093` first. This is another reason item 1 outranks item 3. |
| Fixing the explanation surfaces a note/reason duplication that makes feedback noisier than it is today. | Covered by an acceptance criterion: collapse to one line when they coincide. |
| "One more small fix" creep after item 3. | The out-of-scope list above is the contract. Anything not on the backlog goes into a notes file for after Oct 3. |

## After this sprint

The tool is frozen until it has review history. The next engineering decision should be
made from `drill weak` output and the wrong-but-arguably-right list from item 2 — real
usage data — not from another QA sweep. Three agent sweeps have now found what agents can
find.
