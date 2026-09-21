# DESIGN: why a rejected form is wrong

Status: proposal. Design only — no code changed by this document.

`grade()` emits one L1 message for every rejected form:

```
En España no se dice «X» — prueba con «Y».
```

That sentence is true for a LatAm/Spain lexical swap and false everywhere
else. `gr-001` rejects `está aburrido` with it; `gr-002` rejects `es aburrido`
with the mirror sentence. Both are ordinary Spanish. The *verdict* is right
in both cases — only the explanation lies.

Two more lies are worse than the reported one, and neither is in
`grammar_repair`:

- `pc-043` rejects `están` while `cz-043` **teaches** `están` as its answer.
  Thirty `vosotros` cards do this: `tienen`, `son`, `están`, `hablaron`,
  `su casa` are all correct Peninsular Spanish (they are *ustedes*), and the
  deck tells the learner Spain does not say them.
- `pc-071` rejects `embarazada` as if Spain did not use the word. Spain uses
  it constantly; it means *pregnant*. Twelve `false_friend` cards do this.

So the fix is not a grammar-deck patch. It is a per-card reason, and the
deck that most needs it is the one the current message was written for.

---

## 0. What should NOT be built

Read this first; three of these are the obvious designs.

1. **No new `card` column.** `docs/qa/store_durability.md` P1-4: `connect()`
   runs `CREATE TABLE IF NOT EXISTS`, which is a silent no-op against an
   existing table. The next column added to `card` crashes every existing
   install on first read with `IndexError: No item with that key`, and there
   is no migration runner. Writing one is a durability project, in the file
   (`store.py`) with the most review-history risk in the repo. Not for this.
2. **No per-reject-form mapping.** 43 of 193 reject-bearing cards carry more
   than one form. Exactly **one** (`pc-062`: `siéntense` = register,
   `sentados` = malformed) mixes categories, and it is better fixed by
   splitting the card. A per-form schema costs a breaking JSONL format
   change, new `import_jsonl` validation, a `_content_hash` change, a new
   `--reject` CLI syntax and every test fixture — to serve one card.
3. **No heuristic inference inside the grader.** Mapping `ser_estar →
   meaning` in code gets ~155/193 right and is silently wrong on ~38,
   including every card that is mis-decked (`gr-067`, `gr-077`, `gr-078` are
   regionalisms sitting in `grammar_repair`). A wrong category is exactly
   the bug being fixed; it must be authored and testable, not guessed.
4. **No `region` default.** Justified in §3.
5. **No fifth "idiom/collocation" category.** The only candidates
   (`pc-036` rejecting *una cerveza de barril pequeña*, `pc-091` rejecting
   *es un robo caro*) are not errors at all. They are verdict bugs (§4.5),
   not a missing taxonomy slot.
6. **No LLM at grade time, no English in the messages.** The grader is
   deterministic and stdlib-only; the learner-facing voice is Spanish.

---

## 1. Where the category lives

### The constraint that decides it

`grade()` is called from `cli.py` and `app.py` with `card.accept` and
`card.reject` — fields that came **out of SQLite**, not off disk. So the
category must survive the JSONL → DB → `Card` round trip. Of the existing
`card` columns only two are free-form and already round-trip: `tags_json`
and `note`. `note` is learner-facing prose rendered next to `verdict.detail`
(`app.py:357`), so it is not a machine field.

That leaves `tags`. It is a JSON array, it is already in `_content_hash`
(`store.py:_content_hash`, which includes `tags` *specifically* so tag edits
propagate on re-import), and it needs no schema change.

### Options compared

| | Where | Card edits | Schema / migration | `_content_hash` | Missing-field behaviour |
|---|---|---|---|---|---|
| **A** | derive from `deck` | 0 | none | none | n/a |
| **B** | new top-level field + `card.reject_reason` column | 193 | **ALTER TABLE — no migration path (P1-4)** | must add field | column absent → crash |
| **C** | per-reject-form mapping (`reject` becomes objects) | 193 + format break | none | must add field | old files still load |
| **D** | reserved `why:<cat>` entry in existing `tags` | 193 | **none** | **already covered** | no tag → `unspecified` |
| **E** | infer from existing tags in the grader | 0 | none | none | n/a |

**A is dead on arrival.** `grammar_repair` alone splits 44 *meaning* / 30
*form* / 3 *region*; `peninsular_contrast` splits 51 *region* / 29 *register*
/ 14 *meaning*. Deck-derivation is wrong for 117 of 193 cards (61%).

**B is the textbook answer and is blocked by P1-4.** It also buys nothing D
does not: nothing queries the category in SQL, so a dedicated column earns
no index and no join.

**C** solves a problem that occurs once (§0.2).

**E** is untestable-by-construction (§0.3).

### Chosen: D — a reserved `why:` tag

```json
{"id": "gr-001", ..., "tags": ["ser_estar", "adjectives", "why:meaning"]}
```

- **455 existing cards:** 262 have no `reject` list and need **no edit at
  all** — they can never reach L1. Only **193** are touched, and ~155 of
  those (80%) are assignable by a mechanical deck/tag rule (§4).
- **DB schema:** unchanged. No migration, no P1-4 exposure.
- **`_content_hash`:** unchanged — `tags` is already hashed. The 193 edited
  cards come back from the next `drill import` as `updated`; `sched` and
  `review` rows are untouched by the `UPDATE` path, so no scheduling or
  history is lost.
- **A card file lacking the field:** `reject_reason_from_tags([])` returns
  `"unspecified"`. Old decks, hand-added cards from `drill add`, and
  third-party JSONL all keep working with an honest generic message.
- **Forward compatibility:** `import_jsonl` ignores unknown top-level keys,
  and an old build reading a new deck simply carries an extra tag string it
  does not interpret. Both directions are non-breaking.

### The cost of D, stated plainly

`tags` is a display and analytics field, so a `why:` tag leaks into three
places and each needs a one-line filter:

| Site | Symptom | Fix |
|---|---|---|
| `app.py:287` | `#why:meaning` chip rendered on the card **before** the learner answers — a hint leak | filter `why:` from the chip list |
| `app.py:~447` (progress tags) | noise | same filter |
| `store.tag_performance` → `export._weak_tags` → `cli.py:1179` "Weakest tags" | `why:form` competes with real tags for the top-5 weakness list | filter in `tag_performance`, so every consumer inherits it |

Filtering in `tag_performance` covers the stats path in one place; the two
GUI sites read `card.tags` directly and need their own filter. Put the
predicate in `grader.py` next to the prefix constant and import it.

A cleaner variant — author `"reject_reason": "meaning"` as a top-level JSONL
key and have `import_jsonl` fold it into `tags_json` — was considered and
rejected: it makes the on-disk field and the stored field differ, which is
surprising in the one function whose correctness is "what you wrote is what
you get".

---

## 2. The taxonomy

Four categories plus the default. The assignment rule is a single decision
tree, which is what keeps it from being mis-assigned:

```
Is the rejected form well-formed Spanish at all?
├── no  ................................................. form
└── yes — so why is it wrong *here*?
    ├── it belongs to another variety of Spanish ........ region
    ├── it is the ustedes/formal person, not vosotros ... register
    └── it denotes something else ...................... meaning
```

| Category | When | `reason` (shown large) | `detail` (shown below, yellow) |
|---|---|---|---|
| `region` | Correct Spanish, but Latin American. `carro`, `jugo`, `celular`, `hoy comí` | `En España no se dice «X» — prueba con «Y».` | `«X» es de Latinoamérica; en España: «Y»` |
| `register` | Correct Peninsular Spanish, but the *ustedes* person where the card drills *vosotros*. `tienen`, `están`, `su casa`, `siéntense` | `«X» es correcto, pero aquí toca vosotros — prueba con «Y».` | `«X» es la forma de ustedes; en España, con amigos, se usa vosotros: «Y»` |
| `meaning` | Correct Spanish everywhere, but it says something else. `es aburrido` for *bored*, `embarazada` for *embarrassed*, `lo hice para ti`, `fui a Madrid cada verano` | `«X» es español correcto, pero significa otra cosa — aquí: «Y».` | `«X» existe, pero no dice lo que pide esta tarjeta; la respuesta es «Y»` |
| `form` | Not well-formed Spanish. `quiero que me llamas`, `quiero te lo dar`, `me gustan la paella`, `estoy hambre` | `«X» no es correcto en español — la forma es «Y».` | `«X» no es una forma válida aquí; lo correcto es «Y»` |
| `unspecified` *(default)* | The card does not say | `Aquí no vale «X» — la respuesta es «Y».` | `«X» no es la forma que pide esta tarjeta; la correcta es «Y»` |

`X` is the matched reject form (`r.strip()`, as today), `Y` is `accept[0]`.

### Two hard constraints on any template

1. **`detail` must be non-empty and must contain `«Y»`.**
   `tests/test_content.py::test_rejects_name_the_alternative` requires
   non-empty `detail`; `test_grader.py` and `test_grader_adversarial.py`
   assert the alternative word is *inside* `detail`.
2. **The first `«…»` in `detail` must be the rejected form `X`.**
   `cli.py:_offending_reject` parses `re.search(r"«([^»]+)»", verdict.detail)`
   to tell a `drill add` author which reject entry made their card
   unanswerable. Every template above satisfies this. It is a load-bearing
   coupling and belongs in a test (§5.6), not in a comment.

`region`'s strings are **byte-identical to today's**, so the whole existing
suite is unaffected by the template work.

### Why four and not three, or twelve

`register` is not a nicety — it is 29 cards and the source of the
`pc-043`/`cz-043` contradiction, and folding it into `region` would keep
telling the learner that Spain does not say `están`. The categories
rejected for being too thin are listed in §0.5. Every surviving category
has ≥29 members, which is the practical test for "will this be
mis-assigned".

---

## 3. The API change

```python
# drill/grader.py

REJECT_TAG_PREFIX = "why:"
REJECT_REASONS: tuple[str, ...] = ("region", "register", "meaning", "form")
DEFAULT_REJECT_REASON = "unspecified"


def reject_reason_from_tags(tags: Sequence[str]) -> str:
    """The card's `why:` tag, or DEFAULT_REJECT_REASON.

    Unknown or malformed values degrade to the default rather than raising:
    a typo in a deck must never abort a review mid-session. `tests/
    test_content.py` is where a bad value is caught, not here.
    """


def is_reason_tag(tag: str) -> bool:
    """True for a `why:` tag — display and analytics sites filter on this."""


@dataclass(frozen=True)
class Verdict:
    accepted: bool
    layer: str
    reason: str
    matched: str | None
    detail: str | None
    reject_reason: str | None = None   # NEW, set only on L1_banned


def grade(
    attempt: str,
    *,
    accept: Sequence[str],
    reject: Sequence[str] = (),
    reject_reason: str = DEFAULT_REJECT_REASON,   # NEW
) -> Verdict:
```

**Backward compatibility.** `reject_reason` is keyword-only with a default,
so all 40-odd existing `grade(...)` calls in `cli.py`, `app.py`,
`scenario.py` and the tests compile and pass unchanged. `Verdict` gains a
sixth field **with a default, at the end**, so positional construction and
`dataclasses.replace` keep working; nothing in the repo constructs a
`Verdict` outside `grader.py` today. The field is deliberately **not**
persisted — `review.layer` already records *that* a rejection happened, and
adding a `review` column would walk straight into P1-4.

Call sites become, mechanically:

```python
verdict = grade_attempt(
    attempt, accept=card.accept, reject=card.reject,
    reject_reason=reject_reason_from_tags(card.tags),
)
```

- `cli.py:367` (`_grade_and_reschedule`, serves both the review loop and the
  listening drill), `cli.py:880` (sprint), `app.py:331`.
- `cli.py:1014` (`cmd_add` self-rejection check) passes
  `reject_reason_from_tags(tags)` — the tags the author just typed.
- `scenario.py:119` has no tags on a `Turn`; leave it at the default. A
  scenario turn's reject list is a self-consistency check, never shown to a
  learner.

### The default, and why `unspecified` is honest rather than convenient

`region` would be the convenient default: it is what ships today, it would
let the 69 regional cards go untagged, and it would keep every existing
string identical. It is also precisely the bug. Defaulting to `region`
means the *next* untagged grammar card — added by `drill add` from a tutor
session, per `docs/TUTOR.md` — reproduces the gr-001 lie on day one, and the
blast radius grows with the deck.

`unspecified` says only what the card's data actually supports: this form is
on the reject list, and here is the accepted answer. It asserts no
linguistic claim, so it cannot be false. It is mildly less useful than a
correct category and strictly more honest than a wrong one — which is the
trade a learning tool should always take, and the same trade
`drill/grader.py`'s own header comment already makes ("a deterministic
grader that is too strict teaches the user the tool is broken").

The cost of the honest default — that untagged cards get a blander message —
is bounded to zero at rollout, because step 1 tags all 193 cards *before*
the grader can read them (§6).

---

## 4. Assigning the 455 existing cards

**262 cards need no edit** (`cloze_grammar` 75/75, `numbers_listening`
83/85, `travel_production` 85/100, `grammar_repair` 3/80,
`peninsular_contrast` 16/115): they have no `reject` list, so `L1_banned` is
unreachable. A card with no reject list must **not** get a `why:` tag —
§5.2 makes that a test, so the tag never becomes ambient noise.

### Counts (cards / reject forms)

| Category | Cards | Forms | Where |
|---|---:|---:|---|
| `region` | 69 | 101 | pc 51, tv 13, gr 3, nl 2 |
| `meaning` | 60 | 64 | gr 44, pc 14, tv 2 |
| `form` | 30 | 35 | gr 30 |
| `register` | 29 | 31 | pc 29 |
| *needs a verdict fix first* | 5 | 8 | pc 5 |
| **total** | **193** | **239** | |

### Mechanical rules (~155 cards, 80%)

Apply in order; first match wins.

| # | Rule | → | Cards |
|---|---|---|---|
| 1 | `deck == numbers_listening` | `region` | 2 |
| 2 | `deck == travel_production` and `id not in {tv-027, tv-056}` | `region` | 13 |
| 3 | `deck == peninsular_contrast` and `"vosotros" in tags` | `register` | 29 |
| 4 | `deck == peninsular_contrast` and `"false_friend" in tags` | `meaning` | 11 |
| 5 | `deck == peninsular_contrast`, otherwise (minus §4.5 list) | `region` | 51 |
| 6 | `deck == grammar_repair` and tags ∩ {`ser_estar`, `pret_imperf`, `por_para`} | `meaning` | 34 |
| 7 | `deck == grammar_repair` and tags ∩ {`clitics`, `gustar_type`} | `form` | 16 |

Rules 3–5 are why `peninsular_contrast` must be split by tag rather than by
deck: 43 of its 99 reject cards are *not* regionalisms.

### Judgement calls (~38 cards)

- **`grammar_repair` / `subjunctive`, 14 cards.** Split by whether the
  rejected mood is licensed at all:
  - `form` (8): `gr-025, 026, 027, 030, 033, 034, 037, 038` — a trigger
    (`quiero que`, `ojalá`, `es posible que`, `para que`) demands the
    subjunctive; the indicative is not Spanish there.
  - `meaning` (6): the three mirror pairs `gr-028/029` (future event vs
    habit), `gr-031/032` (`no creo` vs `creo`), `gr-035/036` (unknown vs
    known antecedent) — both members exist and mean different things.
- **`grammar_repair` / `haber_tener`, 5 cards.** `gr-065, 066, 068, 069` →
  `meaning` (`tiene tres cafés` is grammatical; it just says *he has three
  cafés*). `gr-067` → **`region`**: `hoy ya comí` is the LatAm preference,
  Spain's present perfect — a regionalism mis-decked into
  `grammar_repair`.
- **`grammar_repair` / `common_errors`, 11 cards.** `gr-070, 071, 072, 073,
  074, 076, 079, 080` → `form` (`estoy hambre`, `busco a mis llaves`,
  `solo ir` are not Spanish). `gr-077, 078` → **`region`**: *tener + años +
  gerundio* is the LatAm construction where Spain uses *llevar*. Again
  mis-decked, not mis-graded.
- **`peninsular_contrast` exceptions, 3 cards.** `pc-033` (`el sanitario`),
  `pc-105` (`la factura de compra`), `pc-114` (`tamaño` for clothing) →
  `meaning`: all three words are used in Spain and mean something else.
- **`travel_production` exceptions, 2 cards.** `tv-027` (`el menú` = the set
  lunch, not the menu) and `tv-056` (`tamaño`) → `meaning`.

An LLM pass can propose all 38; each must be reviewed against the decision
tree in §2 before it lands. The `why:` value is one token per line — a
reviewer can diff 193 lines faster than they can re-read the taxonomy.

### 4.5 Cards where the *verdict* is wrong, not the explanation

These cannot be categorised, because no honest category fits a form that is
not an error. Fix the data; do not tag them.

| Card | Rejects | Problem | Suggested fix |
|---|---|---|---|
| `pc-085` | `vamos` | `vamos` is universal Spanish — and is the **accepted answer of `cz-054`**. The deck contradicts itself. | drop `vamos`, keep `ándale` → `region` |
| `pc-084` | `está bien` | Completely normal in Spain; only `okey` is the borrowing. | drop `está bien`, keep `okey` → `region` |
| `pc-036` | `una cerveza de barril pequeña` | A correct circumlocution, not an error. The card teaches an idiom (`una caña`); rejecting the paraphrase punishes a right answer. | drop the reject list; keep the `note` |
| `pc-091` | `es un robo caro` | Same shape — unidiomatic, not wrong. | drop the reject list |
| `pc-062` | `siéntense`, `sentados` | The only genuinely mixed card: `siéntense` is `register`, `sentados` is `form`. | split into two cards, or drop `sentados` and tag `register` |

Two more to review, lower confidence:

- **`gr-019`** accepts `intenté llamarte` and rejects `quería llamarte`.
  *Quería llamarte pero no contestaste* is ordinary Spanish; the intended
  contrast is `quise`/`quería`, and the card as written may reject a correct
  answer. Verdict, not explanation.
- **`pc-043` and the other 28 `vosotros` cards.** The verdict is defensible
  (the card drills the vosotros conjugation) but only under `register`. If
  the project decides `están` should be *accepted* with a nudge rather than
  rejected, that is a scheduler/UX change and a separate design.

---

## 5. Test plan

### `tests/test_content.py`

1. **`test_reason_tag_is_valid`** — every `why:` tag in `data/*.jsonl` has a
   value in `REJECT_REASONS`. Catches typos (`why:meaing`) that would
   silently degrade to `unspecified`.
2. **`test_reason_tag_iff_reject_list`** — a card has exactly one `why:` tag
   iff it has a non-empty `reject`. Catches both drift directions: an
   untagged reject card (falls back to the bland default) and a stray tag on
   a card that can never reach L1. After §6 step 1 this pins the count at
   193.
3. **`test_mirror_pairs_are_not_region_or_form`** — *the test that would
   have caught gr-001/gr-002.* Accent-fold and normalise every `accept`
   form across **all** decks into one index; for every `reject` form that
   hits that index, assert the rejecting card's reason is `meaning` or
   `register`. A form another card teaches as correct cannot be
   ungrammatical (`form`) and cannot be absent from Spain (`region`).
   Against today's data this fires on 9 pairs: `gr-001/002`, `gr-003/004`,
   `gr-007/008`, `pc-043`↔`cz-043`, `pc-073`↔`pc-074` (legitimately
   `meaning`, passes), and `pc-085`↔`cz-054` (forces the §4.5 fix).
4. **`test_every_reject_form_is_caught`** *(exists)* — extend to assert
   `v.reject_reason == reason_from_tags(card)`, so the plumbing from tag to
   verdict is covered on all 239 real forms, not just fixtures.
5. **`test_rejects_name_the_alternative`** *(exists)* — extend: `detail`
   must contain `accept[0]`, not merely be non-empty. Cheap, and it locks
   every future template.
6. **`test_detail_names_the_rejected_form_first`** — for every reject form,
   the first `«…»` in `detail` equals the matched form. Protects
   `cli.py:_offending_reject`'s regex, which is otherwise an invisible
   coupling.

### `tests/test_grader.py`

7. **`test_each_reason_produces_its_own_message`** — parametrised over the
   four categories on one synthetic card: four distinct `reason` strings,
   all naming `«Y»`.
8. **`test_default_reason_makes_no_regional_claim`** — `grade(...)` with no
   `reject_reason` must produce a message containing neither `"España"` nor
   `"Latinoamérica"`. This is the regression guard for "someone made
   `region` the default again because the diff was smaller".
9. **`test_unknown_reason_degrades_to_default`** — `reject_reason="banana"`
   returns the `unspecified` message and does not raise.
10. **`test_region_message_is_unchanged`** — byte-exact assertion on the
    `region` `reason` and `detail`. Makes any future edit to the one
    template with 69 cards behind it deliberate.
11. **Existing L1 tests stay untouched and must stay green** —
    `test_l1_banned_carro_rejected_with_peninsular_alternative`,
    `test_latam_vocabulary_is_hard_rejected` (5 cases),
    `test_latam_answer_blocks_unlock_end_to_end`. They assert only
    `layer == "L1_banned"` and that the alternative appears in `detail`,
    which every template satisfies. If any of them goes red, a template
    broke constraint §2.1.

### `tests/test_app_views.py` / stats

12. **`test_reason_tags_are_not_displayed`** — `why:` never appears in the
    GUI chip list or in `tag_performance` output. Guards the §1 cost.

---

## 6. Rollout order

Four steps. The suite is green after each, and steps 1 and 2 touch disjoint
files so they can run in parallel.

**Step 1 — data + display filter (files: `data/*.jsonl`, `drill/app.py`,
`drill/store.py::tag_performance`, `tests/test_content.py`).**
Add the `why:` tag to all 193 reject-bearing cards (§4), apply the §4.5
verdict fixes, and filter `why:` from the three display/analytics sites.
Land tests 1, 2, 3, 12. **Inert by construction:** the current grader never
reads `tags`, so no message changes and every existing test still passes.
This is also the step that makes the gr-001 contradiction *visible* in CI
before anything can regress.

**Step 2 — grader (file: `drill/grader.py`, `tests/test_grader.py`).**
Add `REJECT_REASONS`, `DEFAULT_REJECT_REASON`, the five templates,
`reject_reason_from_tags`, `is_reason_tag`, the `Verdict` field and the
`grade()` kwarg. **No call site changes.** Every caller keeps the default,
so behaviour changes for exactly nobody, and the existing suite passes
because `unspecified`'s `detail` still names the alternative. Land tests 7,
8, 9, 10.

**Step 3 — call sites (files: `drill/cli.py`, `drill/app.py`).**
Thread `reject_reason=reject_reason_from_tags(card.tags)` through the four
call sites in §3. This is the step where the learner's message actually
changes. Land tests 4, 5, 6 — which now exercise the full path on all 239
real reject forms.

**Step 4 — re-import and docs.**
`drill import` reports 193 cards `updated` (tags are hashed; `sched` and
`review` untouched). Update `docs/qa/grader.md`'s "the only hard rejection
this grader cares about is LatAm vocabulary" claim, and the module docstring
at `drill/grader.py:1-7` that states the same thing — it is now wrong in
four ways.

If steps 1 and 2 land out of order, nothing breaks: step 2 alone leaves
every card on `unspecified` (honest but bland), and step 1 alone changes
nothing at all. Only step 3 depends on both.
