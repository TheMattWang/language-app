# 10 — Local translation for the immersion word-swap: the deck, not the model, should choose and inflect

> **Correction (2026-10-12, research/13):** the "tc-big" timings below were measured on the base `opus-mt-en-es` (78M). Real `opus-mt-tc-big-en-es` is 226 MB on disk, adds ~545 MB RAM, and runs ~2× slower. Research/13 also reverses this doc for the sentence and full-text stages of immersion.

Compiled 2026-10-12. The question is which local model should do in-context EN→ES translation for
the immersion feature, where some English words or phrases in reading text are swapped for Spanish
that fits grammatically (gender, number, conjugation) and matches the learner's dialect (es-ES or
es-419). The constraints: free, fully local, runs on users' own 8GB laptops through Ollama and/or MLX,
and the owner's machine is a fanless M3 Air with 16GB. This builds on `02-local-slm.md`,
`02a-quality-floor.md`, `02b-model-survey.md` and `06-bench-local-baseline.md` without redoing them.
Labels: **MEASURED** (run on Matt's M3 Air on 2026-10-12, CTranslate2 4.8.2 CPU int8 greedy, or Ollama
temp 0), **ESTIMATED** (derived), **UNVERIFIED** (not backed by a source fetched this session). The
2026-10-12 span measurements use **n=3 spans** (n=7 for the CT2 quality spot-check). They are
illustrative, not a quality verdict.

## ⚠ License corrections and flags (read first)

Licenses below were checked against the HuggingFace model API and LICENSE files on 2026-10-12. This
file does **not** edit 02b or any other file. These corrections need to be applied there separately.

1. **Ministral-3-3B-Instruct-2512 is Apache-2.0, not "Mistral Research License"** as `02b-model-survey.md`
   says. Its card reads "Open-source license allowing usage and modification for both commercial and
   non-commercial purposes" ([HF card](https://huggingface.co/mistralai/Ministral-3-3B-Instruct-2512)).
   The research-license label probably belongs to the older Ministral-8B-2410 generation (UNVERIFIED,
   because the HF API call for 8B-2410 failed). Whether the 8B/14B-2512 sizes are also Apache was not
   checked.
2. **Gemma 4 E2B-it / E4B-it are Apache-2.0**, not the Gemma Terms of Use that 02b presumed
   ([HF E2B](https://huggingface.co/api/models/google/gemma-4-E2B-it),
   [HF E4B](https://huggingface.co/api/models/google/gemma-4-E4B-it)). Gemma 3 and TranslateGemma
   remain under the Gemma Terms. Whether Google layers extra use-policy terms onto Gemma 4 on its own
   website was not checked.
3. **Qwen2.5-3B-Instruct is under the Qwen RESEARCH License**, which allows "NON-COMMERCIAL PURPOSES
   ONLY". It defines Non-Commercial as "for research or evaluation purposes only"
   ([LICENSE](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/blob/main/LICENSE)). The 02 candidate
   table's "Qwen2.5 (0.5B/1.5B/3B/7B) — Apache-2.0" is therefore wrong for the 3B, and the 72B is also
   non-Apache. The 0.5B, 1.5B, 7B and 14B are Apache-2.0. **`drill/llm.py` `DEFAULT_MODELS` currently
   ships `qwen2.5:3b` / `mlx-community/Qwen2.5-3B-Instruct-8bit`.** A free consumer app is arguably
   neither research nor evaluation, so that default cannot be redistributed as the shipped model.

## TL;DR

1. **Use no dedicated MT model as the primary engine.** Classic encoder-decoder MT (Opus-MT, NLLB,
   MADLAD, M2M-100) translates whole strings and has no Spanish-variety switch. Translation-tuned LLMs
   (TranslateGemma, Tower+, SalamandraTA, Hunyuan-MT, Seed-X) are better translators, but only two
   expose any dialect handle. Tower+ is non-commercial, and TranslateGemma's acceptance of
   `es-ES`/`es-MX` is unconfirmed. **None does "translate only this phrase so it fits" natively.**
2. **Dialect cannot come from prompting at the sizes we can ship.** That was already settled in 06,
   where every 1.5–3B model failed vosotros, and no public benchmark measures dialect fidelity in
   generation. The deck already resolves es-ES vs es-419 per card (`drill/dialect.py`). The swap
   should inherit the dialect from the deck, not ask a model for it.
3. **Speed is a non-issue.** Opus-MT int8 on CTranslate2 takes **11–24 ms/span** and 1.5–3B LLMs on
   Ollama take **143–357 ms/span** (MEASURED, n=3). RAM is what differs: Opus-MT adds **~385 MB**,
   NLLB-600M adds ~1.17 GB, and a second 3–4B LLM adds 2–3 GB.
4. **Ollama cannot serve encoder-decoder MT** ([ollama#2802](https://github.com/ollama/ollama/issues/2802)
   is still open). Dedicated MT needs a second runtime, and CTranslate2 is the right one.
5. **Recommended: a deterministic hybrid.** Spans come from the learner's deck and get rule-based
   inflection from the deck's dialect-specific lemma. The already-resident Apache ≥3B LLM acts only as
   a closed-choice verifier. Opus-MT is an optional fast fallback for non-deck spans.
   **Exclude NLLB, Tower, Aya, SeamlessM4T (non-commercial) and Qwen2.5-3B (research license).**

---

## 1. Dedicated MT vs small instruct LLMs: neither natively swaps a span in context

**Classic MT is tiny and fast but string-in, string-out.** The candidates:

- `opus-mt-tc-big-en-es`: 0.2B Marian transformer-big with a single `spa` target
  ([HF](https://huggingface.co/Helsinki-NLP/opus-mt-tc-big-en-es)).
- MADLAD-400-3B: selects its target with a `<2xx>` prefix, and the card does not say whether regional
  Spanish tags exist ([HF](https://huggingface.co/google/madlad400-3b-mt)).
- NLLB-200: a single `spa_Latn` target.

Given a bare span, these models lose the context. In the 2026-10-12 spot-check (MEASURED, n=7,
context-free spans), NLLB-600M rendered "the bill" as **"el proyecto de ley"** (legislation), while
Opus-MT gave "la factura". In a restaurant, Peninsular usage wants "la cuenta", so neither was right.
Opus-MT also **silently dropped the second sentence** of a two-sentence input, so input must be
sentence-split before translation.

**The 2025–26 translation-tuned LLMs are the quality frontier, but most are too big or carry the
wrong license:**

- **TranslateGemma** 4B/12B/27B: Gemma 3 base, SFT followed by RL on MetricX-QE/AutoMQM rewards, 55
  languages. The 4B has a **2K-token input context**, and its chat template takes exactly one
  `source_lang_code`/`target_lang_code` entry
  ([HF](https://huggingface.co/google/translategemma-4b-it),
  [coverage](https://www.letsdatascience.com/news/google-releases-translategemma-open-translation-models-1e60758a)).
- **Tower+** 2B/9B/72B (Unbabel, June 2025): built on Gemma 2 2B for the 2B
  ([HF](https://huggingface.co/Unbabel/Tower-Plus-2B),
  [Slator](https://slator.com/from-ai-translation-to-ai-localization-with-unbabels-open-weight-tower/)).
- **SalamandraTA** 2B/7B (BSC, 38 European languages; the 7B was the basis of a WMT25 submission)
  ([arXiv 2508.12774](https://arxiv.org/html/2508.12774v1)).
- **Hunyuan-MT-7B**: first in 30 of 31 WMT25 pairs, ~8B in BF16, no smaller size
  ([arXiv 2509.05209](https://arxiv.org/abs/2509.05209v2),
  [HF](https://huggingface.co/tencent/Hunyuan-MT-7B)).
- **Seed-X-7B**: Mistral architecture
  ([HF](https://huggingface.co/ByteDance-Seed/Seed-X-RM-7B)).

The 7B models exceed the ~2s/turn ceiling that 06 extrapolated for 7–8B on the Air. They are viable
only for batch pre-processing of reading text, not interactive use.

**The research literature says span-in-context is a pipeline problem, not a model capability.**
Three established routes exist:

- **Translate the whole sentence, then word-align the span back out.** awesome-align is mBERT-based
  and BSD-3. It reports fine-tuned AER of Fr-En 4.1 and De-En 15.2, but has **no En-Es number**
  ([GitHub](https://github.com/neulab/awesome-align)).
- **Tag-wrap the span and translate.** LLMs place tags well but can lose, hallucinate or corrupt them.
  NMT with detag-and-project gave *better* translation quality than prompted BLOOM
  ([MT Summit 2023](https://aclanthology.org/2023.mtsummit-research.13/)).
- **Prompt an LLM directly.** This is code-mixed generation, and small models do it badly:
  - BLOOMZ and Flan-T5-XXL could not produce mixed-language phrases at all
    ([arXiv 2303.13592](https://arxiv.org/abs/2303.13592v4)).
  - A 2026 survey reports "systematic degradation in grammaticality" in mixed-language settings
    ([arXiv 2602.11181](https://www.arxiv.org/pdf/2602.11181), seen via summary).
  - The LREC 2026 English–Spanish work concludes that **fine-tuning is a key step** for LLMs to
    consistently produce fluent code-switched text, and that reference metrics do not track human
    judgement ([2026.lrec-1.703](https://aclanthology.org/2026.lrec-1.703/)).

The Ollama spot-check matched the literature (MEASURED, n=3, prompt "Translate only the span X into
Peninsular Spanish as it would appear in this sentence"):

- **qwen2.5:1.5b** gave "el boleto" for "the bill" in "Could we have the bill, please?". On another
  span it ignored the instruction and returned the whole sentence.
- **gemma2:2b** gave "el recibo".
- **llama3.2:3b** got "La cuenta", but also produced "un vaso de vino tinto" where Spain wants
  "una copa".

**Answer to (1):** a ≥3B instruct LLM can *attempt* "translate only this phrase so it fits", and none
of the dedicated MT models can without an alignment wrapper. Neither is reliable enough to be the
authority on what the learner reads. That is the same conclusion 06 reached for conversation: the
model is the engine, not the language authority.

## 2. en→es quality is high everywhere; dialect control exists almost nowhere

**Verified en-es numbers are sparse:**

- `opus-mt-tc-big-en-es` publishes **FLORES-101 devtest chrF 0.5644 / BLEU 28.5**, newstest2013 BLEU
  35.9 and tatoeba BLEU 57.2 ([HF](https://huggingface.co/Helsinki-NLP/opus-mt-tc-big-en-es)).
- TranslateGemma publishes only **55-language WMT24++ averages**. The 4B scores MetricX 5.32 / COMET
  81.6 and the 12B scores 3.60 / 83.5 ([HF](https://huggingface.co/google/translategemma-4b-it)).
  These are not en-es figures.
- **No en-es FLORES/COMET row was retrieved** for NLLB-600M/1.3B, MADLAD-3B, Tower+ 2B, SalamandraTA,
  Hunyuan-MT, Qwen3-4B or Gemma 4. The MADLAD paper has FLORES tables, but the en-es row was not
  extracted ([arXiv 2309.04662](https://arxiv.org/pdf/2309.04662)).

en→es is among the highest-resource pairs, so sentence-level differences between candidates are
probably smaller than differences in dialect control and span extraction (ESTIMATED, not verified
with en-es numbers). The 02a floor still applies to anything that *judges* Spanish. ≤1.7B models sit
at chance on EsCoLA. 3–4B instruct is the floor: SmolLM3-3B +0.245, Qwen2.5-3B-Instruct +0.214,
gemma-3-4b-it +0.190, Llama-3.2-3B-Instruct +0.174 MCC.

**Dialect control:**

| Model family | Dialect handle | Usable? |
|---|---|---|
| NLLB | `spa_Latn` only | No handle |
| Opus-MT | `spa` only | No handle |
| Hunyuan-MT | `es` only ([HF](https://huggingface.co/tencent/Hunyuan-MT-7B)) | No handle |
| MADLAD | `<2xx>` tags; regional Spanish undocumented | Unknown |
| Tower+ | Separate "Spanish" and "Spanish (Latin America)" targets, named in the prompt ([HF](https://huggingface.co/Unbabel/Tower-Plus-2B)) | Non-commercial |
| TranslateGemma | ISO 639-1 + ISO 3166-1 regional codes (example `de-DE`); unsupported codes raise when the template is applied ([HF](https://huggingface.co/google/translategemma-4b-it)) | `es-ES`/`es-MX` acceptance is **UNVERIFIED**, and a one-line test settles it |

Even an accepted code would not prove the model produces *vosotros* or *ordenador*.

The dialect literature measures **recognition, not production**:

- "It's the same but not the same" finds Peninsular Spanish the variety best identified by all nine
  models tested ([arXiv 2504.20049](https://arxiv.org/abs/2504.20049)).
- Kawasaki (Feb 2026) probes 900+ lexical items across 21 countries and finds Spain's variants among
  the best recognized ([arXiv 2602.09346](https://arxiv.org/abs/2602.09346)).

06 showed the gap between knowing and producing: gemma2:2b emitted `os gustaría` spontaneously but
not under instruction. **No benchmark measures "translate into es-ES and count vosotros/lexeme
fidelity".** This repo's probe gate (`drill/probes.py`) remains the only instrument for that axis,
as 02 already noted.

**Answer to (2):** no shippable model can be trusted to target es-ES vs es-419 by instruction.
Dialect errors concentrate in a small, enumerable set: 2nd-person plural forms plus a few hundred
divergent lexemes such as coche/carro, ordenador/computadora, móvil/celular, zumo/jugo and
conducir/manejar. That favours a lexicon-and-rules layer.

**VARILEX** is the best expert source for that layer: 934 items and 9,057 variants across 21
countries, with item A141 "car" giving coche (Spain) / carro
([UPM Data-in-Brief](https://oa.upm.es/91162/3/S2352340925008108.pdf)). Its access and license are
**UNVERIFIED**. The repo already has the mechanism: cards are authored es-ES, carry `variants` for
es-419, and `register.dialect_markers()` derives LatAm markers from `why:region` rejects.

## 3. Latency, memory and runtimes: CTranslate2 wins on RAM, and Ollama can't serve MT at all

**MEASURED on the M3 Air, 2026-10-12** (CT2 4.8.2 CPU int8, greedy, warm, median of 5; Ollama temp
0, num_predict 24, warm, median of 3; **n=3 spans** for span latency):

| Engine | Disk | RAM added | Latency per 1–5 word span | 10–14 word sentence |
|---|---|---|---|---|
| Opus-MT en-es, CT2 int8, 4 threads | **77 MB** | **~385 MB** (incl. HF tokenizer) | **11.3–23.7 ms** | ~38 ms |
| Opus-MT en-es, CT2 int8, 1 thread | 77 MB | ~385 MB | 16.3–37.3 ms | ~60 ms |
| NLLB-200-distilled-600M, CT2 int8, 4 threads | 599 MB | ~1.17 GB | 116–200 ms | 301–359 ms |
| qwen2.5:1.5b / gemma2:2b / llama3.2:3b (Ollama) | 986 MB / 1.6 GB / — | (resident LLM) | **143–357 ms** | — |

The prompt asked for 84–200 ms as the NLLB range. The note table's per-span cells are 116–200 ms, and
84 ms does not appear in it, so this file reports 116–200 ms.

Every engine above is "instant" for click-to-translate (<400 ms). **The real budget is RAM.** On an
8GB machine already holding OS, app, ASR and a conversational LLM, Opus-MT's ~0.4 GB is affordable.
NLLB-600M's ~1.2 GB or a second 3–4B LLM is probably not (ESTIMATED; the full-stack measurement has
not been run).

**Runtimes:**

- **Ollama cannot serve encoder-decoder MT.** Issue #2802 (MADLAD) is still open. Maintainers note
  that Ollama sits on `llama-server`, while llama.cpp's T5 support (PR #5763) landed only in
  `llama-cli` ([ollama#2802](https://github.com/ollama/ollama/issues/2802)). No NLLB, M2M100 or
  Marian GGUF path was found. Whether current `llama-server` has gained encoder-decoder support is
  UNVERIFIED.
- **The only Ollama route to a translation specialist is a decoder model.** Community TranslateGemma
  GGUFs exist (`hf.co/42ailab/TranslateGemma-4B-GGUF:Q4_K_M`,
  [HF](https://huggingface.co/42ailab/TranslateGemma-4B-GGUF)) but were not run.
- **MLX:** there is a third-party MADLAD-3B port (INT4 ~1.7 GB, INT8 ~3.1 GB, no published latency)
  ([soniqo](https://soniqo.audio/guides/translate)) and an mlx-examples T5 example. No mlx-community
  NLLB, Opus-MT or TranslateGemma build was found ("not found", not "nonexistent"). MLX is
  Apple-only, so it cannot be the sole runtime for x86 8GB laptops.
- **CTranslate2** supports Marian/Opus-MT, NLLB, M2M-100, T5 and MADLAD-400. It offers int8, runs on
  x86-64 and ARM64 (Apple Accelerate), and has **no Metal backend**
  ([README](https://github.com/OpenNMT/CTranslate2)). Its published 4-thread Xeon En→De benchmark is
  696 tok/s and 516 MB at int8. That suggests tens of milliseconds per span on x86 laptops
  (ESTIMATED from a server CPU).
- **Embeddable alternatives:** transformers.js Opus-MT en-es quantized ONNX (~53 MB encoder + ~60 MB
  merged decoder, [HF](https://huggingface.co/Xenova/opus-mt-en-es/tree/main/onnx)) and Bergamot.
  Bergamot reached ~870 words/s in Firefox Wasm on a 2017 Intel MBP, but the ARM64 Wasm GEMM was slow
  at the time ([Mozilla Hacks](https://hacks.mozilla.org/2022/06/neural-machine-translation-engine-for-firefox-translations-add-on/)).

Shipping CT2 needs no Ollama. It can be a Python sidecar with ctranslate2 + sentencepiece (no torch),
or native C++ linked into the app.

## 4. Licenses: half the strong translators are non-commercial

From the HF license tags fetched 2026-10-12:

| Status | Models |
|---|---|
| **Clean (Apache-2.0 / MIT)** | MADLAD-400 3B/10B; M2M-100 (MIT); Opus-MT en-es (Apache-2.0); Qwen2.5-0.5B/1.5B/7B/14B; Qwen3-1.7B/4B and Qwen3.5-4B; Gemma 4 E2B/E4B; Phi-4-mini (MIT); Salamandra-2B and SalamandraTA-2B; EuroLLM-1.7B/9B; Ministral-3-3B-2512 |
| **Attribution required** | **Opus-MT tc-big en-es** is **CC-BY-4.0** ([HF](https://huggingface.co/api/models/Helsinki-NLP/opus-mt-tc-big-en-es)): commercial use allowed, ship an attribution |
| **Permissive with obligations** | **Gemma 3 / TranslateGemma** (Gemma Terms): the §3.2 use restrictions must go into the app's own ToS, plus a Notice file, plus Google's right to "restrict (remotely or otherwise) usage" ([Gemma Terms](https://ai.google.dev/gemma/terms)). **Llama 3.2**: ship the Agreement, display "Built with Llama", keep the NOTICE; a user of an "integrated end user product" is exempt from the redistribution terms ([LICENSE](https://raw.githubusercontent.com/meta-llama/llama-models/main/models/llama3_2/LICENSE)) |
| **Copyleft** | **SalamandraTA-7B is GPL-3.0** ([HF](https://huggingface.co/BSC-LT/salamandraTA-7b-instruct)) |
| **Excluded** | **NLLB-200** CC-BY-NC-4.0 ([HF](https://huggingface.co/api/models/facebook/nllb-200-distilled-600M)); **SeamlessM4T v2** CC-BY-NC-4.0; **TowerInstruct** CC-BY-NC-4.0; **Tower-Plus** CC-BY-NC-**SA**-4.0; **Aya Expanse / Aya-23** CC-BY-NC-4.0; **Qwen2.5-3B** Qwen Research License (see corrections) |

**On the NC licenses:** CC's NonCommercial test is "not primarily intended for or directed towards
commercial advantage", and the CC wiki gives no safe harbour for donations, ads or a paid tier
([CC wiki](https://wiki.creativecommons.org/wiki/NonCommercial_interpretation)). An NC model in a
strictly free app is probably permissible. It becomes a liability the day the app takes donations or
adds a Pro tier. The Qwen Research License is stricter still: "research or evaluation purposes
only".

**Morphology tooling for §5:**

- spaCy: MIT.
- verbecc (conjugator): LGPL-3.0, active 2026.
- mlconjug3: MIT, but its Spanish model was trained unsupervised, so expect errors on irregulars
  ([docs](https://mlconjug3.readthedocs.io/en/latest/readme.html)).
- apertium-spa: GPL-2.0.
- FreeLing: license UNVERIFIED.

This is not legal advice.

## 5. The hybrid is more reliable, because the deck removes the model's two worst failure modes

**No study directly compares deterministic deck-driven swapping with LLM-chosen swapping for learner
reading text.** That gap is real. The indirect evidence all points one way:

- The macaronic-learning line chose *which* words to switch with explicit models, not free generation.
  Labutov & Lipson found optimized switching significantly beat random switching on learner recall
  ([ACL 2014](https://mirror.aclweb.org/acl2014/P14-1/pdf/P14-1053.pdf)).
- Renduchintala et al. modelled which L2 words a reader will understand from cognates, context and
  exposure ([P16-1175](https://aclanthology.org/P16-1175/), [D19-1679](https://aclanthology.org/D19-1679/)).
- Spanish inflection from lemma plus features is close to solved: **99% intrinsic accuracy** for verb
  inflection ([W17-4120](https://preview.aclanthology.org/setup/W17-4120)).
- LLM code-mixing still needs fine-tuning to be fluent (§1).

The deck therefore removes the two largest LLM risks. One is **swapping words the learner hasn't
studied**. The other is **rewriting that changes meaning**. The dialect comes free, because the
deck's lemma is already es-ES or es-419.

**The remaining risk sits outside the swapped word** (from linguistic analysis; no measured rates
found):

- **Agreement:** "the red car" must become *el coche rojo* as a unit, with the determiner's gender
  and the adjective after the noun. Swap whole NPs, or a bare noun only where English has no
  determiner.
- **Verbs:** English underdetermines the Spanish form.
  - "you" maps to tú, usted, vosotros or ustedes, and that choice differs by dialect.
  - The English simple past does not say whether Spanish wants preterite or imperfect.
  - Subjunctive triggers.
  - Stranded clitics.

  Swap verbs only when person and tense are unambiguous.
- **Word sense:** "run" can be *correr*, *funcionar* or *dirigir*, and a deck entry holds one sense.
  This is where a model verifier earns its place: "does *bill* here mean a restaurant check, yes or
  no?"
- **Multiword expressions and phrasal verbs** ("give up", "run out of"): spaCy lemmatization splits
  them, so skip anything with a `prt` dependent or that matches an MWE blocklist.

Keeping the LLM in a **closed-choice** role (yes/no sense check, or picking among pre-generated
forms) suits the measured weaknesses. 06 showed small models ignore open instructions, and the LREC
2026 work shows reference metrics fail on open code-mixed output, while a constrained answer can be
checked. Two cautions apply. The verifier must run with thinking disabled or constrained decoding,
because Qwen3 thinking-mode scored xquad_es **0.0** in 02a. And spaCy is an analyser, not a
morphological generator (UNVERIFIED), so generation needs verbecc, a lexicon, or Spanish forms stored
on the deck card.

**Answer to (5):** yes. The hybrid is more reliable by construction for the 80% case: deck nouns as
full NPs, unambiguous verbs. It leaves a small residue of sense ambiguity that a verifier can cover.
It cannot generalize to arbitrary non-deck spans. That is the only place a translator, i.e. Opus-MT
plus alignment, is needed.

## Verdict

**v1 = deterministic deck-driven swap, the resident Apache-licensed ≥3B LLM as a closed-choice
verifier, and Opus-MT tc-big int8 on CTranslate2 as an optional non-deck fallback.**

1. **Select spans deterministically from the learner's deck** with spaCy lemma, POS and dependency
   parsing.
   - Swap only safe units: full noun phrases with their determiner and adjectives.
   - Swap verbs only where person and tense are unambiguous.
   - Skip MWEs and phrasal verbs (`prt` dependents, plus a blocklist).
2. **Inflect deterministically from the deck's dialect-specific Spanish lemma.** Use forms stored on
   the card where available, otherwise verbecc (LGPL, used as a library). **The dialect comes from
   the deck plus a curated variant table**, which is the `variants`/`why:region` mechanism the packs
   already have. It does not come from prompting a model.
3. **The verifier is the conversational LLM that is already resident**, so no second model is
   loaded. It must have a permissive license: **Qwen3-4B (Apache-2.0, thinking disabled) or Gemma 4
   E4B (Apache-2.0)**. It answers only closed questions, such as a sense check or an agreement check
   among pre-generated forms. Swaps it rejects are simply not shown.
4. **Optional fast fallback for non-deck spans:** `opus-mt-tc-big-en-es` int8 via CTranslate2
   (CC-BY-4.0, attribute it). It costs 77 MB and ~385 MB RAM and runs in 11–24 ms per span on the Air
   (MEASURED, n=3). Translate the whole sentence, extract the span by alignment, and run the same
   verifier and variant-table pass.
5. **Runtime:** Ollama or MLX for the LLM, as already in `drill/llm.py`. CTranslate2 for the MT,
   because **Ollama cannot serve encoder-decoder MT**.
6. **Excluded:** NLLB, Tower/Tower+, Aya and SeamlessM4T (non-commercial); Qwen2.5-3B (research
   license). That means `drill/llm.py`'s `qwen2.5:3b` default must change before distribution.
7. **Optional, held back:** TranslateGemma 4B is the only shippable model with a plausible regional
   handle. Its Gemma-Terms obligations and the unverified `es-ES` code acceptance keep it optional
   until measured.

## Needs measuring

All on the M3 Air unless noted. Extend `eval/quality_probe.py`, which now delegates to
`drill/probes.py`, with a `swap` probe family alongside the conversational probes, and reuse
`register.check()` and `dialect_markers()` as the dialect oracle.

1. **Span-swap agreement accuracy.** Build ~200 English reading sentences containing deck lemmas,
   with hand-annotated gold Spanish NP/verb renderings for es-ES and es-419. Score these three
   against gold for determiner gender and number, adjective agreement and placement, and verb
   person/tense:
   - the deterministic pipeline;
   - the LLM-only prompt, for Qwen3-4B no-think, Gemma 4 E4B, Llama 3.2 3B and Ministral-3-3B;
   - Opus-MT plus alignment.

   Report the pass rate per unit type: NP, verb, bare noun.
2. **Dialect lexical fidelity.** Build a VARILEX-style table of ~100 high-frequency divergent
   concepts (car, computer, phone, juice, drive, bus, apartment, glass of wine…) with an es-ES and an
   es-419 answer for each, in sentence context. Measure the per-variety hit rate for each LLM, for
   TranslateGemma with a regional code, and for Opus-MT. Also measure vosotros vs ustedes on 2pl
   spans. This is the first generation-side dialect benchmark for the project.
3. **Word sense on polysemous spans.** Use ~50 sentences with bill, run, bank, glass, check, light and
   similar words, where the deck holds one sense. Measure the verifier's yes/no accuracy, and its
   false-reject rate on correct-sense occurrences, per model at Q4 and Q8.
4. **TranslateGemma regional-code acceptance.** Apply the chat template with `es-ES`, `es-MX`, `es-419`
   and `es-AR`, and record which raise. For the accepted codes, run benchmark 2. Also measure
   tag-wrapped span retention, i.e. the tag-loss rate. Use the community GGUF on Ollama.
5. **Span-extraction accuracy.** Compare awesome-align (mBERT, untuned and fine-tuned) with CT2
   `return_attention=True` argmax alignment for pulling the Spanish span out of an Opus-MT sentence
   translation. Measure exact-span match on the benchmark-1 set. No En-Es AER is published.
6. **8GB x86 latency.** Run the Opus-MT CT2 int8 bench (`bench/ct2_bench.py`) and the Ollama span
   bench on an 8GB Intel/AMD laptop, and on an 8GB M1/M2 if one is available. The current x86 figure
   is extrapolated from a Xeon.
7. **Full-stack resident memory.** Measure RSS with ASR, the conversational LLM (Qwen3-4B or Gemma 4
   E4B at Q4/Q8), Opus-MT CT2 and spaCy `es_core_news_sm` all loaded, during a reading session with
   swaps. Do it on the Air and under an 8GB cap, and record sustained thermals over 20 minutes.
8. **Fallback bake-offs.** Measure en-es FLORES-200 chrF++ and COMET-22 locally for opus-mt-tc-big,
   MADLAD-3B (CT2), TranslateGemma-4B and Qwen3-4B. No published en-es row exists for most of them.
   Also measure verbecc vs mlconjug3 accuracy on irregular and vosotros forms.
