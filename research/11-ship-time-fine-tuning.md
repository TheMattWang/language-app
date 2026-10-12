# 11 — Ship-time fine-tuning: worth it, and how

> Scope: whether drill should ship a fine-tune of its 3–4B conversation-partner model. It would be
> trained **once by the developer and shipped to every user**, and it would be judged on dialect/register
> adherence, persona and language-lock, and grammaticality. This is a different question from
> `04-rl-adaptation.md`, which rejected **per-user** weight adaptation at N=1. 04's objections (no data
> volume, no population, overfitting to one learner) do not carry over to a single developer-side run
> on synthetic data, so this file starts from scratch. It covers the evidence, the no-training
> alternatives, data, feasibility on the M3 Air, distribution (MLX and Ollama) with licences, and the eval
> gate that decides train vs not-train. Research date: 2026-10-12.
>
> **Sourcing convention (as in 02a):** [PRIMARY] means a paper, official docs, a licence file, or source
> code read this session. [SECONDARY] means a blog, aggregator or search snippet. **UNVERIFIED** means a
> claim with no fetched source, a single weak source, or background knowledge; treat it as a hypothesis.
> **computed** means my own arithmetic from stated inputs, not a measurement. Several primary sources
> were read through a summarizing fetcher rather than verbatim; this is flagged where it matters.
>
> **Scale warning that applies to all of §1:** almost no fine-tuning evidence below is on a 3–4B
> model. The nearest results are at 8B (Tülu 3, Abdulhai et al., P3B3's 8B rows) or 35B+ (Command R in
> LCB). Every transfer to 3–4B is an extrapolation and is labelled as one.

---

## TL;DR

1. **Don't train yet. The decision depends on one number nobody has measured: the vosotros base
   rate under sampling.** 06 ran one sample per probe. Validator + regeneration only *filters*. If a
   candidate base emits vosotros on a group-address turn with probability p, best-of-n succeeds with
   probability 1−(1−p)^n, and less than that because samples from one prompt are correlated. At
   p≈0.3, three tries give ~66% (computed). At p≈0, nothing at inference time rescues it except
   steering or a different base, and **a ship-time SFT LoRA becomes the justified next step.**
2. **Fine-tuning evidence is real but mostly at ≥8B, and it says that cheap fixes come first.** On
   Command R (35B), **5-shot prompting lifted monolingual line-level language-lock from 86.2 to 99.0**,
   which is as much as multilingual SFT gave (98.3). Preference tuning was the only lever that moved the
   hard cross-lingual case, where the user writes English (**78.2→89.4**). At 8B, DPO added
   **+8.3 IFEval points over SFT** (Tülu 3), and multi-turn PPO cut persona inconsistency by **>55%**
   (Llama-3.1-8B). On dialect, **generic pt-PT SFT did not install pt-PT under prompt control at 8B**
   (Gervásio-8B-ptpt scored 46.6/100 when prompted for pt-PT). That warns against expecting a small
   generic SFT to fix vosotros. Targeted contrastive data is a different intervention and is untested
   in the literature.
3. **LoRA reshapes behaviour; it does not add competence.** "LoRA learns less and forgets less." Use
   it for variety, language-lock and persona. Do not expect it to fix grammar the base lacks. For
   grammar, **base-model choice is the bigger lever** (02a).
4. **Ollama is the bottleneck for the no-training stack.** Ollama has **no `logit_bias`** and **no raw
   GBNF**, only `format` = JSON or a JSON schema. Token bans and grammars therefore need `llama-server`
   or mlx-lm `logits_processors`. drill's `_mlx_chat` already uses `make_sampler`, so the MLX seam is
   one argument away.
5. **Training is cheap; data and licences are the work.** A 3B QLoRA on a 16 GB M2 Pro peaked at
   **~2.5 GB** [SECONDARY]. Core mlx-lm has **no DPO**; the third-party `mlx-lm-lora` package does. A
   rented 24 GB GPU costs **~$0.34–2.22 per plausible run** (computed). Synthetic teacher data must
   come from **Apache-2.0/MIT open-weight teachers**: OpenAI, Anthropic and Gemini terms all forbid
   training competing models on outputs.
6. **Base-model licence changes the shortlist. Re-verify before acting.** **Qwen2.5-3B-Instruct is
   under the Qwen RESEARCH licence (non-commercial, "research or evaluation purposes only")**, yet it
   is drill's current default (`drill/llm.py`). Prefer **Qwen3-4B-Instruct-2507 (Apache-2.0)**, then
   **Gemma 3 4B** (terms pass-through), then **Llama 3.2 3B** (name must start with "Llama").
7. **Ship a merged model, not an adapter, to Ollama users.** One research pass found that **Ollama
   v0.34.1 (2026-09-14) removed LoRA `ADAPTER` support and in-tree GGUF quantization.** This is
   single-pass evidence; re-verify. The path is: fuse → llama.cpp `convert_hf_to_gguf.py` →
   `llama-quantize` Q8_0/Q4_K_M → `FROM model.gguf`. MLX users can take a **~13–60 MB adapter**
   (computed) or a fused 4/8-bit model.
8. **The current probe set can't decide anything yet.** 20 probes cannot rule out an 80% true pass
   rate (19/20 → Wilson lower bound **0.764**, computed). Separating 80% from 95% needs **~30–42
   independent probes** per behaviour. Claiming ≤5% failure at 95% confidence needs **59 consecutive
   passes**. The gate needs to be built before either training or ruling training out.

---

## 1. Does LoRA/QLoRA or DPO on a 3–4B instruct model fix the three failures?

06 measured three failures on the Air: (a) **vosotros failed by every model** despite an explicit
instruction plus a "Somos dos" cue; (b) **every model broke character into English within 5 turns**,
through single English words, parenthetical translations, or dropping the persona to become a tutor;
(c) **ungrammatical or invented Spanish**. It also found that **gemma2:2b produced Peninsular forms
(`os gustaría`, `venga`) spontaneously**. The forms are in the weights but not under instruction
control.

### 1a. Dialect / register adherence: generic SFT is not enough at 8B; targeted data is untested

| Evidence | Model scale | Finding | Tag |
|---|---|---|---|
| P3B3 (pt-PT vs pt-BR, multi-turn, 0 = pt-BR … 100 = pt-PT) | 8B–31B, frontier | Unprompted, most models lean pt-BR: Llama-3.1-8B **12.6**, Qwen3-8B **10.4**, Gervásio-8B-ptpt **12.7**. Prompted for pt-PT: Gemma-3-12b **92.9**, Qwen3.5-9B **86.1**, but **Qwen3-8B 32.7** and **Gervásio-8B-ptpt 46.6**. Paper attributes the gap to pre-training data and scale, "not fine-tuning alone." **Controllability degrades in later turns.** ([P3B3](https://arxiv.org/html/2606.16753v1)) | [PRIMARY], read via summarizer; column assignment inferred from prose, so treat individual cells with caution |
| AMALIA-9B | 9B | The only model "consistently biased toward pt-PT" (**91.2** unprompted, **95.9** prompted). It had pt-PT data in **both mid-training and post-training** ([AMALIA](https://arxiv.org/abs/2603.26511), [P3B3](https://arxiv.org/html/2606.16753v1)) | [PRIMARY] |
| Mayor-Rocher et al., 7 Spanish varieties | 9 models | Peninsular is "the best identified by all models"; only GPT-4o recognizes variation. This tests **identification (MCQ), not generation** ([arXiv 2504.20049](https://arxiv.org/abs/2504.20049)) | [PRIMARY] |

So what for drill: Gervásio is the cautionary case. **pt-PT instruction tuning at 8B still left the
model at 46.6 when explicitly prompted.** That was generic in-variety SFT, though, not training on
contrastive markers. drill's lever is narrower: the same reply in vosotros vs ustedes, with the label
set by the system-prompt variety. Since gemma2:2b shows the forms exist, **preference pairs and SFT
on group-address turns are the most plausible cheap lever. That is an inference; no paper tests it
on es-ES vs es-419 at any size.** P3B3's late-turn decay means any test must be multi-turn (§6).

### 1b. Language-lock and persona: few-shot first, preference tuning for the "user writes English" case

The Language Confusion Benchmark (LCB) separates **line-level** confusion (a whole reply in the wrong
language) from **word-level** confusion (single wrong-language words). All numbers below are on
Command R-class models, i.e. **35B+, extrapolated to 3–4B** ([Marchisio et al., LCB](https://arxiv.org/html/2406.20052)) [PRIMARY]:

| Intervention (Command R) | Monolingual LPR | Cross-lingual LPR | Monolingual WPR |
|---|---|---|---|
| Base, no template | 86.2 | 1.1 | — |
| 1-shot / 5-shot | 94.1 / **99.0** | 90.7 / 95.0 | — |
| English-only SFT | 77.8 | 78.3 | 96.2 |
| Multilingual SFT (as little as 10% multilingual) | **98.3** | 78.2 | 95.5 |
| + multilingual preference tuning | 98.9 | **89.4** | **93.4** (down) |
| + English-only preference tuning (on English SFT) | 74.3 | 85.7 | **90.9** (down from 96.2) |

On decoding, monolingual WPR falls from **97.2 at T=0 to 94.2 at T=0.7 and 86.5 at T=1.0**. drill
samples at **T=0.7** (`drill/llm.py`). Top-p matters less.

How this maps to 06's failures. A single English word ("directions") and parenthetical subtitles are
**word-level** confusion. Persona drop into an English-speaking tutor is **line-level** confusion plus
drift. The `breakdown` probe ("Sorry, I don't know how to say this…") is LCB's **cross-lingual**
setting. That is the one setting where SFT did nothing (78.3→78.2) and preference tuning helped
(→89.4). One model, one paper, so this is **weak evidence that DPO pairs earn their keep on exactly
drill's breakdown moment.** Preference tuning also *cost* word-level purity (95.5→93.4), so WPR must
be gated separately after DPO.

Persona drift: LLaMA2-chat-70B and GPT-3.5 show "significant instruction drift within eight rounds,"
which the authors attribute to attention decay over the system prompt ([Li et al.](https://arxiv.org/abs/2402.10962)) [PRIMARY]. 06's 5-turn drift in 2–3B models fits that; that small models
are *at least* as fragile is **UNVERIFIED but plausible**. **Multi-turn PPO with an LLM-judged
consistency reward on Llama-3.1-8B-Instruct cut inconsistency by >55%** and beat the SFT and KTO
baselines ([Abdulhai et al., NeurIPS 2025](https://arxiv.org/html/2511.00222)) [PRIMARY; SFT/KTO
numbers are only in a figure and were not extracted]. That is **8B**, and the ordering (online RL >
offline KTO/SFT) suggests single-turn SFT under-fixes multi-turn drift. **Train on multi-turn
dialogues where the user tries to pull the partner out of character.**

### 1c. Grammaticality: don't expect LoRA to buy it

"In the standard low-rank settings, LoRA substantially underperforms full finetuning" on code and
math, while it "better maintains the base model's performance on tasks outside the target domain"
([Biderman et al., LoRA Learns Less and Forgets Less](https://arxiv.org/abs/2405.09673)) [PRIMARY].
No paper fetched measures LoRA's effect on non-English grammaticality at 3–4B. Inference: SFT on
clean, native-reviewed restaurant dialogues should cut errors **inside that narrow domain** by
imitation. "una copa tinto" becomes less likely once 1k examples say "una copa de tinto". It will not
raise general competence. 02a's ranking is the bigger lever: EsCoLA MCC at 3–4B ranges **0.174–0.245**
across instruct models. Swapping base is free compared with a training run.

### 1d. DPO vs SFT for constraint adherence: bigger gain at small scale

| Model | IFEval (prompt loose) |
|---|---|
| Tülu 3 SFT 8B | 72.8 |
| Tülu 3 DPO 8B | **81.1** |
| Tülu 3 final 8B (RLVR) | 82.4 |

[PRIMARY, [model card](https://huggingface.co/allenai/Llama-3.1-Tulu-3-8B)]. The 70B gap is ~0.5 points
(SFT 82.1 → DPO 82.6). That figure is **UNVERIFIED (search snippet)**. If it holds, preference tuning
matters *more* for constraint-following at small scale, which points to **SFT → DPO** as the
order. ORPO/KTO head-to-heads at 3–4B were not found.

**§1 bottom line:** for (b) language-lock, cheap prompting fixes most line-level confusion and DPO
helps the cross-lingual case. For persona, multi-turn training data is needed. For (a) vosotros, the
evidence is negative for generic SFT and silent for targeted SFT/DPO. For (c) grammar, LoRA is the
wrong tool. Nothing here is measured at 3–4B.

---

## 2. No-training alternatives: what each fixes, and why they come first

The prior is that **inference-time fixes must be shown insufficient before any training run.** They
are reversible, they need no data pipeline, and drill already has the validator
(`drill/register.py`).

### 2a. Method × failure matrix

| Method | vosotros | LatAm/Spain lexicon | English leak | Persona | Grammar | Constraint |
|---|---|---|---|---|---|---|
| Validator + regenerate (n≤2) | **filters only; useless if base rate ≈0** | good (lexeme list) | good with lexicon + LID | partial (persona-name check) | partial (LanguageTool) | +0.35–0.81s per retry (06); samples correlated |
| Deterministic LatAm→ES post-replacement | no | good for nouns | no | no | **risk**: `la computadora → el ordenador` flips article gender | needs agreement handling |
| Logit bias / token bans | weak; positive bias on `os`/`-áis` likely ungrammatical | good if lexeme is a single whole-word token | good for function words (` the`, ` you`) and `(` | no | slight risk | **not in Ollama**; subword collateral |
| GBNF / JSON schema | no | no | can ban `(` | structural fields only | format limits degrade quality ([Tam et al.](https://arxiv.org/pdf/2408.02442)) | Ollama: JSON schema only |
| Few-shot in-persona turns + per-turn reminder + capped history | partial (UNVERIFIED) | partial | **good line-level** (LCB 5-shot 99.0) | **good** (targets attention decay, Li et al.) | neutral | context cost (prefill is ~free, 06) |
| Lower temperature (≤0.3–0.5) | no | no | helps word-level (LCB) | slight | helps (UNVERIFIED) | less variety |
| Control vector / steering | possible (research bet) | possible | possible | unknown | may degrade | llama-server: startup-only; MLX: custom hook |
| Different base model | **only real no-training fix if one base has p≫0** | plausible | varies | varies | **biggest lever** (02a) | licence (§5c) |

Sources: validator/LID/LanguageTool from [LanguageTool languages](https://dev.languagetool.org/languages)
(Spanish has 1644 XML rules; **the only variant is voseo, no es-ES/es-MX split**) [PRIMARY]; lingua-py
claims single-word accuracy, but only on the author's own benchmark ([GitHub](https://github.com/pemistahl/lingua-py)) [SECONDARY];
fastText `lid.176.ftz` scores ~83% on short WiLI extracts, which is general short text, not single
words ([vignette](https://erised.las.iastate.edu/CRAN/web/packages/fastText/vignettes/language_identification.html)) [SECONDARY]. Whole-utterance LID will miss
"directions" inside a Spanish sentence, so the existing `_ENGLISH` lexicon in `register.py` is the
right primary check and LID only a second signal.

### 2b. Regeneration can only find what the model already samples

If one sample passes with probability p and samples are independent, best-of-n succeeds with
probability 1−(1−p)^n (computed):

| p (per-sample pass) | n=1 | n=2 | n=3 | n=5 |
|---|---|---|---|---|
| 0.00 | 0 | 0 | 0 | 0 |
| 0.05 | 0.05 | 0.10 | 0.14 | 0.23 |
| 0.10 | 0.10 | 0.19 | 0.27 | 0.41 |
| 0.30 | 0.30 | 0.51 | 0.66 | 0.83 |
| 0.70 | 0.70 | 0.91 | 0.97 | 1.00 |

Samples from one prompt are **positively correlated**: a model that chose tú for this context tends to
choose it again. Real gains will therefore be smaller than the table. Treat it as an upper bound and
measure the empirical retry success directly. The latency budget allows 1–2 retries (08 §(a): clause-1
regenerate ≈0.2–0.3s). Regeneration therefore works for English leaks, which plausibly have high
per-sample p (UNVERIFIED), and fails for vosotros if p is near 0. 06's "the fix is
decoding/verification, not a bigger model" is right for English leaks. For vosotros it is **unproven
until p is measured.**

### 2c. Ollama withholds the controls that matter

- **`logit_bias`**: Ollama's OpenAI-compat page marks it unsupported, and the native options list
  has none ([Ollama OpenAI compat](https://docs.ollama.com/api/openai-compatibility), [API docs](https://raw.githubusercontent.com/ollama/ollama/main/docs/api.md)) [PRIMARY].
  llama.cpp `llama-server` takes `"logit_bias": [[id, false]]` for a hard ban, including string
  tokens ([server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md))
  [PRIMARY]. **Pitfall:** a string bias applies to *every* sub-token. Banning "carro" as `car`+`ro`
  would also suppress `cargar`, `caro` and `carta`. Ban only single whole-word tokens, or use a
  stateful prefix-trie processor.
- **Grammars**: Ollama `format` accepts `json` or a JSON schema; raw GBNF was proposed in
  [PR #2404](https://github.com/ollama/ollama/pull/2404) and is not documented. llama-server accepts
  `grammar` and `json_schema` [PRIMARY]. A grammar can ban `(` (killing parenthetical subtitles) but
  cannot express "Spanish, not English" or "use a 2pl verb" over free text.
- **mlx-lm**: `LogitsProcessor = Callable[[tokens, logits], logits]`, and `make_logits_processors(logit_bias=…)`
  exists ([sample_utils.py](https://raw.githubusercontent.com/ml-explore/mlx-lm/main/mlx_lm/sample_utils.py)) [PRIMARY].
  drill's `_mlx_chat` calls `generate(…, sampler=make_sampler(temp=…))`, so passing
  `logits_processors=[…]` is a small change and a stateful ban processor fits the signature.
- **Control vectors**: llama.cpp `cvector-generator` builds them from positive/negative prompt files
  (PCA or mean), applied with `--control-vector-scaled` at **server startup only**, not per request
  ([cvector-generator](https://github.com/ggml-org/llama.cpp/tree/master/tools/cvector-generator))
  [PRIMARY]. Language steering exists in the literature ([LAPE](https://arxiv.org/html/2402.16438v1),
  [Neural FOXP2 on LLaMA-3 8B](https://www.arxiv.org/pdf/2602.00945)) [PRIMARY], but **no paper steers
  between Spanish varieties**, and none at 3–4B. It is a research bet and a natural fit for the interp
  track. It is not a ship-time fix.

Note from 12: since **v0.40.0** Ollama runs supported architectures on MLX automatically on Apple
Silicon (12 §TL;DR) [PRIMARY per 12, unverified on hardware]. That changes nothing above: the
missing controls are API surface, not backend.

### 2d. Prompting moves that cost nothing

These are inferences from LCB and Li et al., and their effect on these models is **UNVERIFIED**:
- Write the system prompt *and* 2–5 few-shot turns in the target variety. drill's `SYSTEM_PROMPTS`
  are already in Spanish. Include one turn where the user writes English and the waiter stays in
  Spanish.
- Re-inject a short reminder in the latest user message every turn to counter attention decay.
- Cap history.
- Prefill the assistant turn ("¡Vale! ", "Venga, ") via mlx-lm prompt append or an Ollama partial
  assistant message.
- Drop T to ~0.3–0.5.

### 2e. Two dialects, one product

The user picks Spain or LatAm. Every no-training fix above is already conditional per variety. drill
has per-variety `SYSTEM_PROMPTS`, and `register.check(text, variety)` takes the variety. Lexeme bans
must be swapped per variety too: ban `carro` for es-ES and `coche` for es-419. Do not run a union
list. That consideration carries into training (§3d).

---

## 3. If training: data, counts, DPO pairs, risks

### 3a. Teachers: which outputs you may legally train a redistributed model on

| Teacher | Terms (date seen) | Usable? |
|---|---|---|
| OpenAI API | "Use Output to develop models that compete with OpenAI" prohibited. **Official page returned 403**; wording is from snippets and a 2024-12-11 mirror ([mirror](https://open.windriver.com/info/uni-license-list/licenses/openai-tou-20241211.html)) | **No** (UNVERIFIED current text) |
| Anthropic (Commercial, eff. 2025-06-17) | may not "build a competing product or service, including to train competing AI models" ([terms](https://www.anthropic.com/legal/commercial-terms)) [PRIMARY] | **No** |
| Gemini API (2026-04-28) | "may not use the Services to develop models that compete" ([terms](https://ai.google.dev/gemini-api/terms)) [PRIMARY] | **No** |
| Mistral API (Commercial, eff. 2026-09-25) | competition clause covers **image** outputs only; reverse-engineering clause remains ([terms](https://legal.mistral.ai/terms/commercial-terms-of-service)) [PRIMARY] | Arguably yes; read §2.2(e) |
| Qwen2.5-7B/32B-Instruct, Qwen3-32B, Qwen3-235B-A22B-Instruct-2507, Mistral-Small-3.2-24B, gpt-oss-120b | **Apache-2.0** (HF tags, 2026-10-12) [PRIMARY] | **Yes, cleanest** |
| DeepSeek-R1, DeepSeek-V3-0324 | MIT ([R1 LICENSE](https://huggingface.co/deepseek-ai/DeepSeek-R1/blob/main/LICENSE)) [PRIMARY]; *original* V3 licence counts synthetic-data distillation as a Derivative | Yes for MIT releases |
| Qwen2.5-72B (Qwen License) | must display "Built with Qwen"/"Improved using Qwen" ([LICENSE](https://huggingface.co/Qwen/Qwen2.5-72B-Instruct/blob/main/LICENSE)) [PRIMARY] | Yes, with notice |
| Llama 3.x | training on outputs forces **"Llama" at the start of the model name** ([3.3 LICENSE](https://github.com/meta-llama/llama-models/blob/main/models/llama3_3/LICENSE)) [PRIMARY] | Yes, with naming burden |
| Gemma | "Outputs are not deemed Model Derivatives", yet the same §1.1(e) sweeps in models trained on Gemma synthetic data ([Gemma Terms](https://ai.google.dev/gemma/terms)) [PRIMARY, quote truncated by fetcher] | Ambiguous; avoid as teacher |

Whether a 3B Spanish waiter "competes" with a frontier API is a legal question these sources do not
resolve. Not legal advice. The practical answer is to **use an Apache-2.0 teacher.** The largest that
fits is Qwen3-235B-A22B-Instruct-2507 or Mistral-Small-3.2-24B on a rented GPU or a host serving the
open weights. The host's own ToS is unchecked (**UNVERIFIED**). A 24B teacher at 4-bit may fit a 24 GB
card (UNVERIFIED).

**Gate the teacher first.** Run the §6 probe set against the teacher. A teacher that misses vosotros
20% of the time teaches the student to miss it, and the validator filter only removes what it can
detect. Teacher grammar errors propagate unless filtered; no paper quantifies this for Spanish.

### 3b. Human seed and replay data

No permissively licensed, dialect-labelled Spanish role-play dataset exists in what was searched, so
**the role-play data must be synthesized.** Permissive general-Spanish data is useful as **replay
against forgetting**: Aya Dataset/Collection (Apache-2.0), OpenAssistant oasst1/oasst2 (Apache-2.0),
bertin alpaca-spanish (CC-BY-4.0) (HF tags, [aya_dataset](https://huggingface.co/datasets/CohereLabs/aya_dataset), [oasst2](https://huggingface.co/datasets/OpenAssistant/oasst2), [alpaca-spanish](https://huggingface.co/datasets/bertin-project/alpaca-spanish)) [PRIMARY].
**Avoid for training**: PersonaHub (CC-BY-NC-SA; reuse the *method*), EsCoLA (CC-BY-NC-SA; fine for
eval), ChatSubs (NC; sources conflict on -ND), OpenSubtitles (`license:unknown`), and Magpie sets
(they inherit the generator licence, e.g. llama3.1).

### 3c. How many examples

- **LIMA**: 1,000 curated examples; a 16× increase "plateaus". **Adding 30 multi-turn dialogue chains
  took excellent responses from 45.2% to 76.1%** and fails from 15/42 to 1/46 turns ([LIMA](https://arxiv.org/html/2305.11206)) [PRIMARY; 65B base, ablation model size UNVERIFIED].
- **Deita**: 6K selected samples competitive ([arXiv 2312.15685](https://arxiv.org/abs/2312.15685)).
  **AlpaGasus**: 9k filtered beats 52k unfiltered ([arXiv 2307.08701](https://arxiv.org/abs/2307.08701)).
  **40 multilingual examples** improve multilingual instruction-following ([Shaham et al.](https://arxiv.org/abs/2401.01854)) [PRIMARY].
- **DPO**: "near optimal performance even with smaller subsets" ([Saeidi et al.](https://arxiv.org/abs/2404.14723)) [PRIMARY]; no 3–4B pair counts found.

Target (inference, extrapolated from 7B–65B): **~1–5k diverse multi-turn SFT dialogues of 6–10
turns, split across es-ES and es-419**, plus a replay slice of general Spanish/English instructions.
No canonical replay ratio was found. For DPO, a starting guess of ~1–2k pairs is **UNVERIFIED**; let
the §6 gate say when to stop. This regime is "superficial alignment" (format/register), not knowledge
injection. Biderman's ~100K-pair regime is for teaching new capability, which is not the goal.

### 3d. Pipeline, and one adapter vs two

Pipeline (inference, assembled from Self-Instruct/Magpie/Persona Hub/Deita practice, cited in notes):
1. Build a scenario taxonomy (venue × role × learner level × **variety** × goal × adversarial move:
   learner writes English / asks for translation / uses wrong-variety lexeme / groups up).
2. Have the Apache teacher generate at **low-moderate temperature** (LCB: high T raises confusion).
3. Filter with `drill.register.check` and the probe extras (`_uses_vosotros`, `_no_echo`).
4. Run an LLM-judge pass for naturalness, grammar and pragmatics. 06's "¿Cuánto os gustaría pagar?"
   is fluent nonsense, which a regex will not catch.
5. Near-dedup (MinHash or embedding).
6. Do diversity-aware selection.
7. **Have a native reviewer spot-check ~100 dialogues per variety.**

**One adapter conditioned on the variety tag vs two adapters:**

| | One adapter, variety in system prompt | Two adapters (es-ES, es-419) |
|---|---|---|
| What it learns | the *conditional* "vosotros iff es-ES", matching drill's existing `SYSTEM_PROMPTS[variety]` | an unconditional shift per adapter |
| Contrastive DPO | natural: same context, chosen/rejected **flip with the tag** | not available within one adapter |
| Over-correction risk | low if both varieties are in the data | an es-ES-only adapter can leak vosotros into LatAm use if users switch, but each is used alone |
| Ollama distribution | **one** merged GGUF (~2–3.4 GB) | **two** merged GGUFs, since adapters are gone (§5) |
| MLX distribution | one ~13–60 MB adapter | two small adapters, hot-swappable via `adapter_path` |

**Recommendation: one adapter, trained on both varieties with the tag.** It matches the app's runtime
contract and gives the cleanest DPO signal. It also halves Ollama download weight. If the es-419 base
rate is already high (measure it), es-419 data acts mostly as an anchor against over-correction. That
anchor is still worth having.

### 3e. DPO pairs from validator pass/fail, and their failure modes

- **On-policy pairs**: sample N completions per prompt from the SFT'd student. Chosen = passes
  validator and judge floor; rejected = fails. On-policy/negative-gradient methods beat offline
  ([Tajwar et al.](https://arxiv.org/abs/2404.14367)) [PRIMARY]. The validator is deterministic, so
  iterative rounds are cheap.
- **Likelihood displacement**: a vosotros/ustedes pair differs by one or two tokens. That is
  exactly the low-edit-distance, high-embedding-similarity case where DPO can **lower the chosen
  response's likelihood** and shift mass elsewhere ([Razin et al.](https://arxiv.org/abs/2410.08847), [Smaug/DPOP](https://arxiv.org/abs/2402.13228)) [PRIMARY].
  Mitigations: **add an SFT/NLL term on chosen** (DPOP or DPO+SFT), keep β moderate (mlx-lm-lora
  example uses 0.1), filter the most similar pairs (CHES), and mix in high-edit-distance pairs, for
  example a whole tutor-mode English turn vs an in-persona Spanish turn.
- **Length bias**: length-match chosen and rejected, or use SimPO's length-normalized reward
  ([Singhal et al.](https://arxiv.org/abs/2310.03716), [SimPO](https://arxiv.org/abs/2405.14734)) [PRIMARY].
- **Language of pairs**: English-only preference tuning **dropped WPR 96.2→90.9** (LCB). Pairs must be
  Spanish-side, and WPR is gated after DPO.

### 3f. Risks

- **Catastrophic forgetting**: observed "in LLMs ranging from 1b to 7b"; general instruction replay
  helps ([Luo et al.](https://arxiv.org/abs/2308.08747)) [PRIMARY]. LoRA forgets less than full FT and
  "helps maintain more diverse generations" (Biderman) [PRIMARY]. Use low rank, 1–3 epochs, and replay.
- **Spanish quality regression**: teacher errors are baked in, and narrow SFT can cut general
  Spanish. Gate on EsCoLA/La Leaderboard (§6d). No study quantifies this at 3–4B.
- **Breaking in-context translation**: an adapter hammered on "never emit English" may refuse or
  degrade drill's legitimate translation mode (inference). **Include translation-mode examples, with
  their own system prompt, in the SFT mix, and add a translation regression probe.**
- **Safety drift**: benign fine-tuning can degrade safety alignment ([Qi et al.](https://arxiv.org/abs/2310.03693)) [PRIMARY]. Add a small held-out refusal set.
- **Train/serve quantization mismatch**: a QLoRA adapter trained against 4-bit weights but served on
  Q8 or bf16 is slightly off-distribution (UNVERIFIED quality impact). See §4.

---

## 4. Feasibility: the Air vs renting a GPU once

**Memory is not the constraint.**
- Qwen2.5-3B-Instruct 4-bit on a **16 GB M2 Pro**, mlx-lm 0.32.0, `--num-layers 8 --batch-size 1
  --max-seq-length 512 --grad-checkpoint --mask-prompt`: **~2.5 GB peak**, 3.3M trainable params (0.108%),
  20 iters in ~16 s ([dev.to](https://dev.to/rainytechlab/fine-tune-an-llm-on-your-mac-with-mlx-qlora-in-16-seconds-real-run-no-cloud-39ni)) [SECONDARY, first-hand run].
- A second report gives a 3B **5.0 GB** peak at batch 2, seq 1024 [SECONDARY via snippet; article 403].
- Unsloth lists 3B at **3.5 GB QLoRA / 8 GB 16-bit LoRA** as CUDA minimums ([Unsloth](https://unsloth.ai/docs/get-started/fine-tuning-for-beginners/unsloth-requirements)) [PRIMARY].
- If 8 GB holds roughly for MLX, then **bf16 LoRA on a 3B is plausible on the Air**, which removes
  the QLoRA mismatch (UNVERIFIED on MLX).

**Tooling:**
- `mlx_lm.lora`: QLoRA is automatic when `--model` is quantized. Defaults are rank 8, scale 20,
  16 layers, and all Linear layers in those blocks (attention + MLP). `--mask-prompt` restricts
  loss to completions; use it ([LORA.md](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/LORA.md), [lora.py](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/lora.py)) [PRIMARY].
- **Core mlx-lm has no DPO.** `tuner/losses.py` has only KL/JS ([tuner](https://github.com/ml-explore/mlx-lm/tree/main/mlx_lm/tuner)) [PRIMARY].
- **`mlx-lm-lora`** (PyPI 5.8.6) adds SFT/DPO/CPO/ORPO/GRPO/Online-DPO with `{"prompt","chosen","rejected"}`
  JSONL and `--train-mode dpo --beta 0.1` ([GitHub](https://github.com/Goekdeniz-Guelmez/mlx-lm-lora)) [PRIMARY]. It publishes no DPO memory numbers. DPO adds a reference forward pass
  (adapter-disabled), so it should still fit at batch 1, seq ≤1024 (**UNVERIFIED**).

**Speed and heat are the real costs.**
- The M3 Air has ~100 GB/s of bandwidth against the M2 Pro's ~200 GB/s, so expect proportionally
  slower training (inference from specs). 06's decode numbers confirm the Air is bandwidth-bound.
- Under sustained load the M3 Air hit ~114 °C and throttled ([Wccftech](https://wccftech.com/m3-macbook-air-severely-throttles-under-load/)) [SECONDARY].
- Lid-closed GPU throughput "drops to around half"; the fanned 14" MBP is ~25% faster on the same chip
  ([Notebookcheck](https://www.notebookcheck.net/External-heatsink-helps-MacBook-Air-with-Apple-M3-achieve-significantly-better-performance.814308.0.html)) [SECONDARY].
- Run lid-open on a hard surface. Don't serve inference during training.
- 04's estimate of 20–60 min for a few hundred to 1k examples is itself unmeasured. A 3–5k multi-turn
  set plus DPO is plausibly several hours on the Air (**UNVERIFIED**; measure it, see Needs measuring).

**Renting once:**
- **RunPod** RTX 4090 at **$0.34/hr community, $0.74/hr secure** (structured data; the visible table
  shows $0.89) ([RunPod](https://www.runpod.io/pricing)) [PRIMARY, internally inconsistent].
- **Modal** L4 ~$0.80/hr (computed from $0.000222/s); the Starter plan includes $30/month of compute
  ([Modal](https://modal.com/pricing)) [PRIMARY].
- **Unsloth** free-Colab notebooks cover Llama 3.2 3B conversational and Qwen3 4B ([README](https://github.com/unslothai/unsloth)) [PRIMARY].
- At an assumed 1–3 GPU-hours (UNVERIFIED), a run costs **~$0.34–2.22 on a 4090, or $0 inside
  Modal's credit** (computed).
- Teacher generation with a 24B–235B model needs the rented GPU or a hosted endpoint regardless.

**Trade-off:**
- The **Air** yields an MLX adapter with no conversion, at $0, and is fine for 3–4B SFT. It is
  slow, thermally capped, and DPO tooling is third-party.
- **Cloud** gives PEFT adapters that llama.cpp's `convert_lora_to_gguf.py` and HF tooling accept
  directly, fast iteration for DPO rounds, and colocation with the teacher.
- Recommendation: **prototype SFT on the Air** (small sets, fast gate turnaround). **Do the full
  SFT+DPO run on a rented GPU in the same session as teacher generation** if the Air's measured
  it/s makes iteration take longer than an evening.

---

## 5. Distribution: MLX, Ollama, sizes, licences

### 5a. MLX users: adapter or fused

`mlx_lm.fuse --model … --adapter-path … [--dequantize] [--upload-repo]`. Fusing onto a 4-bit base
**dequantizes, adds `scale·BᵀAᵀ`, and re-quantizes with the same group size/bits unless
`--dequantize`** ([fuse.py](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/fuse.py), [tuner/lora.py](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/tuner/lora.py)) [PRIMARY]. `--export-gguf` only supports
`llama`/`mixtral`/`mistral`. It works for Llama 3.2 but **not for Qwen or Gemma 3** [PRIMARY].
Ship either:
- the **adapter** (`adapters.safetensors` + `adapter_config.json`), loaded with
  `load(base, adapter_path=…)`; or
- a **fused 8-bit model** on HF (02a: Q8 is effectively free for Spanish; drill's MLX default is
  already 8-bit). A fused QLoRA 3B at 4-bit measured **1.6 GB** [SECONDARY].

Computed adapter sizes (all 7 attention+MLP linears per block, params = r·(in+out), 16-bit):

| Base | r=8, 16 layers (mlx default) | r=16, 16 layers | r=16, all layers |
|---|---|---|---|
| Qwen2.5-3B | 6.7M ≈ 13 MB | 13.3M ≈ 27 MB | 29.9M ≈ 60 MB |
| Llama-3.2-3B | 6.9M ≈ 14 MB | 13.9M ≈ 28 MB | 24.3M ≈ 49 MB |
| Gemma-3-4B (text) | 7.0M ≈ 14 MB | 14.0M ≈ 28 MB | 29.8M ≈ 60 MB |

(computed from HF `config.json`; doubles if saved fp32. Qwen3-4B-Instruct-2507 not computed.)

### 5b. Ollama users: merged GGUF only

**LOAD-BEARING, SINGLE-PASS, RE-VERIFY.** Current `server/create.go` defines
`errAdaptersUnsupported = "LoRA adapters are no longer supported"` and returns HTTP 400 on any
adapter. Tag-bisect: absent in v0.34.0, present from **v0.34.1**
([create.go@v0.34.1](https://github.com/ollama/ollama/blob/v0.34.1/server/create.go)). The commit is
98acec40ae (2026-09-15): "drop GGUF conversion… so GGUF conversion and quantization stay in llama.cpp
tooling" ([commit](https://github.com/ollama/ollama/commit/98acec40ae)). Release notes: "GGUF model
creation now requires using llama.cpp tooling for safetensor conversion and quantization"
([releases](https://github.com/ollama/ollama/releases)). Import doc: "Ollama does not quantize GGUF
models during import." Create-time `--quantize` now covers only MLX safetensors imports (`int4, int8,
nvfp4, mxfp4, mxfp8`) ([import.mdx](https://github.com/ollama/ollama/blob/main/docs/import.mdx))
[PRIMARY, all from one research pass]. 12 independently found Ollama adapter support for
Qwen3/Gemma 3+ "undocumented", which is consistent but weaker. Even before removal, `ADAPTER` covered
only Llama/Mistral/Gemma 1–2 and warned against QLoRA adapters
([modelfile.md@v0.12.0](https://github.com/ollama/ollama/blob/v0.12.0/docs/modelfile.md),
[import.md@v0.12.0](https://github.com/ollama/ollama/blob/v0.12.0/docs/import.md)) [PRIMARY]. **Check
on the Air with `ollama --version` and a throwaway `ADAPTER` Modelfile before relying on either
claim.**

Path:
1. Fuse the adapter onto the **original bf16 base**, not a dequantized 4-bit one, which would
   compound quantization error.
2. Run llama.cpp `convert_hf_to_gguf.py`. Whether it accepts mlx-lm's fused output for Qwen3/Gemma 3
   key layouts is **UNVERIFIED**; the fallback is to train on cloud with PEFT and merge there.
3. Run `llama-quantize` to **Q8_0** (Qwen2.5-3B 3.3 GB, Llama 3.2 3B 3.4 GB on Ollama's library) and
   **Q4_K_M** (~1.9–2.0 GB) ([qwen2.5](https://ollama.com/library/qwen2.5), [llama3.2](https://ollama.com/library/llama3.2)) [PRIMARY].
   Gemma 3 4B shows 2.5 or 3.4 GB (Q4) and 4.1 or 5.0 GB (Q8); the gap is likely the vision
   projector (UNVERIFIED).
4. Write a Modelfile with `FROM ./model-Q8_0.gguf` plus a `LICENSE """…"""` block.
5. Publish with `ollama push` or HF Hub, from which Ollama pulls `hf.co/<user>/<repo>:Q8_0` (12).

**Merged + quantized is the only viable Ollama option on ≥v0.34.1.** It is also simpler: one GGUF
serves Ollama, llama-server and LM Studio. It also enables the llama-server route of §2c.

### 5c. Licences for redistributing a fine-tune

| Base | Licence | Obligations for a free OSS app shipping a fine-tune | Verdict |
|---|---|---|---|
| **Qwen2.5-3B-Instruct** | **Qwen RESEARCH LICENSE** (2024-09-19): "Non-Commercial … research or evaluation purposes only"; grant "FOR NON-COMMERCIAL PURPOSES ONLY" ([LICENSE](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/blob/main/LICENSE)) | copy of licence, modified-file notices, Notice file, "Built with Qwen" | **Avoid as base.** A free end-user app is arguably not "research or evaluation" (legal judgment). **LOAD-BEARING, quotes came via a summarizing fetch, so re-read the LICENSE file verbatim.** |
| **Qwen3-4B-Instruct-2507** | **Apache-2.0** (HF tag) ([card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)) | keep LICENSE/NOTICE | **Preferred**, if it passes the gate. 02a disqualified *Qwen3-4B* for thinking-mode output collapse; the 2507 Instruct release is presumed non-thinking (**UNVERIFIED**; `register.py`'s `thinking` check will catch it) |
| **Gemma 3 4B it** | Gemma Terms (mod. 2026-04-01); a fine-tune is a Model Derivative | pass §3.2 use restrictions through **as an enforceable provision** in the app's terms, ship a copy of the terms, Notice file ([terms](https://ai.google.dev/gemma/terms)) | OK, but an MIT app licence alone does not satisfy it. **§1.1(e)/§3.1 quotes were truncated by the fetcher; re-read.** |
| **Llama 3.2 3B Instruct** | Llama 3.2 Community License | ship licence + Notice; "Built with Llama" displayed; **model name must start with "Llama"**; AUP; >700M MAU clause ([LICENSE](https://github.com/meta-llama/llama-models/blob/main/models/llama3_2/LICENSE)) [PRIMARY, verbatim] | OK, with naming burden. The EU restriction covers only multimodal 3.2 models ([USE_POLICY](https://github.com/meta-llama/llama-models/blob/main/models/llama3_2/USE_POLICY.md)) |

The licence binds independently of fine-tuning: drill's `DEFAULT_MODELS` currently points users at
`qwen2.5:3b` / `Qwen2.5-3B-Instruct-8bit`. Not legal advice. SmolLM3-3B (Apache-2.0, top 3B EsCoLA
in 02a) is also a clean base if it passes the gate.

---

## 6. The eval gate: turn `quality_probe.py` into a decision instrument

Current state: `eval/quality_probe.py` now delegates to `drill/probes.py`. That has **9 single-turn
probes** (5 es-ES, 4 es-419), **5 samples each at T=0.7** by default, and is judged by
`register.check` plus regex extras. Its docstring already defers the ship threshold to this file. The
redesign below makes "train vs not" a measurement.

### 6a. Statistics: what a probe set can and cannot tell you (all computed)

| Question | Answer |
|---|---|
| Does 19/20 rule out an 80% true rate? | **No.** Wilson 95% CI [0.764, 0.991] |
| Probes to separate 80% vs 95% at 80% power (exact binomial, one-sided α=0.05) | **~30** (n=30: power 0.81; normal approx gives n≈32 one-sided, ≈42 two-sided) |
| Consecutive passes to claim failure ≤5% at 95% confidence | **59** (ln 0.05 / ln 0.95 = 58.4; rule-of-three gives 60) |
| 57/60 | Wilson [0.863, 0.983] |
| McNemar exact, base vs adapter on the same probes | needs **≥6 discordant pairs all in one direction** for two-sided p<0.05 (2·0.5⁶ = 0.031) |

The **probe, or the dialogue, is the unit**, not the sample. Five samples of one prompt are
correlated, so pooling them into a Wilson interval overstates precision. Miller reports clustered SEs
up to ~3× naive ones and recommends **paired** standard errors for model comparisons
([Miller, Adding Error Bars to Evals](https://arxiv.org/html/2411.00640v1)) [PRIMARY]. Resampling
each question still cuts conditional variance (by one third at 2 samples, per Miller), so keep
multiple samples per probe but report per-probe pass rates, with clustered SEs or a probe-level
majority pass.

### 6b. Gate design

1. **Expand each of the 5 probe types to N ≥ 40 distinct probes per variety**: vosotros/group-address,
   l2_errors, breakdown (English), latam_trap/spain_trap, recovery. Vary venue, persona, group size,
   phrasing, and English intrusion type. The vosotros type needs the most care: include
   non-group turns where tú is correct, so a model that sprays `os` everywhere fails. Target ~200
   probes per variety, ~400 total.
2. **Sample k=3–5 per probe at the deployment temperature**, the T drill actually ships. If §2d lowers
   T, the gate moves with it. Report **p̂ per probe**. That number directly feeds the §2b best-of-n
   table, because the gate measures the base rate regeneration depends on.
3. **Multi-turn probes for persona and variety drift.** Drift appears by turn 5 (06) and within 8
   rounds (Li et al.). P3B3 shows variety control decays across turns. Script **≥30 dialogues of
   8–10 turns per variety**, with a scripted learner that escalates: English sentence → "can you
   translate?" → wrong-variety lexeme → group address. Score every assistant turn. A dialogue passes
   only if all turns pass. Use the dialogue as the cluster.
4. **Held-out probes, written before and apart from training data.** Write them by hand, or with a
   different generator and different templates from §3d's taxonomy, and freeze them in the repo before
   any synthetic data exists. Run near-dup checks (n-gram overlap) between train and eval. Otherwise
   the adapter is graded on its own homework.
5. **Both varieties, always.** es-419 probes catch over-correction: vosotros leaking into LatAm
   sessions after es-ES-heavy training.
6. **Grammar scoring**: `register.check` cannot see grammar. Add LanguageTool (offline server, `language=es`)
   as an automatic flag and an Apache-licensed LLM judge (temperature 0, rubric: agreement,
   prepositions, pragmatics). **Human spot-check ~50 turns per run** to calibrate both. LanguageTool's
   false-positive rate on LLM Spanish is unknown.
7. **Regression gate on general Spanish**: EsCoLA MCC (02a's metric; **CC-BY-NC-SA, fine for eval,
   never train on it**, [HF](https://huggingface.co/datasets/nbel/EsCoLA)) plus a La Leaderboard subset
   such as belebele_spa, xstorycloze_es and copa_es ([La Leaderboard](https://arxiv.org/abs/2507.00999)),
   plus an LCB Spanish slice for WPR/LPR ([code/data](https://github.com/for-ai/language-confusion)).
   Add the **translation-mode probe** (§3f) and a ~30-item refusal set.

### 6c. Thresholds (proposed, to be set against the measured baseline)

| Metric | Ship bar | Train trigger (best no-training stack, best base) |
|---|---|---|
| English-leak, single-turn (breakdown + recovery) | ≥95% probe pass after ≤2 regenerations | <95% |
| Group-address vosotros (es-ES) | ≥90% probe pass after ≤2 regenerations | **raw per-sample p̂ < ~0.54**: 3 independent samples reach 90% only if 1−(1−p)³ ≥ 0.9, i.e. p ≥ 0.536 (computed); correlation pushes the real bar higher |
| Multi-turn dialogue pass (all turns) | ≥80% of dialogues | <80% |
| es-419 group-address ustedes / no vosotros | ≥95% | — (over-correction tripwire) |
| General Spanish (EsCoLA MCC, La Leaderboard subset) | no drop beyond 95% CI of base | — (adapter rejected if it drops) |
| WPR after DPO | ≥ SFT-only WPR | — |

Base vs adapter is decided by **McNemar on paired probe outcomes**, not by comparing two marginal pass
rates.

---

## Verdict

**Not yet. Train only if measurement says inference-time fixes have run out, and expect vosotros to
be the place that happens.** English leaks and persona drop are line- and word-level confusion. LCB
shows few-shot prompting, low temperature and a validator handle most of that, and drill already has
the validator and the retry budget. Vosotros is different. Regeneration filters and cannot create.
06 saw zero vosotros across three models from one sample each, which tells you nothing about p under
sampling. If p is near zero on every licence-clean base, **a ship-time SFT LoRA (+ optional DPO),
trained once, is the justified next step.** It is cheap: the Air can do 3–4B QLoRA, or a one-off
rented GPU costs a few dollars. It is distributed as one merged GGUF for Ollama and an adapter or
fused model for MLX. Grammar is a base-selection problem, not a LoRA problem.

Ordered sequence:
1. **Fix the base-model licence first.** Re-read Qwen2.5-3B's LICENSE. If confirmed non-commercial,
   move `DEFAULT_MODELS` candidates to Qwen3-4B-Instruct-2507 / Gemma 3 4B / SmolLM3-3B / Llama 3.2 3B.
2. **Build the §6 gate** (held-out probes frozen first, multi-turn dialogues, both varieties).
3. **Measure per-sample base rates** for every candidate at deployment T. Pick the base by the gate,
   not by leaderboard.
4. **Stack the free fixes**:
   - variety-native few-shot turns
   - a per-turn reminder
   - capped history
   - T ≈ 0.3–0.5
   - the existing validator with ≤2 regenerations
   - LatAm↔ES lexeme map with article fix-up

   Re-gate.
5. **Unlock token controls** via mlx-lm `logits_processors` (ban `(`, ` the`, ` you`, per-variety
   single-token lexemes) or llama-server for Ollama-format users. Re-gate.
6. Optional research detour, not on the ship path: a llama.cpp control vector built from es-ES/es-419
   contrastive prompts.
7. **If the vosotros (or multi-turn) train trigger still fires:** generate ~1–5k multi-turn dialogues
   per §3d with an Apache-2.0 teacher that itself passes the gate. Train **one variety-conditioned SFT
   LoRA** with replay and translation-mode examples, on the Air if measured speed allows. Gate it
   (McNemar vs base, regression set).
8. **Only if SFT leaves a gap**, especially on breakdown/cross-lingual: on-policy DPO with
   validator pairs, an SFT term, moderate β, length matching, and high-edit-distance pairs mixed in.
   Re-gate WPR.
9. **Ship**: fuse onto the bf16 base, convert and quantize Q8_0 (plus Q4_K_M for 8 GB Macs) via llama.cpp,
   add Modelfile + LICENSE, and publish the MLX adapter or fused 8-bit. Re-verify the Ollama v0.34.1
   adapter removal on the installed version first.

## Needs measuring

| # | Experiment on the Air | What to run | Decision it informs |
|---|---|---|---|
| 1 | Vosotros base rate under sampling | Extended `drill probe` with ≥40 group-address es-ES probes × 5 samples at T=0.7 and T=0.3, for Qwen3-4B-Instruct-2507, gemma3:4b, llama3.2:3b, SmolLM3-3B, gemma2:2b (spontaneous-Peninsular control). Report per-probe p̂ and the empirical retry success | **The train/no-train fork.** p̂ comfortably above ~0.54 → regeneration suffices; p̂ ≈ 0 everywhere → SFT; in between → check #2 before deciding |
| 2 | Retry correlation | For probes with 0<p̂<1, sample 3 retries conditioned on a first failure; compare observed success with 1−(1−p̂)^n | Whether best-of-n math can be trusted for latency budgeting |
| 3 | English-leak and persona under the free stack | 30 multi-turn scripted dialogues/variety, baseline prompt vs few-shot + per-turn reminder + T 0.3–0.5 + validator; McNemar on dialogue pass | Whether language-lock/persona need training at all |
| 4 | Token-ban side effects | mlx-lm `logits_processors` banning `(`, ` the`, ` you`, per-variety single-token lexemes; first scan tokenizations of target lexemes in each vocab; re-run gate + LanguageTool | Whether bans are safe to ship or distort fluency |
| 5 | Teacher qualification | Run the gate against the Apache-2.0 teacher (rented GPU) | Whether a teacher exists that is good enough to distill from |
| 6 | Training throughput and thermals | `mlx_lm.lora` QLoRA on Qwen3-4B-Instruct-2507 4-bit, `--batch-size 1 --grad-checkpoint --mask-prompt --max-seq-length 1024`, 200 iters, lid open; log it/s, peak memory, and it/s over time (throttle). Repeat with a bf16 base (LoRA, not QLoRA) and with `mlx_lm_lora.train --train-mode dpo` | Air vs rented GPU; whether bf16 LoRA (no train/serve mismatch) fits; whether DPO fits in 16 GB |
| 7 | Pilot SFT effect | 500 validator-filtered dialogues, one variety-conditioned adapter, gate vs base (McNemar, both varieties, regression set) | Whether targeted SFT moves vosotros at 3–4B at all, before scaling to 5k + DPO |
| 8 | Ollama adapter path | `ollama --version`; Modelfile with `ADAPTER ./x.gguf`; `ollama create` | Confirms or refutes the v0.34.1 removal claim before choosing a distribution path |
| 9 | Fuse → GGUF round-trip | Fuse pilot adapter onto bf16 base, `convert_hf_to_gguf.py`, `llama-quantize` Q8_0/Q4_K_M, re-run gate through Ollama | Whether the mlx-lm → llama.cpp path works for the chosen architecture, and the quantization cost on the gated behaviours |
| 10 | Translation-mode regression | Translation probe set on base vs adapter | Whether language-lock training broke in-context translation |
