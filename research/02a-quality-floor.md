# 02a — Spanish Quality Floor for Small LLMs (Appendix to `02-local-slm.md` §2)

> Appendix to `02-local-slm.md` §2. Scope: at what parameter count does a local SLM stop producing
> grammatical, register-appropriate Spanish, and how much faster does Spanish degrade than English
> as size and precision drop. Research date: 2026-09-12.
>
> **Sourcing convention:** every number below is [PRIMARY] (pulled from the evaluation artifacts or
> the paper itself) unless tagged [SECONDARY] (blog/forum) or **UNVERIFIED** (my trained knowledge,
> no source fetched this session — treat as a hypothesis to check, not a citation).

---

## 1. Headline

**~1.5B is below the floor. The floor is instruction-tuned 3–4B. The comfort zone is 7–9B.**

This is now measured rather than inferred: all 17 models at ≤1.7B on La Leaderboard score Spanish
grammatical acceptability at chance. Not "worse" — at chance. There is no partial-credit regime
below 2B; the capability is simply absent.

---

## 2. Primary data source

**La Leaderboard** — the Spanish/Catalan/Basque/Galician LLM leaderboard.

- Results dataset (what I actually mined — 69 model result JSONs, full lm-evaluation-harness output):
  https://huggingface.co/datasets/la-leaderboard/results
- Paper: https://arxiv.org/abs/2507.00999 [PRIMARY, title/authors confirmed]

**Access note / reproducibility warning:** the La Leaderboard HF *Space* was down at time of research
(`Exit code: 1`, `httpx.ReadTimeout` in `save_url_to_cache`), and the paper's HTML on arXiv renders
only a table of contents, not the results appendix. Both were bypassed by pulling the backing
`la-leaderboard/results` dataset repo directly. If you need to re-verify, go to the dataset repo,
not the Space and not the paper HTML.

### Key metric: EsCoLA MCC

**EsCoLA** = Spanish Corpus of Linguistic Acceptability (is this sentence grammatical?).
Scored by **MCC** (Matthews correlation coefficient), not accuracy — class imbalance makes raw
accuracy misleading here. MCC 0.0 = chance. This is the single most load-bearing metric in this
appendix because it isolates *grammaticality* from world knowledge.

---

## 3. The size threshold — EsCoLA MCC by parameter count [PRIMARY]

### ≤1.7B — all at chance (range −0.042 to +0.079, n=17 models)

| Model | MCC |
|---|---|
| gemma-3-1b-it | −0.026 |
| gemma-3-1b-pt | −0.000 |
| Llama-3.2-1B | +0.031 |
| Llama-3.2-1B-Instruct | −0.004 |
| Carballo-bloom-1.3B | +0.034 |
| FLOR-1.3B | +0.040 |
| FLOR-1.3B-Instructed | −0.042 |
| phi-1_5 | +0.057 |
| DeepSeek-R1-Distill-Qwen-1.5B | −0.010 |
| Qwen2.5-1.5B | +0.038 |
| Qwen2.5-1.5B-Instruct | +0.079 |
| leniachat-qwen2-1.5B-v0 | +0.041 |
| EuroLLM-1.7B | −0.040 |
| EuroLLM-1.7B-Instruct | +0.028 |
| Qwen3-1.7B | −0.005 |
| SmolLM2-1.7B | +0.004 |
| SmolLM2-1.7B-Instruct | −0.039 |

**Note that this includes Spanish-native and Spanish-targeted models** (FLOR-1.3B,
Carballo-bloom-1.3B, leniachat-qwen2-1.5B, EuroLLM-1.7B). Being trained on Spanish does not rescue
a 1B-class model. Capacity, not data mix, is the binding constraint at this size.

### 2.3–2.6B — first flicker of signal

salamandra-2b +0.019 · salamandra-2b-instruct +0.006 · leniachat-gemma-2b-v0 +0.000 ·
gemma-2-2b +0.060 · **gemma-2-2b-it +0.166** (first non-trivial score anywhere on the curve)

### 3.1–4.3B — the floor

| Model | MCC |
|---|---|
| **SmolLM3-3B** | **+0.245** |
| **Qwen2.5-3B-Instruct** | **+0.214** |
| **gemma-3-4b-it** | **+0.190** |
| **Llama-3.2-3B-Instruct** | **+0.174** |
| gemma-3-4b-pt | +0.106 |
| SmolLM3-3B-Base | +0.089 |
| Llama-3.2-3B | +0.057 |
| Qwen2.5-3B | +0.028 |
| Qwen3-4B | −0.003 (see §6 — thinking-mode artifact) |

**Critical pattern — at this size, instruction tuning is what unlocks grammaticality judgment:**
- Qwen2.5-3B: base **0.028** → Instruct **0.214**
- Llama-3.2-3B: base **0.057** → Instruct **0.174**
- SmolLM3: Base **0.089** → instruct **0.245**

A 3B *base* model is still near the floor. A 3B *instruct* model clears it. Do not substitute a base
checkpoint here.

### 6–9B — comfort zone

gemma-2-9b-it **+0.345** · Gromenauer-7B +0.322 · gemma-2-9b +0.288 · Qwen2.5-7B-Instruct +0.262 ·
RigoChat-7b-v2 +0.258 · EuroLLM-9B-Instruct +0.246 · Meta-Llama-3.1-8B-Instruct +0.242 ·
Qwen3-8B-Base +0.231 · occiglot-7b-es-en +0.230 · salamandra-7b +0.215 · Qwen2.5-7B +0.207 ·
Yi-1.5-9B-Chat +0.185 · aya-expanse-8b +0.155 · Qwen3-8B +0.145 · Mistral-7B-v0.3 +0.134 ·
OLMo-2-7B +0.115

**But several Spanish-specific 6–7B models are STILL at chance:** bertin-gpt-j-6B −0.016 ·
latxa-7b-v1.2 +0.013 · Aitana-6.3B +0.020 · FLOR-6.3B +0.044 · aguila-7b +0.062. Older Spanish
models built on weak bases (GPT-J, BLOOM) underperform newer general multilingual models of the same
size. **Prefer a recent general model over an older Spanish-specific one.**

### 14–40B

Qwen2.5-14B-Instruct-GPTQ-Int8 **+0.456** (best on the entire leaderboard) ·
ALIA-40b-instruct-2601 +0.393 · DeepSeek-R1-Distill-Qwen-14B-bnb-4bit **−0.029** (reasoning-distill
collapse, see §6)

---

## 4. Aggregate Spanish scores (corroborating the same curve)

### Official `laleaderboard_es` aggregate (%) — the 19 newer-format runs that carry it [PRIMARY]

SmolLM3-3B-Base 59.2 · Qwen2.5-3B 58.4 · Qwen3-8B-Base 57.9 · Qwen2.5-3B-Instruct 57.8 ·
gemma-3-4b-pt 57.3 · gemma-3-4b-it 56.7 · Llama-3.2-3B-Instruct 56.5 · SmolLM3-3B 53.6 ·
Llama-3.2-3B 53.3 · OLMo-2-1124-7B 52.5 · OLMo-2-1124-7B-Instruct 50.9 ·
Teuken-7B-research-v0.4 50.8 · Teuken-7B-commercial-v0.4 50.1 · SmolLM2-1.7B 46.8 · Qwen3-8B 45.4 ·
SmolLM2-1.7B-Instruct 44.8 · gemma-3-1b-it 44.3 · Qwen3-4B 41.9 · Qwen3-1.7B 40.8

### "core10" Spanish mean — my computation, covers all 69 models [PRIMARY data, MY derivation]

~50 of the 69 runs predate the official aggregate field. I computed a mean over 10 accuracy-metric
tasks present in every file: `belebele_spa_Latn, copa_es, openbookqa_es, paws_es, xnli_es,
xstorycloze_es, escola, teleia, spalawex, wnli_es`. Validated against `laleaderboard_es` on the 19
models having both — agreement within ~2 points (gemma-3-4b-it 58.6 vs official 56.7; Qwen2.5-3B
58.2 vs 58.4; Llama-3.2-3B-Instruct 56.9 vs 56.5).

**Label this as a derived number, not an official leaderboard score, if you cite it.**

- Top: Qwen2.5-14B-Instruct-GPTQ-Int8 66.3 · gemma-2-9b-it 64.8 · ALIA-40b-instruct-2601 64.7 ·
  aya-expanse-8b 61.8 · Meta-Llama-3.1-8B-Instruct 61.7 · RigoChat-7b-v2 61.1 · Qwen2.5-7B 60.9 ·
  gemma-2-9b 60.2 · Qwen2.5-7B-Instruct 60.1 · Gromenauer-7B-Instruct 60.0 · EuroLLM-9B-Instruct 59.8
- Mid: gemma-3-4b-it 58.6 · Qwen2.5-3B 58.2 · SmolLM3-3B-Base 58.1 · occiglot-7b-es-en-instruct 57.8 ·
  Qwen2.5-3B-Instruct 57.8 · Llama-3.2-3B-Instruct 56.9 · gemma-3-4b-pt 56.7 · Mistral-7B-v0.3 56.5 ·
  gemma-2-2b-it 54.6 · SmolLM3-3B 53.9 · salamandra-7b-instruct 53.2 · Llama-3.2-3B 52.5
- Bottom: gemma-3-1b-it 46.2 · SmolLM2-1.7B 45.9 · SmolLM2-1.7B-Instruct 44.5 ·
  EuroLLM-1.7B-Instruct 44.4 · gemma-3-1b-pt 44.4 · Llama-3.2-1B 43.0 · Llama-3.2-1B-Instruct 42.8 ·
  Qwen3-1.7B 42.3 · salamandra-2b-instruct 42.0 · phi-1_5 39.7 · DeepSeek-R1-Distill-Qwen-1.5B 36.6

### Within-family size deltas — the clean scaling signal [PRIMARY]

| Family | Small → Large | Delta |
|---|---|---|
| Llama-3.2 | 1B-Instruct 42.8 → 3B-Instruct 56.9 | **+14.1** |
| gemma-3 (it) | 1b 46.2 → 4b 58.6 | **+12.4** |
| gemma-3 (pt) | 1b 44.4 → 4b 56.7 | **+12.3** |
| gemma-2 (it) | 2b 54.6 → 9b 64.8 | **+10.2** |
| EuroLLM-Instruct | 1.7B 44.4 → 9B 59.8 | **+15.4** |
| salamandra-instruct | 2b 42.0 → 7b 53.2 | **+11.2** |
| Qwen2.5-Instruct | 1.5B 54.8 → 3B 57.8 → 7B 60.1 → 14B-Int8 66.3 | +11.5 across range |
| FLOR (Spanish-specific, weak base) | 1.3B 45.9 → 6.3B 48.6 | only **+2.7** |

The FLOR row is the counterexample worth keeping: 5× the parameters bought +2.7 points because the
base model was weak. Scaling helps only on a good base.

---

## 5. English-vs-non-English degradation as size and precision drop

This is where the evidence is **thinner and more caveated than the size-threshold evidence**. Read
the caveats — several of the most quotable papers do not actually test Spanish.

### 5a. Multilingual reasoning, English vs Spanish, by size [PRIMARY]

**"Multilingual Reasoning Gym: Multilingual Scaling of Procedural Reasoning Environments"** —
Dobler, Lehnerer, Scozzafava, Janke, Ali. https://arxiv.org/abs/2603.10793
14 languages, 94 tasks, native-speaker validation in 10. Table 2, verbatim caption: "Average@8 scores
of different models across languages ... at easy task difficulty".

| Model | EN | ES |
|---|---|---|
| gemma-3-1b-it | 4.7 | **4.5** |
| gemma-3-4b-it | 16.1 | **20.0** |
| gemma-3-12b-it | 23.2 | **20.9** |

**Correction worth recording:** earlier search-snippet figures circulating for this table
(ES 6.2 / 28.1 / 30.1) are **wrong**. Use 4.5 / 20.0 / 20.9.

Reading: at 1B, both EN and ES are at floor — the model is not doing the task in either language, so
there is no "gap" to measure. The interesting jump is 1b→4b. Spanish is not dramatically behind
English in this benchmark; the failure at 1B is task-general, not Spanish-specific.

### 5b. Quantization tax, smaller models penalized harder [PRIMARY — but no Spanish]

**"The Multilingual Quantization Tax: Structural Collapse and Typological Fragility in Edge SLMs"** —
Mohammad Wathiq Soualhi (sole author). https://arxiv.org/abs/2608.09941
Evaluates the 2B and 4B instruction-tuned variants of Gemma 4 (E2B-it / E4B-it) and Qwen 3.5, on
MMLU-Pro-X Lite (10-choice) + Global PIQA.

> Verbatim: "2B models suffer significantly higher degradation (Δ=**5.76%**) than 4B models
> (Δ=**4.10%**, p=0.036 via paired t-test across all granular language-domain subtasks, N=224)."

Also: Gemma architectures averaged **4.56%** quantization tax; Qwen averaged **5.30%**.

**LOAD-BEARING CAVEAT: the languages tested are EN, ZH, RU, JA, AR, HI, SW, YO. Spanish is NOT
tested.** Do not cite this as Spanish evidence. It supports the general claim "quantization hurts
smaller models more in non-English" and nothing narrower.

### 5c. Quantization degradation across 70 languages [PRIMARY — Spanish not broken out]

**"Tiny Aya: Bridging Scale and Multilingual Depth"** — Cohere (Salamanca, Hooker, Üstün, Kreutzer,
Fadaee, Gomez, Blunsom, Pineau). https://arxiv.org/abs/2603.11510
70 languages, 3.35B params, region-aware post-training, submitted 2026-03-12. Evaluated on mDolly.

> Verbatim: "We observe an average degradation of **1.4 points for Q4_K_M** and **2.1 points for
> Q4_0**. We observe **negligible average degradation for Q8_0**."

**Caveat: Spanish is not broken out separately.** Any per-Spanish read of these numbers is inference.

### 5d. The English-centric-quantization control [PRIMARY]

**"English K_Quantization of LLMs Does Not Disproportionately Diminish Multilingual Performance"** —
Karl Audun Borgersen, Morten Goodwin. https://arxiv.org/abs/2503.03592
Llama3.3 70B; importance matrices built in English, Norwegian, Malayalam; evaluated on MixEval.

> Verbatim conclusion: "current quantization practices do not disproportionately harm multilingual
> performance."

This is a useful counterweight — it argues the *calibration-set language* is not the problem. Note it
is a 70B model, so it says nothing about the SLM regime where 5b found a real size interaction.

### 5e. Spanish-specific quantization evidence — from the leaderboard itself [PRIMARY]

The single best Spanish-grammaticality model on all of La Leaderboard is an **8-bit GPTQ quant**
(Qwen2.5-14B-Instruct-GPTQ-Int8, EsCoLA MCC 0.456, core10 66.3) — it beats the fp16 field. Contrast
with the **4-bit bnb** DeepSeek-R1-Distill-Qwen-14B at MCC −0.029.

This is independent, *Spanish-specific* corroboration of Tiny Aya's "negligible degradation for Q8_0"
and is the strongest ES-specific quantization datapoint available. **Practical rule: Q8/Int8 is
effectively free for Spanish; treat 4-bit as a real risk at small sizes.**

### 5f. Iberian-language SLMs on end-user devices [PRIMARY, title/authors confirmed]

**"Evaluating Compact LLMs for Zero-Shot Iberian Language Tasks on End-User Devices"** — Couto Seller,
Sanz Torres, Vogel-Fernández, González Carballo, Sánchez Sánchez, Carruana Martín, de Miguel Ambite.
https://arxiv.org/abs/2504.03312 — directly on-topic for the M3 deployment scenario.

---

## 6. Failure modes that are NOT size-related (and will fool you)

These came out of the raw leaderboard JSONs and matter more for app design than the scaling curve.

### 6a. Reasoning/thinking-mode structured-output collapse [PRIMARY, Spanish-specific] ⚠️

Qwen3-8B scores **xquad_es f1 = 0.0**, **belebele_spa_Latn = 22.9** (chance for 4-way), mgsm 0.0.
Qwen3-4B and Qwen3-1.7B show the identical pattern. Their base counterpart **Qwen3-8B-Base scores
xquad_es 59.5**.

The underlying Spanish competence is intact; the thinking-trace output format breaks extractive and
multiple-choice parsing. **For a conversation app that needs parseable/structured output, avoid Qwen3
thinking-mode variants, or enforce constrained/grammar-based decoding.** This is the clearest
concrete warning in the whole dataset.

Same mechanism, milder: several instruct models score xquad_es f1 far below their base
(Qwen2.5-3B-Instruct 25.0 vs base 77.0; ALIA-40b 6.8; Qwen2.5-14B-Int8 20.6). Chat formatting vs.
extractive-span scoring — **not** a Spanish comprehension deficit. Do not read these as Spanish
quality signals.

### 6b. Degenerate benchmark — do not cite `humorqa`

`humorqa = 58.8` for ~35 different models — an always-one-class degenerate result on a 51-item set.
Worthless as a discriminator.

### 6c. TELEIA is too small to separate models

**TELEIA** = Spanish-as-a-foreign-language exam benchmark.
Paper: "Evaluating Large Language Models with Tests of Spanish as a Foreign Language: Pass or Fail?" —
Mayor-Rocher, Melero, Merino-Gómez, Grandury, Conde, Reviriego. https://arxiv.org/abs/2409.15334

> Verbatim conclusion: "The results show that LLMs perform well at understanding Spanish but are still
> far from achieving the level of a native speaker in terms of grammatical competence."

**Correction recorded:** the benchmark in this paper is **TELEIA**, not DELE/SIELE.

**Access gap:** the paper is PDF-only (`/html/…v1` → 404; ar5iv → 307 redirect back to `/abs/`), so
its own per-model table was never retrieved. Substituting La Leaderboard's independent TELEIA run:

ALIA-40b 66.7 · gemma-3-4b-it 66.7 · aya-expanse-8b 66.7 · Qwen3-8B-Base 61.9 · gemma-2-9b-it 57.1 ·
gemma-2-9b 57.1 · SmolLM3-3B-Base 57.1 · Gromenauer-7B-Instruct 57.1 · Llama-3.2-3B-Instruct 57.1 ·
Qwen2.5-14B-Int8 52.4 · Qwen2.5-3B 52.4 · gemma-3-4b-pt 52.4 … gemma-3-1b-it 38.1 ·
Llama-3.2-1B-Instruct 33.3 · Qwen3-1.7B 23.8 · Llama-3.2-1B 19.0 ·
DeepSeek-R1-Distill-Qwen-1.5B 19.0 · gemma-3-1b-pt 14.3

**⚠️ CRITICAL CAVEAT: stderr 0.08–0.11 implies n ≈ 21 items** (teleia_cervantes_ave n≈4, teleia_pce
n=7, teleia_siele n≈8–10). **Individual TELEIA numbers are not statistically separable.** Only the
broad "1B floor vs ≥3B" gap survives. **Never quote head-to-head TELEIA comparisons.**

---

## 7. Peninsular vs. Latin American Spanish — EVIDENCE GAP

**I found no dialect-stratified evaluation.** This is a genuine gap, not a search failure — flagging
it explicitly so §2 can state it as a known limitation rather than silently assume dialect neutrality.

What the benchmark suite actually is: EsCoLA, TELEIA, xquad_es, belebele_spa_Latn, copa_es,
openbookqa_es, paws_es, xnli_es, xstorycloze_es, spalawex, wnli_es. **None of these is dialect-split.**
La Leaderboard's own framing is Spanish/Catalan/Basque/Galician — i.e. it stratifies by the
co-official *languages of Spain*, not by Peninsular-vs-LatAm varieties of Spanish. Several of its
corpora (EsCoLA, TELEIA, spalawex — Spanish law) are Peninsular in origin, which if anything means
**the leaderboard's "Spanish" scores skew Peninsular and may overstate LatAm-variety quality.**

The following are **UNVERIFIED** (trained knowledge, no source fetched — do not cite, flag for
follow-up if the app targets a specific market):
- **UNVERIFIED:** SLMs are widely believed to default to a broadly Peninsular or neutral
  "international" Spanish register, since web-scraped Spanish training data skews toward Spain-based
  and pan-regional media.
- **UNVERIFIED:** *voseo* (Rioplatense/Central American) is believed to be handled markedly worse
  than *tuteo* by small models, with models often silently normalizing *vos* forms to *tú*
  conjugations. No benchmark measured this.
- **UNVERIFIED:** *vosotros* (Peninsular 2pl) vs *ustedes* (LatAm 2pl) selection is believed to be
  inconsistent in small models and not reliably steerable by system prompt below ~7B.
- **UNVERIFIED:** region-specific lexicon (coche/carro, ordenador/computadora, zumo/jugo) is believed
  to be a weak point where small models mix registers within a single response.
- **Register-appropriateness generally** (tú/usted consistency across a multi-turn conversation) is
  **not measured by any benchmark found.** EsCoLA measures grammaticality, not register. For a
  conversation-partner app this is arguably the more important axis and it is **unmeasured**.

**Recommendation for §2:** if the app targets a specific dialect, this must be settled by a hand-built
eval (a few dozen prompts probing voseo, vosotros, and tú/usted consistency), because the public
benchmark suite will not answer it.

---

## 8. Structured output / function calling in Spanish — CONFIRMED ABSENCE

Relevant if the app does tool-calling or needs JSON from the model.

**No public benchmark measures function-calling or JSON-schema adherence in Spanish, or in any
non-English natural language, as of 2026-09-12.** Verified two ways:

1. **BFCL (Berkeley Function Calling Leaderboard) has no natural-language split** [PRIMARY, verified
   at the dataset level]. Full v4 category listing from
   https://github.com/ShishirPatil/gorilla/tree/main/berkeley-function-call-leaderboard/bfcl_eval/data :
   `format_sensitivity, irrelevance, live_irrelevance, live_multiple, live_parallel,
   live_parallel_multiple, live_relevance, live_simple, memory, multi_turn_base,
   multi_turn_long_context, multi_turn_miss_func, multi_turn_miss_param, multiple, parallel,
   parallel_multiple, simple_java, simple_javascript, simple_python, web_search`.

   **False-friend warning:** the BFCL README says "our evaluation dataset spans diverse categories,
   and across multiple languages" — but the same README disambiguates two sections later, verbatim:
   "to evaluate model performance on diverse scenarios and **support of multiple programming
   languages**", listing "Chatting Capability, Function Relevance Detection, REST API, SQL, Java, and
   JavaScript." **"Multiple languages" in BFCL means Java/JavaScript/SQL/Python, not Spanish.**
   Anyone citing BFCL as multilingual evidence is misreading that line.

2. **No Spanish function-calling benchmark on HF Hub** [PRIMARY]. HF datasets API search for
   "function calling spanish" returns exactly two hits, both *training* sets from one author, not
   evaluations: `Bluckr/function-calling-assistant-spanish-pofi-v2` (228 downloads, 3 likes, last
   modified 2024-05-18) and its 300-row mini variant. Search for "function calling multilingual"
   returns **zero** datasets. The ~30 BFCL-tagged Hub datasets are all forks/re-splits of the English
   v1–v4 sets.

**Therefore:** any claim about Spanish structured-output reliability at a given model size is
extrapolation from English benchmarks, not measurement. Nearest available evidence is weak and
English-only:
- [SECONDARY] Llama-3B at 1/9 tool-calling tasks = 11% accuracy —
  https://dev.to/anak_wannaphaschaiyong_11/why-small-llms-fail-at-tool-calling-the-shocking-discovery-from-our-llama-3b-benchmark-5lg
- [SECONDARY] Llama-3.2-3B beats Qwen3-14B on raw JSON validity while losing on argument accuracy and
  multi-turn — https://dev.to/pitambarmahato/can-local-llms-actually-call-functions-i-tested-2-models-on-6-real-api-tasks-19kc

The strongest *real* signal remains §6a — the Qwen3 Spanish extractive collapse is a measured,
Spanish-specific instance of exactly this failure mode. **Use constrained/grammar decoding rather than
trusting an SLM's free-form JSON in Spanish.**

---

## 9. Real-world deployment anecdotes (thin)

- [SECONDARY] https://news.ycombinator.com/item?id=48887124 — "I built a fully locally hosted language
  learner app… using a local LLM, Qwen TTS, local STT, and comfyUI image gen… generates dialogue,
  images, audio, quizzes, and pronunciation tests… Currently supports **Spanish**, French, German,
  Japanese, and Simplified Chinese. **Runs on a 4060 16GB card.**" Existence proof at a 16GB budget —
  but the model and size are never stated, so it does not pin the quality floor.
- [SECONDARY] https://news.ycombinator.com/item?id=45811484 — ConvoLive (https://convolive.com).
  Verbatim: **"Unfortunately, on-device local LLM ended up being too demanding and slow."** /
  "Ultimately, it was too slow to be conversational." Used https://github.com/mybigday/llama.rn.
  **Caveat: phone deployment, not an M3 Mac. This is a latency finding, not a Spanish-quality finding,
  and should not be transferred to the Air.**

---

## 10. Recommendation for `02-local-slm.md` §2

| Tier | Model | core10 | EsCoLA MCC | Verdict |
|---|---|---|---|---|
| Do not ship | anything ≤1.7B | 40–46 | ~0.00 | Spanish grammaticality at chance |
| Floor | Qwen2.5-3B-Instruct | 57.8 | 0.214 | minimum viable |
| Floor | gemma-3-4b-it | 58.6 | 0.190 | minimum viable, TELEIA 66.7 |
| Comfort | gemma-2-9b-it | 64.8 | 0.345 | target if RAM allows |
| Ceiling | Qwen2.5-14B-Instruct-Int8 | 66.3 | 0.456 | best measured Spanish grammar |

Rules that fall out of the evidence:
1. **≥3B, and instruction-tuned.** A 3B base checkpoint is not a substitute for a 3B instruct one.
2. **Q8/Int8 is effectively free for Spanish.** 4-bit is a real risk below ~7B.
3. **Avoid reasoning/thinking-mode variants** (Qwen3 family) for anything needing parseable output.
4. **Prefer a recent general multilingual model over an older Spanish-specific one** — bertin,
   Aitana, FLOR, aguila all underperform their size class.
5. **Dialect and register are unmeasured.** Build a hand eval if targeting a specific market.

---

## 11. Research blockers (for reproducibility)

1. **Reddit unreachable** by all three routes attempted (WebFetch domain block; direct curl returns an
   HTML shell only; `r.jina.ai` proxy returns HTTP 403). §9 is HN-only as a result.
2. **La Leaderboard HF Space down** (`Exit code: 1`, `httpx.ReadTimeout`) — fully worked around via the
   `la-leaderboard/results` dataset repo.
3. **arXiv 2409.15334 (TELEIA) is PDF-only** — HTML 404, ar5iv 307-redirects to `/abs/`. Paper's own
   per-model table not retrieved; §6c substitutes La Leaderboard's independent run.
4. **arXiv 2507.00999 HTML renders only a table of contents**, not the results appendix.
5. **Search budgets exhausted:** WebSearch 200/200; arXiv API and Semantic Scholar API both returning
   HTTP 429 (arXiv: 4 queries × 5 retries, all failed). §8's conclusion was reached by direct
   GitHub/HF artifact inspection instead — which is primary-source evidence, and stronger than the
   search-snippet route would have been.
