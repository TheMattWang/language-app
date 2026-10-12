# 13 — Progressive immersion: from word swaps to full Spanish, and which MT engine carries each stage

Compiled 2026-10-12. The owner changed the immersion brief in two ways:

- **(a) Immersion is progressive.** It starts with single words, then moves to phrases, then whole
  sentences, then full conversion, until the reading text is entirely Spanish. So sentence-level and
  document-level MT quality become central rather than a fallback.
- **(b) Decoder-only LLMs are no longer the default translator.** Encoder-decoder or dedicated MT
  models may beat a 3–4B decoder at equal or smaller size.

This file builds on `10-local-translation-models.md` (deck-driven picker plus LLM verifier;
encoder-decoder MT rejected as the *primary* engine), `09-system-wide-immersion.md` (density cap
around 15%), `02a-quality-floor.md` (3–4B is the floor for judging Spanish) and `06-bench-local-baseline.md`
(every 1.5–3B model failed the vosotros probe). It does not edit any of them.

Labels:

- **MEASURED**: run on Matt's M3 Air (16GB, macOS 26.2) on 2026-10-12 in this session. CT2 4.8.2 CPU
  int8 at 4 threads with beam 4. Ollama 0.40.3 at temperature 0 on Metal. Scripts and raw JSON are in
  the session scratchpad, not the repo.
- **REPORTED**: from a cited source.
- **ESTIMATED**: derived by arithmetic or reasoning, not run.
- **UNVERIFIED**: no source was fetched this session.

The measured set is **24 inputs, n=1 output per engine and condition**. It shows failure modes. It
is not a quality ranking.

## ⚠ Correction to 10 (read first)

**`10`'s Verdict calls the 77 MB / ~385 MB / 11–24 ms engine "opus-mt-tc-big-en-es". It was
actually `Helsinki-NLP/opus-mt-en-es`**, the 2020 Marian *base* model with 78M params. The scratchpad
model directory from that run is `opus-en-es-int8`, built from `Helsinki-NLP/opus-mt-en-es`.

tc-big is a separate model with 235M params (MEASURED param count). Converted to CT2 int8 it is
**226 MB on disk, adds ~545 MB RSS after load and peaks at ~674 MB max RSS** (MEASURED). That is
about 1.4× the RAM of base, and it runs about 2× slower (§5). Its published quality is better, its
license is different (CC-BY-4.0 rather than Apache-2.0), and so is its cost. Every "tc-big" figure in
`10` should be read as "base".

## TL;DR

1. **The progression is a design hypothesis, not something the evidence has tested.** No study
   compares word-, phrase- and sentence-level switching, and none trials a staged word → phrase →
   sentence → full-L2 curriculum.
   - **Word stage:** well supported for beginners, and only when the swapped words are chosen well.
     Renduchintala 2019 found chosen tokens understood at 0.79–0.80 against 0.38–0.61 for random
     tokens.
   - **Full-L2 stage:** governed by lexical coverage, with 95% as the minimum and 98% comfortable.
     The relationship is linear, with no cliff.
   - **"Mixing has a ceiling":** inferred from code-switching grammar and switch-cost studies, not
     measured on learners.
   - **Practical rule:** keep word and phrase insertion inside an English frame. Flip a whole
     sentence once the Spanish would have to supply the sentence's grammar: function words, verb
     morphology, clitics.
2. **The owner's hypothesis holds on parameter efficiency.**
   - **Published FLORES-200 en→es:** the 0.23B bilingual `opus-mt-tc-big-en-es` (chrF 56.44 /
     BLEU 28.5) ties the 2.9B MADLAD-3B (56.4 / 28.0) and NLLB-54B (56 / 28.1), and beats NLLB
     0.6–3.3B and M2M-100 (REPORTED).
   - **Measured on the 24-sentence set:** both Opus models produced no non-words or agreement errors (one ser/estar slip from tc-big: "Mi batería **es** baja"), while the
     general 3–4B decoders produced non-words and wrong agreement. Llama 3.2 3B wrote "sentadose",
     "comedéis" and "Inclúyese para continuar". Qwen3-4B-Instruct wrote "Ejecutá" (Rioplatense
     voseo) in es-ES and "un pequeño panadería".
   - **TranslateGemma 4B** (a translation-tuned decoder) was the most fluent and the most
     register-consistent. It costs about 20× the params and about 5× the per-sentence latency of
     tc-big (MEASURED), and it is under the Gemma Terms.
3. **No encoder-decoder MT model produces vosotros out of the box.** Opus base and tc-big scored
   0/4 on the 2nd-person-plural items. TranslateGemma `es-ES` scored 3/4 with correct `usted` in a
   formal email. Qwen3-4B scored 4/4 but **over-applied vosotros** to a formal email ("Estimada
   Señora García, gracias por vuestro correo") and to singular requests (MEASURED).
4. **Lexical variety control works pre-decode on encoder-decoder MT.** CT2 `suppress_sequences`
   with the other variety's lexemes flipped tc-big between *coche/auto*, *ordenador/computadora*,
   *zumo/jugo*, *billete/boleto*, *melocotones/duraznos* and *patatas/papas* (MEASURED). Because the
   decoder conditions on its own output, **agreement followed the swap**: *ordenador … **lo**
   reinicié* against *computadora … **la** reinicié*. A post-edit pass would have left the wrong
   clitic.
   - Banning is blunt. Banning *conducir* for es-419 made tc-big drop the meaning "drives" entirely
     ("va al trabajo").
   - TranslateGemma's `es-MX` code changed pronouns and *computadora*, but **kept Peninsular
     *coche*, *aparcamiento*, *zumo*, *billete* and *móvil***. A region code is not lexical control.
5. **Runtime:**
   - **CTranslate2 is CPU-only on macOS** (Accelerate/Ruy; `device="mps"` errors). That suits a
     0.2B model, because it leaves the GPU to the resident LLM.
   - **Ollama cannot serve encoder-decoder models.** llama-server never calls `llama_encode`, and
     Marian cannot be converted to GGUF.
   - There is **no MLX Marian port** (this is a natural mlx-kernels project).
   - **Apple's on-device Translation framework** is untested here. This Mac's Xcode 15.4 SDK has no
     Translation Swift API.
6. **Verdict in one line:**
   - **Word and phrase stages:** deck-driven, as in 10.
   - **Sentence and full-text stages:** **Opus-MT tc-big on CT2** as the primary engine, with
     sentence splitting, a document-level address-consistency pass, and variety from deck lexicon
     bans before decoding.
   - **Upgrade path:** a tagged es-ES/es-419 fine-tune of tc-big for vosotros. Fine-tuning on MPS
     works for base, but **tc-big hit NaN loss on MPS** in a smoke test (MEASURED).
   - **TranslateGemma 4B:** optional quality tier, gated on its license.

---

## 1. The progression: what the evidence supports at each stage

### 1.1 Nobody has tested the staged progression

The only research line that explicitly imagines a continuum is the JHU macaronic work.

- **ACL 2016.** Renduchintala et al. built mixed German–English sentences out of words *and*
  phrases, moving German phrases into English-like positions. They framed macaronic text as a
  beginner scaffold that would generalize to "full German sentences (for more advanced students)"
  ([P16-1175 PDF](https://www.cs.jhu.edu/~jason/papers/renduchintala+al.acl16-macmodel.pdf)).
  A companion demo let users drag a sentence toward more L1 or more L2
  ([P16-4023](https://aclanthology.org/P16-4023/)).
- **EMNLP 2019.** The outcome study **retreated to "simple lexical substitutions" only** and did
  not test the continuum ([D19-1679](https://aclanthology.org/D19-1679.pdf)).
- **LoomVue.** The only product found that shifts text "between English and Spanish as the reader's
  skill" grows is LoomVue, funded by IES SBIR. Its evidence is a 13-student pilot measured on
  *self-perceived* vocabulary. The Phase II randomized pilot has no published results
  ([IES 4691](https://ies.ed.gov/funding/grantsearch/details.asp?ID=4691)).

**So every stage boundary below is a design decision, not an evidence-backed curriculum.**

### 1.2 Stage evidence

| Stage | What the learner sees | Evidence | Strength |
|---|---|---|---|
| **S1 word** | English frame plus deck words in Spanish | Renduchintala 2019 (39 MTurk absolute beginners), Spanish: open-class comprehension **0.80 with model-chosen swaps vs 0.61 random**; closed-class (function words) **0.82 with 41% replaced**. Immediate retention only, 0.50 vs 0.40 ([D19-1679 Tables 2–3](https://aclanthology.org/D19-1679.pdf)). Broccoli (N=58): short-term gain, parity at 1–4 weeks (see `09`) | Moderate for short-term receptive gains; weak long-term |
| **S2 phrase/chunk** | English frame plus Spanish NPs and verb chunks | No outcome study. JHU 2016 modelled phrases but did not measure learning ([P16-1175](https://www.cs.jhu.edu/~jason/papers/renduchintala+al.acl16-macmodel.pdf)) | Unstudied |
| **S3 sentence flip** | Some whole sentences in Spanish inside an English document | No learner study. The closest analogue is glossed L2 reading: glossed readers learned **45.3% / 33.4%** (immediate / delayed) of unknown targets vs **26.6% / 19.8%** unglossed (secondary citation of [Yanagisawa et al. 2020](https://cambridge.org/core/journals/studies-in-second-language-acquisition/article/how-do-different-forms-of-glossing-contribute-to-l2-vocabulary-learning-from-reading/38124150D59DF3039EE1FF5AE88FE922), via [PMC9851552](https://pmc.ncbi.nlm.nih.gov/articles/PMC9851552)) | Indirect |
| **S4 full L2 (+ L1 on tap)** | Spanish text, English sentence on demand | Lexical coverage literature. **95% is the minimum and 98% the comfortable target**, but the relationship is "relatively linear" with "no indication of a vocabulary threshold" ([Schmitt, Jiang & Grabe 2011](https://www.lextutor.ca/cover/papers/schmitt_etal_2011.pdf), N=661). The Hu & Nation 98% figure came from 66 students and **"could not be fully replicated"** ([Kremmel et al. 2023 abstract](https://aila2021.dryfta.com/program/abstract-archive/abstract/public/416/unknown-vocabulary-density-reading-comprehension-and-the-98-coverage-figure-replicating-hu-nation-2000)). Graded readers reach 95%/98% at roughly 2,000/3,000 word families (English data, secondary: [JER/JALT](https://jalt-publications.org/content/index.php/jer/article/download/4/2/25)). No Spanish-specific figures were found | Well established that coverage drives comprehension; thresholds are soft |
| **S5 full L2, no L1** | Authentic Spanish | Novels need about 9,000 families for 98% coverage ([Nation 2006](https://www.wgtn.ac.nz/__data/assets/pdf_file/0018/1626120/2006-How-large-a-vocab.pdf)) | Well established |

**On LLM-simplified L2 text,** the one learner experiment found **no comprehension gain** from
AI-simplified or expert-simplified passages once topic familiarity was controlled
([Murphy Odo 2025, LLT](https://www.lltjournal.org/item/1186)). Do not assume that "rewrite to A2"
helps. Measure it.

### 1.3 Does word-level mixing have a ceiling? Probably, but the evidence is indirect

**What is measured.** Intra-sentential switches cost reading time, even for fluent bilinguals.

- Spanish–English bilinguals read code-switched sentences more slowly in both directions
  ([Litcofsky & Van Hell 2017](https://sites.psu.edu/kaitlynlitcofsky/files/2017/02/Litcofsky_Neuropsychologia_2017-2ez3z0j.pdf)).
- A single inserted English noun in a Spanish sentence produces a late positivity (LPC) tied to
  sentence-level re-integration. The effect is absent in early-window positivity for frequent
  switchers (n=24; [Valdés Kroff et al. 2020](https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2020.02138/full)).
- The cost depends on the type of switch. Community-typical patterns, such as a Spanish
  determiner plus an English noun, appear cheaper
  ([Beatty-Martínez & Dussias, via eScholarship](https://escholarship.org/content/qt68m6j5sh/qt68m6j5sh.pdf)).

**What is not measured.**

- No matched intra- vs inter-sentential reading-cost comparison was found.
- No study finds a density at which the matrix language should flip.
- None of the switch-cost studies used *learners* reading *designed* mixed text.

**The inference** ([speculative], from code-switching grammar plus per-switch costs):

- Fluent bilinguals' mixed sentences keep one *matrix* language that supplies word order, function
  words and inflection, and insert content items from the other language. That is Myers-Scotton's
  Matrix Language Frame and Poplack's equivalence constraint. Neither was fetched this session.
- Word-level immersion is exactly that pattern: an English frame with Spanish NP and verb
  insertions.
- **The ceiling comes when the Spanish would have to supply the frame.** That means Spanish
  determiners agreeing with Spanish nouns across English words, Spanish verb morphology with
  clitics, and *se* constructions. At that point a Spanish clause with English holes reads worse
  than a fully Spanish clause.
- Each switch point carries an integration cost. One flipped sentence therefore has two switch
  points (in and out), while six scattered word swaps have up to twelve.

One countervailing datum: JHU's beginners understood swapped Spanish *function words* well, at
0.82. So "never swap function words" is not a hard rule. *Which* tokens are swapped (whether they
are predictable from context or cognates) mattered more than their part of speech.

### 1.4 Proposed progression with gates (design, [speculative] thresholds)

| Stage | Unit | Gate to enter (per sentence, not per learner) | Density |
|---|---|---|---|
| S1 | Deck nouns as full NPs; unambiguous verbs (as `10` §5) | Lemma is in the deck and passes the verifier | ≤2% new tokens, ≤15% total (`09`) |
| S2 | Chunks: NP + PP, fixed expressions, verb + object | All chunk lemmas known; chunk is a syntactic constituent (spaCy subtree); no clitic crosses the boundary | Same total cap; fewer, longer switches |
| S3 | **Whole sentence** | **Known/inferable coverage of the Spanish sentence ≥95%**, with the remainder glossed **and** the sentence would exceed the S1/S2 cap if done word by word | A share of sentences per document, rising with level |
| S4 | Whole paragraph or document, English on tap | Document-level coverage ≥95% with glosses | 100% Spanish, L1 reveal per sentence |
| S5 | Full Spanish | Coverage ≥98%, reveal rate low | 100% |

The control signals already proposed in `09` carry over: reading-speed slowdown of ≤10% (a
heuristic) and the reveal rate. Coverage is computable because the app knows which lemmas are in the
learner's SRS state and which the MT output contains. That requires lemmatizing the Spanish output
with spaCy `es_core_news_*`.

**The engineering consequence that matters:** from S3 onward, **MT output is the Spanish input the
learner absorbs**. Any error is taught, and the 3–4B verifier sits at EsCoLA MCC ≈0.17–0.25 (`02a`),
so it cannot be the safety net for grammaticality. Engine choice for S3–S5 is therefore a
*correctness* decision first and a fluency decision second.

## 2. Encoder-decoder / dedicated MT vs decoder-only at ≤4B, en→es

### 2.1 Published quality (REPORTED)

FLORES-200 devtest eng→spa. The primary source is the Helsinki-NLP score databases
([OPUS-MT-leaderboard](https://github.com/Helsinki-NLP/OPUS-MT-leaderboard/tree/master/scores),
[External-MT-leaderboard](https://github.com/Helsinki-NLP/External-MT-leaderboard/tree/master/scores)).
MADLAD comes from its paper (different harness, same sacrebleu metrics).

| Model | Params | Arch | FLORES chrF / BLEU | Other en→es | License for a free app |
|---|---|---|---|---|---|
| **opus-mt-tc-big-en-es** | 0.23B | Marian enc-dec (big) | **56.44 / 28.5** | NTREX chrF 65.46 / BLEU 42.4 | **CC-BY-4.0**, ship attribution ([HF](https://huggingface.co/Helsinki-NLP/opus-mt-tc-big-en-es)) |
| opus-mt-en-es (2020 base) | 0.08B | Marian enc-dec (base) | No row for this checkpoint; 2021 base models score 55.1–55.2 / 26.4–26.5 | newstest2013 BLEU 35.0 ([HF](https://huggingface.co/Helsinki-NLP/opus-mt-en-es)) | Apache-2.0 |
| Mozilla Firefox base-memory en-es | not found | Marian (Bergamot) | 55.53 / 26.5 | NTREX 64.33 / 40.4 | MPL-2.0; repo archived 2025-12-15 ([GitHub](https://github.com/mozilla/firefox-translations-models)) |
| MADLAD-400-3B-MT | 2.94B | T5 enc-dec | 56.4 / 28.0 | WMT 61.1 / 37.3; **NTREX en→es_MX 5.7 / 2.4 (collapsed)** ([arXiv 2309.04662](https://arxiv.org/pdf/2309.04662)) | Apache-2.0 |
| NLLB-200 600M / 1.3B / 3.3B | 0.6–3.3B | enc-dec | 54.00 / 25.9; 55.39 / 27.7; 55.26 / 27.3 | | **CC-BY-NC** (reference only) |
| M2M-100 418M / 1.2B | 0.4–1.2B | enc-dec | 51.26 / 22.2; 53.85 / 25.4 | | MIT |
| SeamlessM4T v2 | 2.3B | enc-dec | not found | | CC-BY-NC |
| T5Gemma 2 (270M-270M / 1B-1B / 4B-4B) | 0.37–7B | enc-dec from Gemma 3 | **No MT results, and no translation-tuned checkpoint released** ([arXiv 2512.14856](https://arxiv.org/abs/2512.14856)) | | Gemma Terms |
| **TranslateGemma 4B** (Jan 2026) | 4.3B (Ollama) | decoder (Gemma 3) | not published | **WMT24++ en→es_MX MetricX-24 2.51** vs Gemma 3 4B 3.35 and Gemma 3 27B 2.54 (lower is better) ([arXiv 2601.09012](https://arxiv.org/pdf/2601.09012)) | Gemma Terms (see §2.4) |
| HY-MT1.5-1.8B (Dec 2025) | 1.8–2.0B | decoder | aggregates only: FLORES EN⇔XX XCOMET-XXL 0.8942; Int4 0.8665 ([arXiv 2512.24092](https://arxiv.org/html/2512.24092)) | | **License "does not apply in the EU, UK and South Korea"** ([License](https://huggingface.co/tencent/HY-MT1.5-1.8B/blob/main/License.txt)), so excluded for a global app |
| SalamandraTA-2B | 2.25B | decoder | EN→XX aggregate chrF 61.74 vs MADLAD-3B 63.04 on the same table ([HF](https://huggingface.co/BSC-LT/salamandraTA-2b-instruct)) | | Apache-2.0 |
| Tower+ 2B | 2.6B | decoder (Gemma 2) | not found | | CC-BY-NC-SA |
| Qwen3-4B, Gemma 4 E2B/E4B, Llama 3.2 3B, Phi-4-mini, Ministral 3B, SmolLM3 | 3–4B | decoder | **No en→es FLORES/WMT row found for any of them** | | Apache/MIT (Llama: Llama license) |

**Reading the table:**

- On sentence-level FLORES en→es, the ≤3.3B ceiling is about chrF 55–56.5. A 0.23B *bilingual*
  Marian reaches it.
- Extra multilingual parameters buy almost nothing on a high-resource pair. That is confounded:
  bilingual vs massively multilingual training is not an architecture effect.
- In the cleanest controlled comparison found, decoder-only NMT trained from scratch performs "on
  par" with encoder-decoder ([Gao et al., AACL 2022](https://arxiv.org/abs/2210.11807)).
  **Specialization and data, not architecture, explain Opus-MT's efficiency.**
- That still supports the owner's point in practice. The specialized small models that exist and
  are licensable for en→es are encoder-decoders.
- **No common metric places TranslateGemma 4B and Opus-MT on the same scale.** TranslateGemma
  publishes MetricX on WMT24++ only. Opus has no WMT24++ row. That head-to-head is in Needs
  measuring.

### 2.2 MEASURED on the Air: 24 realistic inputs

**The set** (`mt13_set.py` in the scratchpad) covers:

- 10 Spain-vs-LatAm lexical items: car / car park, computer, mobile, juice, drive, ticket, flat,
  bill, glass of wine, peaches / potatoes.
- 4 items of informal 2nd person plural.
- A Peninsular present-perfect item.
- Two multi-sentence UI and email strings.
- A formal email, a Slack message, news, technical docs, an idiom, and two polysemy items (run,
  bank).

**Engines and conditions:**

- **Opus base and tc-big:** CT2 int8, beam 4. Each was run on the **whole** input and on
  **regex-sentence-split** input.
- **Decoders:** TranslateGemma 4B (Q4_K_M), Llama 3.2 3B and Qwen3-4B-Instruct-2507 (Q4_K_M) via
  Ollama. Each was run in an es-ES condition and an es-419 condition.
  - TranslateGemma got its model-card prompt with `Spanish (Spain) (es-ES)` or
    `Spanish (Mexico) (es-MX)`.
  - The general models got an explicit instruction: "Peninsular Spanish … use vosotros … Spain
    vocabulary", or the LatAm equivalent.
- **Qwen3-4B default tag:** the default `qwen3:4b` tag is the thinking-only 2507 model. With
  `think:false` it still emitted reasoning preambles, so the run was killed and the `-instruct`
  tag used instead.

Scoring is automatic substring matching for the lexical and vosotros items, plus manual reading of
every output. The table counts *items*. It is not a quality metric.

| Engine / condition | es-ES lexeme on lexical items (/10) | LatAm lexeme (/10) | vosotros on 2pl items (/4) | Content omitted |
|---|---|---|---|---|
| opus-mt-en-es, whole input | 7 | 2 | 0 | **2 drops**: "Are you all ready?" vanished; "We apologise for the inconvenience." vanished |
| opus-mt-en-es, split | 7 | 2 | 0 | 0 |
| opus-mt-tc-big, whole input | 7 | 3 | 0 | 0 (merges sentences with commas, no loss) |
| opus-mt-tc-big, split | 6 | 4 | 0 | 0 |
| TranslateGemma 4B `es-ES` | 8 | 0 | **3** | 0 |
| TranslateGemma 4B `es-MX` | **7** (still *coche, aparcamiento, zumo, billete, móvil*) | 1 | 0 | 0 |
| Llama 3.2 3B, Spain prompt | 6 | 1 | 3 | "I might not answer" became "no responderé"; "on my mobile" dropped |
| Llama 3.2 3B, LatAm prompt | 3 | 5 | 0 | similar |
| Qwen3-4B-Instruct, Spain prompt | 8 | 1 | 4 (over-applied, see below) | "missed the train" became "he quedado fuera del tren" |
| Qwen3-4B-Instruct, LatAm prompt | 4 | 4 | 1 ("sentaos" in LatAm) | "me fui el tren" |

**Failures read by hand (MEASURED, single outputs):**

- **Opus base (both modes):** drops whole sentences when given multi-sentence input. This
  reproduces `10`. Sentence splitting fixes it.
- **Opus base and tc-big:**
  - Idioms come out literal ("Está lloviendo gatos y perros").
  - tc-big split rendered "the bill" as "la factura". Whole-input tc-big gave "la cuenta".
  - Address is inconsistent once sentences are split: "Niños, siéntense y cenen. **Espera a tu**
    padre"; "**Inicia** sesión… **Su** sesión ha expirado"; "Querida Sra. García, gracias por
    **tu** email… reunirme con **usted**". The plural "I'll call you" became singular "**Te**
    llamaré".
  - Otherwise clean, with three exceptions: tc-big split wrote "Mi batería **es** baja" (ser/estar), base rendered "gas" as "gasolina" for an oven, and base rendered "contact support" as "contacto con el **apoyo**" (wrong sense).
- **TranslateGemma 4B:**
  - Most fluent: "lloviendo a cántaros", "a orillas del río", consistent `usted` in the formal and
    UI strings.
  - **Grammar error:** "algunas melocotones" (gender agreement).
  - **Lexical error:** in the es-MX run "peaches" became "**melones**".
  - "a glass of red wine" became "un vaso" in both runs, where Spain wants "copa". Opus got "copa".
- **Llama 3.2 3B:** produced non-words and malformed forms.
  - "Niños, **sentadose** y **comedéis** **vuestro cena**"
  - "**Inclúyese** para continuar"
  - "**Ponése** a mi teléfono"
  - "lloviendo **chivos** y perros"
  - "peaches" became "manzanas"
  - "he **pasado** el tren"
- **Qwen3-4B-Instruct:**
  - **Vosotros over-applied** to a formal singular addressee: "Estimada Señora García, gracias por
    **vuestro** correo. **Os** estaría encantado de reunirnos". Also to singular requests: "**Os**
    pido un vaso de vino", "¿**Podéis** dar la cuenta?".
  - **Rioplatense voseo** in the es-ES condition: "**Ejecutá** … **reiniciá** vuestro terminal".
  - "**un** pequeño panadería"; "peaches" became "peras"; "jugo" in the es-ES condition.

**Conclusions from this set:**

1. **Telling a 3–4B general model "use Peninsular Spanish" trades one error class for another.**
   You get vosotros, but in the wrong places, plus new grammar errors. This matches `06`.
2. **Small enc-dec MT is the safest *grammatical* source per parameter.** Its failures are
   omission on multi-sentence input (fixed by splitting), literal idioms, and cross-sentence
   register drift (fixable in a post-pass, §3.4). It produced no non-words or agreement errors in
   this set.
3. **TranslateGemma 4B is the best translator here**, but it still made an agreement error and a
   lexical error in 48 outputs, and its region code does not control vocabulary.

### 2.3 Latency and memory (MEASURED unless marked)

| Engine | Disk | RAM | Per input (1–4 sentences, 7–25 words), median [range] | Notes |
|---|---|---|---|---|
| opus-mt-en-es, CT2 int8, beam 4, 4 threads | 77 MB | +387 MB after load, 501 MB max RSS | **91–101 ms** [40–175] | `10` measured greedy at ~38 ms for a 10–14-word sentence |
| opus-mt-tc-big-en-es, CT2 int8, beam 4, 4 threads | 226 MB | +545 MB after load, 674 MB max RSS | **206–213 ms** [109–464] | about 2× base |
| TranslateGemma 4B Q4_K_M, Ollama Metal, `es-ES` half | 3.3 GB pull, 2.9 GB resident (`ollama ps`) | (resident) | **1,070 ms** [597–1,690]; decode ~30 tok/s | The `es-MX` half slowed to a median of 1,490 ms with decode down to 12–20 tok/s late in the run. Cause unknown; thermal throttling is plausible on the fanless Air |
| Llama 3.2 3B, Qwen3-4B-Instruct | — | — | 1.5–2.5 s medians | **Contaminated.** Another session started `eval/vosotros_rate.py` with `qwen3:4b-instruct-2507-q8_0` on the same Ollama server at 17:56. Llama's run overlapped partly, Qwen's fully. Do not use these latencies |

The CT2 runs (17:44–17:45) and the TranslateGemma run (ended 17:47) predate that process. Whether
anything else was running during them was not checked.

**Full-text arithmetic (ESTIMATED from the rows above):**

- **Page size:** a 500-word page is about 25 sentences.
- **tc-big:** about 25 × ~0.1–0.2 s, i.e. **2.5–5 s** sequentially on CPU. Batching should cut this
  (unmeasured).
- **TranslateGemma at ~30 tok/s:** about 700–800 Spanish tokens is **~25 s** of decode alone.
- **What follows for S4/S5:** Opus-class MT can convert a page as it is opened. A 4B decoder needs
  background pre-translation or progressive rendering. This is a throughput argument for enc-dec
  that the per-span latencies in `10` hid.

### 2.4 License notes for the stage engines

- **Opus-MT tc-big:** CC-BY-4.0. Commercial use is fine; ship the attribution.
- **Opus-MT base:** Apache-2.0.
- **TranslateGemma:** Gemma Terms. They require use restrictions in the app's ToS, a Notice file,
  and acceptance of Google's remote-restriction right (`10` §4).
- **⚠ Do not distil TranslateGemma into the Opus fine-tune.** The Gemma Terms define "Model
  Derivatives" to include models trained with "synthetic data Outputs by Gemma … to cause that
  model to perform similarly to Gemma". This is quoted from the license text that ships inside the
  Ollama `translategemma:4b` Modelfile, read this session. Synthetic es-ES data from TranslateGemma
  would turn the shipped Opus model into a Gemma derivative. Use real parallel data or an
  Apache-licensed generator for synthetic data.
- **Excluded, as in `10`:** NLLB, SeamlessM4T, Tower/Tower+ (all NC), and HY-MT (territory
  exclusion).

## 3. Variety control for MT

### 3.1 Target tags: the standard method, but not available off the shelf for Spanish

- Variety tags (Johnson-style `<2es_ES>` tokens) with multilingual-style training are the
  established method. Lakew et al. found that treating varieties as one class gives inconsistent
  output, and that tagged multi-variety training gave significant BLEU gains for pt-BR/pt-PT and
  fr/fr-CA ([WMT 2018, W18-6316](https://aclanthology.org/W18-6316/)).
- FRMT (Google, TACL 2023) is the region-aware benchmark. It covers pt-BR/PT and zh-CN/TW, has a
  *lexical* bucket of region-divergent terms, and assumes 0–100 exemplars per region
  ([arXiv 2210.00193](https://arxiv.org/pdf/2210.00193)). **No es-ES vs es-419 equivalent was
  found.**
- **No checkpoint at the scale considered here has a working Spanish-variety tag:**
  - Opus-MT has a single `spa` target.
  - MADLAD's `es_MX` tag **collapses** to chrF 5.7 on NTREX (REPORTED, above).
  - TranslateGemma accepts `es-MX` (MEASURED: the prompt ran) but moved only pronouns and
    *computadora*.
- DeepL ships "Spanish (Latin American)" (ES-419) as "a general, more neutral style of Spanish"
  ([DeepL](https://support.deepl.com/hc/en-us/articles/360019925219-Languages-supported-by-DeepL)).
  That is a reasonable working definition of the app's es-419 target too.

### 3.2 Lexicon via constrained decoding: works now, with CT2 `suppress_sequences` (MEASURED)

**Capabilities.** CT2's `translate_batch` exposes `suppress_sequences`, `target_prefix`,
`prefix_bias_beta`, `return_alternatives` and `end_token`. It has **no positive lexical constraints**
("this word must appear")
([CT2 Translator API](https://opennmt.net/CTranslate2/python/ctranslate2.Translator.html)).

**Test.** I banned the other variety's lexemes, lower-case and capitalized, as target-SPM token
sequences:

- **es-ES:** ban *carro, auto, computadora, celular, jugo, maneja, boleto, departamento,
  billetera, papas, duraznos, frutillas, estacionamiento*.
- **es-419:** ban *coche, aparcamiento, ordenador, móvil, zumo, conduce/conducir, billete, piso,
  cartera, patatas, melocotones*.

I then re-ran tc-big (split mode) on the 13 lexical and idiom items.

**Results:**

| Item | es-ES bans | es-419 bans |
|---|---|---|
| car | coche … aparcamiento | **auto … estacionamiento** |
| computer | **ordenador … lo reinicié** | computadora … la reinicié |
| juice | **zumo** | jugo |
| ticket | billete | **boleto**, but register flipped to usted ("No se olvide de comprar su boleto") |
| peach | melocotones, patatas | **duraznos, papas** |
| mobile | móvil | teléfono (neutral) |
| drive | conduce | **"Él va al trabajo"**: meaning of *drive* lost |
| bill | **factura** (not banned) | factura |
| wallet | **cartera** | billetera |

**Agreement survives because the decoder conditions on what it has emitted.** That is the decisive
advantage over a deterministic post-edit (§3.4).

**Lessons:**

1. Ban only the *other* variety's **exclusive** forms. *Conducir* is not Peninsular-only, and
   banning it lost meaning.
2. Bans cannot *add* a preferred form. *Piso* never appeared for "apartment", and *cuenta* lost to
   *factura* in split mode. A second pass is needed for preferred forms: either an
   `return_alternatives`/n-best rerank by deck-lexicon score, or Dinu-style inline source
   annotation, which requires fine-tuning
   ([Dinu et al. 2019](https://aclanthology.org/P19-1294/), UNVERIFIED, not fetched).
3. The ban list comes straight from `data/es/peninsular_contrast.jsonl` `reject` fields plus the
   pack `variants`. It needs inflected forms (plural, capitalized) enumerated.

Suppress-run latency was 0.3–1.8 s per input. That run overlapped the other session's Ollama load,
so the latency is contaminated. Whether `suppress_sequences` itself adds measurable overhead is
unmeasured.

### 3.3 Fine-tuning Opus-MT on Peninsular / LatAm data

**Feasibility (MEASURED smoke test).** HF `MarianMTModel` on PyTorch MPS, AdamW, batch 16 × ~13
source tokens, 10 timed steps:

- **opus-mt-en-es (78M params):** 556 ms/step, 2.6 GB MPS allocated. Contaminated by the
  concurrent Ollama load.
- **opus-mt-tc-big-en-es (235M):** 1,026 ms/step, 3.4 GB, and the **loss was NaN** within 13
  steps at lr 2e-5. The cause is not diagnosed. Candidates are an MPS kernel issue, fp32 overflow in
  tc-big, or the tokenizer target path; the base model's loss was finite.

**So:**

- Fine-tuning base on the Air is practical as is.
- tc-big needs debugging on MPS (try CPU, fp32 with grad clipping, or a different torch) before
  it can be planned.
- **No published cost, data-size or forgetting figures were found for Marian variety adaptation.**
  The standard guard against forgetting is mixing general en-es data with variety-tagged data, as
  in Lakew (UNVERIFIED for this setting).

**Data:**

- **ParaCrawl is CC0** ([ParaCrawl](https://paracrawl.eu/news),
  [AWS registry](https://registry.opendata.aws/paracrawl/)). Filtering by source domain (`.es` for
  es-ES; `.mx/.ar/.co/.cl` for es-419) is the obvious split. Whether the release keeps per-pair
  source URLs is UNVERIFIED.
- **Europarl and DGT-TM** are EU-translator Spanish, probably Peninsular norms. Their licenses were
  not confirmed this session (UNVERIFIED). Their register is formal, so they are poor sources of
  vosotros.
- **OpenSubtitles:** mixed Spain/LatAm dubbing, and no corpus license was found. Avoid it for a
  shipped model.
- **The UN corpus** is neutral international Spanish.

**Vosotros is the hard part, because it is rare.**

- No measurement of vosotros frequency in parallel corpora was found.
- Formality resources (CoCoA-MT, IWSLT formality tracks) cover tú/usted, not vosotros/ustedes.
  CoCoA-MT includes en→es
  ([arXiv 2205.04022](https://ar5iv.labs.arxiv.org/html/2205.04022)). IWSLT 2023 had no Spanish
  ([IWSLT 2023](https://iwslt.org/2023/formality)).
- Vosotros is a *variety* feature, so formality tags will not produce it.
- A fine-tune will learn vosotros only if the tagged es-ES data contains enough informal 2pl. That
  probably means deliberately mining it: subtitle-like dialogue from Spain, or **rule-converting
  ustedes→vosotros in source-tagged informal-plural pairs** to create synthetic training data.

### 3.4 Deterministic post-edit with the deck tables: only for same-gender, clitic-free cases

`peninsular_contrast.jsonl` maps concepts to accepted and rejected forms. Swapping after decoding
is safe only when nothing else agrees with the swapped word.

- **Gender-preserving pairs are safe-ish:** coche/carro, zumo/jugo, patata/papa (but *papa* also
  means "Pope" and *papá* "dad"), móvil/celular.
- **Gender-changing pairs break agreement:** ordenador (m) / computadora (f). The measured
  tc-big output "Mi computadora se congeló … así que **la** reinicié" would become "Mi ordenador …
  **la** reinicié", which is wrong.
  - Fixing it needs determiner, adjective and **clitic** repair.
  - Clitics can sit clauses away from the noun.
  - spaCy is an analyser, not a generator (`10` §5).

**Rule:** prefer pre-decode bans (§3.2). Allow post-edit only for same-gender pairs with no
anaphoric clitic in the sentence. Re-run the agreement check after any edit.

**Address consistency** is a separate post-pass, and the most important one for S3–S5. Opus
decides tú/usted *per sentence* (§2.2), so the document needs one address form chosen up front:

- tú for UI and casual text, usted for formal email;
- vosotros or ustedes for the plural, by variety.

Then **force it**. One option is to translate with `target_prefix` per sentence where the opening
is predictable. The other is a rule rewrite of verb person, clitic and possessive, using verbecc
(LGPL) for the morphology. The 2pl rewrite (ustedes→vosotros for es-ES) is morphologically regular
(-an → -áis/-éis/-ís; imperative -ad/-ed/-id; *os*; *vuestro*). Two cases are ambiguous:

- *su* (his / her / their / your-formal);
- 3pl verbs that are genuine "they".

So gate the rewrite on a source-side cue ("you guys", "you all", "everyone", vocatives such as
"kids", plural antecedents) and let the resident LLM answer a closed question: "is *tienen* here
addressed to the listeners, yes/no?". This is the `10` verifier pattern, applied to address.

## 4. Runtimes on Apple Silicon

| Runtime | Encoder-decoder support | Apple GPU/ANE | Status |
|---|---|---|---|
| **CTranslate2** 4.8.2 | Marian, M2M-100, NLLB, T5, mBART, **T5Gemma** in the converter list. MADLAD is not listed, although it is T5-architecture ([CT2 Transformers guide](https://opennmt.net/CTranslate2/guides/transformers.html); `10` said MADLAD was supported, which conflicts, UNVERIFIED) | **CPU only**: Accelerate/Ruy; `device="mps"` → `ValueError: unsupported device` ([PyPI](https://pypi.python.org/pypi/ctranslate2), [forum](https://bbs.pyvideotrans.com/show/2912)) | Working here (MEASURED). CPU-only suits a 0.2B model: the GPU stays free for the resident LLM |
| **Ollama / llama.cpp** | libllama has T5 (`llama_encode`, [PR #8141](https://github.com/ggml-org/llama.cpp/pull/8141)), but **llama-server / llama-cli never call `llama_encode`**, so T5 GGUFs crash or emit garbage ([#26565](https://github.com/ggml-org/llama.cpp/issues/26565)). Marian → GGUF unsupported ([report](https://medium.com/@0x01aa/from-hugging-face-to-apple-silicon-my-journey-deploying-a-translation-model-on-macos-and-ios-c3062ae015cb)) | Metal | **Not viable for enc-dec.** Decoders only, i.e. TranslateGemma |
| **MLX** | Official T5 example (t5-small…11b, FLAN-T5) ([mlx-examples t5](https://github.com/argmaxinc/mlx-examples/blob/main/t5/README.md), fork mirror). **No MLX Marian, NLLB or M2M port found.** Third-party MADLAD-3B port (`10`) | Metal | Porting Marian is a contained mlx-kernels project: sinusoidal positions, standard cross-attention, the T5 example as template. Main value would be GPU batch throughput for S4/S5 whole-page conversion; per sentence, CPU int8 is already ~0.1–0.2 s |
| **ONNX Runtime** (+ CoreML EP) | A developer shipped opus-mt on macOS/iOS this way after llama.cpp, MLX and Core ML conversions failed ([Medium](https://medium.com/@0x01aa/from-hugging-face-to-apple-silicon-my-journey-deploying-a-translation-model-on-macos-and-ios-c3062ae015cb)). transformers.js quantized ONNX exists (`10`) | CoreML EP op coverage for the Marian decoder with KV cache: UNVERIFIED | Alternative to CT2 if C++ embedding is unwanted |
| **Bergamot / translateLocally** | Marian int8 students, MIT, native messaging for extensions ([summary](https://awesome.ecosyste.ms/projects/github.com%2FXapaJIaMnu%2FtranslateLocally)) | CPU | Mozilla en-es models are MPL-2.0. Native arm64 build: UNVERIFIED |
| **Apple Translation framework** | `TranslationSession` (macOS 15+), all processing on-device; `init(installedSource:target:)` works without SwiftUI once models are installed; batch API ([Apple docs](https://developer.apple.com/tutorials/data/documentation/translation/translationsession.json)) | Apple's own | **Not testable here.** This Mac has Xcode 15.4 (macOS 14.5 SDK), which ships the `Translation.framework` .tbd but no Swift interface for `TranslationSession`/`LanguageAvailability` (MEASURED: `cannot find 'LanguageAvailability' in scope`). The Translate app has "Spanish (Spain)"; iOS 27 beta adds "Spanish (Mexico)" ([Cult of Mac 2026-07-09](https://www.cultofmac.com/news/apple-translate-ios-27-9-new-language-support)); whether the API exposes es-ES vs es-MX as distinct targets is unknown. It is a black box: no lexicon bans, no prefix control. Known `.installed`-but-Code-16 bug ([forum 813109](https://developer.apple.com/forums/thread/813109)) |

## Verdict

**Engine per stage:**

| Stage | Engine | Variety control |
|---|---|---|
| **S1 words** | **Unchanged from `10`.** Deck-driven deterministic swap, forms from the card or verbecc, resident Apache 3–4B LLM as a closed-choice verifier | Free: the deck lemma is already es-ES or es-419 |
| **S2 phrases/chunks** | **Deck-driven where every lemma is in the deck.** Otherwise **Opus-MT tc-big on CT2**: translate the whole sentence, extract the chunk by alignment, verify with the LLM. Swap only syntactic constituents with no clitic crossing the boundary | Deck forms, plus tc-big `suppress_sequences` bans from `peninsular_contrast.jsonl` / pack variants |
| **S3 sentence flips** | **Opus-MT tc-big, CT2 int8, CPU, sentence-split** (never whole multi-sentence strings). It is the primary engine from here on: 0.23B, top FLORES en→es in the ≤3.3B class (REPORTED), no non-words or agreement errors in the measured set (one ser/estar slip), ~0.1–0.2 s per sentence, ~0.55–0.67 GB | Pre-decode lexeme bans (other variety's *exclusive* forms only), n-best rerank by deck lexicon for preferred forms, and the **document address pass** (one tú/usted/vosotros/ustedes decision per document, enforced by rule with an LLM yes/no gate) |
| **S4/S5 full text** | **Same tc-big pipeline**, batched over the page, plus an idiom/MWE guard (detect English idioms and keep them English-glossed or translate from a curated list), since Opus renders idioms literally (MEASURED) | Same, plus coverage tracking per §1.4 |
| **Quality tier (optional)** | **TranslateGemma 4B** for background pre-translation of saved articles: more fluent, idiomatic, register-consistent; best vosotros behaviour measured (3/4, no over-application) | Its `es-ES` code helps pronouns, **not** vocabulary, so the lexeme check still applies. Gemma Terms obligations. Never use its output as training data for the shipped MT |
| **Do not use** | General 3–4B instruct models (Llama 3.2 3B, Qwen3-4B) as **translators** at S3+. They produced non-words, voseo leakage and misplaced vosotros (MEASURED). Keep them as verifiers only | — |

**This reverses `10`'s "no dedicated MT as the primary engine" for S3 onward.** `10` was right for
in-context *span* swaps, where the deck should decide. Once whole sentences are Spanish, a
specialized 0.23B MT model beats a general 3–4B decoder per parameter, per millisecond and on
grammatical safety.

**The upgrade path for variety** is a **tagged es-ES/es-419 fine-tune of Opus-MT**:

- **Data:** CC0 ParaCrawl split by domain, plus mined or rule-synthesized informal-2pl pairs for
  vosotros.
- **Start with base** (fine-tuning on MPS is MEASURED to work) **until the tc-big NaN on MPS is
  understood.**
- **Ship it only if** it beats tc-big + bans + the address pass on the probes in Needs measuring.

## Needs measuring

All on the M3 Air unless noted, with **no other Ollama client running**. Check `ollama ps` and
`pgrep` before each run; this session's decoder latencies were contaminated by a concurrent
`eval/vosotros_rate.py`.

1. **Same-scale quality head-to-head.** Use FLORES-200 devtest en→spa (1,012 sentences) and
   WMT24++ en→es_MX.
   - **Engines:** opus-mt-en-es, opus-mt-tc-big, Mozilla base-memory, MADLAD-3B (CT2 if it
     converts), TranslateGemma 4B Q4_K_M, Qwen3-4B-Instruct, Gemma 4 E4B, SalamandraTA-2B.
   - **Metrics:** chrF++ and MetricX-24 or COMET-22. CometKiwi's license is UNVERIFIED (believed
     non-commercial), so use it for evaluation only.
   - **Purpose:** this is the missing Opus-vs-TranslateGemma comparison.
2. **es-ES / es-419 generation benchmark (FRMT-style).** About 100 sentences, each containing one
   divergent concept from `peninsular_contrast.jsonl`, plus ~40 informal-2pl and ~20 formal-2pl
   sentences.
   - Score lexeme hit rate, vosotros recall, **vosotros false-positive rate** (Qwen's failure), and
     usted preservation.
   - Engines: tc-big ± bans ± address pass, TranslateGemma with each region code, and the
     fine-tune.
3. **Ban list quality.** Measure the meaning-loss rate when bans fire, i.e. the *conducir* → "va al
   trabajo" class, human-judged. Curate an *exclusive-forms* list. Measure whether n-best rerank
   recovers preferred forms (*piso*, *cuenta*).
4. **Address-consistency pass.** On ~50 multi-sentence UI, email and dialogue strings, measure
   per-document tú/usted/vosotros consistency before and after the rule pass, plus the LLM gate's
   yes/no accuracy on "is this 3pl verb addressed to the listeners".
5. **Fine-tune.**
   - Diagnose the tc-big NaN on MPS: CPU run, grad clipping, fp32 attention, a different torch.
   - Fine-tune base, then tc-big, on domain-split ParaCrawl with `<es_ES>`/`<es_419>` tags.
     Report steps/hour, data size vs vosotros recall, and FLORES drop (forgetting).
   - Confirm that ParaCrawl keeps source URLs for the domain split.
6. **Full-page throughput.** Run tc-big CT2 batched over a 500-word page at 1/2/4/8 threads, and
   record sustained thermals over 20 minutes of S4 reading on the fanless Air. Compare with
   TranslateGemma background pre-translation; the page estimates in §2.3 are arithmetic only. Also
   check whether `suppress_sequences` with ~100 banned sequences adds latency.
7. **Apple Translation framework.** Install Xcode 16+ and print
   `LanguageAvailability().supportedLanguages` and `status(from: en, to: es-ES | es-MX | es-419)`
   on macOS 26 (and 27 when available).
   - If es-ES and es-MX are distinct targets, run benchmarks 1 and 2 on it.
   - It would be a zero-weight engine with built-in variety, but a black box.
   - Also confirm it works in a non-sandboxed Developer ID app (the `09` AX helper constraint).
8. **Learner-side checks of the progression (owner as subject).** Measure reading speed and reveal
   rate at S1 word density vs S3 sentence flips for the same page and the same known-lemma
   coverage. This is the only direct test of the "word-mixing ceiling" in §1.3, which no published
   study has run. Add a delayed (1–4 week) recall check on words met mostly in flipped sentences
   vs mostly as word swaps.
9. **Coverage estimator accuracy.** Compare spaCy-lemmatized MT output against SRS state, using the
   owner's self-report as ground truth on ~30 sentences. This validates the §1.4 S3 gate (≥95%
   known/inferable).
10. **MLX Marian port.** It is a candidate mlx-kernels project. Its worth depends on benchmark 6
    showing CPU CT2 is the S4/S5 bottleneck.

---

*Measurement artifacts (session scratchpad, not the repo):* `bench/mt13_set.py`,
`bench/mt13_ct2.py`, `bench/mt13_ollama.py`, `bench/mt13_suppress.py`, `bench/ft_smoke.py`, and
the raw outputs `bench/r_*.json`. Models pulled to Ollama this session: `translategemma:4b`
(3.3 GB), `qwen3:4b` (thinking-only), `qwen3:4b-instruct`. The CT2 tc-big int8 conversion is in
`models/tcbig-en-es-int8`.
