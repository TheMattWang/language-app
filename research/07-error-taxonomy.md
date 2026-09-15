# 07 — Shared error taxonomy

**Owner:** main session (synthesis). Written 2026-09-12 after Track 05's agent died and this
cross-track question was reassigned. Inputs: `03-speech-stack.md` §2/§3, `04-rl-adaptation.md` §8,
`06-bench-local-baseline.md`, `../docs/00-constraints.md`.

Cross-track question #4 verbatim: *pronunciation scoring (03), grammar grading by the SLM (02), and
recall outcomes (04) are three different signals feeding one learner model. They need a shared error
taxonomy.*

This document is the taxonomy plus the record schema that carries it. It is a **v0 specification, not
a survey** — it is meant to be implemented as-written and then corrected against real recordings.

---

## 1. Why the three signals must share one vocabulary

They don't share a detector, a latency class, or a reliability level — and that is exactly why they
need a shared *name space*. Concretely:

- FSRS (04) schedules an **item**. It needs to know *which* item a failure belongs to. If the
  pronunciation scorer says "bad /r/ in `perro`" and the grammar grader says "gender error in
  `la problema`" and neither resolves to an `item_id`, neither can ever move a review interval.
- 04 §8.2 already reserves a single field — `error_type : taxonomy tag | null` — for all of this.
  There is one field, so there must be one vocabulary.
- 04 §8.4's retention linkage requires `item_id` to be **stable across content-schema versions**
  ("keep a mapping table rather than renumbering, or every retention curve breaks"). The same
  constraint applies to tags, for the same reason: a renamed tag is a broken longitudinal series.

The taxonomy is therefore an **append-only, versioned, closed vocabulary**. Not free text.

---

## 2. The one non-obvious design decision: two actors, one taxonomy

06 measured that all three viable local models **break Peninsular register** (failed the `vosotros`
probe despite explicit instruction plus a "Somos dos" cue) and **all of them offered an English exit
within five turns** — fatal, because the app's entire premise is that English is not an available
exit. 06 calls register and character-break enforcement the project's replacement top risk.

So the tutor makes errors from the same families the learner does: wrong register, LatAm lexis in a
Peninsular scenario, code-switching to English. Rather than build a second ad-hoc "guardrail
violation" vocabulary, every observation carries an **`actor`** field:

| `actor` | Consumer | Effect of an observation |
|---|---|---|
| `learner` | learner model / FSRS / difficulty controller | updates the in-context profile, may schedule a review |
| `tutor` | output guard | **regenerate the turn before it is ever spoken**; log the violation rate as a model-selection metric |

This is genuinely load-bearing, not tidiness: `eval/quality_probe.py`'s flags (ENGLISH-LEAK,
no-vosotros, EMPTY, THINKING-LEAK) become `actor=tutor` observations under the same tags the
learner's register errors use, which means **the model-selection gate and the runtime guard share
one implementation**. Build the detector once.

---

## 3. Design rules

1. **Closed vocabulary, append-only.** Tags are added, never renamed or renumbered. A retired tag is
   marked deprecated in the registry with a `superseded_by` pointer; the mapping table is the same
   mechanism 04 §8.4 demands for `item_id`.
2. **Observation ≠ attribution.** A detector emits an *observation* (evidence, timestamped, scored).
   The learner model *accumulates* observations into a belief about an item. Nothing writes directly
   to the profile. This keeps 04's warning tractable — a rotting profile is debuggable when you can
   replay the observations that produced it.
3. **Every observation names its detector, version, score and threshold.** Without `threshold`, a
   recalibration silently invalidates every past observation and you can't tell which.
4. **Reliability is a field, not a footnote** (§6). Only tier A and calibrated tier B are ever
   asserted to the learner. Tier C is logged and may steer difficulty silently — it never becomes
   "you said this wrong."
5. **No silent unknown bucket.** Anything a detector can't classify becomes `<channel>.unclassified`
   and is *counted*. A rising unclassified rate is the signal that the taxonomy needs extension;
   a swallowing `other` bucket hides that forever.
6. **Communication success is a first-class channel, ranked above grammaticality.** The thesis is
   forced production, not correctness. An exchange that completed with three gender errors beats a
   grammatically perfect exchange the learner abandoned.

---

## 4. Channels

Six. The channel is the first dotted segment of every tag.

| Channel | What it covers | Primary detector | Tier |
|---|---|---|---|
| `phon` | segmental pronunciation | phoneme-CTC + GOP (03 §3), per-word Whisper confidence (03 §2) | B/C |
| `flu` | prosody, pausing, speech rate, filled pauses | VAD + forced-alignment timestamps (03 §3.3) | B |
| `gram` | morphosyntax | SLM grader, constrained (§7.2) | C |
| `lex` | word choice, false friends, dialect lexis | lexicon rule-match | A |
| `prag` | register, address form, code-switching, character break | rule-match + closed-list | A |
| `task` | did the exchange actually complete | scenario engine exit conditions | A |
| `recall` | delayed retrieval outcome | FSRS review (04 §8.4) | A |

`task` and `recall` are outcome channels — they attach to a turn or an item without a span.

---

## 5. The v0 tag registry

Deliberately small. Every tag below is one a v0 detector can actually emit; nothing aspirational.

### 5.1 `phon.*` — from 03 §3.2's English-L1 error table

Scorable in v0 (03: "the categorical, acoustically-clean contrasts first"):

```
phon.rhotic.trill_as_approximant      # rr / word-initial r- produced as English [ɹ]
phon.rhotic.trill_as_tap              # rr produced as a single tap [ɾ]
phon.rhotic.tap_as_approximant        # intervocalic r produced as [ɹ]
phon.sibilant.theta_as_s              # distinción failure: c/z produced [s]  (Peninsular-only, locked by 00-constraints)
phon.sibilant.s_as_theta              # overcorrection: [θ] where [s] is correct
phon.labial.b_as_v                    # imported English /v/ on v-spelled words
phon.unclassified
```

Deferred to v2 (03: needs formant tracking or duration modelling; "lower-salience accent markers
rather than comprehension-breaking errors"). Tags are **reserved now** so the namespace doesn't
shift later:

```
phon.vowel.schwa_reduction
phon.plosive.intervocalic_d_not_spirantized
phon.diphthong.hiatus_break
```

### 5.2 `flu.*` — free once ASR + alignment exist (03 §3.3)

```
flu.pause.long_midclause          # silence >250ms inside a clause
flu.pause.excessive_count         # per-utterance rate above baseline
flu.filled_pause                  # eh/em/este
flu.rate.below_target
flu.unclassified
```

### 5.3 `gram.*` — English-L1 Spanish morphosyntax

```
gram.agreement.gender
gram.agreement.number
gram.copula.ser_estar
gram.aspect.preterite_imperfect
gram.mood.subjunctive_missing
gram.mood.subjunctive_overused
gram.clitic.placement
gram.clitic.case            # covers leísmo — note Peninsular leísmo de persona is standard, see §9
gram.prep.por_para
gram.verb.person_inflection
gram.article.missing_or_extra
gram.unclassified
```

### 5.4 `lex.*` and `prag.*` — the Peninsular-fidelity channels

```
lex.dialect.latam_for_peninsular   # carro/celular/computadora/estacionamiento/jugo…
lex.false_friend                   # embarazada, éxito, actualmente, realizar…
lex.register.too_formal
lex.register.too_informal
lex.unclassified

prag.address.vosotros_missing      # ustedes used for a plural informal group in Spain
prag.address.tu_usted_mismatch
prag.codeswitch.english            # THE fatal one — 06: every model offered an English exit ≤5 turns
prag.character_break               # tutor drops the scenario persona / narrates as an assistant
prag.formula.missing               # no greeting/closing where the scenario register demands one
prag.unclassified
```

`prag.codeswitch.english` and `prag.character_break` are the two tags where `actor=tutor` matters
most: they map 1:1 onto `eval/quality_probe.py`'s ENGLISH-LEAK and THINKING-LEAK flags, and
`prag.address.vosotros_missing` onto its no-vosotros flag.

### 5.5 `task.*` and `recall.*`

```
task.completed
task.abandoned_by_learner
task.abandoned_english          # learner escaped to English — the thesis-critical failure
task.exit_condition_unmet
task.tutor_gave_answer          # tutor solved it instead of forcing production

recall.correct
recall.lapse                    # attributed if a co-occurring observation exists this turn
recall.lapse.unattributed       # failed, no detector could say why — track this rate
```

---

## 6. Reliability tiers

The three signals have wildly different trustworthiness and the schema must carry that, because 03
and 06 both give hard reasons not to trust two of them.

| Tier | Meaning | v0 policy |
|---|---|---|
| **A** | Deterministic / verifiable. Lexicon match, closed-list rule, scenario exit condition, FSRS outcome. No model judgement. | Assert to learner. Drive scheduling. |
| **B** | Acoustically measurable, needs per-phoneme calibration against real recordings. GOP on θ/s, b/v, trill-vs-tap; pause metrics. | Assert **only after** the Day-1 calibration in 03's validation plan passes. Until then: log, don't surface. |
| **C** | Model-judged or continuous-gradient. SLM grammar grading; vowel reduction; diphthong timing; /d/→[ð]. | **Never asserted in v0.** Logged; may silently steer difficulty. |

Why `gram.*` sits in tier C: 06 measured that the local models themselves produce ungrammatical and
invented Spanish ("una copa tinto", invented Madrid tapas), and the index closes cross-track #5 with
*the model is the conversational engine, not the language authority*. A judge that cannot reliably
produce correct Spanish cannot be trusted to adjudicate it. Grammar grading is logged from day one
(it costs one extra constrained generation) but does not tell the learner they were wrong until it
has been validated against a held-out set.

This tiering is the direct schema expression of 03's §2.5 design rule — *the assessment path is the
only signal ever used to tell the learner "you mispronounced X"* — generalized to all three signals.

---

## 7. How each detector emits

### 7.1 Pronunciation (03)

Two sub-detectors off the **assessment path only**, never off the conversational transcript:

- `whisper_conf` — per-word probability from `word_timestamps=True`, greedy decode. A dip below the
  calibrated threshold (03 suggests starting 0.5–0.6) emits **no tag by itself**; it emits a
  *localization hint* that gates the phoneme pass. This matters: 03 flags as risk #1 that greedy
  decode may still auto-correct, so a confidence dip is a pointer, not a verdict.
- `ctc_gop` — `wav2vec2-xlsr-53-espeak-cv-ft` posteriors, forced-aligned (MFA `spanish_mfa` for
  ground truth; WhisperX alignment is explicitly *not* trustworthy at phone level per
  m-bain/whisperX#1247). Emits `phon.*` with `score` = normalized log-posterior margin of the target
  phone against the best competitor, and `threshold` = the per-phoneme calibrated cut. **Per-phoneme
  thresholds, not one global score** — 03 §3.2 is explicit that short/reduced vowels have noisier
  posteriors.

### 7.2 Grammar (02)

The SLM grader must be **constrained to the closed `gram.*` list** via structured output (GBNF /
outlines), returning `{error_type, span, expected, observed, confidence}` or the empty list. It may
not invent a tag and it may not write prose. Two consequences:

- An out-of-vocabulary tag is a **bug**, caught at parse time, not a new category.
- Because the model is not the language authority, a `gram.*` observation is only promoted from
  tier C toward assertion when a **deterministic check corroborates it** — e.g. gender agreement
  checked against a bundled lexicon rather than believed from the model. Start with the two that are
  cheaply verifiable offline (`gram.agreement.gender`, `gram.agreement.number`) and leave the rest
  logged-only.

### 7.3 Recall (04)

FSRS review events already carry `grade` and `item_id` (04 §8.4). The only addition here: on a
lapse, join against observations emitted in the same turn. If one exists, the lapse gets the
attributed tag; otherwise `recall.lapse.unattributed`. The unattributed rate is a direct measure of
**how much of the learner's failure the detectors can see at all** — arguably the single most
informative number in v0.

---

## 8. The record

Extends 04 §8 rather than replacing it. 04 §8.2's `error_type` field stays exactly where it is —
this is the detail table it points into, emitted zero-or-many times per turn.

```
error_observation
  observation_id     : uuid
  decision_id        : uuid          # FK to 04 §8.1 — which tutor decision
  turn_id            : uuid
  timestamp          : ISO8601
  actor              : learner | tutor
  error_type         : dotted tag, closed vocabulary (§5)
  taxonomy_version   : string         # bump on any registry append
  item_id            : stable id | null   # 04's stability rule applies verbatim
  detector           : ctc_gop | whisper_conf | slm_grader | lexicon_rule | scenario_engine | fsrs_review | prosody | human
  detector_version   : string
  tier               : A | B | C
  score              : float | null   # detector-native: GOP margin, logprob, grader confidence
  threshold          : float | null   # what score was compared against, at emit time
  severity           : blocking | salient | cosmetic
  surfaced           : bool           # was this shown to the learner
  span               : {start_ms,end_ms} | {char_start,char_end} | null
  expected           : string | null
  observed           : string | null
  evidence_ref       : path | null    # audio clip / transcript offset, for later re-scoring
```

`severity` is about **communicative cost**, not detector confidence (that's `score`/`tier`). A
gender error is `cosmetic`; an unintelligible trill that made the bartender say "¿cómo?" is
`blocking`. Only `blocking` and `salient` are candidates for surfacing, and only from tiers A/B —
which means v0 shows the learner very little, on purpose.

**Why `evidence_ref` earns its place:** thresholds in tiers B and C will be wrong at first. With a
retained clip, recalibration re-scores history offline. Without it, every observation logged before
the fix is dead weight — the same unrecoverability argument 04 §8 makes for `propensity_score`.

---

## 9. Known traps

- **Peninsular leísmo is not an error.** `gram.clitic.case` must not fire on *le* for a masculine
  personal direct object — that is standard in Spain and RAE-accepted. The rule needs a
  Peninsular-specific exception list, otherwise the app corrects the learner *toward* Latin American
  Spanish while claiming to teach Castilian. Same shape of trap as θ/s, which 03 flagged as
  unscorable until the dialect was fixed; `docs/00-constraints.md` fixed it.
- **`phon.sibilant.s_as_theta` fires on real Andalusian/ceceo input** and on any speaker whose model
  is a southern variety. Low prior for this user, but do not silently "correct" it.
- **Tier-C observations must not leak into the in-context profile as assertions.** 04's closing risk
  is a rotting profile that looks like "the model isn't adapting." The concrete guard: profile
  entries carry the tier and observation count that produced them, and tier-C entries are phrased as
  hypotheses ("possibly struggling with X") or excluded entirely in v0.
- **Tag sprawl.** If `*.unclassified` exceeds a few percent of observations, extend the registry
  deliberately in one versioned pass — don't let detectors start emitting ad-hoc strings.

---

## 10. What has to be validated before this is trustworthy

Every tier-B tag depends on 03's unresolved risks #1 and #2, which this taxonomy cannot resolve on
paper:

1. Does greedy Whisper + word confidence actually surface deliberate mispronunciations, or does it
   auto-correct anyway? (03 command 3 — "THIS SINGLE TEST validates or kills the entire §2
   strategy.") If it fails, `whisper_conf` localization hints are worthless and every `phon.*`
   observation must come from the phoneme pass alone.
2. Does `wav2vec2-xlsr-53-espeak` output the *wrong* phone for a genuinely mispronounced sound, or
   smooth it over? (03 command 4.) If it smooths, the entire `phon.*` channel drops to tier C and v0
   ships with **no pronunciation assertions at all** — which is a survivable outcome, but it should
   be a decision, not a discovery mid-build.
3. Per-phoneme GOP thresholds need real recordings of this user. Until then tier B is logged-only.

Nothing above blocks implementing the **schema**, which is the point — 04's argument is that the
logging is the one thing you cannot add retroactively. Ship the record now; promote tiers later.
