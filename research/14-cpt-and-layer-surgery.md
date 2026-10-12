# 14 — Continued pretraining and layer surgery for variety control

> Scope: whether drill should shift its 3–4B partner model toward a Spanish variety with **continued
> pretraining (CPT)** or **model surgery** (layer swapping, merging, partial-layer tuning, activation
> steering, weight orthogonalization), instead of or before 11's instruction SFT-LoRA. The target is a
> **conditional** behaviour: vosotros, Spain lexicon and Spain discourse markers iff the session is
> es-ES, and ustedes and LatAm lexicon iff it is es-419. It also lays out an interpretability protocol
> that first **locates** where that distinction lives in a 3–4B model and then intervenes only there,
> sized for the M3 Air (16 GB, fanless) with MLX. Research date: 2026-10-12.
>
> **Sourcing convention (as in 02a/11):** [PRIMARY] means a paper, official docs, config/tokenizer
> file or source code read this session. [SECONDARY] means a blog, aggregator or search snippet.
> **UNVERIFIED** means no fetched source, a single weak source, or background knowledge; treat it as
> a hypothesis. **[PRIMARY, not re-read]** marks a primary source cited from prior knowledge and not
> re-fetched this session, so verify numbers before quoting them. **computed** means my own arithmetic
> from stated inputs, not a measurement. Some P3B3 table cells were reconstructed by a fetch tool from a
> flattened table; treat single cells with caution, as 11 did.
>
> **Scale warning that applies to the whole file:** **no paper controls es-ES vs es-419 (or
> vosotros/ustedes) by CPT, surgery, merging or steering, at any scale.** The variety evidence is
> Portuguese (pt-PT/pt-BR, 8–9B), Québec French (1–8B LoRA-CPT), and Arabic dialects (7–9B
> steering). The surgery evidence is **language-level** (Swahili vs English, etc.) at 7–13B. Every
> transfer to vosotros at 3–4B is an extrapolation and is labelled as one.

---

## TL;DR

1. **CPT is the only evidenced route to move a model's *default* variety, and the evidence is
   observational.** AMALIA-9B, with **~5.8B pt-PT tokens** in a modified final pretraining phase
   (≈5% of ~107B) **plus** pt-PT SFT/DPO, scores **91.2/100 pt-PT unprompted**. Gervásio-8B, which had
   pt-PT SFT only, scores **12.7 unprompted and 46.6 prompted**, essentially its own base Llama-3.1-8B
   (12.6 / 47.7). There is **no controlled CPT-vs-SFT ablation for any language**, and AMALIA does not
   separate mid-training from post-training.
2. **drill does not need a new default; it needs a switch.** CPT on Spain text pushes the
   *unconditional* prior toward es-ES. That is half of the job and actively hurts the other half:
   it risks vosotros and Spain lexicon leaking into es-419 sessions. The live 2026-10-12 measurement
   already shows this failure mode. **qwen2.5:3b echoed the learner's Spain word "zumo" in 10/10
   es-419 replies** (Wilson 95% lower bound 0.72, computed): in-context lexical cues outrank the
   system-prompt variety.
3. **The vosotros failure is partly a pragmatic decision, not just conjugation.** The same run gave
   **vosotros in 0/13 group-address samples**, and the model mostly **dodged by not addressing the
   group at all**. Factor the target as P(vosotros reply) = P(address the group in 2pl) ×
   P(vosotros | 2pl address). A conjugation-level fix (late-layer agreement, verb-ending logit bias)
   cannot repair the first factor. Even at the 95% upper bound of 0/13 (p ≤ 0.23), three samples
   reach at most **~54%** success against 11's 90% bar (computed). **Regeneration cannot rescue
   qwen2.5:3b.**
4. **Licensed CPT data is Spain-heavy in lexicon and light on vosotros.** Clean sources exist at
   web scale: HPLT v2 (CC0) and FineWeb-2 (ODC-By) filtered to .es, plus CEREAL labels (**5.7M .es
   docs / 70.5M segments**), ParlaMint-ES (CC BY) and BOE. Every conversational Peninsular source
   checked is restricted or unclear: OpenSubtitles is "unknown", RTVE is academic-only, CORPES is NC
   and not downloadable. **Nobody has measured vosotros frequency per corpus.** Parliament is likely
   near zero (Señorías + formal ustedes). CPT would teach coche/zumo/ordenador well and 2pl-informal
   address poorly.
5. **Surgery evidence is language-level and modest.** Layer swapping on Llama 3.1 8B (bottom 5 + top 2
   layers) moved Swahili MGSM **29.5→32.4** but made Japanese **worse (42.7→38.5)**. For **dialect**,
   the one study (Arabic, 7–9B) found that **sparse neurons cannot induce dialect from neutral
   prompts while a mid-stack residual vector can**, and that **plain prompting beat steering** on raw
   dialect ID. Expect a distributed mid-layer direction, not a neuron set.
6. **Shipping decides the surgery menu.** Ollama needs a merged GGUF. **Additive steering vectors
   cannot be baked into Qwen3's weights** because `o_proj`/`down_proj` have no bias. llama.cpp control
   vectors are startup-only, and Ollama has none. **In drill's MLX path, a steering vector is ~5 KB
   per layer (computed) applied by wrapping `model.layers[i]`, and it can be switched per request on
   the variety flag.** That makes it the only option where conditionality is free. Directional
   ablation *can* be baked in as orthogonalized weights that convert to a normal GGUF, but it only
   removes a direction and applies unconditionally.
7. **Recommended order: base choice → measure → locate → steer (MLX) / layer-targeted LoRA
   (Ollama) → CPT last.** P3B3 shows prompt-steerability varies ~4× by family at small scale
   (Gemma-4-E4B **21.9→94.4** with a pt-PT prompt vs Qwen3-8B **10.4→32.7**). Gemma 3 4B also has
   Gemma Scope 2 SAEs for every layer. **Make it the first base to gate and the first model to
   dissect.** Localization on the Air is a few evenings: a 100-pair residual sweep takes ~70–75 min
   on Qwen3-4B (computed estimate). CPT on base + chat vector is a rented-GPU job of roughly
   **$90–270 per 1B tokens** (computed). Reserve it for the case where SFT and steering both fail on
   *lexicon/naturalness*, not on vosotros.

---

## 1. CPT for dialect/variety adaptation

### 1a. Does CPT move the default variety more than SFT?

| Evidence | Scale | Finding | Tag |
|---|---|---|---|
| P3B3 (pt-PT vs pt-BR, LLM judge, 0 = pt-BR … 100 = pt-PT), unprompted / pt-PT-prompted | 8B–70B | Gervásio-8B-ptpt **12.7 / 46.6**; its base Llama-3.1-8B **12.6 / 47.7**; Gervásio-70B 22.8 / 75.2; **AMALIA-9B 91.2 / 95.9**; Qwen3-8B 10.4 / 32.7; Qwen3.5-9B 35.1 / 86.1; Gemma-3-12b 23.4 / 92.9; **Gemma-4-E4B 21.9 / 94.4** ([P3B3](https://arxiv.org/html/2606.16753v1)) | [PRIMARY]; AMALIA 91.2 confirmed in text, other cells reconstructed |
| P3B3 authors | — | Gervásio "still exhibits a pt-BR bias"; "pre-training data and scale play a critical role". **No CPT-vs-SFT ablation is run** ([P3B3](https://arxiv.org/html/2606.16753v1)) | [PRIMARY] |
| AMALIA tech report | 9B | Not from scratch: it modifies EuroLLM-9B's final pretraining phase. That phase is 40B original mix + 60B code-expanded + 1.4B synthetic long-context + **5.8B Arquivo.pt pt-PT web** ≈ 107B tokens (pt-PT ≈ 5%, computed), on 80 h × 256 H100. It is followed by pt-PT persona SFT and **478K DPO pairs**. No stage ablation ([AMALIA](https://arxiv.org/html/2603.26511v1)) | [PRIMARY] |
| AMALIA-DPO vs Gervásio-8B | 9B vs 8B | PT-C **67.1 vs 30.0**, IFEval 61.6 vs 55.6, but **GSM8K 52.4 vs 67.3, BBH 47.3 vs 68.1** ([AMALIA](https://arxiv.org/html/2603.26511v1)) | [PRIMARY] |
| Québec French LoRA-CPT (LREC 2026) | 1.35B, 1B, 8B | **86.57M-token** Québec corpus (60% edited text, 40% forums/comments), LoRA r=16 on MLP only (~1% params), up to 6 epochs. Reports "improvement on the minority dialect benchmarks with minimal regression on the prestige language" but gains "highly contingent on corpus composition". Per-task rows are noisy: Llama-3.2-1B on one COLE QC task went 45.84 → 27.89 (3 ep) → 42.45 (6 ep) ([PDF](https://aclanthology.org/2026.lrec-1.840.pdf)) | [PRIMARY] |
| Cecilia 2B (Cuban Spanish CPT on Salamandra-2B) | 2B | improved Spanish tasks "with some trade-offs" ([Springer](https://link.springer.com/chapter/10.1007/978-3-032-11358-0_11)) | [SECONDARY, snippet] |
| Mayor-Rocher et al. | 9 models | Peninsular is the best-*identified* variety. That is identification, not generation ([arXiv 2504.20049](https://arxiv.org/abs/2504.20049)) | [PRIMARY] |

**Reading.** The Gervásio row is the cleanest negative result available: pt-PT SFT on an 8B
instruct model left both its unprompted and its prompted variety scores at base level. 06's vosotros
failure has the same shape. AMALIA is the positive case, but it confounds CPT with heavy in-variety
post-training, a different base (EuroLLM), and extra code data. **Calling CPT "the" lever overreads
it. The defensible claim is that no model reached a pt-PT default without in-variety pretraining
data, and SFT alone did not get there.**

Two things carry over to drill, and one does not:

- **Carries over: prompt-steerability is a model-family property, and it is large.** Gemma-4-E4B
  moves 21.9→94.4 with a prompt; Qwen3-8B moves 10.4→32.7. If the same holds in Spanish, choosing the
  base is worth more than any CPT run, and it costs nothing (TL;DR 7, Verdict step 1).
- **Carries over: the default is what you get when the conditioning signal is weak.** In multi-turn
  play, P3B3 found that controllability decays in later turns (11 §1a). A stronger default prior
  helps there.
- **Does not carry over: AMALIA wants pt-PT always.** drill wants es-ES *only when told*. Pushing the
  es-ES prior up in a model that already ignores the system-prompt variety (the 10/10 "zumo" echo)
  makes es-419 sessions worse. 11's tripwire (es-419 no-vosotros ≥95%, §6c) becomes the likely point
  of failure. No paper tests conditional variety CPT. A plausible but **UNVERIFIED** variant is to
  CPT on a *mixed, tagged* corpus (es-ES docs prefixed with a variety tag and es-419 docs with
  another, using CEREAL ccTLD labels), so the model learns the tag → variety map during CPT. I found
  no evidence that metadata-conditioned CPT works at this scale.

### 1b. Token budgets

| Run | Tokens | Model | Tag |
|---|---|---|---|
| Québec LoRA-CPT | 0.087B × ≤6 epochs | 1–8B | [PRIMARY] ([PDF](https://aclanthology.org/2026.lrec-1.840.pdf)) |
| Dialect/variety CPT gains reported from | ~0.35B | — | [PRIMARY], as cited in the Québec paper's related work |
| CataLlama (Catalan) | 0.445B | Llama | [PRIMARY], same table |
| Chat Vector Trad. Chinese CPT | ~3.1B, peak LR 5e-5 | LLaMA2-7B/13B | [PRIMARY] ([Chat Vector](https://arxiv.org/html/2310.04799v3)) |
| Latxa (Basque) | 4.2B | Llama | [PRIMARY], Québec table |
| AMALIA pt-PT slice | 5.8B of ~107B | 9B | [PRIMARY] |
| Ibrahim et al. German shift | 200B | 405M / 10B | [PRIMARY] ([arXiv 2403.08763](https://arxiv.org/html/2403.08763)) |

**Ibrahim et al. recipe** [PRIMARY] ([arXiv 2403.08763](https://arxiv.org/html/2403.08763)): re-warm
and re-decay the LR (η_max 3e-4 → η_min 3e-5, ~1% warmup). Higher η_max means more adaptation and more
forgetting. Add replay: **25% for a strong shift** (English→German at 405M brought average loss to
1.75, matching union retraining; with no replay, Pile loss went 2.17 → 3.56) and **~5% for a weak
shift** (10B: 1.89 vs 1.87 union; English downstream 47.68 vs 48.00). es-ES vs es-419 is a "weak
shift" in loss terms, which argues for ~5–25% general Spanish/English replay. Whether a weak-shift
mix moves a categorical paradigm choice like vosotros is untested.

Drill-scale bracket (inference from the table): **50M–500M es-ES tokens**, where the Québec and
Catalan work sits. No study gives a "variety default vs tokens" curve at any scale.

### 1c. Catastrophic forgetting of chat, and the fix

CPT on an instruct model erodes instruction following. CPT on a base model loses chat entirely. The
fix that has numbers is **Chat Vector**: θ = θ_CPT-base + (θ_instruct − θ_base)
([Huang et al., ACL 2024](https://arxiv.org/abs/2310.04799)) [PRIMARY].

| Config (LLaMA2-7B, Vicuna GPT-4 score) | English | Trad. Chinese |
|---|---|---|
| llama2-7b-chat | 7.91 | 5.23 |
| CPT → SFT | **1.64** | 6.33 |
| CPT + chat vector | **7.04** | **6.58** |

([Chat Vector, Table 5](https://arxiv.org/html/2310.04799v3)) [PRIMARY]

Other findings from the same paper [PRIMARY]:
- At 13B, CPT on the **chat** model then SFT (6.46) was worse than CPT on base + CV (7.03). CP→FT+CV
  was best (7.37).
- Knowledge survives: TMMLU+ CP 25.91, CP+CV 26.93.
- Safety improves: unsafe Insult 66.0% (CP→FT) vs 7.5% (CP→FT+CV).
- **Failure mode: replying in the wrong language.** CP+CV gave only 62.6% correct-language replies on
  safety prompts, and Chinese-LLaMA CP+CV was 20.9% Chinese. Scaling the vector to 0.5 restored 99.9%
  Chinese but dropped Vicuna to 4.61. **CP→FT+0.5·CV kept 7.89 with 100% Chinese.**
- Breeze-7B used coefficient 0.5 and excluded embeddings and the LM head.
- Chat vectors taken from different chat models all worked (7.03 / 6.85 / 7.28).

Instruction residuals (ICML 2025) confirm that domain CPT up to 1B tokens degrades instruction
following and that re-adding the residual restores it, on LLaMA and Qwen. I did not retrieve numbers
([ICML](https://icml.cc/virtual/2025/47382)) [PRIMARY abstract].

**The Spanish analogue of "wrong language" is "wrong variety".** The instruct delta carries the
instruct model's LatAm/neutral prior back in (inference). The paper's mitigations map directly:
sweep the delta coefficient (0.5–1.0) and add a small SFT after the merge (CP→FT+CV). That SFT is
11's SFT-LoRA. **So CPT + CV does not replace 11's SFT. It is a substrate under it.**

**Base availability for the recipe:**

| Instruct | Base | Status |
|---|---|---|
| Qwen3-4B-Instruct-2507 (Apache-2.0, 11's preferred) | Qwen3-4B-Base (Apache-2.0, 36T-token series) | Base verified [PRIMARY] ([HF](https://huggingface.co/Qwen/Qwen3-4B-Base)). **Not verified that 2507 was post-trained from these exact weights.** The Base card does not mention 2507. Check ‖Δ‖ and cosine per layer before trusting the delta. |
| gemma-3-4b-it | gemma-3-4b-pt | Same-release pair; existence **UNVERIFIED** this session |
| Llama-3.2-3B-Instruct | Llama-3.2-3B | Same-release pair; existence **UNVERIFIED** this session |
| SmolLM3-3B | SmolLM3-3B-Base (Spanish one of 6 native languages; open recipe and intermediate checkpoints) | Verified [PRIMARY] ([HF](https://huggingface.co/HuggingFaceTB/SmolLM3-3B-Base)) |

No chat-vector result below 7B was found.

### 1d. LoRA-CPT vs full CPT

"LoRA Learns Less and Forgets Less" (Llama-2-7B, 0.25–20B CPT tokens on code and math)
([arXiv 2405.09673](https://arxiv.org/html/2405.09673v2)) [PRIMARY]:
- LoRA r=256 peaked at HumanEval 0.224 after 20B tokens; full FT reached 0.218 by 4B tokens.
- Forgetting score (higher = less forgetting) at 20B code: full **0.545**, LoRA r=16 **0.635**.
- Full FT learns perturbations of rank 10–100× typical LoRA configs. Best LoRA LR is ~10× full FT.

A variety shift (a pronoun/verb paradigm plus a few hundred lexemes) is plausibly low-rank, unlike
code or math. So **LoRA-CPT directly on the instruct model, with replay**, is a cheaper alternative
to base-CPT + CV, and it forgets less. This is an inference, untested for vosotros; Québec is the
only dialect evidence for the LoRA form.

### 1e. Feasibility: the Air vs a rented GPU

| Item | Number | Tag |
|---|---|---|
| Full FT of a 4B model | bf16 weights 8 GB + grads 8 GB + Adam 16–32 GB ⇒ **32–48 GB + activations** | computed. **Impossible on 16 GB.** |
| QLoRA, 4-bit 4B | ~2–2.5 GB weights; bs 1–2, seq 1024–2048, grad checkpointing | computed. Fits. 11 cites a 3B QLoRA peak of ~2.5 GB [SECONDARY]. |
| mlx-lm support | `lora`/`dora`/`full`, automatic QLoRA on a quantized `--model`, raw `{"text": …}` data, `--grad-checkpoint` | [PRIMARY] ([LORA.md](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/LORA.md)) |
| Only official MLX training speed | Mistral-7B LoRA, 4 layers, bs 1: ~250 tok/s on **M1 Max 32 GB** | [PRIMARY] |
| Air guess for 3–4B QLoRA | ~200–500 tok/s | **UNVERIFIED** scaling guess. Measure it. |
| Air at 300 tok/s | 10M tokens ≈ 9.3 h; 30M ≈ 28 h; **100M ≈ 93 h**; 1B ≈ 39 days | computed, before thermal throttling (11 §4: the M3 Air throttles; lid-closed GPU throughput ~halves) |
| H100 SXM at assumed 40% MFU | 6N FLOP/token = 2.4e10 ⇒ ~16.5k tok/s ⇒ 1B tokens ≈ 16.8 h ⇒ **$45–67 per 1B** at $2.69–3.99/h | computed. The 989 TFLOPS peak is UNVERIFIED. RunPod's page lists conflicting prices [PRIMARY]. |
| Reality check | AMALIA's run implies ~8% MFU (9B, 32K context) | computed. **Budget 2–4× ⇒ ~$90–270 per 1B tokens.** |
| A100 80GB at 40% MFU | ~5.2k tok/s ⇒ ~$63–95 per 1B | computed |

**So the Air is a pilot machine for CPT (≤10–50M tokens of QLoRA-CPT), not a CPT machine.** A real
base-CPT at 0.1–1B tokens is one rented H100 for a few hours to a day. The chat-vector merge then
runs on CPU (mergekit, §3c), followed by conversion to GGUF/MLX. Compare 11's SFT-LoRA at
~$0.34–2.22 per run (computed in 11). **CPT costs one to two orders of magnitude more, before any
data work.**

---

## 2. Peninsular corpora: licences, filtering, and the 2pl gap

### 2a. What can legally go into redistributed weights

| Source | Licence / terms | Size | Variety | Vosotros expectation | Tag |
|---|---|---|---|---|---|
| **HPLT v2** | **CC0** | 8T tokens across 193 languages; es share not found | mixed; filter by URL | low (web prose) | [SECONDARY] ([paper](https://www.utupub.fi/items/ef9c168a-0156-4ee4-a44e-5ce0b056b0a5/full)) |
| **FineWeb-2** | **ODC-By 1.0** plus Common Crawl ToU | ~3T words, 1000+ languages | mixed; filter by URL | low | [SECONDARY] ([card](https://huggingface.co/datasets/HuggingFaceFW/fineweb-2/blob/cab26bb3cab1ca7c26bb13a48f80fc3d2def4620/README.md)) |
| **CEREAL** (labels over OSCAR 22.01 es) | annotations **CC0**; text copyright not held by the authors | **.es: 5.7M docs / 70.5M segments**; 21.4M Spain docs after classifier labelling (MX 2.4M, AR 2.0M) | Spain-labelled | low–medium (forums, recipes: "os dejo la receta") | [PRIMARY] ([NAACL 2024](https://aclanthology.org/2024.naacl-long.204), [site](https://cereal-es.github.io/CEREAL)) |
| **ParlaMint-ES** 4.1 | **CC BY 4.0** | 83.6 MB tgz; ES word count not shown (whole set 1.23B words / 29 parliaments) | Spain by construction | **likely ≈0** (Señorías, formal ustedes) | [PRIMARY] ([CLARIN.SI](https://www.clarin.si/repository/xmlui/handle/11356/1912)) |
| ParlaMint-ES-CN (Canary Islands) | CC BY 4.0 | — | **ustedes variety**, so a negative/es-419-like signal | 0 | [SECONDARY] |
| **BOE** | commercial reuse with attribution ("Basado en datos de la Agencia Estatal BOE"); Biblioteca Jurídica Digital excluded (CC BY-NC-ND) | — | Spain | 0 (legal register) | [PRIMARY] ([aviso legal](http://boe.es/informacion/aviso_legal/)) |
| Gutenberg 19th-c. novels (Galdós, Clarín, Pardo Bazán) | US public domain | — | Spain | high but archaic ("vuestra merced") | UNVERIFIED |
| Spanish Wikipedia | CC BY-SA 4.0 (share-alike on weights unsettled) | ~39.2% of edits from Spain | mixed | ≈0 | [PRIMARY] for 39.2% ([arXiv 2412.11750](https://arxiv.org/html/2412.11750v1)); licence UNVERIFIED |
| OpenSubtitles (OPUS) | **"unknown"** | largest conversational source | EU and LatAm dubs mixed; no confirmed es-ES subset | probably highest | [PRIMARY] ([HF card](https://huggingface.co/datasets/Helsinki-NLP/open_subtitles)) |
| RTVE databases | **academic use only**; no transfer or copies | — | Spain | spoken | [SECONDARY] ([licence](https://catedrartve.unizar.es/docs/RTVE_database_license_v2025_v3.pdf)) |
| CORPES XXI (RAE) | NC (BY-NC-SA on the manuals); **"only browsable and not fully downloadable"** | >395M forms, ~30% Spain | tagged | has an oral subcorpus | [PRIMARY]/[SECONDARY] |
| Corpus del Español (Davies) | paid licence, redistribution restricted | NOW ~7B words | country tags | — | [PRIMARY] size; licence UNVERIFIED |
| Val.Es.Co / ESLORA / CORLEC / C-ORAL-ROM | typically NC or research-only, ≤~1M words | — | Spain, spoken | high | UNVERIFIED |

**Redistribution-safe stack** (inference): HPLT v2 or FineWeb-2 filtered to .es or to the CEREAL ES
label, plus ParlaMint-ES, plus BOE, plus Gutenberg PD novels. Attribution goes in the model
card/NOTICE. OpenSubtitles is safer used to *measure* features (eval, lexicon mining) than to train
on. That is a judgment call, not legal advice, and it matches 11 §3b's "avoid for training".

### 2b. Variety filtering

| Method | Granularity | Reported accuracy | Tag |
|---|---|---|---|
| URL ccTLD / domain allowlist (.es plus elpais.com, rtve.es, …) | document | high precision by construction; 33% of OSCAR es docs have a ccTLD | [PRIMARY] (CEREAL) |
| CEREAL docTransformer (XLM-R large, n×512 chunks) | document | 3-class es/mx/mix **89.0% test**; 4-class 89.65%; 5-class 88.8% | [PRIMARY] ([NAACL 2024](https://aclanthology.org/2024.naacl-long.204)) |
| Sentence-level variety ID (DSL-TL, AR vs ES) | sentence | **~77%**; ~38% of sentences carry no variety signal; human annotators **54.9%** | [PRIMARY] ([arXiv 2412.11750](https://arxiv.org/html/2412.11750v1)) |
| 2pl-informal regex (`vosotr[oa]s`, `os`, `vuestr…`, `-áis/-éis/-ís` with a `país/maíz` stoplist, `-ad/-ed/-id`, `-aos/-eos/-íos`) | document | **no published P/R**; near-deterministic positive, sparse; `os` collides with other languages, so require ≥2 distinct markers | inference |
| Lexical contrast pairs (coche/carro, zumo/jugo, ordenador/computadora, móvil/celular, aparcamiento/estacionamiento, vale) | document | soft score | inference |

Filter at **document** level; sentence-level ID is too weak. For an es-419 replay or anchor set,
apply the mirror rule: drop any document with a vosotros hit.

### 2c. Is there enough spoken 2pl conversational text?

**Unknown, and probably not in the licensed sources.** No published per-corpus vosotros frequency
was found in English or Spanish searches. A plausible ranking, entirely unmeasured, is: EU-dubbed
subtitles > forums/comments > fiction dialogue > web prose > parliament ≈ BOE ≈ 0. The sources likely
to be dense are exactly the ones that are licence-blocked (OpenSubtitles, RTVE, spoken corpora).
Web volume is not the constraint: 70.5M .es segments is plenty for lexicon-level CPT at 3–4B
(inference). **Register and grammatical person are the constraint.**

Two consequences:
- **CPT on the licensed stack would mostly teach Spain lexicon and discourse markers, not 2pl
  address.** The forums/recipes slice is where vosotros appears, and how big that slice is has not
  been measured. Measure it (Needs measuring #6): it takes about an hour to run the regex over
  ParlaMint-ES, a .es HPLT/FineWeb-2 sample and a Galdós sample, and report hits per 10k tokens.
- **Dense vosotros data has to be synthetic**, from an Apache-2.0 teacher (11 §3a) prompted over a
  grid of scenario × register × addressee plurality and filtered by the regex. Raw-text CPT on
  synthetic group dialogue is SFT without the chat template, so at that point the line between "CPT"
  and 11's SFT disappears. Salamandra (Apache-2.0, BSC) is a Spain-centric teacher candidate, but
  its vosotros accuracy is unmeasured ([arXiv 2502.08489](https://arxiv.org/abs/2502.08489)) [PRIMARY].

---

## 3. Layer replacement and model surgery

### 3a. Layer swapping (Bandarkar et al. 2024)

**Method** [PRIMARY] ([arXiv 2410.01335](https://arxiv.org/html/2410.01335)): fine-tune two experts
from the same base, one on target-language instruction data and one on English math. Then replace
the math expert's **bottom 5 and top 2 of 32 layers** (Llama 3.1 8B) with the language expert's. The
choice follows from where each expert's weights moved:
- The language expert changed attention most in the first and last few layers; its FFNs barely moved
  until the last layers.
- The math expert barely changed its bottom 16 layers.

**Results**, MGSM 8-shot avg (math expert → swap) [PRIMARY]:

| Language | Math expert | Layer swap |
|---|---|---|
| Swahili | 29.5 | 32.4 |
| Telugu | 20.1 | 22.7 |
| Bengali | 38.3 | 37.1 |
| Japanese | 42.7 | **38.5** |

The abstract's "10%" is relative and cross-language, and the per-language effects are mixed.

**The same edge-vs-middle pattern elsewhere:**
- MoE routing is language-specific at the edges and aligned in the middle, and steering only helped
  in the middle (~1–2%) ([arXiv 2510.04694](https://arxiv.org/html/2510.04694v1)) [PRIMARY/SECONDARY].
- Logit lens on Llama-2 finds English-ish middle layers ([Wendler et al.](https://arxiv.org/abs/2402.10588)) [PRIMARY, not re-read].

**For drill:** the swap analogue is to train an es-ES expert from the same instruct model (LoRA-CPT or
SFT), fuse it, and copy only its edge layers into the instruct model. Cost is the expert run plus a
CPU tensor copy. The result is a dense checkpoint that ships like any model.

Two problems:
1. **Variety is not language.** The Arabic dialect evidence (3b) puts the useful lever **mid-stack**,
   not at the edges. Which layers to swap is an empirical question, and it is exactly what §4
   answers.
2. **A swap is unconditional.** An es-ES-swapped model is an es-ES model. drill would ship two GGUFs
   (11 §3d's two-adapter column) or accept leakage.

**Survives Q4/Q8?** Not studied. A full-SFT expert's layers move further than a LoRA delta, so they
are more likely to survive Q4 (**UNVERIFIED**). Q8 is effectively free for Spanish (02a). No
evidence exists at 3–4B, for variety, or for Qwen3/Gemma 3/SmolLM3.

### 3b. Language-specific neurons and layers; dialect is distributed

| Finding | Scale | Tag |
|---|---|---|
| LAPE (Tang et al., ACL 2024): language-specific neurons sit mostly in the **top and bottom layers**; activating or deactivating them steers output language | LLaMA-2, BLOOM, Mistral | [PRIMARY] ([arXiv 2402.16438](https://arxiv.org/abs/2402.16438)) |
| Kojima et al. 2024: same edge-layer finding, language steered via neurons | decoder PLMs | [PRIMARY, not re-read] ([arXiv 2404.02431](https://arxiv.org/abs/2404.02431)) |
| Neural FOXP2: per-layer SAEs → language neurons → SVD of English→target activation differences → signed sparse shift in **low-to-mid layers** makes Spanish/Hindi the default | LLaMA-3 8B per 11; sizes not in the abstract | [PRIMARY] ([arXiv 2602.00945](https://arxiv.org/abs/2602.00945)) |
| **Arabic dialects** (Elozeiri et al. 2026): dialect neurons are <1% of MLP dims but span only **5–21%** of the residual dialect direction. **Neuron steering cannot induce dialect from MSA prompts; vector steering can.** Best layers mid-stack (ALLaM 11–20 of 32; Fanar 19–24 of 42), α 1–3, steering only the **first 30 generated tokens**. ADI2: Fanar EGY **0.018→0.384**, MOR 0.025→0.410, SAU 0.004→0.010. Coherence falls at high α. **The explicit-prompt baseline led on raw ADI2.** | 7B, 9B | [PRIMARY] ([arXiv 2607.03936](https://arxiv.org/html/2607.03936v3)) |
| Ferrando & Costa-jussà: English and Spanish subject–verb agreement in Gemma 2B share a circuit, driven mainly by **one attention head** writing a language-independent "subject number" direction to the last position. The English direction flips Spanish verb number | 2B | [PRIMARY] ([arXiv 2410.06496](https://arxiv.org/abs/2410.06496)) |
| "A Universal Vibe?": a small cross-lingual informal-register SAE subspace that sharpens in deeper layers; steering transfers to 6 unseen languages; ~90% of completions stay in the target language | Gemma-2-9B-IT | [PRIMARY abstract] ([arXiv 2603.26236](https://arxiv.org/abs/2603.26236)) |

**Implication.** Vosotros sits on two axes: *variety* (es-ES vs es-419) and *formality* (Spain's
formal plural is ustedes). The plausible mechanism is a distributed residual direction (dialect,
register), not a neuron set. Neuron surgery (LAPE-style) is the wrong tool. Expect diff-in-means at a
mid layer to work and neuron ablation to be weak. **Cost:** a LAPE pass is a forward sweep over two
corpora, minutes to an hour on the Air (inference). **Ship:** neuron masks are a weight edit and ship
as GGUF, but the Arabic result says they won't induce the variety.

### 3c. Merging: task arithmetic, TIES, DARE, Chat Vector

- **Chat Vector** (1c) is task arithmetic with a single delta and is the only merge with
  language-adaptation numbers.
- Task arithmetic, TIES (trim, sign-elect, disjoint merge), DARE (random drop and rescale of deltas)
  and Sakana's evolutionary merge exist ([2212.04089](https://arxiv.org/abs/2212.04089),
  [2306.01708](https://arxiv.org/abs/2306.01708), [2311.03099](https://arxiv.org/abs/2311.03099),
  [2403.13187](https://arxiv.org/abs/2403.13187)) [PRIMARY, not re-read]. **None in the notes is
  about language or variety adaptation.**
- Layer swapping beat the best model soup on Swahili and Telugu (3a).
- **mergekit** supports Linear, SLERP, Task Arithmetic, TIES, DARE, DELLA, Model Stock, Passthrough
  and more. It "can be run entirely on CPU or accelerated with as little as 8 GB of VRAM", with lazy
  out-of-core loading, under LGPL-3.0. The README names Llama, Mistral, GPT-NeoX and StableLM, and
  **Qwen3/Gemma 3 support is unconfirmed** (check `mergekit/_data/architectures/`)
  ([README](https://github.com/arcee-ai/mergekit)) [PRIMARY].

**Where TIES/DARE would earn their keep:** when merging *two* deltas, e.g. (variety-CPT − base) +
(instruct − base). Interference between them is what TIES's sign election targets. Task arithmetic
with a coefficient sweep is the baseline to beat. **Cost:** CPU only. A 4B fp16 model is ~8 GB per
copy (computed), and lazy loading should keep it within 16 GB (UNVERIFIED). **Ship:** dense
checkpoint → `convert_hf_to_gguf.py` → `llama-quantize`.

### 3d. Partial-layer fine-tuning

- **mlx-lm `--num-layers N` trains the *last* N blocks** (`model.layers[-max(num_layers,0):]`). The
  surgery notes had flagged this as unverified; the interp notes confirmed it from source
  ([tuner/utils.py](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/tuner/utils.py))
  [PRIMARY]. **The default LoRA (16 layers) never touches the bottom half.** Training only the
  bottom/edge or a located middle window needs ~10 lines of custom code that applies the same LoRA
  conversion to chosen `model.layers[i]`.
- LISA samples a random subset of layers to train each step and matches LoRA at similar memory
  ([arXiv 2403.17919](https://arxiv.org/abs/2403.17919)) [PRIMARY, not re-read].
- **No partial-layer study for dialect or variety exists.** The justification is entirely §4's
  localization plus 3a's "language changes concentrate in edge attention".
- **Ship:** identical to 11 (fuse → GGUF → quantize). An adapter over fewer layers is smaller. Note
  `--export-gguf` covers only llama/mistral/mixtral, so Qwen3 and Gemma 3 must go through llama.cpp
  ([LORA.md](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/LORA.md)) [PRIMARY].

### 3e. Activation steering and directional ablation

**Methods:** ActAdd, CAA (Llama 2 7B/13B chat), RepE, ITI, repeng
([2308.10248](https://arxiv.org/abs/2308.10248), [2312.06681](https://arxiv.org/abs/2312.06681),
[2310.01405](https://arxiv.org/abs/2310.01405)) [PRIMARY, not re-read]. Diff-in-means (mass-mean)
directions are more causally implicated than logistic-probe directions
([Marks & Tegmark](https://arxiv.org/abs/2310.06824)) [PRIMARY].

**Reliability:**
- Steerability varies widely across inputs and is brittle to reasonable prompt changes out of
  distribution. It depends more on the dataset than the model, and some datasets show
  **anti-steerability for almost 50% of inputs** ([Tan et al., NeurIPS 2024](https://arxiv.org/pdf/2407.12404))
  [PRIMARY/SECONDARY].
- Higher cosine among the per-pair activation differences predicts better steering
  ([arXiv 2505.22637](https://arxiv.org/pdf/2505.22637)) [SECONDARY]. That gives a cheap pre-check.

**Baking into weights:**
- **Additive steering cannot be baked into stock Qwen3.** In mlx-lm `qwen3.py`, `o_proj` and
  `down_proj` are `nn.Linear(…, bias=False)` ([qwen3.py](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/models/qwen3.py))
  [PRIMARY]. Llama and Gemma are also bias-free by default (UNVERIFIED for Gemma 3 and SmolLM3
  configs). An additive vector would need tensors the GGUF loader does not read. A LoRA cannot
  express it either: LoRA is input-dependent and the vector is a constant add. The shippable proxy is
  **distillation**: train a small LoRA to imitate the steered model (inference).
- **Directional ablation can be baked in.** Arditi et al. orthogonalize every residual-writing matrix
  (embeddings, attention out, MLP out, plus output biases), `W ← W − r̂r̂ᵀW`. This is proven
  equivalent to inference-time ablation, and was shown on Qwen 1.8B/7B Chat and Gemma 2B/7B IT
  ([arXiv 2406.11717](https://arxiv.org/html/2406.11717)) [PRIMARY]. It produces a normal GGUF. **It
  can only remove a direction.** Projecting out an "es-419-ness" direction does not guarantee the
  model falls into es-ES, given a near-zero es-ES baseline. It also applies unconditionally, so it
  would mean one GGUF per variety.

**Runtime support:**

| Runtime | Steering support | Tag |
|---|---|---|
| llama.cpp | `cvector-generator` (PCA or `--method mean`) → `.gguf` control vector; `--control-vector-scaled`, `--control-vector-layer-range`; README: "works better when apply to layers higher than 10" | [PRIMARY] ([README](https://github.com/ggml-org/llama.cpp/blob/master/tools/cvector-generator/README.md)) |
| llama-server | control vectors are **startup flags only**, with no per-request field (LoRA does have `/lora-adapters` and a per-request `lora` field); changing the scale needs a restart (open issue) | [PRIMARY] ([server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)); [SECONDARY] ([#10685](https://github.com/ggml-org/llama.cpp/issues/10685)) |
| **Ollama** | **no control-vector parameter found.** Since v0.40.0 it runs MLX on Apple Silicon (12), but the missing control is API surface, not backend | [SECONDARY] ([Modelfile](https://docs.ollama.com/modelfile)) |
| **mlx-lm** | no built-in hook, but `Model.layers` is a plain list of `TransformerBlock`s iterated in `for layer, c in zip(self.layers, cache)`. Wrap entry *i* to add α·v̂ to `h`, or ablate it; the switch can be per request | [PRIMARY] ([qwen3.py](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/models/qwen3.py)) |

**Conflict to flag (Ollama adapters).** 11 §5b says Ollama **v0.34.1 removed `ADAPTER`**
(`errAdaptersUnsupported`, commit 98acec40ae). This session found that **current Ollama docs still
document `ADAPTER`** for Safetensors and GGUF LoRA adapters, listing Llama/Mistral/Gemma 1–2 and Llama
3.2 ([import](https://docs.ollama.com/import), [Modelfile](https://docs.ollama.com/modelfile))
[SECONDARY], and found no release-note confirmation of the removal. Neither pass is conclusive; docs
can lag code. 11's Needs-measuring #8 (`ollama --version` plus a throwaway `ADAPTER` Modelfile) still
settles it. **The recommendation does not depend on it:** even before the claimed removal, `ADAPTER`
did not cover Qwen3/Gemma 3, so a merged GGUF remains the Ollama path.

### 3f. Quantization survival, all surgery options

- **Steering directions survive weight quantization well at 7–9B.** Cosine to FP16 is
  **0.989–0.998 (INT8)** and **0.945–0.990 (NF4)**. Sentiment steering was "Equivalent" under INT8
  and "Inconclusive" under NF4. Compression alone cut Mistral-NF4 GSM8K 0.545→0.365 at α=0
  ([arXiv 2609.06473](https://arxiv.org/abs/2609.06473)) [PRIMARY]. Runtime steering adds in fp
  activations after dequantization, so it is less exposed to rounding (inference).
- **Small weight deltas may be rounded away at 4-bit.** Unlearned models kept ~21% of the target
  knowledge at full precision and **~83% after 4-bit quantization**
  ([arXiv 2410.16454](https://arxiv.org/abs/2410.16454)) [PRIMARY]. The likely mechanism is that a
  small delta falls inside one quantization bin. That is an inference, but it applies to LoRA merges,
  chat-vector scaling, orthogonalization and gentle CPT alike.
- 02a: Q8 is effectively free for Spanish; 4-bit is a real risk below ~7B.
- **Gate the exact shipped artifact** (GGUF Q8_0/Q4_K_M, MLX 8/4-bit), never fp16.

| Option | Ship artifact | Q8 | Q4 | Tag |
|---|---|---|---|---|
| Layer swap | dense GGUF/MLX | likely fine | larger delta, more likely to survive | UNVERIFIED |
| Chat-vector / TIES / DARE merge | dense GGUF/MLX | likely fine | risk if the variety delta is small | inference from 2410.16454 |
| Partial-layer LoRA, fused | dense GGUF/MLX | likely fine | same risk as 11's LoRA | inference |
| Orthogonalization | dense GGUF/MLX | likely fine | **highest risk**: a rank-1 edit per matrix | inference |
| Runtime steering (MLX) | stock weights + ~5 KB vector per layer | fine | direction cos 0.945–0.990 at NF4 (7–9B) | [PRIMARY] for 7–9B |

---

## 4. The interp angle: locate the switch, then intervene only there

**Why it matters for drill specifically.** There are at least three candidate failure sites, and
each points to a different intervention:
- **(S1) Variety identity is not read from the system prompt.** The "zumo" echo suggests the model
  takes variety from local lexical context instead.
- **(S2) The addressing decision.** The model chooses not to address the group at all (the dodge),
  which happens upstream of any verb.
- **(S3) The agreement step.** Given a 2pl informal addressee in es-ES, the model picks ustedes
  morphology anyway. This is Ferrando-style late agreement.

S3 alone would favour late-layer LoRA or a logit fix. S1 or S2 would favour a mid-layer direction
injected from the system prompt onward. **No prior interp work localizes Peninsular vs LatAm Spanish,
vosotros/ustedes, or T-V address in any model**, so this is an open seam as well as a ship question.

### 4a. Model choice

| | **Gemma 3 4B (it + pt)** | **Qwen3-4B-Instruct-2507 (+ Qwen3-4B-Base)** |
|---|---|---|
| Why | **Gemma Scope 2** SAEs (`resid_post`, `attn_out`, `mlp_out`) and transcoders for **every layer**, PT and IT; headline depths 25/50/65/85% ≈ layers 8/17/22/29 (computed; check the folder names) ([HF](https://huggingface.co/google/gemma-scope-2-4b-it)) [PRIMARY]. P3B3 shows Gemma is the most prompt-steerable small family (Gemma-4-E4B 21.9→94.4) | 11's **licence-preferred** ship base (Apache-2.0). Shares the target tokenization with Llama 3.2 and SmolLM3 |
| Geometry | 34 layers, d=2560, **8 query heads** × 34 = **272 heads**, 5:1 local/global attention (window 1024; irrelevant at short T) | 36 layers, d=2560, 32 query heads × 36 = **1,152 heads** |
| bf16 size | ≈3.88B text-only ≈ **7.8 GB** (load without the vision tower) | ≈4.02B ≈ **8.0 GB** |
| Head sweeps | ~4× cheaper (computed) | expensive; use attribution patching first |
| Licence for shipping | Gemma Terms pass-through (11 §5c) | Apache-2.0 |
| Base/instruct pairing | same-release pair (UNVERIFIED) | 2507 ↔ Base pairing **unverified** |

All [PRIMARY] from the HF `config.json` files ([Qwen](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507/resolve/main/config.json),
[Gemma mirror](https://huggingface.co/unsloth/gemma-3-4b-it/resolve/main/config.json)); parameter counts are computed.

**Recommendation:**
- **Dissect Gemma 3 4B first.** It has SAE features, cheaper head sweeps and single-token targets
  (4b), and it is the base most likely to be prompt-steerable, which is Verdict step 1 anyway.
- **Replicate the located-layer result on Qwen3-4B-Instruct-2507** because that is what would ship.
- **Run PT and IT checkpoints of each.** The difference separates a pretraining prior from a
  post-training (chat-template) prior. That is the empirical question behind "CPT vs SFT".

### 4b. Tokenization: what the metric can be

Measured from each tokenizer.json with HF `tokenizers`, leading space included [PRIMARY]:

| Item | Qwen3 / Llama 3.2 / SmolLM3 | Gemma 3 |
|---|---|---|
| queréis / quieren | [" quer","éis"] / [" qu","ieren"] | [" quer","éis"] / **1** |
| tenéis / tienen | 2 / 1 | **1 / 1** |
| vosotros / ustedes | [" vos","otros"] / [" usted","es"] | **1 / 1** |
| sois, habéis, podéis, hacéis, estáis | 2 each (most end in "éis") | 2 each |
| **os / les** | **1 / 1** | **1 / 1** |
| **vais / van** | **1 / 1** | **1 / 1** |
| zumo / jugo | 2 / 2 | 2 / 1 |
| coche / carro | 2 / 1 | 1 / 1 |

Consequences:
- **Do not use first-token logit difference on queréis/quieren** in Qwen, Llama or SmolLM3. " qu" is
  a generic prefix (qué, que, quién), so p(" qu") does not measure ustedes-ness.
- **Primary metric: summed teacher-forced log-prob** of the full form. For each pair, Δ = Σ log
  p(vosotros-form tokens) − Σ log p(ustedes-form tokens).
- **Clean single-token sanity set: os/les and vais/van** in all four models. Gemma adds tenéis/tienen
  and vosotros/ustedes.
- **Suffix probe:** p("éis" | " quer") across layers tracks when 2pl-informal agreement is
  committed. The stem is shared, so this is a clean conditional.
- Lexical pairs differ in token count across models, so use summed log-prob there too.
- The chat-template tokens were not checked. Check them before building system-prompt contrasts.

### 4c. Minimal-pair dataset (~200–500 pairs per family, held-out templates and cities)

Corruption is **symmetric token replacement** (the counterpart cue at the same length), not Gaussian
noise, and the metric is logit/log-prob difference
([Zhang & Nanda](https://arxiv.org/abs/2309.16042)) [PRIMARY]. **Cue token counts must match per
model.** Check with the tokenizer, and pad with neutral tokens if needed.

| Family | Clean vs corrupt | Target slot | What it isolates |
|---|---|---|---|
| **A. Variety, system-prompt cue** | drill's es-ES vs es-419 system prompt, length-matched (e.g. "España" vs a same-length LatAm country) | "Chicos, ¿qué ___" / "¿___ a pedir?" (vais/van) / "¿___ traigo…?" (os/les) | **the actual production conditioning signal** (S1) |
| **B. Variety, in-context cue** | "Estoy en Madrid con mis amigos." vs "Estoy en Bogotá…"; "Vale, tío," vs "Órale, güey,"; "un zumo" vs "un jugo" | same | lexicon/city as variety evidence. Also tests the "zumo" echo: does a learner lexeme outrank the system prompt? |
| **C. Formality control (Spain-internal)** | "Chicos, ¿qué…" vs "Señores, ¿qué desean…" (both es-ES) | 2pl verb | v_formality, so v_variety can be checked for orthogonality to it |
| **D. Addressing decision (the dodge)** | group addressee ("Somos dos", "Chicos") vs single addressee ("Chico") | reply-initial position, **before any verb** | P(2pl address at all) (S2). Metric: teacher-forced log-prob of matched continuations, 2pl ("¿Qué queréis…") vs 2sg ("¿Qué quieres…") vs impersonal ("¿Qué se…"); plus the sampled rate of any 2pl form in the first k tokens |
| **E. Neutral baseline** | no variety cue | all targets | baseline P(vosotros) |
| **F. Conflict** | es-419 system prompt + Spain lexeme from the learner (and the mirror) | lexical slot + 2pl slot | the echo directly: which cue wins, at which layer |

Out of scope but noted: voseo (Río de la Plata) is a third pronoun system, so keep es-419 cues
non-voseante.

### 4d. Protocol

**Phase 0: behavioural decomposition** (before any internals). On the candidate bases, sample 11's
group-address probes at deployment T. Log three rates:
- P(addresses group in 2pl),
- P(vosotros | 2pl),
- P(echo of the other variety's lexeme).

The qwen2.5:3b result (0/13, mostly dodges) says the first factor is small, but that is one model.
**If P(vosotros | 2pl) is high and only the address rate is low, the target is S2, not
morphology.**

**Phase 1: probes.**
- At every layer, fit a diff-in-means direction and an L2 logistic probe on the residual at (i) the
  last cue token, (ii) the final prompt token, (iii) the first generated token. Label = es-ES/es-419.
- Report **selectivity** = accuracy − accuracy on a control task with random labels per cue type
  ([Hewitt & Liang](https://arxiv.org/abs/1909.03368)) [PRIMARY].
- **Cross-cue transfer:** train on family B lexical cues and test on family A system-prompt cues
  and on held-out cities. A probe that only reads "zumo" will fail this.
- Compute cos(v_variety, v_formality) per layer (family C).

**Phase 2: logit lens.**
- Apply the final norm and unembedding to each layer's residual
  ([nostalgebraist](https://www.lesswrong.com/posts/AcKRB8wDpdaN6v6ru/interpreting-gpt-the-logit-lens), URL UNVERIFIED).
- Plot Δ(layer) for es-ES vs es-419 contexts on os/les and vais/van, and p("éis" | " quer").
- The first layer where Δ separates is the candidate decision layer.
- The logit lens is unreliable in early layers. A tuned lens fixes that
  ([Belrose et al.](https://arxiv.org/abs/2303.08112)) [PRIMARY], but no MLX implementation was
  found, so treat early-layer null results as uninformative.

**Phase 3: activation patching.**
- **Denoising first:** patch es-ES activations into the es-419 run, which finds sufficient
  components. **Then noising:** patch es-419 into es-ES, which finds necessary components. They
  answer different questions ([Heimersheim & Nanda](https://arxiv.org/abs/2404.15255)) [PRIMARY].
- Metric: normalized recovery (Δ_patched − Δ_419) / (Δ_ES − Δ_419).
- Sweep `resid_pre[l, p]` for every layer and every position from the first differing token on.
  Earlier positions are identical, so patching them is a no-op.
- Then `attn_out[l]` and `mlp_out[l]` per layer, then per head at the final position.
- Timings, all computed estimates from an extrapolated M3 prefill rate of ~310–330 tok/s for a 4B
  model (llama.cpp 7B PP512 187 tok/s scaled by params, [#4167](https://github.com/ggml-org/llama.cpp/discussions/4167); MLX bf16 may differ ±2×):
  - Residual sweep, Qwen3-4B, T=24, 16 post-cue positions: 576 runs per pair, **~43 s per pair,
    ~70–75 min per 100 pairs**.
  - Adding attn/mlp: **~3.5–4 h**.
  - Caching the shared-prefix KV and starting the forward at layer l cuts this ~50%.
  - Head patching at the final position: **~2.4 h per 100 pairs on Qwen (1,152 heads), ~0.6 h on
    Gemma (272)**.
  - Gemma's residual sweep is similar (34 vs 36 layers).
- Run the sweeps on families A, B and D separately. **The key comparison is whether A (system
  prompt), B (lexicon) and D (addressing) localize to the same layer window.**

**Phase 4: attribution patching for triage.**
- First-order patching via `mx.value_and_grad` on cached residuals: 2 forwards + 1 backward per pair,
  so **<1 min for 100 pairs** (computed).
- Rank all heads and MLPs, then verify the top-20 with exact patching.
- Use AtP* corrections for attention saturation and cancellation false negatives
  ([Syed et al.](https://arxiv.org/abs/2310.10348), [AtP*](https://arxiv.org/abs/2403.00745)) [PRIMARY].

**Phase 5: mechanism.**
- **H1 vs H2.** Patch only the 1-D variety direction (diff-in-means or 1-D DAS,
  [Geiger et al.](https://arxiv.org/abs/2303.02536)) at the best layer.
  - If it flips **both** os/les and zumo/jugo, variety identity mediates the pronoun system (H2:
    one switch).
  - If it flips lexicon but not pronouns, vosotros runs through a separate channel (H1: an
    agreement/addressing circuit à la Ferrando's single head).
- Path-patch from the top heads to the final position
  ([Goldowsky-Dill et al.](https://arxiv.org/abs/2304.05969)) [PRIMARY].
- On Gemma, encode the located layer's residual with the Gemma Scope 2 SAE (64k–256k width, medium
  L0) and look for "Spain", "2pl-informal" and "group-address" features. SAELens is PyTorch, so
  export `W_enc`, `W_dec` and `b` to safetensors and apply them in MLX (a matmul plus JumpReLU).

**Phase 6: interventions, each only at the located window.**
1. **Diff-in-means steering.** Add α·v̂ at layer(s) l\* to the residual.
   - Apply it to post-cue positions and generated tokens. Also test a first-30-tokens variant, which
     is what the Arabic setup used.
   - Sweep α. The Arabic study's chosen values were 1–3 in its own units, so recalibrate α to the
     residual norm here.
   - **Implementation:** wrap `model.layers[l*]` in mlx-lm (subclass `TransformerBlock.__call__`, or
     replace the list entry) to return `h + α·v̂`, with α set from drill's `variety` per request.
   - **Steer S2 separately:** add a "group-address" direction from family D, so the model addresses
     the group before the variety vector conjugates it.
2. **Directional ablation, then weight orthogonalization.**
   - Ablate the es-419 component at runtime and measure.
   - If it helps, bake `W ← W − r̂r̂ᵀW` into every residual-writing matrix
     ([Arditi et al.](https://arxiv.org/html/2406.11717)) [PRIMARY].
   - Convert to GGUF Q8_0 and Q4_K_M and re-measure. 3f flags this as the most quantization-fragile
     option.
   - The result is an es-ES-only artifact.
3. **Layer-selective LoRA vs controls.** Train with the same data (11's §3d synthetic group-address
   dialogues, both varieties tagged), the same rank and the same steps, under four layer selections:
   - (a) LoRA on the located window only;
   - (b) mlx-lm default, the last 16 layers;
   - (c) a random window of equal size, 3 seeds;
   - (d) all layers.

   **The interp claim holds only if (a) ≥ (d) > (c) on vosotros at equal Spanish quality.** If (b)
   wins, the localization was not load-bearing.
4. **(Optional) distil steering into weights for Ollama.** Generate with the steered MLX model and
   SFT a layer-selective LoRA to imitate it. This is the only way an additive vector reaches a GGUF
   (inference).

**Phase 7: evaluation.**
- Flip rate on held-out templates.
- **P(address group)** and **P(vosotros | 2pl)** separately.
- es-419 leakage. 11's tripwire is ≥95% no-vosotros in es-419.
- Echo rate (family F).
- **Anti-steerability fraction**, i.e. inputs that move the wrong way (Tan et al.).
- Held-out Spanish perplexity and EsCoLA MCC, against 02a's base values: gemma-3-4b-it 0.190.
- Language retention (no English).
- Then **11's full §6 gate**, multi-turn included, because P3B3's late-turn decay applies to
  steering too.

### 4e. Tooling state and feasibility on the Air

**Measured state of the machine** [PRIMARY, per notes]:
- `transformers` 4.57.3 sits on **torch 2.0.1**, which is too old. transformers needs ≥2.1 and
  disables PyTorch, so TransformerLens, nnsight and SAELens do not run as-is.
- **mlx_lm is not installed.**
- The only cached MLX model is `mlx-community/Qwen2.5-3B-Instruct-8bit`.

Day-0 setup: `pip install mlx-lm`, then fetch bf16 Gemma 3 4B (text-only) and Qwen3-4B-Instruct-2507.
Upgrade torch only if Gemma Scope via SAELens is wanted. PyTorch MPS needs macOS 14+ and cannot
offload ([HF](https://huggingface.co/docs/transformers/main/perf_train_special.md)) [PRIMARY].

**Libraries:**
- mlxterp ([GitHub](https://github.com/coairesearch/mlxterp)) has activation patching, logit lens
  and steering, but names only Llama/Mistral.
- Dyno Lab ([GitHub](https://github.com/canivel/dynolab)) is SwiftUI + MLX with patch sweeps and
  probes, but no SAE import.
- pyvene has an open MPS issue ([#67](https://github.com/stanfordnlp/pyvene/issues/67)).

**Recommended harness:** ~100 lines of hand-rolled MLX that wraps `TransformerBlock.__call__` to
stash, replace or add to `h`. Batch the patched variants along the batch dimension (equal lengths,
so no padding). Use `mx.value_and_grad` for attribution.

**Memory:**
- bf16 Qwen3-4B is 8.0 GB and Gemma text-only is 7.8 GB.
- The residual cache is ~4.4 MB per prompt (36 × 24 × 2560 × 2 B, computed), which is negligible.
- Leave ~4–5 GB headroom for macOS (UNVERIFIED rule of thumb). **This fits, but do localization in
  bf16, not 8-bit**: quantized weights perturb activations.
- Long sweeps on the fanless Air will throttle (11 §4). Run lid open and budget ~1.5–2× the computed
  times (UNVERIFIED factor).

**Feasibility verdict:** Phases 0–5 for one model and three families are **about 2–4 evenings of
compute on the Air** (computed from the estimates above; unmeasured). Phase 6 steering is minutes per
α point. Phase 6 LoRA is 11's QLoRA training cost × 4 arms.

---

## 5. Comparison against 11's SFT-LoRA path

Baseline facts for every row:
- drill needs **conditional** control.
- 11's train trigger is a raw per-sample vosotros p̂ < ~0.54.
- 11's ship bar is ≥90% group-address pass after ≤2 regenerations, with the es-419 tripwire at ≥95%.
- Ollama needs a merged GGUF; MLX can take adapters, fused models, or runtime code.

| Option | Cost | Spanish-quality risk | Ship: Ollama / MLX | Conditional? | Expected vosotros effect (evidence strength) |
|---|---|---|---|---|---|
| **Prompt + regenerate** (11 baseline) | $0 | none | ✓ / ✓ | ✓ (per-variety prompt) | Bounded by p. **qwen2.5:3b: 0/13, so ≤~54% at 3 samples even at the CI upper bound** (computed). Gemma-family prompt-steerability may be far higher (P3B3 pt analogue: 21.9→94.4). **Moderate evidence that base choice matters; none in Spanish.** |
| **SFT LoRA** (11) | Air $0 or rented **$0.34–2.22/run** (11, computed) | low with replay (LoRA forgets less) | merged GGUF / adapter or fused | ✓ (one tagged adapter) | **Generic SFT: negative** (Gervásio 46.6 ≈ base 47.7). **Targeted group-address SFT: untested.** Addresses S2 only if the data contains group-address turns. |
| **DPO** (after SFT, 11) | same + `mlx-lm-lora` | WPR drop seen in LCB (95.5→93.4) | same | ✓ (pairs flip with the tag) | Untested. **1–2-token vosotros/ustedes pairs invite likelihood displacement** (11 §3e). Strongest use is D-family pairs (address vs dodge), which have higher edit distance. |
| **CPT-LoRA on instruct** (.es web + replay) | Air pilot 10–30M tok ≈ 9–28 h at 300 tok/s (computed, UNVERIFIED speed); 0.1B+ rented | low–moderate; Québec reports minimal prestige regression, with noisy per-task rows | merged GGUF / fused | **✗** (shifts the prior); tagged-corpus variant UNVERIFIED | **Weak for vosotros**: the licensed corpus is light on 2pl (unmeasured). **Moderate for Spain lexicon** (Québec dialect gains at 87M tokens). Raises es-419 echo risk. |
| **CPT on base + chat vector** | rented H100 ≈ **$90–270 per 1B tokens** (computed) + data pipeline + the 2507↔Base pairing check | moderate: wrong-variety replies analogous to CV's wrong language; AMALIA lost GSM8K/BBH vs Gervásio | merged GGUF / fused | ✗ unless followed by tagged SFT (CP→FT+CV) | **Strongest evidence for moving the default** (AMALIA 91.2, observational, 9B, 5.8B tokens + post-training). Default ≠ conditional; still needs 11's SFT on top. |
| **Layer swapping** (es-ES expert edges → instruct) | cost of the expert + CPU copy | Japanese regressed (42.7→38.5) | dense GGUF / MLX | ✗ (one artifact per variety) | Language-level, modest (+2.9 Swahili avg); **no variety evidence**; which layers is unknown until §4. |
| **TIES/DARE merge** | CPU (mergekit; Qwen3/Gemma 3 support unconfirmed) | depends on the deltas | dense GGUF / MLX | ✗ | **No language/variety evidence in the notes.** A tool for combining CPT and instruct deltas, not an effect in itself. |
| **Partial-layer LoRA on located layers** | §4 localization (evenings on the Air) + 11's SFT cost | lower than full LoRA if the window is narrow (inference) | merged GGUF / adapter | ✓ (tagged data) | **No direct evidence; research bet.** Pays off if the (a) ≥ (d) > (c) ablation holds. Fewer layers means a smaller adapter. |
| **Runtime steering (diff-in-means/CAA)** | localization + minutes; no training | fluency falls at high α (Arabic); anti-steerability up to ~50% on some datasets | **Ollama: none. llama-server: startup-only (one process per variety). MLX: per-request, ~5 KB/layer** | **✓ free** (α set from `variety`) | Dialect vector steering moved Fanar EGY 0.018→0.384 (9B) **but prompting beat it on raw ADI2.** **Best as a supplement where prompting fails.** Survives NF4 (direction cos ≥0.945, 7–9B). |
| **Weight orthogonalization (baked)** | localization + CPU edit + conversion | small if the direction is clean (Arditi-style edits) | dense GGUF / MLX | ✗ (es-ES-only artifact) | **Can only remove** an es-419 direction; does not guarantee vosotros. Most Q4-fragile (inference). Mainly useful as a causal test. |

**Reading the table:**
1. **Only three options are naturally conditional:** prompting, tagged SFT/DPO, and runtime
   steering. Everything that edits weights unconditionally (CPT without tags, swaps, merges,
   orthogonalization) forces a second artifact for es-419 or risks the tripwire.
2. **Ollama users can only receive weight edits.** The best Ollama candidates are 11's tagged
   SFT-LoRA, ideally restricted to §4's located layers, or a distilled-steering LoRA.
3. **MLX users can receive runtime steering** on top of stock weights. drill already runs
   `_mlx_chat`, so this is one wrapper class and a vector file.
4. **CPT is the only option aimed at the default prior.** That is the wrong target unless the gate
   shows es-ES lexicon/naturalness failing *after* SFT, since vosotros is not what CPT data is rich
   in.

---

## Verdict

**Do not start with CPT. Start with base choice and measurement. Then use interp to decide between
runtime steering for MLX and layer-targeted LoRA for Ollama, and keep CPT as the last resort for
lexicon and naturalness, not for vosotros.** CPT has the only real evidence for moving a *default*
variety, but that evidence is observational, 9B, ~5.8B tokens plus in-variety post-training, with no
ablation. drill needs a *conditional* switch. The licensed Peninsular text CPT would use is rich in
Spain lexicon and probably poor in 2pl address. And the live measurement shows part of the failure is
the model **dodging group address entirely**, which no amount of Spain prose fixes.

Ordered plan, tied to 11's gate:

1. **Base choice, free.** Run 11's Needs-measuring #1 (≥40 group-address probes per variety × 5
   samples, T=0.7 and T=0.3) on gemma3:4b, Qwen3-4B-Instruct-2507, llama3.2:3b and SmolLM3-3B, logging
   the Phase 0 decomposition (address rate, vosotros | 2pl, echo rate).
   - **If any licence-clean base reaches per-sample p̂ ≥ 0.54 with es-419 no-vosotros ≥95%:** stop.
     Ship it with 11's free stack.
   - qwen2.5:3b is already out, on licence (11) and on p (0/13).
2. **Free stack on the best base** (11 Verdict step 4: few-shot, per-turn reminder, T 0.3–0.5,
   validator, and the lexeme map, which handles the "zumo" echo). Re-gate.
3. **Localize** (§4 Phases 0–5) on Gemma 3 4B, and replicate the key layer on the ship base. Decision
   criteria (proposed thresholds, to be set against the measured noise):
   - **Pass** if one contiguous window of ≤~4 layers recovers most of the logit difference under
     denoising patching on family A, the same window shows up for B, and the probe there has high
     selectivity and transfers across cue types.
   - Additionally, if family D (addressing) localizes to the same window, one vector can fix both
     factors.
   - **Fail** if recovery is smeared across the stack, or if A and B localize to different layers.
     Then surgery has no clean target, so skip to step 5 with standard all-layer LoRA.
4. **Steer at runtime (MLX path).** Use a diff-in-means vector at the located window, α keyed on
   `variety`, plus a group-address vector if Phase 0 says the dodge dominates.
   - **Ship criterion:** steered p̂ ≥ 0.54 per sample (so 11's ≥90% after ≤2 regenerations is
     reachable), es-419 no-vosotros ≥95%, EsCoLA/perplexity within the base's 95% CI, and
     anti-steerability under ~10% (proposed).
   - Measure on the **8-bit MLX** artifact that ships.
   - If it passes, MLX users get it as app code. Ollama users still need step 5.
5. **Weights for Ollama.** Use 11's step 7: one variety-tagged SFT-LoRA (plus optional DPO with
   address-vs-dodge pairs), run as **the §4 three-arm ablation**: located window vs last-16 default
   vs random window.
   - Ship the located-window adapter if it is ≥ the all-layer adapter on vosotros at equal regression
     scores (McNemar on paired probes, 11 §6c). Otherwise ship the default.
   - Fuse onto bf16, convert, quantize, and **re-gate on Q8_0 and Q4_K_M**.
   - If steering passed step 4 but SFT data is the bottleneck, distil the steered model into this
     LoRA.
6. **CPT only if** the SFT'd model passes vosotros but fails es-ES *lexicon/naturalness* on the
   multi-turn gate (e.g. Spain lexeme probes under 11's bars).
   - Then run a QLoRA-CPT pilot on the Air (10–30M tagged .es tokens + 5–25% replay) and re-gate both
     varieties.
   - Escalate to a rented base-CPT + chat-vector + tagged-SFT run (CP→FT+CV, ~$90–270 per 1B tokens
     computed) only if the pilot moves lexicon without tripping es-419.
   - Before any Qwen chat-vector work, verify the 2507↔Base pairing (per-layer ‖Δ‖ / cosine).
7. **Not on the plan:** neuron-level (LAPE) surgery, since dialect is distributed (Arabic result);
   untagged Spain-only CPT; orthogonalization as a ship artifact. Use orthogonalization only as a
   causal test, because it is unconditional and Q4-fragile.

**Why this order fits the owner's loop.** "Find the interp/topology → optimize what's load-bearing"
maps one-to-one onto steps 3 → 4/5. The three-arm LoRA ablation turns the interp finding into a
falsifiable efficiency claim: the located layers are load-bearing if and only if tuning only them
matches tuning everything. No paper has localized Spanish variety or T-V address. A clean result is
publishable as a byproduct.

## Needs measuring

| # | Experiment on the Air | What to run | Decision it informs |
|---|---|---|---|
| 1 | Address-vs-conjugation decomposition | 11's ≥40 group-address probes/variety × 5 samples (T 0.7, 0.3) on gemma3:4b, Qwen3-4B-2507, llama3.2:3b, SmolLM3-3B; classify each reply as vosotros / ustedes / 2sg / no-address; also the "zumo"/"jugo" echo rate both ways | Base choice. Whether the target is S2 (addressing) or S3 (morphology). Whether p ≥ 0.54 anywhere (stop here) |
| 2 | Tooling bring-up | `pip install mlx-lm`; bf16 Gemma 3 4B text-only + Qwen3-4B-2507; `mlx_lm.benchmark` prefill tok/s at T≈24 and 512; peak memory | Replaces the extrapolated ~310–330 tok/s; whether bf16 localization fits with headroom |
| 3 | Minimal-pair build + tokenizer audit | Families A–F, ~200–500 pairs each; length-match cues per tokenizer; check chat-template tokens; os/les, vais/van single-token sets | Validity of every metric in §4 |
| 4 | Probe + logit-lens sweep | Per-layer diff-in-means/logistic probes with control-task selectivity and cross-cue transfer; logit lens on os/les, vais/van, p("éis" \| " quer"); cos(v_variety, v_formality) | Candidate decision layer; whether variety ≠ formality |
| 5 | Patching sweeps | Residual (layer × post-cue position) denoising + noising, 100 pairs/family (~70–75 min each on Qwen, computed); attn/mlp per layer; attribution patching → top-20 heads exact | Steps 3 pass/fail; whether A, B, D share a window |
| 6 | Corpus vosotros density | Regex (≥2 distinct 2pl markers) over ParlaMint-ES, a .es HPLT/FineWeb-2 sample, Gutenberg Galdós; hits per 10k tokens | Whether any licensed CPT corpus carries 2pl at all; go/no-go on CPT-for-vosotros |
| 7 | Runtime steering | Wrap `model.layers[l*]`; α sweep; post-cue vs first-30-tokens; variety vector ± group-address vector; on bf16 and the shipped 8-bit MLX model | Step 4 ship criterion on MLX; quantization robustness of the direction |
| 8 | Orthogonalization round-trip | Bake `W − r̂r̂ᵀW` into residual writers; `convert_hf_to_gguf.py`; Q8_0 and Q4_K_M; re-measure | Whether a removal-only edit moves vosotros, and whether Q4 erases it |
| 9 | Three-arm layer-selective LoRA | Same tagged data/rank/steps: located window vs last-16 (mlx default) vs random window ×3 seeds vs all layers; 11's gate + McNemar + EsCoLA | Whether localization is load-bearing; which adapter ships to Ollama |
| 10 | Chat-vector pairing check | Per-layer ‖θ_2507 − θ_Base‖ and cosine (CPU, safetensors) for Qwen3-4B; same for gemma-3-4b-it/pt | Whether base-CPT + CV is even well-defined for the ship base |
| 11 | QLoRA-CPT pilot (only if Verdict step 6 triggers) | 10–30M tagged .es tokens + replay, `{"text": …}`, `--grad-checkpoint`, lid open; log tok/s and throttle curve; gate both varieties | Whether CPT moves lexicon without tripping the es-419 tripwire; Air vs rented GPU |
| 12 | Ollama adapter conflict | `ollama --version`; throwaway `ADAPTER` Modelfile (11 #8) | Resolves 11 (removed in v0.34.1) vs current docs (still documented) |
