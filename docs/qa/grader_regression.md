# QA: adversarial regression on the hardened grader (false-reject hunt)

Scope: `drill/grader.py` after commit `2449f68` ("Fix grader false accepts
found by QA, plus two P0s and a GUI dead end"), which added two gates:
`_DIACRITIC_HOMOGRAPHS` (L3/L4 `continue` on se/sé-style pairs) and
`_SUB_MIN_LEN = 4` (minimum char length before a single-token substitution is
forgiven). Method: fresh throwaway scripts (not `tests/test_grader*.py`)
loading all 455 cards from `data/*.jsonl` (`scenarios.jsonl` excluded, its
schema is per-turn not per-card). `~/.langapp/drill.db` was never opened.
Scripts live in the session scratchpad, not this repo.

## Headline numbers

- **Every card accepts its own accept forms verbatim: 0/634 failures.**
  Baseline is clean.
- **Accent-stripped accept forms: 4/220 false rejects (1.8%), all four
  intentional.** All four (`cz-035`, `cz-038`, `cz-040` → "está"/"esta";
  `cz-053` → "sé"/"se") are single-token cloze cards where the accent *is*
  the tested distinction — this is the new gate working as designed, not a
  regression. **The specific P0 scenario named in the brief — a long sentence
  containing a homograph word (e.g. "dónde está …") typed with all accents
  stripped — does NOT regress.** Verified directly and against every
  multi-token sentence in the decks that contains a homograph word (`el`,
  `tu`, `mi`, `si`, `se`, `de`, `te`, `que`, `como`, `cual`, `quien`, `donde`,
  `cuando`, `cuanto`, `esta`, `este` — 220+ sentences checked): all pass at
  `L3_accent`. Reason: `_is_diacritic_homograph` compares the *whole joined
  canonical string*, not per-token, so it only ever fires when the entire
  accept form is one token (true cloze-gap case) — exactly what the code
  comment claims. This gate is correctly scoped.
- **Single-char-typo substitution sweep (1,760 probes: one interior-letter
  swap per alphabetic token, across every accept form in every card):
  739/1,760 false rejects (42.0%) overall.** Split by the mutated token's
  length: **short tokens (<4 chars): 712/725 false rejects (98.2%)**; long
  tokens (≥4 chars): 27/1,035 (2.6%), and every one of those 27 traces to two
  *pre-existing, unrelated* bugs (below), not the two new gates.

**The false-reject rate this task asked me to hunt: ~42% of realistic
single-letter typos are now wrongly rejected, concentrated almost entirely
(98.2%) on words under 4 characters** — which in Spanish includes most
prepositions, articles, pronouns, and short high-frequency verbs (`de`, `en`,
`el`, `la`, `te`, `se`, `mi`, `tu`, `que`, `por`, `con`, `es`, `da`, `voy`,
`hoy`, `fui`, `sea`). This is the P0.

## P0 — `_SUB_MIN_LEN = 4` blocks real single-letter typos on short words,
not just short-word-vs-different-word confusions

The gate was added to stop `soy`→`estoy` and `sed`→`hambre` style false
*accepts* (different real words that happen to be edit-distance ≤2). But it
applies uniformly to the *same* short token whether the difference is a
genuine typo or a real word swap — it can't tell them apart, because it only
looks at length and edit distance, not vocabulary. The result: any accept
form containing a token under 4 characters now fails to tolerate a
single-letter typo on that token, including on function words that
`_OPTIONAL_TOKENS` explicitly says should "never decide a verdict" when
*dropped* — but a substitution isn't a drop, so that forgiveness doesn't
apply here.

Reproducing calls (exact, from `drill.grader.grade`):

```python
grade("hoi", accept=["hoy"], reject=[])
# -> accepted=False, layer='L5_reject'  (expected: True, L4_close)

grade("vou", accept=["voy"], reject=[])
# -> accepted=False, layer='L5_reject'  (expected: True, L4_close)

grade("sde", accept=["sed"], reject=[])
# -> accepted=False, layer='L5_reject'  (expected: True, L4_close)

grade("hoi ya he comido", accept=["hoy ya he comido"], reject=["hoy ya comí"])
# -> accepted=False, layer='L5_reject'  (expected: True, L4_close)
# card gr-067

grade("hoi hace mucho calor",
      accept=["hace mucho calor hoy", "hoy hace mucho calor"],
      reject=["está mucho calor hoy", "es mucho calor hoy"])
# -> accepted=False, layer='L5_reject'  (expected: True, L4_close)
# card gr-073

grade("madrid está em el centro de españa",
      accept=["Madrid está en el centro de España"], reject=[])
# -> accepted=False, layer='L5_reject'  (expected: True, L4_close)
# card gr-012 — a one-key slip on "en" fails the whole sentence

grade("uon", accept=["uno"], reject=[])          # card nl-002
grade("dks", accept=["dos"], reject=[])          # card nl-003
grade("mol", accept=["mil"], reject=[])          # card nl-035
# all -> accepted=False, layer='L5_reject'  (expected: True, L4_close)
```

Observed: `L5_reject`, generic "no coincide" message, in every case above.
Expected: `L4_close` accept — these are single-letter substitution typos on
words the learner otherwise produced correctly, exactly the class of mistake
L4 exists to forgive (per the module's own design stance: "a deterministic
grader that is too strict teaches the user the tool is broken").

Affected cards (non-exhaustive — any card whose accept form contains a token
<4 chars, which is most of them): `nl-002`, `nl-003`, `nl-035`, `gr-001`
through `gr-052` (nearly all, via `es`/`el`/`la`/`en`/`de`/`que`/`mi`/`tu`/
`te`/`se`/`no`/`un`/`ir`/`ya`/`lo` typos), `cz-034/037/039/042/052/057/058/
060/062/064/065/066/067/068/069/070/071/072/073/075`, `pc-*` and `tv-*`
sentence cards wherever a short function word is mistyped. Full list (712
rows) in the scratchpad sweep output; representative sample above.

**Fix direction to consider** (not applied — QA is read-only): gate on
whether the differing token pair is a *known different word* vs a token that
isn't a real word at all. A cheap proxy: only skip the substitution
forgiveness for short tokens when the mutated form is itself a real Spanish
word / present in some vocabulary list (as `hambre`≠`sed`, `soy`≠`estoy`
both are), not merely "edit-distance ≤2 and short." Absent a lexicon, even
lowering `_SUB_MIN_LEN` to 3, or requiring edit distance ≤1 (not ≤2) for
tokens 2–3 chars long, would recover most of these without reopening the
`sed`/`hambre` hole (edit_distance("sed","hambre") is nowhere near ≤1, and
edit_distance("soy","estoy") is 2, so a ≤1 threshold for short tokens closes
that specific hole too — worth double-checking against the original QA
doc's 33 false-accept cases before changing).

## P1 — two pre-existing false-reject bugs surfaced by the sweep (not caused
by the new gates, but real and worth a ticket)

These account for all 27 "long token" (≥4 char) failures in the typo sweep
above — none of them are `_SUB_MIN_LEN` or `_DIACRITIC_HOMOGRAPHS` related;
both predate commit `2449f68` (present in the original `cb6bd00` add).

1. **`_strip_trailing_politeness` eats a legitimate content word that
   happens to collide with the politeness vocabulary (`hola`, `perdona`,
   `gracias`, `oye`, `porfa`).** `hola` is both "hello" (forgiven filler) and
   a one-letter typo away from `hora` ("hour" / "time"), a real content word
   in several travel cards.

   ```python
   grade("he estado esperando media hola",
         accept=["he estado esperando media hora"], reject=[])
   # -> accepted=False, layer='L5_reject'
   # card tv-075. Canonicalization strips trailing "hola" as politeness,
   # leaving 4 tokens vs the accept form's 5 -> token-count mismatch -> reject.

   grade("para qué hola", accept=["para qué hora", "¿para qué hora?"], reject=[])
   # -> accepted=False, layer='L5_reject'   # card tv-092
   ```

   Similarly, `perdona` mistyped from `persona` (mid-word swap the other
   direction) hits `_strip_leading_politeness` and gets stripped instead of
   compared — cards `pc-112`, `tv-045`, `tv-077`, `tv-080`, `tv-084`.

2. **Pronoun canonicalization is asymmetric between attempt and accept.**
   `_strip_leading_pronoun` only strips a leading token that, after
   accent-folding, is an *exact* member of `_PRONOUNS_FOLDED`. The accept
   form's correctly-spelled `vosotros` gets stripped; a typo'd `vosoyros`
   does not (it isn't in the set), so the two canonicalized token lists end
   up different lengths and `_close_enough`'s off-by-one branch then requires
   the extra token to be in `_OPTIONAL_TOKENS` (pronouns aren't).

   ```python
   grade("vosoyros tenéis", accept=["vosotros tenéis"], reject=[])
   # -> accepted=False, layer='L5_reject'
   # cards pc-041 .. pc-058 (all 18 vosotros/vosotras conjugation cards)
   ```

Both are P1, not P0: they're narrower (politeness-word collision needs the
mistyped word to land near `hola`/`perdona`/etc; pronoun asymmetry only hits
the `vosotros` conjugation subset of `peninsular_contrast`), and both predate
this hardening pass, so they are not a regression from it — but they were
invisible until this sweep and directly hurt real cards.

## P2 — noise / false positives from the fuzzer, not grader bugs

- `grade("ahorro dinero para qee podamos viajar en diciembre", ...)` mutating
  `podamos`→`podemos` for card `gr-030` correctly triggers `L1_banned`
  because `podemos` (indicative) is literally in that card's `reject` list —
  the card tests subjunctive-vs-indicative on purpose. Correct behavior, not
  a bug; excluded from the P0 counts above.

## What's clean (verified, not just assumed)

- Diacritic-homograph gate: correctly scoped to single-token accept forms
  only, confirmed against all 220+ multi-token sentences in the decks that
  contain a homograph word — 0 regressions.
- Optional-token insertion/omission (articles, `un`/`una`, clitics) still
  forgiving: `grade("quiero café", accept=["quiero un café"])` → `L4_close`.
- ñ-vs-n strictness (`año`/`ano`) is unrelated to this hardening pass (present
  since the initial `cb6bd00` commit) and behaves as designed — e.g.
  `grade("donde esta el bano", accept=["¿Dónde está el baño?"])` rejects, but
  for the pre-existing ñ reason (`L5_reject`, "Cuidado con la ñ"), not the new
  diacritic-homograph gate. Swapping in a correctly-ñ'd form
  (`"Donde esta el baño"`) accepts fine at `L3_accent`.
- Ser/estar and other real-distinction cards still correctly reject when the
  distinguishing word is dropped or swapped (`grade("aburrido", accept=["es
  aburrido"], reject=["está aburrido"])` → rejected, as it should be).
