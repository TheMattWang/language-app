# 02 — Local SLM selection, serving, and performance budget on Apple Silicon

Target hardware: MacBook Air M3, 16GB unified memory, 10 GPU cores, fanless, ~142GB free
disk, fully offline. Companion to `06-bench-local-baseline.md` (measured Ollama numbers on
this exact machine) — that file supersedes this one wherever they'd otherwise conflict on
latency, because it is MEASURED and everything below on raw tok/s is largely ESTIMATED.

**Status: §1 and §2 are complete — no `TODO — sub-agent pending` sites remain anywhere in this
file.** §1's model survey landed as `02b-model-survey.md`, §2's quality floor as
`02a-quality-floor.md`; both are merged below and both appendices remain the source of record for
their own numbers. The `ESTIMATED` labels in §3/§5/§6 are still estimates and still want
measurement.

**Headline result up front, because it reframes every question below:** track 06 measured
that LLM decode latency is not the bottleneck for a 1.5–3B model (0.35–0.81s/turn) — the
binding constraint is **Peninsular-register controllability**, not speed or raw fluency.
All three models track 06 tested failed an explicit vosotros instruction. This means
Questions 1–2 below should be read as "which model is easiest to constrain and verify,"
not "which model is most fluent."

---

## 1. Model candidates

**Merged 2026-09-12 from `02b-model-survey.md`** (live HuggingFace model-card, org-page,
Ollama-library and mlx-community fetches). That appendix is the source of record for sizes,
licenses, context windows and packaging; §2 and §9's amendment — both from
`02a-quality-floor.md` — are the source of record for quality. Two caveats travel with the merge:

- **02b's coverage is narrower than a search would give.** Its WebSearch budget was exhausted, so
  every fact came from WebFetch of one specific page. Treat a model's absence from this table as
  *"not checked,"* not *"doesn't exist."*
- **02b's own §3 verdict predates 02a and is deliberately not reproduced here.** It ranked
  Salamandra-2B as "the highest-value single test to run" and Gemma 3 1B as "highest-priority
  retest," generalizing track 06's inverse-size register finding into a small-model-first
  selection rule. §2 blocks that inference: 06 measured *production*, EsCoLA measures *judgment*,
  and a model can be a fluent speaker while sitting at chance as a grader. The shortlist below
  follows §2/§9, not 02b §3.

**What all three tracks independently converged on:** no public benchmark isolates register or
dialect. 02a found none across the entire La Leaderboard suite, 02b found none across every model
card it fetched, and 06 had to measure it by hand. Three independent arrivals at the same absence —
`eval/quality_probe.py` is the only instrument that exists for the axis this product is built on.

### Candidate table

| Model | Params | License | Notes |
|---|---|---|---|
| Qwen2.5 (0.5B/1.5B/3B/7B) | various | Apache-2.0 | Already on Matt's machine via Ollama; measured in track 06. Strong multilingual instruct tuning, well-documented Spanish MMLU/Belebele scores from the Qwen2.5 technical report. |
| Qwen3 (0.6B/1.7B/4B/8B) | various | Apache-2.0 | Successor family; 4B config confirmed directly from HF (`Qwen/Qwen3-4B/config.json`): 36 layers, 32 query heads / 8 KV heads (GQA), head_dim 128, hidden_size 2560, bf16, max_position_embeddings 40960. Dense + MoE variants exist. **The 4B is disqualified for any parseable-output role** — Qwen3's thinking mode scores xquad_es f1 **0.0** (§2), and 06 measured an empty 4.1s turn from qwen3.5:2b that spent its whole budget reasoning. Sizes 0.6/1.7/4/8/14/30/32/235B; Ollama `qwen3:0.6b|1.7b|4b|8b` (40K ctx, 256K on some tags); MLX widely available; 32,768 native / 131,072 with YaRN. "100+ languages" is claimed but **no numeric multilingual score was found — UNVERIFIED**. |
| Gemma 3 (1B/4B/12B/27B) | various | Gemma license (custom, permissive-ish, has use restrictions — not OSI Apache/MIT) | 4B config confirmed via public mirror `unsloth/gemma-3-4b-it` (official Google repo is gated, returns HTTP 401 to unauthenticated fetches): 34 layers, 8 query heads / 4 KV heads, head_dim 256, hidden_size 2560, **hybrid local/global attention** — sliding_window 1024, sliding_window_pattern 6 (5 local layers : 1 global layer), max_position_embeddings 131072. This hybrid attention has a large, favorable effect on KV-cache memory (see §4). Sizes 270M/1B/4B/12B/27B; Ollama carries `gemma3:270m|1b|4b|12b|27b` plus **`-it-qat`** quantization-aware-training variants; MLX widely available; 32K ctx on 270M/1B, 128K on 4B+. Published multilingual numbers exist **only for the 27B** (Global-MMLU-Lite 75.1, WMT24++ 53.4) — nothing size-specific for 1B/4B. Quality per §2: gemma-3-4b-it EsCoLA +0.190 / TELEIA 66.7; gemma-3-1b-it at chance. |
| gemma2:2b | 2B | Gemma license | Already on Matt's machine; track 06's **best performer on Peninsular vocabulary retention** (held `coche`/`venga` against a LatAm-word pull) despite being the smallest non-trivial model tested. Ranking was inverse to parameter count on this axis. |
| llama3.2 (1B/3B) | 1B/3B | Llama 3.2 community license | Already on Matt's machine; measured in track 06. 3B leaked LatAm vocabulary (`estacionamiento`) and code-switched single English words mid-sentence. Llama 3.2 Community License (gated download, free under 700M MAU); Ollama `llama3.2:1b|3b`, 128K ctx; MLX widely available. **MMLU 5-shot, Spanish, 3B: 55.1%** (vs fr 54.6, pt 54.5, hi 43.3) — the only per-language number published for any model this size. EsCoLA +0.174 (§2): clears the floor, but only just. |
| BSC Salamandra (2B/7B/40B) | 2B/7B/40B, base + instruct | Apache-2.0 | Barcelona Supercomputing Center, EU-funded, explicitly multilingual-Iberian-focused. **8,192 ctx** on the 7b-instruct card — the shortest window of any candidate here. XStoryCloze 7b-instruct: es 68.17 / ca 70.75 / eu 62.14; PAWS ca 71.22, gl 61.50. **Packaging is the real obstacle:** no official BSC-LT Ollama tag (community ports only — `robbiemu/salamandra` covers all three sizes, plus `hdnh2006/`, `cas/`), and mlx-community carries **only `salamandra-7b-instruct-mlx-bf16` — no 4-bit or 8-bit build exists**, i.e. ~14GB against an 11GB budget. **The earlier "most promising Spanish-specific candidate" claim on this row is retracted:** §2 measures salamandra-2b-instruct at EsCoLA **+0.006** (chance, indistinguishable from the ≤1.7B tier) and salamandra-7b at **+0.215** (mid-field, well below gemma-2-9b-it's 0.345). Iberian training data did not buy grammaticality. It may still buy *register* — which nothing public measures — but that is now a `quality_probe.py` question, not a reason to rank it first. |
| BSC ALIA (2B/7B/40B) | 2B/7B/40B | Apache-2.0 | 32,768 ctx (4× Salamandra's), 9.37T tokens across 35 European languages + code. 5-shot Spanish: commonsense 79.5%, QA 73.4%, translation BLEU 25.9. `ALIA-40b-instruct-2601` scores EsCoLA **+0.393**, second-best on the entire La Leaderboard (§2) — but 40B is far out of budget, and the **2B/7B rows are individually UNVERIFIED** (only the 40b card was fetched). **Not found on Ollama at all; MLX availability unverified.** Ruled out by packaging, not by quality — which makes it the candidate most worth re-checking if a serving path appears. |
| Latxa (7B/13B/70B) | 7B/13B/70B | **Llama 2 license** (continued pretraining of Llama 2 on Basque) — *not* Apache-2.0, as an earlier draft of this row claimed | **Basque, not Spanish** — never a direct candidate. Its value here has inverted: it was listed as proof that region-specific fine-tuning improves fidelity, but §2 measures latxa-7b-v1.2 at EsCoLA **+0.013**, at chance on Spanish grammaticality, alongside bertin (−0.016), Aitana-6.3B (+0.020), FLOR-6.3B (+0.044) and aguila-7b (+0.062). Basque-targeted pretraining did not transfer to Spanish, and the wider pattern is that **a recent general multilingual model beats an older Spanish-specific one.** Latxa is now evidence *against* the regional-finetune hypothesis, not for it. Own-language scores, for completeness: 7B avg 40.94, 70B avg 61.08. |
| Ministral 3B / 8B / 14B (`2512` tags) | 3B/8B/14B | **Mistral Research License — non-commercial by default**, commercial use on request. **Not Apache-2.0**; an earlier draft of this row said Apache and was wrong. | 128K ctx, interleaved sliding-window attention. Carries the **best Spanish number of any small model surveyed: Spanish MMLU 59.6 vs Llama 3.1 8B's 54.6** (Mistral's own comparison, so read it as a vendor claim). Packaging is good — Ollama 3b/8b/14b tags, and `mlx-community/Ministral-3-{3B,8B}-Instruct-2512-{4,5,6,8}bit` all confirmed. **Disqualified on license, not on capability.** Worth revisiting only if this stays a personal, non-commercial tool. Mistral Small 24B (2501, Apache-2.0, 32K) is out of budget. |
| Phi-4-mini | 3.8B | **MIT** — the most permissive license in this table | 128K ctx; Ollama `phi4-mini` / `phi4-mini:3.8b`, **requires Ollama ≥0.5.13**; MLX build UNVERIFIED (high confidence it exists, not confirmed). Supports 22 languages including Spanish but publishes **no Spanish-specific number** — only aggregates: Multilingual MMLU 49.3 (5-shot), MGSM 63.9 (0-shot CoT). The English-optimized prior stands unrefuted, so: **fallback only.** No Phi-4-mini successor ≤8B exists as of 2026-09-12 (the only successor found is `Phi-4-reasoning-vision-15B`, out of budget and a reasoning variant besides). |
| Gemma 4 (E2B/E4B/12B/26B-A4B/31B) | E2B ≈ 5B, E4B ≈ 8B | **UNVERIFIED** | Exists as of 2026-09. `mlx-community/gemma-4-e2b-it-4bit` and `-5bit` **confirmed to exist**; **not on Ollama**; **no benchmarks published and the license not confirmed.** Too new to recommend, concrete enough to re-check before any model is finalized. |
| Checked-for and absent at this size: Qwen3.8, Llama 4, Phi-4 successors | — | — | **Confirmed absences, not search failures.** Qwen3.8's smallest confirmed dense text tier is ~27–28B (plus a 180B "Flash-Next" MoE) — out of budget, license unverified. Llama 4 is Scout/Maverick only (17B active, 109–400B total); the meta-llama org page was checked directly and there is **no small Llama newer than 3.2**. Phi's only successor is the 15B reasoning-vision model. **Nothing released after Gemma 3 / Qwen3 / Llama 3.2 is simultaneously small enough and packaged for this machine.** |
| SmolLM3-3B | 3B | Apache-2.0 | 64K trained / 128K with YaRN; natively trained on 6 languages including Spanish. **EsCoLA +0.245 — the top of the entire 3–4B instruct tier** (§2), above Qwen2.5-3B-Instruct's 0.214 and gemma-3-4b-it's 0.190; its own base checkpoint is +0.089, so instruction tuning is doing all the work. Its *published* numbers are unremarkable by comparison and are base-model only (Global MMLU 38.51, Belebele 47.00, Flores-200 5-shot 48.25) — the EsCoLA result is the one that matters. Packaging is the cost: **no official HuggingFaceTB Ollama tag**, community ports only (`alibayram/smollm3` at 87.8K pulls is the most-used; also `Impulse2000/`, `pedrolucas/`), though `mlx-community/SmolLM3-3B-{3,4,5,6,8}bit` plus a `-4bit-DWQ` are all confirmed. **Promoted from TODO row to first-class candidate by this merge** — it was a placeholder, and it turns out to top its tier. |

### Ranked shortlist for this app (16GB M3 Air, Peninsular-Spanish conversational partner)

**Rewritten 2026-09-12 to agree with §2 and §9's amendment.** The earlier version of this list
ranked Salamandra-smallest at #2 and Qwen3-4B at #2b; §2 kills both — salamandra-2b-instruct is at
chance on EsCoLA (+0.006) and Qwen3's thinking mode collapses on structured output (xquad_es f1
0.0). Three constraints now bound the list jointly: **latency** (06: 7B+ is ~2s/turn, marginal),
**the quality floor** (§2: nothing ≤1.7B is above chance; the floor is instruction-tuned 3–4B), and
**packaging** (02b: several otherwise-good models have no quantized build for this machine). The
survivors are the 3–4B instruct tier.

1. **SmolLM3-3B** — tops the 3–4B tier on EsCoLA (+0.245) and is Apache-2.0. Cost: Ollama has
   community ports only (`alibayram/smollm3`), though `mlx-community/SmolLM3-3B-4bit` is clean. The
   biggest *change* this merge makes to the shortlist.
2. **gemma-3-4b-it** (or `-it-qat`) — EsCoLA +0.190, TELEIA 66.7, official Ollama tag including
   QAT variants, MLX widely available. The best-packaged candidate that clears the floor, and the
   one §9's amendment names.
3. **Qwen2.5-3B-Instruct** — EsCoLA +0.214, Apache-2.0, well-trodden. §9's second named pick.
   Prefer Q8 where it exists: §2 found int8 costs nothing on Spanish.
4. **gemma2:2b** — **incumbent, and only in the speaker role.** 06's best measured Peninsular
   vocabulary retention, and +0.166 is the first non-trivial point on the EsCoLA curve — but still
   below the 3–4B floor. Keep it as the conversational engine and the baseline to beat; never
   promote it to `scoring/slm_grader.py`.
5. **llama3.2:3b** — EsCoLA +0.174 clears the floor, and it is the only model at this size with a
   published Spanish-specific number (MMLU-es 55.1). But 06 measured it leaking `estacionamiento`
   and code-switching English mid-sentence. Comparison point, not a first choice.
6. **salamandra-7b-instruct** — stretch test only, and an expensive one: ~2s/turn extrapolated,
   8K context, **and no quantized MLX build exists** (see below). Worth running through
   `quality_probe.py` if it can be served at all, because register is the one axis no public
   benchmark covers — but its EsCoLA +0.215 says the Iberian training data did not buy
   grammaticality, so this is a genuine gamble rather than the sure thing the earlier draft implied.

**Dropped outright:** qwen2.5:1.5b (06's worst character break — dropped persona and offered to
tutor in English — and §2 puts the whole ≤1.7B tier at chance, so its 0.35s/turn buys nothing);
Qwen3-4B (reasoning-mode structured-output collapse); Ministral 3B/8B (non-commercial license,
despite the best Spanish MMLU in the survey at 59.6); ALIA (no Ollama or MLX path found); Latxa
(Basque); Gemma 4 and Qwen3.8 (too new / too large).

**On the 7B escape hatch, which has closed.** The earlier version of this paragraph held 7B-class
models open "unless a 4-bit quant on MLX substantially beats the ~12–15 tok/s Ollama estimate." For
Salamandra specifically **that quant does not exist** — mlx-community carries only
`salamandra-7b-instruct-mlx-bf16`, roughly 14GB against an ~11GB budget. Reaching it now means
quantizing by hand or trusting a community Ollama re-upload. That is a day of work, not a flag,
and it should be spent only after the 3–4B tier has been measured on `quality_probe.py`.

---

## 2. The quality floor question

Track 06's empirical answer, which should be treated as more authoritative than any
literature-based estimate below: **raw fluency is not the limiting factor even at 1.5-2B;
instruction-controllability of register is.** Concretely:

- All three tested models (1.5B, 2B, 3B) could produce grammatically fluent Spanish.
- All three tested models **failed** to reliably produce vosotros forms under explicit
  instruction + explicit in-context cue.
- Peninsular-register fidelity did not scale with parameter count (2B beat 3B).
- The failure mode that matters most for the product (character breaks / English exits)
  also did not scale cleanly with size — it appeared in every tested model, in different
  forms (full persona drop, parenthetical translation, single-word code-switch).

**Reframed quality-floor question:** it is not "is model X fluent enough in Spanish" — at
1.5B and up, all tested models clear a fluency floor. It is "can model X's output be
reliably constrained or verified externally," because none of them can be trusted as an
unsupervised source of register-correct Spanish. This directly motivates §6/§8's emphasis
on a post-generation validator over relying on a bigger or "more Spanish-fluent" model.

**Now quantified by `02a-quality-floor.md`** (69-model La Leaderboard mining, 2026-09-12).
The headline is sharper and more uncomfortable than the ESTIMATED text this replaces:

> **~1.5B is below the floor. The floor is instruction-tuned 3–4B. The comfort zone is 7–9B.**

All 17 La Leaderboard models at ≤1.7B score **at chance** on EsCoLA (Spanish grammatical
acceptability, scored by MCC; range −0.042 to +0.079). Not "degraded" — at chance. There is
no partial-credit regime below 2B. gemma-2-2b-it (+0.166) is the first non-trivial score
anywhere on the curve; the 3–4B instruct tier lands at +0.17 to +0.25 (SmolLM3-3B 0.245,
Qwen2.5-3B-Instruct 0.214, gemma-3-4b-it 0.190, Llama-3.2-3B-Instruct 0.174); 6–9B reaches
+0.24 to +0.35 (gemma-2-9b-it 0.345).

**Reconciling 02a with 06 — they do not conflict, they measure different things.** EsCoLA is
a *metalinguistic judgment* task (is this sentence grammatical?); 06 measured *production*.
A 1.5B model can emit fluent Spanish while being unable to judge Spanish. Both findings are
true simultaneously, and together they say something the architecture already assumed:
**a small model is a speaker, not a grader.** This is direct empirical backing for 07's
decision to put `gram.*` observations in reliability tier C (logged, never asserted to the
learner) and for 08's external-validator-over-bigger-model stance in `guard/`. If anything
02a strengthens it: below ~2B the grammaticality signal is not weak, it is absent, so an SLM
grader at that size is not a noisy oracle but a coin flip.

**Where 02a does move the model choice:** its rule 1 is **≥3B and instruction-tuned** — a 3B
*base* checkpoint is not a substitute for a 3B *instruct* one (Qwen2.5-3B 0.028 → Instruct
0.214; Llama-3.2-3B 0.057 → Instruct 0.174; SmolLM3 0.089 → 0.245). 06's latency numbers
keep this affordable: llama3.2:3b measured 0.81s/turn, comfortably inside 03's budget. The
1.5B tier should be treated as a latency-floor reference point, not a shippable candidate.

**Quantization, Spanish-specific:** the single best Spanish-grammaticality model on the whole
leaderboard is an **8-bit** quant (Qwen2.5-14B-Instruct-GPTQ-Int8, MCC 0.456) beating the
fp16 field, while a 4-bit bnb reasoning-distill of the same size sits at −0.029. Corroborated
by Tiny Aya's 70-language measurement (Q8_0 negligible degradation; Q4_K_M −1.4, Q4_0 −2.1
points). **Practical rule: Q8/Int8 is effectively free for Spanish; 4-bit is a real risk
below ~7B.** Combined with #2's RAM resolution (~6–7GB freed by dropping the resident-7B
assumption), a 3–4B at Q8 (~3.5–4.5GB) fits — so the quantization rule and the RAM budget do
not collide, but Q4 is no longer the automatic default it looked like.

**Two caveats that matter more than the numbers:**
- **Avoid reasoning/thinking-mode variants entirely.** 02a §6a found Qwen3 thinking mode
  produces `xquad_es` f1 of **0.0** — structured-output collapse, Spanish-specific. 06 saw
  the same failure from the latency side (qwen3.5:2b spent its whole budget thinking and
  returned empty). Two independent methods, one conclusion: disqualified by construction.
- **Prefer a recent general multilingual model over an older Spanish-specific one.** bertin
  (−0.016), latxa-7b-v1.2 (+0.013), Aitana-6.3B (+0.020), FLOR-6.3B (+0.044), aguila-7b
  (+0.062) are all **still at chance at 6–7B** — built on weak bases (GPT-J, BLOOM). This
  retires the intuition that a Spanish-labelled model is the safer pick. Salamandra is the
  live exception to check (2b at +0.019/+0.006 is at chance; 7b at +0.215 clears), so §10
  command 4 should target the 7B, not the 2B.

**The dialect/register gap is confirmed, not merely unfound.** 02a §7 checked the entire La
Leaderboard suite (EsCoLA, TELEIA, xquad_es, belebele_spa_Latn, copa_es, openbookqa_es,
paws_es, xnli_es, xstorycloze_es, spalawex, wnli_es) — **none is dialect-split**, and the
leaderboard stratifies by the co-official *languages of Spain*, not Peninsular-vs-LatAm
varieties of Spanish. Several of its corpora (EsCoLA, TELEIA, spalawex) are Peninsular in
origin, which if anything means its "Spanish" scores *skew* Peninsular. Register
consistency (tú/usted across a multi-turn conversation) is measured by no public benchmark
found. 02a's own recommendation — "if the app targets a specific dialect, this must be
settled by a hand-built eval of a few dozen prompts probing voseo, vosotros, and tú/usted
consistency" — is a description of `eval/quality_probe.py`, which already exists and already
runs. **That probe is not a nice-to-have; it is the only instrument that exists for the axis
this product is built on.**

One honest limit on the degradation curves: the most quotable quantization paper (arXiv
2608.09941, 2B Δ=5.76% vs 4B Δ=4.10%) **does not test Spanish** — its languages are EN, ZH,
RU, JA, AR, HI, SW, YO. It supports "quantization hurts smaller models more in non-English"
and nothing narrower. Similarly Tiny Aya does not break Spanish out. The Spanish-specific
quantization evidence is §5e's leaderboard observation, which is real but is a single
datapoint, not a curve.
---

## 3. Serving: MLX vs alternatives on base M3

**Important machine-state fact:** MLX is **not currently installed** on this machine.
Ollama is. Track 06's numbers are all Ollama/llama.cpp-Metal-backend numbers. This makes
"should we switch to MLX" a real, unresolved decision, not a settled one — see day-1
benchmarks (§9).

### Bandwidth-bound arithmetic (why the numbers look like they do)

Base M3 unified memory bandwidth is **~100GB/s (102.4GB/s nominal)** — identical for the
8-core and 10-core GPU SKUs; this is dramatically less than M3 Pro (153.6GB/s), M3 Max
(300-409.6GB/s), or M3 Ultra (819.3GB/s), so benchmarks run on those chips (which dominate
published MLX/llama.cpp benchmarks) are not directly transferable.

Decode is memory-bandwidth-bound for these model sizes:

```
decode_tok_s ≈ (bandwidth_bytes_per_sec × utilization) / bytes_moved_per_token
bytes_moved_per_token ≈ model_size_bytes (weights re-read once per generated token)
```

At ~100GB/s and a realistic 60-85% effective utilization (range spans llama.cpp/Metal
lower-tuned kernels to well-tuned MLX kernels — ESTIMATED, not independently re-verified
this session), a Q4 model's decode speed roughly follows `tok_s ≈ 60-85 GB/s ÷ model_bytes`.
Track 06's measured numbers are consistent with this: model size vs. measured decode tok/s
scales in the expected direction with no anomalies, which is why extrapolating to
untested sizes (e.g. 7-8B) is reasonable.

| Model class | ~4-bit size | Bandwidth-bound decode estimate | Track 06 measured (Ollama, default quant) |
|---|---|---|---|
| 0.5B | ~0.35GB | 170-285 tok/s | qwen2.5:0.5b: **152.3 tok/s** (measured) |
| 1.5-1.7B | ~1.0GB | 60-85 tok/s | qwen2.5:1.5b: **77.9 tok/s** (measured) |
| 2B | ~1.6GB | 37-53 tok/s | gemma2:2b: **36.9 tok/s** (measured) |
| 3B | ~2.0GB | 30-42 tok/s | llama3.2:3b: **30.2 tok/s** (measured) |
| 4B (Qwen3-4B/Gemma3-4B) | ~2.3-3.0GB | 20-37 tok/s | not yet tested — **day-1 priority** |
| 7-8B | ~4.5-5GB | 12-19 tok/s | not tested; track 06 extrapolates ~12-15 tok/s |

The measured numbers sit at the low-to-mid end of the estimated bandwidth-bound range,
implying Ollama's llama.cpp/Metal backend is running at roughly 60-70% effective
utilization on this chip — leaving some headroom that a well-tuned MLX kernel could
plausibly capture, but this is unverified (see §9).

### Runtime comparison

| Runtime | Status on this machine | Notes |
|---|---|---|
| Ollama | **Installed, measured** | llama.cpp/Metal backend under the hood; easy model pulls; what track 06 used. |
| mlx-lm | Not installed | Apple's native framework; `mlx_lm.generate`/`mlx_lm.server`; generally reported faster prefill and sometimes decode vs. llama.cpp on Apple Silicon in community benchmarks, but nearly all published head-to-heads are on M1/M2/M3 Pro/Max/Ultra or M4/M5, **not base M3** — so the magnitude of any advantage here is unverified. mlx-lm 0.31.3 is current (as of this research). |
| llama.cpp (bare, not via Ollama) | Not installed | Same backend as Ollama's engine; unlikely to meaningfully outperform Ollama's numbers since Ollama is a thin wrapper around it. |
| LM Studio | Not installed | GUI wrapper, can run both llama.cpp and MLX backends; convenience layer, not a distinct performance story. |
| MLC | Not installed | Less commonly benchmarked on Apple Silicon lately; lower priority to test. |

**Practical implication:** since track 06 already shows the LLM is not the bottleneck at
1.5-3B, chasing an MLX speed win is now a **low-priority** question per that file's own
conclusion — the exception is if a 4B or Salamandra-7B candidate looks attractive on
quality/register grounds but is borderline on latency, in which case MLX's usually-better
utilization could be the difference between viable and not. Test this specifically for the
4B tier (§9), not for the already-fast 1.5-3B tier.

---

## 4. Memory budget (16GB total)

### KV-cache-per-token math (exact, from confirmed architecture configs)

Formula: `bytes_per_token = 2 (K+V) × num_layers × num_kv_heads × head_dim × bytes_per_element`

**Qwen3-4B** (36 layers, 8 KV heads, head_dim 128, full/global attention throughout):
`2 × 36 × 8 × 128 × 2 bytes (fp16) = 147,456 bytes/token ≈ 144 KiB/token`

| Context | KV cache size (fp16) |
|---|---|
| 2,048 tokens | ~288 MB |
| 8,192 tokens | ~1.13 GB |
| 32,768 tokens | ~4.5 GB |

Grows **linearly and without bound** with context — at long context this dominates memory
regardless of weight quantization.

**Gemma3-4B** (34 layers, 4 KV heads, head_dim 256, hybrid attention: sliding_window=1024,
pattern=6 → ~6 global layers, ~28 local/sliding layers):

Per-layer per-token cost: `2 × 4 × 256 × 2 bytes = 4,096 bytes/token/layer` (same formula,
smaller per-layer footprint than Qwen3-4B despite larger head_dim, because of fewer KV
heads: 4 vs 8).

- **Global layers** (~6): cache grows linearly with context, uncapped, same as Qwen3-4B's
  layers: `6 × 4,096 × context_tokens`.
- **Local/sliding layers** (~28): cache is **capped at the 1024-token window** regardless
  of how long the conversation gets: `28 × 4,096 × 1024 ≈ 112 MB`, constant once
  context > 1024 tokens.

| Context | Global-layer cache | Local-layer cache (capped) | **Total** |
|---|---|---|---|
| 2,048 tokens | ~48 MB | ~112 MB | **~160 MB** |
| 8,192 tokens | ~192 MB | ~112 MB | **~304 MB** |
| 32,768 tokens | ~768 MB | ~112 MB | **~880 MB** |

**This is the single most useful memory finding in this report:** at any context length a
real conversation would use, Gemma3-4B's KV cache is roughly **5x smaller** than Qwen3-4B's
(880MB vs 4.5GB at 32K context) purely from the hybrid attention pattern, independent of
weight quantization choice. For a 16GB machine running ASR+TTS concurrently, this matters
more than the ~10-15% weight-size difference between the two models. (Caveat: Gemma3-4B
numbers sourced from a public non-gated mirror, `unsloth/gemma-3-4b-it`, since Google's
official repo returns HTTP 401 to unauthenticated fetches — treated as reliable since it's
self-consistent with known Gemma 3 architecture facts, but flagged as third-party.)

### Full-stack budget table (ESTIMATED except where noted)

| Component | Estimated size | Notes |
|---|---|---|
| macOS + background processes | ~3.5-5 GB | ESTIMATE; WindowServer, kernel, daemons on a 16GB M-series Mac typically leave 11-12GB free at idle. Not independently measured this session. |
| App overhead (audio I/O, UI, orchestration) | ~0.5-1 GB | ESTIMATE. |
| ASR model (resident) | ~0.15-1.5 GB | Depends on Whisper tier: base ~150MB, small ~500MB, medium ~1.5GB (owned by track 03, not verified here). |
| TTS model (resident) | ~0.1-1 GB | Depends on engine choice (owned by track 03). |
| **LLM weights (4-bit)** | 1.0-3.0 GB | See §1/§3 table by model. |
| **KV cache** | 0.16-4.5 GB | See table above — highly dependent on model choice and context length. |
| LoRA training buffer | not concurrent | Training (per `04-rl-adaptation.md`'s track) is presumably a separate offline mode, not running during live conversation — treat as 0 for the live-conversation budget. |

**Headroom check:** 16GB total, ~4-6GB macOS+app overhead, ~0.5-2GB ASR+TTS →
**~8-11GB available for LLM weights + KV cache.** Every candidate in the shortlist (§1) at
4-bit fits comfortably even at long context, **except** Qwen3-4B pushed to 32K context
(2.3-3GB weights + 4.5GB KV ≈ 7-8GB — still fits, but tight if ASR/TTS run larger models
concurrently). Gemma3-4B's much smaller KV-cache growth makes it the safer long-context
choice memory-wise even though the two models are similar in weight size.

---

## 5. Thermals and battery (fanless M3 Air)

`Largely ESTIMATED — WebSearch quota for this session is fully exhausted (200/200 used),
so no primary source on M3-specific sustained-inference thermal behavior could be
retrieved this session.` One hard fact was confirmed via WebFetch of Apple's current specs
page (`apple.com/macbook-air/specs/`): **13-inch MacBook Air battery capacity is 53.8Wh**
(15-inch is 66.5Wh); Matt's exact screen size isn't stated in the repo, so 53.8Wh (13")
is assumed as the more common config — flag this if precise per-hour battery math matters.

- **Throttling behavior (ESTIMATED, based on general fanless-M-series behavior, not
  M3-Air-specific measurement):** fanless Apple Silicon laptops sustain full clock speed
  for short bursts, then thermally throttle GPU/CPU clocks under **sustained** load
  (minutes, not seconds) as the chassis heats up. For a 1.5-4B model doing short bursty
  decode (0.3-0.8s per turn per track 06, with idle time between turns for the user to
  speak/listen), sustained thermal saturation is less likely than for a continuous
  batch-inference workload — but a 20+ minute unbroken conversation session with ASR+LLM+TTS
  all resident and active is untested and could behave differently. This is explicitly
  named in `06-bench-local-baseline.md` §4 as untested.
- **Mitigation strategies (best-practice, not M3-specific measurement):**
  - Keep decode bursts short (favors the 1.5-3B tier, which already finishes a turn in
    under 1 second — less continuous thermal load than a 7B model's ~2s/turn).
  - Avoid keeping the model "hot" with speculative background pre-generation; let it idle
    between turns.
  - If a session runs long, consider periodic small idle gaps (natural in a conversation
    app, since the user is also speaking).
- **Battery drain (ESTIMATE only, no measured figure available this session):** a rough
  order-of-magnitude approach — if GPU inference draws roughly an incremental 5-10W above
  idle during active decode bursts, and decode is active maybe 10-20% of a real
  conversation's wall-clock time (rest is user speech + TTS playback + think time), average
  incremental draw might be ~1-2W, i.e. **roughly 25-50+ hours of LLM-only battery life
  contribution** at that duty cycle — swamped in practice by ASR/TTS/screen/mic draw, which
  are almost certainly the larger battery cost. This is a rough estimate, not a measurement,
  and should be replaced by an actual `powermetrics`-based reading (see §9).

---

## 6. Quantization quality (MLX formats, Spanish-specific risk)

*(Carried over from the completed quantization/structured-output research agent this
track already ran — `a777da3b97f770448`.)*

- `mlx_lm.convert` supports four `--q-mode` options: **affine** (standard, most common),
  **mxfp4**, **nvfp4**, **mxfp8** — plus a `--quant-predicate` mechanism for mixed-precision
  recipes (e.g. keep embedding/lm_head layers higher-precision, quantize the rest more
  aggressively).
- Learned-quantization CLIs exist for better quality-per-bit: **DWQ, AWQ, GPTQ, Dynamic
  Quantization** — these generally beat naive affine quantization at the same bit-width.
- **Known limitation:** mlx-lm cannot cleanly import externally pre-quantized AutoAWQ/GPTQ
  HuggingFace checkpoints directly (tracked as `ml-explore/mlx-lm#727`) — quantizing
  in-framework via `mlx_lm.convert` is the reliable path.
- **Non-English quantization degradation is a documented phenomenon** in the literature —
  studied concretely for Japanese, Bengali, Malayalam, and other non-Latin-script/
  lower-resource languages, where 4-bit quantization measurably degrades quality more than
  for English at the same bit-width. **Spanish-specific quantization degradation is a total
  literature gap** — no paper found studying this for Spanish specifically. Any Spanish
  quantization-degradation claim in this report should be treated as **EXTRAPOLATED**, not
  measured or cited.
- **Interpretability-guided quantization is a genuine open research seam** (ties directly
  to Matt's personal interp/topology track, `lab/04-interp-guided-quant`): using
  interpretability signals (e.g., which weights/directions carry register-distinguishing
  information — vosotros conjugation, Peninsular lexical choices) to guide a
  mixed-precision quantization recipe that preserves register fidelity preferentially over
  generic fluency, is not something we found prior art for. Given this track's finding that
  register is the actual bottleneck (not fluency), this is a more promising angle than
  generic quantization-quality work: **the paper here would be "does interp-guided
  mixed-precision quantization preserve dialectal/register control better than uniform
  quantization" — untested, unclaimed in the literature we surveyed.**

**Given §2's reframing, quantization quality is probably a second-order concern relative
to the constrain-and-verify architecture** — a validator can catch and regenerate a
register failure regardless of whether it was caused by quantization or by the base model's
limits. Still worth testing empirically (§9) since it's cheap to check.

---

## 7. Speculative decoding / draft models on MLX

*(Carried over from completed research agents `a777da3b97f770448` / `ac44c73c602d42a87`.)*

- mlx-lm's server supports `--draft-model` / `--num-draft-tokens` flags for speculative
  decoding today.
- Native **MTP (Multi-Token Prediction)** support is landing for Qwen3.5/3.6-class models
  via `ml-explore/mlx-lm` PR #990. (Caveat added post-`02b`: **no Qwen3.5 or Qwen3.6 release
  was found** — the 2026 line is Qwen3.8, smallest dense text tier ~27–28B. Read this as an
  upstream-roadmap note, not as a model that can be served on this machine.)
- **Measured Apple Silicon speculative-decoding gains are modest** — 1.03-1.6x, sometimes
  a regression — never the large (2-3x+) speedups seen on CUDA/datacenter GPUs. This is
  architecturally expected: speculative decoding helps most when compute is the bottleneck
  and verification is cheap relative to a full forward pass; on a bandwidth-bound
  unified-memory chip, the draft model's own memory traffic eats into the savings.
- **Given track 06's finding that latency is not the bottleneck at 1.5-3B**, speculative
  decoding is **not a priority** for this app at the model sizes actually being considered.
  It could matter if Salamandra-7B or another 7B-class model turns out to be the only
  register-faithful option and needs a latency assist — worth revisiting only in that
  scenario, with a small model (e.g. Qwen2.5-0.5B or Qwen3-0.6B) as the draft model.

---

## 8. Structured output (JSON / grammar-constrained generation)

*(Carried over from completed research agent `a777da3b97f770448`.)*

- **mlx-lm's native extension point is `logits_processors`** — a hook for masking/biasing
  token logits at each decode step, which is how constrained decoding is implemented on
  MLX.
- **Outlines has an official MLX backend** (`pip install outlines[mlxlm]`) — this is the
  most turnkey path to grammar/JSON-schema-constrained generation on this stack today.
- **llama.cpp's GBNF grammars and XGrammar have no MLX integration** — those are
  llama.cpp/CUDA-ecosystem tools; not usable if the project moves to mlx-lm.
- **"The Constraint Tax" (arXiv 2605.26128)** — found in this track's research — documents
  that constrained decoding measurably costs small models accuracy (they perform worse
  under a hard grammar/schema constraint than generating freely and being validated after
  the fact). This is directly relevant to two things this app needs structured output for:
  (a) any structured grading/feedback JSON, and (b) the register-validator idea from §2/§6.

**Given §2's finding, the practical structured-output architecture recommendation is:**
generate freely (cheaper, better quality per the Constraint Tax finding), then validate
and regenerate on failure — exactly the pattern track 06 recommends for register
enforcement. This gets two problems (grading-JSON reliability and register fidelity) from
one mechanism:

1. Generate the conversational turn or the grading JSON with **no hard grammar constraint**.
2. Run a **cheap external validator** (regex-based, per track 06 §3: check for vosotros
   forms, LatAm lexical items like `carro`/`estacionamiento`/`agarrar`/`computadora`/`jugo`/
   `papa`, English tokens, parenthetical translations; for JSON output, a plain
   `json.loads` parse-and-schema-check) against the raw output.
3. **Regenerate on failure**, up to 1-2 retries — track 06 measured 0.35-0.81s/turn, so
   there is ample latency headroom (target ~1.5-2.0s end-to-end per track 06 §3) to afford
   one or two retries and stay conversational.
4. Fall back to Outlines' MLX-backend hard-constraint mode only if regeneration
   repeatedly fails (a safety net, not the primary mechanism) — this avoids paying the
   Constraint Tax on every turn.

---

## 9. Recommended stack

**Primary model (pending §1 verification and a `quality_probe.py` run):** BSC Salamandra
(smallest available instruct variant) if it passes the register probes and clears a
latency bar; otherwise **gemma2:2b** as the currently-validated best-register fallback,
or **Qwen3-4B** if a larger model is wanted for reasoning/grading-JSON quality and the
memory/latency budget allows (§3/§4 support this at 16GB).

**Fallback model:** gemma2:2b (already validated, cheap, fastest reasonable register
performance measured so far).

**Serving runtime:** keep Ollama for now — track 06 already shows the LLM isn't the
bottleneck, so an MLX migration is a nice-to-have, not urgent. Worth testing MLX
specifically at the 4B tier where a utilization edge could matter more (see benchmarks
below).

**Architecture:** free generation + external regex/schema validator + regenerate-on-failure
(§8), not grammar-constrained decoding as the primary mechanism. Content (vocabulary,
scenarios, menus) should be sourced/templated per track 06, not model-generated.

**Amendment after `02a-quality-floor.md` landed (2026-09-12).** Two of the picks above need
qualifying, and one is now wrong:

- **"BSC Salamandra, smallest available instruct variant" is wrong as written.**
  salamandra-2b-instruct scores **+0.006** on EsCoLA — at chance, indistinguishable from the
  ≤1.7B tier. salamandra-7b reaches **+0.215**. If Salamandra is tested at all, test the 7B;
  the 2B is not a candidate. (06 hasn't measured a 7B's latency, and 06's own extrapolation
  puts 7B near ~2s/turn — so this is a real trade, not a free upgrade.)
- **gemma2:2b survives as the fallback, but only in the speaker role.** Its +0.166 is the
  first non-trivial EsCoLA score on the curve and it was 06's best measured Peninsular
  register performer — but it is still below the 3–4B instruct floor. Keep it as the
  conversational engine; do not promote it to `scoring/slm_grader.py`.
- **Qwen3-4B is disqualified, not merely deprioritized.** §2's reasoning/thinking-mode
  finding (xquad_es f1 0.0; 06's empty 4.1s turn) kills it for any parseable-output role.
  The 4B slot should be **gemma-3-4b-it** (EsCoLA 0.190, TELEIA 66.7) or
  **Qwen2.5-3B-Instruct** (0.214) instead.

Net: the §10 candidate list to actually pull is **gemma-3-4b-it** and **Qwen2.5-3B-Instruct**
at Q8 where available, with gemma2:2b as the incumbent to beat and salamandra-7b as the
stretch test. Nothing here changes the architecture — §8's validator-plus-regenerate stands
regardless of which model wins.

---

## 10. Day-1 validation benchmarks Matt should run himself

```bash
# 1. Pull the two flagship 4B candidates for direct comparison against track 06's data
ollama pull qwen3:4b
ollama pull gemma3:4b

# 2. Run them through the same latency harness track 06 used (adjust path to the scratchpad script)
python3 bench/llm_bench.py --models qwen3:4b gemma3:4b --num-predict 60 --num-ctx 2048

# 3. Run them through the register/quality probes — this is the gate that actually matters
python3 bench/quality_probe.py --models qwen3:4b gemma3:4b --probes vosotros l2_errors breakdown es_LA_trap recovery

# 4. Pull and test BSC Salamandra if a size fits the RAM budget
ollama pull salamandra:7b-instruct   # exact tag TBD pending §1 verification; check `ollama search salamandra`
python3 bench/quality_probe.py --models salamandra:7b-instruct

# 5. Install mlx-lm and compare decode tok/s directly against Ollama at the 4B tier,
#    to see whether MLX's typically-better utilization is worth migrating for
pip install mlx-lm
mlx_lm.generate --model mlx-community/Qwen3-4B-4bit --max-tokens 200 --prompt "Escribe una conversación en un bar de tapas."
# time it and compute tok/s manually if mlx_lm doesn't print it

# 6. Actual thermal/battery measurement instead of estimating (§5's numbers are unverified)
sudo powermetrics --samplers cpu_power,gpu_power -i 1000 -n 60 &
# ...run a 5-10 minute continuous conversation loop concurrently, then inspect the log

# 7. Check whether Outlines' MLX backend adds meaningful latency for JSON grading output
pip install "outlines[mlxlm]"
# construct a small JSON-schema-constrained generation test and compare wall-time to
# free generation + json.loads validation
```

---

## Open items / what's still pending in this file

- ~~§1: full model survey table (general multilingual + Spanish-specific/EU)~~ — **CLOSED**
  by `02b-model-survey.md`, merged into §1's candidate table and shortlist above. Two of the
  2026-era release claims this bullet asked about **do not exist as searched for**, and that
  is a finding, not an unfinished errand: there is no **Qwen3.5 or Qwen3.6** (the 2026 line is
  **Qwen3.8**, whose smallest confirmed dense text tier is ~27–28B — out of budget) and no
  **Phi-5** (Phi's only successor is a 15B reasoning-vision model, so Phi-4-mini 3.8B remains
  the newest small Phi). **Llama 4** is Scout/Maverick only; the meta-llama org page was
  checked directly and nothing small is newer than Llama 3.2. The rest resolved: **Ministral
  3** exists (3B/8B/14B, 2512 tags) but is **non-commercial by default**; **SmolLM3-3B**'s
  Spanish number came from EsCoLA rather than its model card (+0.245, top of its tier);
  **BSC ALIA** exists at 2B/7B/40B with 32K context but has no Ollama path and unverified
  MLX; **Latxa** is Llama-2-licensed, not Apache-2.0, and scores at chance on EsCoLA.
  **Gemma 4** (E2B/E4B/…) exists with MLX builds but no published benchmarks and no
  confirmed license — the one entry worth re-checking before a model is finalized.
  Residual gap 02b itself flags: its WebSearch budget was exhausted, so every fact came from
  WebFetch of one specific page — absence of a model from the table means *not checked*,
  not *doesn't exist*, except where marked a confirmed absence above.
- ~~§2: quantitative non-English-vs-English degradation curves~~ — **CLOSED** by
  `02a-quality-floor.md` (427 lines, 69-model La Leaderboard mining), merged into §2 and
  §9 above. Residual gaps 02a itself flags: no dialect-stratified public benchmark exists
  (Peninsular-vs-LatAm must be settled by `eval/quality_probe.py`), no non-English
  function-calling benchmark exists (confirmed absence, not a search failure), and the
  headline quantization-tax paper does not test Spanish.
- All "ESTIMATED" labels in §3/§5/§6 should be replaced with measured numbers via §9 as
  Matt runs those commands — this file should be updated incrementally as that happens,
  not treated as final.
