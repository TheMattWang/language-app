# 08 — Architecture, data model, and v0 scope

Owner: main session (synthesis). Written 2026-09-12.
This is the other half of track 05's original brief, reassigned after that agent failed.

Inputs: `01-pedagogy.md` §7/§8a, `03-speech-stack.md` §(a)/§(b)/§5.3, `04-rl-adaptation.md` §8,
`06-bench-local-baseline.md`, `07-error-taxonomy.md`, `02-local-slm.md` §8/§9,
`05-landscape-content.md` §2 (content sourcing — referenced, not restated), and the locked
`../docs/00-constraints.md`.

Like 07, this is a **v0 specification, not a survey**. Where a research track left a number
ESTIMATED, this document names the gate that replaces it rather than pretending it is settled.

---

## 1. The three constraints that determine the architecture

Everything below falls out of three facts already established, not from taste:

1. **The LLM is not the bottleneck, and it is not an authority.** 06 measured 0.35–0.81s full
   turns at 1.5–3B and proved every candidate breaks Peninsular register and offers an English
   exit. So the architecture must spend its complexity budget on *constraining and checking* the
   model, not on making it fast. (02 §8/§9 converged independently: free generation + external
   validator + regenerate-on-failure.)
2. **Assessment is off the critical path, by design.** 03 §(b) mandates two parallel consumers of
   one audio stream. That single rule is what makes a 900ms turn and honest error detection
   compatible at all — and it is a *process* decision, so it has to be in the module boundaries.
3. **Logging is the one thing that cannot be added retroactively.** 04 §8 and 01 §8a-8 agree. So
   the store is not an afterthought bolted on at the end; it is built in slice 1 and every later
   slice writes into it.

A fourth, from the constraints file: **< 3 weeks, single user, Mac only.** That forbids a service
architecture. This is one Python process with a small number of threads and one SQLite file.

---

## 2. Module boundaries

Concrete package seams. The rule for every boundary: **the turn loop is the only module that knows
the ordering of the pipeline.** Everything else exposes a function and knows nothing about what
calls it.

```
langapp/
  audio/       device I/O, 16kHz mono ring buffer, resampling.
               THE ONLY place sounddevice / Core Audio appears. One capture stream,
               fanned out to N consumers (03 §(b) requires >=2).
  vad/         Silero frame-level + the endpointing policy (silence threshold,
               semantic-completeness gate). Emits speech-start / speech-end events.
  asr/
    conversational.py   whisper large-v3-turbo, greedy, word timestamps -> text + per-word conf
    assessment.py       wav2vec2-xlsr-53-espeak phoneme CTC -> phone sequence + posteriors
  llm/         one interface: stream_turn(messages, params) -> Iterator[clause].
               Backends: ollama.py (now), mlx.py (later). 02 §9 says Ollama is fine for v0;
               the seam exists so that is reversible, not so it is rewritten.
  guard/       the output guard. Runs over each clause BEFORE it reaches tts.
               Shares its rule set with eval/quality_probe.py (07 §2). Emits
               actor=tutor error_observations. Owns the regenerate decision.
  tts/         Piper es_ES, sentence/clause chunk synthesis, playback handle.
  scenario/    scenario definitions (data, not code), the state machine, and the
               exit-condition evaluator. Exit conditions are checkable predicates over
               the transcript + scenario state -- never an LLM judgment (01 §8a-4).
  probe/       the CEFR placement battery: C-test items + elicited-imitation targets,
               and their scorers. Depends on asr/ and store/ ONLY -- not on llm/ or tts/.
  scoring/     detectors that turn signals into error_observations (07 §7).
               gop.py, lexicon.py, slm_grader.py, prosody.py. All async, all off
               the critical path, all emit into store/ via the writer queue.
  learner/     the profile: weak-area list, ability estimate, item state.
               Reads observations, writes the profile. Nothing else writes the profile (07 §3.2).
  sched/       item/scenario selection + difficulty controller. v0 is a fixed heuristic
               (01 §8a-6) but it emits a FULL decision record anyway (04 §8.1).
  store/       SQLite schema, migrations, and the single-writer event queue. §4 below.
  app/         session loop(s) + CLI. The only module that orchestrates.
eval/          llm_bench.py, quality_probe.py (exist) + the gate scripts from §6.
```

### 2.1 Threading model

One process. Four threads, because the latency budget requires it and nothing more:

| Thread | Owns | May block? |
|---|---|---|
| **audio** | capture callback, ring buffer, playback | never — real-time callback, no allocation, no SQLite |
| **turn** | VAD → conversational ASR → llm → guard → tts. The 900ms path. | only on the model |
| **assessment** | phoneme CTC, GOP, SLM grader, all of `scoring/` | freely — it is behind the conversation |
| **writer** | drains the event queue into SQLite | freely |

The turn thread writes events with `queue.put_nowait` and never touches the DB. This matters more
than it looks: the assessment path and the turn path will otherwise contend for the same SQLite
connection at exactly the moment latency is being measured, and the resulting jitter would be
misattributed to the model.

### 2.2 The one non-obvious call: where the guard sits

03 §5.3 says stream clauses to TTS as they are generated — that is the single largest latency win
available. 06 and 02 say validate the output and regenerate on failure. **These conflict: you
cannot regenerate a sentence you have already spoken.**

Resolution: **validate at clause granularity, and only the first clause is on the critical path.**

- The guard's v0 rules are cheap and regex-shaped (English leak, `vosotros`/`ustedes` address form,
  character break, empty, reasoning-trace leak) — sub-millisecond, from `eval/quality_probe.py`.
- Clause 1 is checked before it is handed to TTS. On failure, regenerate the turn. Measured cost of
  a regeneration at 1.5–3B is one TTFT (8–30ms) plus one clause of decode — call it ~0.2–0.3s, which
  fits inside 03's 900ms budget with the VAD stage's deliberate slack.
- Clauses 2..n are checked as they arrive, while clause 1 is already being spoken. A late failure
  cannot un-speak audio, so it **truncates** the turn at the last good clause and logs
  `actor=tutor` at the offending tag. Truncation is a visible-but-recoverable failure; speaking
  English at the learner is the failure the whole product is trying to prevent.
- Guard violation rate per model is a **model-selection metric**, not just a runtime counter — it is
  the same number `quality_probe.py` produces, which is why they must be one implementation.

This is the only place the architecture spends latency on quality, and it is the right place.

---

## 3. Session flows

Three, and only three, in v0.

**A. Placement probe** (first run, ~5 min, 01 §7).
`audio → vad → asr.conversational → probe.score → store → learner.profile`
No LLM, no TTS, no scenario. This is the entire product on day one and it is a *complete vertical
slice of the load-bearing plumbing* (01 §8a-2) that ships value without touching the two riskiest
components. v0 battery is **C-test + elicited imitation only** — per 01 §8a-1, picture description
and monologue are cut because their scoring needs the LLM-judge step 01 §7.3 flags as the single
most sycophancy-prone piece of the design.

**B. Scenario turn loop** (the forcing function).
```
vad.speech_end
  -> asr.conversational           (turn thread)
  |-> asr.assessment              (assessment thread, forked from the same buffer)
  -> scenario.state.update(transcript)
  -> scenario.exit_conditions.check()      # deterministic predicate, may end the scenario
  -> sched.decide()                        # emits decision record even when heuristic
  -> llm.stream_turn(scenario_prompt + profile + history)
  -> guard.check(clause)                   # §2.2
  -> tts.speak(clause)
```
Exit conditions are the thesis: *you resolve the situation in Spanish or you don't leave.* They are
predicates over scenario state (did the learner obtain the item / correct the charge / get the
platform number), never a model's opinion.

**C. Review/debrief** (post-scenario, non-real-time).
Drains whatever the assessment thread produced, shows it, writes `interaction` grades. This is where
tier-A observations may surface to the learner; tier B/C are logged and shown only as
"we noticed, unverified" or not at all (07 §6).

---

## 4. Data model

One SQLite file, `data/langapp.db`. `journal_mode=WAL`, `synchronous=NORMAL`, single writer thread.
**Append-only** except `item_alias`, `learner_profile`, and clip retention flags.

This schema is 04 §8.1–8.5 made concrete, plus 07 §8's `error_observation`, plus four tables those
specs implied but did not name.

### 4.1 Core event tables (04 §8)

```sql
CREATE TABLE session (
  session_id      TEXT PRIMARY KEY,
  user_id         TEXT NOT NULL,          -- constant; kept per 04 §8.1
  started_at      TEXT NOT NULL,          -- ISO8601
  ended_at        TEXT,
  kind            TEXT NOT NULL,          -- probe | scenario | review
  item_count      INTEGER DEFAULT 0,
  voluntary_return_next_day INTEGER,      -- 04 §8.5 guardrail, NEVER an optimization target
  self_report_satisfaction  INTEGER
);

CREATE TABLE decision (                   -- 04 §8.1
  decision_id     TEXT PRIMARY KEY,
  session_id      TEXT NOT NULL REFERENCES session,
  timestamp       TEXT NOT NULL,
  item_id         TEXT NOT NULL REFERENCES item,
  item_type       TEXT NOT NULL,          -- vocab | grammar_point | scenario | free_conversation
  skill_tags      TEXT NOT NULL,          -- JSON array
  policy_version  TEXT NOT NULL,          -- e.g. "heuristic-v0.1"; hash of sched/ logic
  scheduler_state TEXT NOT NULL,          -- JSON: fsrs_*, days_since_last_review,
                                          --       ability_estimate, rolling_success_rate
  selection_reason TEXT NOT NULL,
  propensity_score REAL,                  -- 1.0 for a deterministic pick -- log it anyway
  explore_flag     INTEGER NOT NULL DEFAULT 0,
  explore_mechanism TEXT NOT NULL DEFAULT 'none',
  explore_param     REAL,
  difficulty_settings TEXT NOT NULL       -- JSON: speech_rate, lexical_level, error_tolerance
);

CREATE TABLE decision_candidate (         -- 04 §8.1 candidate_set, normalized
  decision_id     TEXT NOT NULL REFERENCES decision,
  item_id         TEXT NOT NULL REFERENCES item,
  score           REAL,
  selection_probability REAL,
  PRIMARY KEY (decision_id, item_id)
);

CREATE TABLE turn (
  turn_id         TEXT PRIMARY KEY,
  decision_id     TEXT REFERENCES decision,
  session_id      TEXT NOT NULL REFERENCES session,
  idx             INTEGER NOT NULL,       -- ordinal within the session
  started_at      TEXT NOT NULL,
  -- measured latency decomposition; the columns ARE 03's budget table
  vad_ms          INTEGER, asr_ms INTEGER, llm_ttft_ms INTEGER,
  llm_total_ms    INTEGER, guard_ms INTEGER, tts_first_audio_ms INTEGER,
  end_to_end_ms   INTEGER,
  regenerations   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE interaction (                -- 04 §8.2
  turn_id         TEXT PRIMARY KEY REFERENCES turn,
  decision_id     TEXT REFERENCES decision,
  timestamp       TEXT NOT NULL,
  latency_ms      INTEGER,
  learner_response_raw TEXT,              -- conversational ASR transcript
  learner_response_phones TEXT,           -- assessment-path phone string, may arrive later
  grade           TEXT,                   -- again | hard | good | easy
  error_type      TEXT,                   -- 07 tag; the SUMMARY tag. detail lives in
                                          -- error_observation, which is the source of truth
  hints_used      INTEGER NOT NULL DEFAULT 0,
  self_reported_confidence INTEGER        -- log, never optimize (04 §6)
);

CREATE TABLE generation (                 -- 04 §8.3
  turn_id         TEXT PRIMARY KEY REFERENCES turn,
  decision_id     TEXT REFERENCES decision,
  model_id        TEXT NOT NULL,          -- base + quant + adapter ("none")
  prompt_template_version TEXT NOT NULL,
  profile_snapshot_hash   TEXT NOT NULL REFERENCES profile_snapshot,
  full_prompt     TEXT NOT NULL,
  full_response   TEXT NOT NULL,
  guard_verdict   TEXT NOT NULL           -- pass | regenerated | truncated
);

CREATE TABLE review_event (               -- 04 §8.4
  review_event_id TEXT PRIMARY KEY,
  original_decision_id TEXT REFERENCES decision,
  item_id         TEXT NOT NULL REFERENCES item,
  timestamp       TEXT NOT NULL,
  delta_days      REAL,
  grade           TEXT NOT NULL
);
```

### 4.2 The four tables the specs implied but did not name

**(a) `profile_snapshot` — 04 §8.3 logs a hash of the in-context profile and never says where the
body lives.** A hash with no resolvable body makes every logged prompt unreconstructable, which
defeats the DPO-pair-mining rationale that justified logging `full_prompt` in the first place.

```sql
CREATE TABLE profile_snapshot (
  hash     TEXT PRIMARY KEY,              -- content hash; dedupes across turns for free
  body     TEXT NOT NULL,                 -- the exact profile text injected into the prompt
  created_at TEXT NOT NULL
);
```

**(b) `item` + `item_alias` — 04 §8.4's stability requirement, made enforceable.** 04 says keep a
mapping table rather than renumbering; 07 §3.1 applies the same rule to taxonomy tags. Both get one
mechanism.

```sql
CREATE TABLE item (
  item_id     TEXT PRIMARY KEY,           -- opaque, never reused, never renumbered
  item_type   TEXT NOT NULL,
  content_ref TEXT NOT NULL,              -- pointer into the bundled content set
  content_version TEXT NOT NULL,
  skill_tags  TEXT NOT NULL,              -- JSON array
  retired_at  TEXT
);
CREATE TABLE item_alias (                 -- old id -> current id, across content restructures
  old_item_id TEXT PRIMARY KEY,
  item_id     TEXT NOT NULL REFERENCES item,
  reason      TEXT, migrated_at TEXT NOT NULL
);
```

**(c) `error_observation` — 07 §8 verbatim, as DDL.** This is the detail table behind
`interaction.error_type`.

```sql
CREATE TABLE error_observation (
  observation_id  TEXT PRIMARY KEY,
  decision_id     TEXT REFERENCES decision,
  turn_id         TEXT REFERENCES turn,
  timestamp       TEXT NOT NULL,
  actor           TEXT NOT NULL,          -- learner | tutor          (07 §2)
  error_type      TEXT NOT NULL,          -- closed vocabulary        (07 §5)
  taxonomy_version TEXT NOT NULL,
  item_id         TEXT REFERENCES item,
  detector        TEXT NOT NULL,
  detector_version TEXT NOT NULL,
  tier            TEXT NOT NULL,          -- A | B | C                (07 §6)
  score           REAL,
  threshold       REAL,                   -- what score was compared against, AT EMIT TIME
  severity        TEXT NOT NULL,          -- blocking | salient | cosmetic
  surfaced        INTEGER NOT NULL,
  span            TEXT,                   -- JSON {start_ms,end_ms} or {char_start,char_end}
  expected        TEXT, observed TEXT,
  evidence_ref    TEXT REFERENCES audio_clip
);
CREATE INDEX ix_obs_type ON error_observation(error_type, actor, timestamp);
CREATE INDEX ix_obs_turn ON error_observation(turn_id);
```

**(d) `audio_clip` — 07 §8's `evidence_ref` needs a registry, not a bare path.** 07's argument is
that tier B/C thresholds will be wrong at first and retained audio is what makes offline re-scoring
possible. That only works if the clip's provenance and encoding are known.

```sql
CREATE TABLE audio_clip (
  clip_id     TEXT PRIMARY KEY,
  turn_id     TEXT REFERENCES turn,
  path        TEXT NOT NULL,              -- relative to data/audio/
  sha256      TEXT NOT NULL,
  sample_rate INTEGER NOT NULL,
  codec       TEXT NOT NULL,              -- flac (archival) | opus (compact)
  duration_ms INTEGER NOT NULL,
  keep        INTEGER NOT NULL DEFAULT 1  -- the one mutable flag; retention decisions
);
```

Sizing, so this is not a surprise later: 16kHz mono s16 is ~32KB/s raw. Three weeks at ~20 min/day
of *learner* speech is ~25k seconds ≈ 800MB raw, ~250–400MB as FLAC, well under 100MB as Opus.
Keep FLAC for v0 — the whole point is re-scoring fidelity, and 137Gi free makes the tradeoff free.

### 4.3 Scenario and probe tables

```sql
CREATE TABLE scenario (
  scenario_id TEXT PRIMARY KEY, title TEXT NOT NULL,
  setting     TEXT NOT NULL,              -- airport | hotel | bar | pharmacy | directions |
                                          -- train | problem
  cefr_band   TEXT NOT NULL,
  definition_version TEXT NOT NULL,
  exit_conditions TEXT NOT NULL           -- JSON array of named predicates
);
CREATE TABLE scenario_run (
  run_id      TEXT PRIMARY KEY, scenario_id TEXT NOT NULL REFERENCES scenario,
  session_id  TEXT NOT NULL REFERENCES session,
  started_at  TEXT NOT NULL, ended_at TEXT,
  outcome     TEXT,                       -- 07 §5 task.* tags: completed |
                                          -- abandoned_by_learner | abandoned_english |
                                          -- exit_condition_unmet | tutor_gave_answer
  turns_taken INTEGER, time_pressure_s INTEGER
);
CREATE TABLE exit_condition_check (       -- every evaluation, not just the final one
  run_id TEXT NOT NULL REFERENCES scenario_run, turn_id TEXT REFERENCES turn,
  condition_name TEXT NOT NULL, satisfied INTEGER NOT NULL, evidence TEXT,
  PRIMARY KEY (run_id, turn_id, condition_name)
);

CREATE TABLE probe_run (
  probe_run_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES session,
  battery_version TEXT NOT NULL, completed INTEGER NOT NULL,
  cefr_band_low TEXT, cefr_band_high TEXT,   -- a BAND, not a point estimate (01 §7.2)
  weak_area_profile TEXT                     -- JSON; this is what drives sequencing
);
CREATE TABLE probe_task_result (
  probe_run_id TEXT NOT NULL REFERENCES probe_run, task TEXT NOT NULL,  -- ctest | ei
  item_id TEXT NOT NULL REFERENCES item, raw_response TEXT,
  score REAL NOT NULL, max_score REAL NOT NULL, clip_id TEXT REFERENCES audio_clip,
  PRIMARY KEY (probe_run_id, task, item_id)
);
```

### 4.4 Two schema rules worth stating once

- **`decision` rows are emitted even though nothing learns from them in v0.** This is 04 §8's
  entire thesis and the single most likely thing to get dropped under deadline pressure. A
  deterministic heuristic has `propensity_score = 1.0` and `explore_flag = 0` — writing those is
  three lines, and not writing them makes every future off-policy question unanswerable.
- **01 §8a-6 vs 04 §8.1 is a real tension and it resolves in favor of both.** 01 says do not build
  FSRS scheduling in v0; 04 wants `fsrs_*` in `scheduler_state`. The resolution: v0's scheduler is
  the flat weak-area list 01 asks for, and `scheduler_state` carries `fsrs_*: null`. The *columns*
  are free; the *model* is deferred. Nothing in v0 computes a stability value.

---

## 5. Content

Deliberately not restated here — see `05-landscape-content.md` §2 for source-by-source licensing
and bundling verdicts. What this document commits to:

- Content is **data on disk, versioned, referenced by `item.content_ref` + `content_version`** —
  never model-generated at runtime (06/cross-track #5, CLOSED).
- Scenario definitions and exit-condition predicates live in the same versioned content set, so a
  scenario rewrite is an `item_alias` migration, not silent drift under historical logs.
- **The bundle list is now SETTLED** by 05 §2's "Recommendation for 3-week MVP" — exactly three
  sources, ~50-150MB total: (1) `hermitdave/FrequencyWords` `es_50k.txt` (CC-BY-SA-4.0, <10MB) as
  the frequency spine; (2) a Kaikki.org Spanish Wiktionary JSONL subset filtered to the ~15-20k
  lemmas intersecting that list (CC-BY-SA-4.0/GFDL, tens of MB instead of ~1GB raw) for gloss +
  POS + IPA; (3) spaCy `es_core_news_sm` (MIT, ~10-15MB) — used as a *tool* for tokenization and
  lemmatization at build time and for form-matching at runtime, not as a content source. Tatoeba,
  raw OPUS/OpenSubtitles, Common Voice and RAE CREA/CORPES are all explicitly out of v1.
- **Scenario dialogue is hand-authored.** 05 §2 is unambiguous that none of the bundled corpora
  supply scenario content, and 06 already established the model must not generate it. A few dozen
  short scripted Peninsular exchanges per scenario is hours of work, and it is slice 3's real cost.
  05 §2's hand-built Spain-vs-LatAm lexical pair list (ordenador/computadora, coche/carro,
  móvil/celular, patata/papa, zumo/jugo, conducir/manejar, vale) doubles as the vetting filter for
  those scripts *and* as a runtime detector in `scoring/lexicon.py` — one list, two consumers.

---

## 6. v0 scope, sequenced against the deadline

Today 2026-09-12; departure ~2026-10-03. **21 days.** Slices are ordered so that each one ends with
something that runs, and so the riskiest unknowns are resolved before anything is built on them.

### Slice 0 — gates, not code (days 1–2)

These are decisions, and every one of them changes what gets built. All are already written as
runnable commands in the research; none require new design work.

| Gate | Source | What it decides |
|---|---|---|
| Greedy Whisper + word confidence surfaces deliberate mispronunciations | 03 §(c) cmd 3 | whether the assessment path has a usable localization signal |
| wav2vec2-xlsr-53-espeak emits the *wrong* phone rather than smoothing it | 03 §(c) cmd 4 | whether `phon.*` can ever leave tier C (07 §10) |
| Register/quality probe on 02's shortlist | 02 §10 cmd 3, `eval/quality_probe.py` | which model ships; the guard's violation baseline |
| End-to-end stopwatch | 03 §(c) cmd 9 | replaces 03's ESTIMATED budget table with measured numbers |
| RAM under concurrent ASR+LLM+TTS load | cross-track #2, still open | whether all three stay resident or the LLM unloads between turns |

If the two phoneme gates fail, **v0 ships with no pronunciation assertions at all** (07 §10). That
is survivable and the plan does not change shape — the clips are still retained and re-scorable.

### Slice 1 — probe + plumbing (days 3–6)

`audio/`, `vad/`, `asr/conversational`, `store/` (full schema), `probe/` (C-test + EI),
`learner/` profile write. Ends with: a working 5-minute placement probe that writes a CEFR band, a
weak-area profile, and retained audio. **No LLM, no TTS.** This is 01 §8a-1 and §8a-2 satisfied at
once, and it de-risks the plumbing before either risky component is attached.

### Slice 2 — the voice loop (days 7–11)

`llm/ollama`, `guard/`, `tts/`, `app/` turn loop, one hardcoded scenario. Ends with: a real spoken
turn against the measured latency budget, with the guard's regenerate/truncate behavior working and
`actor=tutor` observations landing in the DB. The guard is built *with* the loop, not after it —
§2.2 is the riskiest single mechanism in the product.

### Slice 3 — scenario engine (days 12–16)

`scenario/` state machine + exit-condition evaluator, 6–7 travel scenarios from the constraints
file (airport, hotel check-in, bar/tapas, pharmacy, directions, trains, a problem — lost bag or
wrong charge), `sched/` heuristic emitting full decision records. Ends with: the forcing function
actually forcing — a scenario you cannot leave without resolving in Spanish.

### Slice 4 — assessment path (days 17–19)

`asr/assessment`, `scoring/` at whatever tier survives slice 0, the debrief flow. **This is the
designated cut line.** If days 17–19 evaporate, the clips and transcripts are already retained
(§4.2d), so the entire slice can be run offline after the trip against real data — which is
strictly better input than anything synthesized before it.

### Slice 5 — hardening (days 20–21)

Airplane mode verification (no network calls anywhere in the stack), cold-start time, thermal
behavior over a 30-minute session on battery (02 §10 cmd 6 — still ESTIMATED), and one dry run of a
full session end to end.

### Explicitly out of v0

Per `../docs/00-constraints.md`, restated so it survives deadline pressure: no LoRA/DPO/GRPO or any
weight adaptation; no bandit or RL item selection; no FSRS stability model; no iOS anything; no
accounts, sync, streaks, or XP (01 §8a-7). The scheduler is a lookup table and that is the correct
answer for 21 days of data.

---

## 7. What this document does not settle

- **Cross-track #2 (RAM under concurrent load)** — the last unresolved cross-track question. It is
  slice 0's fifth gate because it determines whether `llm/` keeps a resident model or pays a load
  cost per turn, and that changes the turn loop's shape.
- **Guard enforcement adequacy** — 06's replacement risk. §2.2 is a *design* for it; whether regex
  clause-level rules actually hold register across a long scenario is unmeasured, and the honest
  fallback if they do not is a narrower scenario prompt, not a bigger model (06 proved size does not
  help here).
- **Content bundle contents** — SETTLED by 05 §2; see §5. What remains is authoring the scenario scripts, not choosing sources.
- **MLX migration** — deliberately deferred (02 §9). The `llm/` seam exists so this stays a
  swap rather than a rewrite; nothing in v0 depends on it happening.
