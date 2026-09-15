# Research index

Wave 1 launched 2026-09-12. Five parallel tracks, one file each.

| # | File | Track | Status |
|---|------|-------|--------|
| 01 | `01-pedagogy.md` | SLA evidence: attrition, forced output, retrieval practice, forcing-function mechanics, Peninsular Spanish curriculum, CEFR placement probe | done |
| 02 | `02-local-slm.md` | Model selection + serving on M3 Air: candidates, quantization, memory budget, tok/s, thermals, structured output | done (§2 closed by `02a`, §1 by `02b`; both merged) |
| 03 | `03-speech-stack.md` | ASR / TTS / pronunciation scoring, the learner-speech honest-transcription problem, latency budget | done |
| 04 | `04-rl-adaptation.md` | What "adapt to the user" means, knowledge tracing, bandits, on-device LoRA feasibility, reward design, instrumentation spec | done |
| 05 | `05-landscape-content.md` | Competitors, OSS building blocks, offline content sourcing | done (narrowed relaunch) |

Constraints that override these docs: `../docs/00-constraints.md`

## Cross-track questions to resolve at synthesis

These span more than one agent's brief and get answered once everything lands:

- **The latency chain.** 03 gives a speech budget, 02 gives LLM tok/s. Do they actually sum to a conversational turn on this machine, or does the dream of a local voice partner die here? This is the project's riskiest assumption.
- **The RAM zero-sum.** ASR + TTS + LLM + (later) a training buffer all compete for ~11GB usable. 02 and 03 each assume a budget; check they don't double-spend it.
- **Honest transcription vs good conversation.** 03's fix for ASR auto-correcting learner errors may require a model or decoding mode that conflicts with 02's latency target. Note the tension.
- **Where the error signal comes from.** Pronunciation scoring (03), grammar grading by the SLM (02), and recall outcomes (04) are three different signals feeding one learner model. They need a shared error taxonomy — reassigned to synthesis (main session) after 05's agent failed. **ANSWERED in `07-error-taxonomy.md`.**
- **Generated vs sourced content.** 05 asks whether the local SLM can author scenarios; 02 knows how badly small models write Spanish. Reconcile.

## Wave 1b — measured, not read

| # | File | Track | Status |
|---|------|-------|--------|
| 06 | `06-bench-local-baseline.md` | Benchmarks on Matt's actual M3 Air: turn latency across 6 local models, Peninsular-register and character-break quality probes | done |

## Synthesis deliverables (main session)

| # | File | Track | Status |
|---|------|-------|--------|
| 07 | `07-error-taxonomy.md` | Shared error taxonomy + observation schema unifying pronunciation (03), grammar grading (02), recall (04) — cross-track #4 | done |
| 08 | `08-architecture-data-model.md` | Module boundaries, threading model, SQLite schema, v0 scope sequenced against the 21-day deadline — the other half of 05's dropped brief | done |

Track 06 partially answers cross-track question #1 (**latency is not the bottleneck**;
LLM turn = 0.35–0.81s) and pre-empts #5 (**small models are not a trustworthy source of
Spanish** — source/template content, let the model handle turn-taking only). It replaces
the latency question with a harder one: **register and character-break discipline.**

## Resolutions so far

**#1 latency — CLOSED.** 06 measured the LLM half (0.35–0.81s full turn, 1.5–3B). 03 budgets
900ms end-to-end assuming 200ms for "LLM prefill + time-to-first-sentence." Measured prefill is
8–30ms and first-sentence lands well inside 200ms at these sizes, so 03's budget holds *with the
models 06 tested*. It does **not** hold under 03's stated premise of a resident 7B Q4 — that
assumption is now dead on latency grounds independently (06 extrapolates ~2s/turn for 7B).

**#2 RAM — partially resolved by #1.** 03 assumed the LLM eats 4–6GB and left ~3–4GB for
ASR+TTS. Dropping to a 1.5–3B Q4 LLM (~1–2GB) roughly doubles the speech budget to ~6–7GB.
whisper large-v3-turbo + Piper + wav2vec2-phoneme-CTC now fit without contention.
Still UNMEASURED under concurrent load — 03 risk #3 and 06 §4 both flag it. Open.

**#3 honest transcription vs latency — no conflict.** 03's fix is two parallel consumers off one
audio stream: greedy word-level Whisper on the conversational path, phoneme-CTC off the critical
path for assessment. The assessment path is async by design, so its cost never enters the turn
budget. The tension the question assumed does not exist. What replaces it: does greedy decoding
actually surface learner error (03 risk #1) — untested, and load-bearing.

**#5 generated vs sourced — CLOSED by 06.** Model is the conversational engine, not the language
authority. Content sourced/templated; model handles turn-taking inside constrained bounds.

**03 risk #5 (dialect) — CLOSED.** `../docs/00-constraints.md` locks Peninsular. Build the θ/s
detector and pick Piper `es_ES`.

**#4 shared error taxonomy — CLOSED by `07-error-taxonomy.md`.** One closed, append-only, versioned
tag vocabulary across six channels (`phon` `flu` `gram` `lex` `prag` `task` `recall`), emitted into
04 §8.2's existing `error_type` field via an `error_observation` detail table. Two structural calls
worth knowing without reading the file: (a) every observation carries an **`actor`** field, so the
tutor's own register failures — 06's top risk — are logged under the same tags as the learner's and
the runtime guard shares an implementation with `eval/quality_probe.py`; (b) observations carry a
**reliability tier**, and `gram.*` sits in tier C (logged, never asserted to the learner in v0)
because 06 proved the model is not a trustworthy language authority. Tier B (`phon.*`) stays
logged-only until 03's validation commands 3 and 4 pass.

**05 landed (narrowed relaunch) — content and OSS decisions are now settled.** Three calls worth
knowing without reading the file: (a) **the bundle is three sources, ~50-150MB** — FrequencyWords
`es_50k.txt` (CC-BY-SA-4.0) as the frequency spine, a Kaikki Spanish Wiktionary JSONL subset
filtered to the ~15-20k lemmas intersecting it (gloss/POS/IPA), and spaCy `es_core_news_sm` (MIT)
as a *tool* rather than content. Tatoeba, raw OPUS/OpenSubtitles, Common Voice and RAE CREA/CORPES
are all out of v1. (b) **No corpus supplies scenario dialogue** — it has to be hand-authored, a few
dozen short Peninsular exchanges per scenario, which is hours of work and belongs to slice 3. This
independently re-closes cross-track #5 from the content side: there was never a sourced option, and
06 already killed the generated one. 05's hand-built Spain-vs-LatAm pair list (ordenador/coche/
móvil/patata/zumo/conducir/vale …) vets those scripts *and* becomes the runtime detector in
`scoring/lexicon.py`. (c) **Build-vs-adopt:** adopt py-fsrs (MIT) directly and WhisperLive (or
imitate it closely); read pipecat for its turn-taking/interruption handling rather than depending on
it; skip LiveKit Agents (a WebRTC SFU is a distributed-systems problem this app does not have),
Vocode, and Rasa. **Kyutai unmute is unusable here** — its reference deployment is Linux/WSL +
~16GB-class NVIDIA and excludes Apple Silicon; inspiration only.

**One integration gap to verify at build time:** Ollama wraps llama.cpp but exposes its *own*
`format` parameter (`"json"` or a JSON Schema) on `/api/generate` and `/api/chat` — it is **not** a
pass-through for raw GBNF. 08's `llm/` seam currently assumes free generation + external validator +
regenerate (02 §9), which is unaffected; but if constrained decoding is ever wanted, the path is
Ollama's `format` field or dropping to `llama-cpp-python`/Outlines, not GBNF over the Ollama API.

**Caveat on 05's own sourcing:** the relaunched agent exhausted its WebSearch quota and marked
several §1 landscape claims and parts of §2/§3 UNVERIFIED. Four items it flags for re-check:
competitor coverage (Duolingo Video Call, Speak's course list), exact spaCy `.whl` sizes/licenses,
the OPUS/Common Voice pages that 404'd, and current relative maturity of Outlines vs guidance and
pipecat vs Vocode. None of these change the bundle decision.

**02a landed — the quality floor is now measured, and it moves the model choice.** Merged into
`02-local-slm.md` §2 and §9. Three things worth knowing without reading the 427-line appendix:

(a) **The floor is instruction-tuned 3–4B, and ≤1.7B is not "worse" — it is at chance.** All 17
La Leaderboard models at ≤1.7B score Spanish grammatical acceptability (EsCoLA, MCC) between
−0.042 and +0.079. The 3–4B *instruct* tier lands at +0.17–0.25, 6–9B at +0.24–0.35. Instruction
tuning is what unlocks it: Qwen2.5-3B base 0.028 → Instruct 0.214. **A 3B base checkpoint is not a
substitute for a 3B instruct one.**

(b) **This does not contradict 06, and the reconciliation is load-bearing.** EsCoLA is a
*metalinguistic judgment* task; 06 measured *production*. A 1.5B model can speak fluent Spanish
while being unable to judge it. Both are true, and together they say: **a small model is a speaker,
not a grader.** That is independent quantitative backing for 07's tier-C placement of `gram.*`
(logged, never asserted) and for 08's `guard/` choosing an external validator over a bigger model —
below ~2B the grammaticality signal is *absent*, so an SLM grader there is a coin flip, not a noisy
oracle.

(c) **Three rules that change what to pull.** Q8/Int8 is effectively free for Spanish (the best
Spanish-grammaticality model on the whole leaderboard is an 8-bit quant, beating the fp16 field)
while 4-bit is a real risk below ~7B — so a 3–4B at Q8 (~3.5–4.5GB) is the shape that fits #2's
freed budget. Reasoning/thinking-mode variants are disqualified by construction (Qwen3 thinking →
xquad_es f1 **0.0**; 06 independently saw the empty 4.1s turn). And **prefer a recent general
multilingual model over an older Spanish-specific one** — bertin, latxa-7b, Aitana-6.3B, FLOR-6.3B
and aguila-7b are all still at chance at 6–7B. Consequences for 02 §9: the "smallest Salamandra
instruct" pick is wrong (2b-instruct = +0.006; test the 7b or nothing), Qwen3-4B is out, and the
list to actually pull is gemma-3-4b-it + Qwen2.5-3B-Instruct with gemma2:2b as incumbent.

**02a also confirms an absence that matters more than its numbers:** no public benchmark in the
entire La Leaderboard suite is dialect-split, and register consistency (tú/usted across a
multi-turn conversation) is measured by nothing it could find. 02a's own recommendation — "a
hand-built eval of a few dozen prompts probing voseo, vosotros, and tú/usted consistency" — is a
description of `eval/quality_probe.py`, which already exists. **That probe is not a nice-to-have;
it is the only instrument that exists for the axis this product is built on.** Slice 0's third
gate is now demanded by the literature side as well as the measurement side.

**02b landed — the survey table is filled, and it corrected two licenses and closed the file.**
Merged into `02-local-slm.md` §1 (candidate table, ranked shortlist, open-items bullet). `02` now
has **no `TODO — sub-agent pending` sites anywhere**. Five things worth knowing:

(a) **Two license facts in the pre-merge file were wrong, and both would have reached a build
decision.** **Ministral 3B/8B/14B is under the Mistral Research License — non-commercial by
default**, not Apache-2.0; it is disqualified on license despite posting the best Spanish MMLU in
the survey (59.6 vs Llama 3.1 8B's 54.6, a vendor claim). **Latxa is Llama-2-licensed**, not
Apache-2.0, being continued pretraining of Llama 2 on Basque.

(b) **Packaging, not quality, eliminates the two Iberian candidates.** mlx-community carries
**only `salamandra-7b-instruct-mlx-bf16`** — no 4-bit or 8-bit build, ~14GB against an ~11GB
budget — and BSC publishes no official Ollama tag (community re-uploads only). **ALIA** (2B/7B/40B,
32K context, four times Salamandra's 8K) is **not on Ollama at all** and its MLX path is
unverified. This voids 02 §1's old escape hatch, which kept Salamandra-7B alive pending "a 4-bit
MLX quant that beats the Ollama estimate": that quant does not exist, so reaching it is a day of
hand-quantizing, not a flag.

(c) **02b's own §3 verdict was deliberately NOT merged.** It predates 02a and ranks Salamandra-2B
as "the highest-value single test to run" with Gemma 3 1B as a "highest-priority retest" —
generalizing 06's inverse-size *production* finding into a small-model-first selection rule. 02a
measures salamandra-2b-instruct at **+0.006** (chance) and the whole ≤1.7B tier at chance. The
merged shortlist follows 02a, and the quarantine is stated in 02 §1 by name so it cannot be
silently readopted.

(d) **SmolLM3-3B was a placeholder row and turns out to top its tier** — EsCoLA **+0.245**, above
Qwen2.5-3B-Instruct (0.214) and gemma-3-4b-it (0.190), Apache-2.0, with clean
`mlx-community/SmolLM3-3B-4bit` builds (Ollama community-only). Its base checkpoint is +0.089, so
instruction tuning is doing all of the work. It is now #1 on 02 §1's shortlist.

(e) **Several 2026 models asked about do not exist as searched for, and that is a finding.** There
is **no Qwen3.5/3.6** (the line is Qwen3.8; smallest confirmed dense text tier ~27–28B, out of
budget) and **no Phi-5** (only a 15B reasoning-vision successor, so Phi-4-mini 3.8B — MIT, the most
permissive license in the table — remains the newest small Phi). Llama 4 is Scout/Maverick only;
the meta-llama org page was checked directly and **nothing small is newer than Llama 3.2**. Gemma 4
(E2B/E4B/…) does exist with MLX builds but publishes no benchmarks and no confirmed license — the
one entry worth re-checking before a model is finalized. Net: **nothing released after Gemma 3 /
Qwen3 / Llama 3.2 is simultaneously small enough and packaged for this machine.**

**02b's closing paragraph is the third independent arrival at the same absence.** 02a found no
dialect-split benchmark across the entire La Leaderboard suite; 06 had to measure register by hand;
02b found none across every model card it fetched. Three tracks, three methods, same gap —
`eval/quality_probe.py` is the only instrument for the axis this product is built on.

**Caveat that travels with 02b:** its WebSearch budget was exhausted, so every fact came from
WebFetch of one specific page. Absence of a model from its table means *not checked*, not *doesn't
exist* — except where marked a confirmed absence in (e).

**Still open for synthesis:** #2 under real concurrent load, and 06's replacement risk: **register
and character-break enforcement.**

**Architecture + data model — WRITTEN in `08-architecture-data-model.md`.** Materializes 03 §(a)'s
pipeline as Python package seams and a four-thread model (audio / turn / assessment / writer), and
04 §8's five event schemas + 07 §8's `error_observation` as concrete SQLite DDL. Three calls worth
knowing without reading the file: (a) **the output guard validates at clause granularity** — clause
1 is checked before TTS and may trigger a regenerate (~0.2–0.3s, inside 03's budget); later clauses
can only *truncate* the turn, because you cannot un-speak audio. This is the only place the
architecture spends latency on quality, and it is 06's top risk. (b) **01 §8a-6 vs 04 §8.1 resolves
in favor of both** — v0 runs the flat weak-area lookup table, while `scheduler_state` carries
`fsrs_*: null`; the columns are free, the model is deferred. (c) Four tables the research implied
but never named: `profile_snapshot` (04 §8.3 logs a profile hash with nowhere to resolve it),
`item`/`item_alias` (04 §8.4's stability requirement made enforceable), and `audio_clip` (07's
`evidence_ref` needs provenance, not a bare path, for tier B/C re-scoring to work).
Slice 0 is five measurement gates, not code — including cross-track #2.

## Provenance notes

**Track 05's agent failed** the same way, but *before* writing anything — that first attempt was a
total loss, nothing recovered from disk or scratchpad. Relaunched 2026-09-12 with a narrowed brief
(`05-landscape-content.md`: landscape, offline content sourcing, OSS building blocks only) plus
hard context rules — no `.output` files, no sibling deliverables, write-to-disk-early. **The
relaunch succeeded**: 151 lines, all three sections, no architecture content (correctly out of
brief). The context rules are the reproducible part of that fix and should be standard for any
future wave. The dropped half (architecture proposal, data model, MVP scope, cross-track #4) moved
to synthesis in the main session, which has already read 01/03/04/06, and became 07 and 08.

**Track 02's agent failed** (same autocompact thrashing) at 435 lines, after writing all ten
sections including §9's recommended stack and §10's day-1 validation commands. What it lost was the
merge of its two feeder agents' results: §1's 2026-era model survey table and §2's quantitative
non-English degradation curves were left marked `TODO — sub-agent pending` in the file (both since
filled — no such marker remains). Recovery was
by appendix rather than a third relaunch of the whole track — `02a-quality-floor.md` (**landed,
427 lines, merged**: the surviving feeder was resumed and wrote its findings straight to disk, no
re-research needed) and `02b-model-survey.md` (a narrowed relaunch, since that feeder was lost with
its parent — **landed, 59 lines, merged**). 02a's recovery confirms the hard-context-rules countermeasure
generalizes beyond 05's relaunch: resuming a surviving feeder is cheaper than relaunching a track. **02's §9 recommendation and §10 command list stand
independently of both**, and 06's measured numbers already supersede 02 on latency, so nothing
downstream is blocked on the appendices — they refine model *choice*, not architecture.

**Track 03's agent failed** (autocompact thrashing) after writing its deliverable. The 337-line
file is complete *and* self-reconciled — its §preamble already carries the 1.5–3B correction from
06, so the failure cost only the agent's closing summary, not content. Cause was context overflow
from reading sibling research files; future waves get bounded briefs that forbid reading other
tracks' full deliverables.
