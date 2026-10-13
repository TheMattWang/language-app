# Does the model know when its Spanish is wrong?

`quality.py` compares three reference-free signals on Qwen3-4B-Instruct-2507 (4-bit MLX), run 2026-10-12. One model, one seed. `results.json`, `quality.png`.

## Results

**EsCoLA dev** (1,053 sentences labelled by linguists, 308 ungrammatical). This is an *absolute* judgement: is this sentence OK?

| signal | AUC |
|---|---|
| surprisal, mean log-prob | 0.639 |
| surprisal, min log-prob | 0.561 |
| linear probe on residual (best, layer 20) | **0.695** |

The probe climbs from 0.51 at layer 0 to about 0.69 by layers 18–22, then eases off. Both signals are weak here. EsCoLA's errors are subtle, and research/02a already put 3–4B models' EsCoLA MCC near 0.2.

**Controlled corruptions** (NTREX Spanish, each clean sentence vs one corrupted copy). This is *relative*: which of the two is better? Each cell is the fraction ranked correctly; ties count half.

| corruption | n | surprisal mean | surprisal min | probe | hub |
|---|---|---|---|---|---|
| gender (el→la) | 139 | **0.93** | 0.56 | 0.86 | 0.76 |
| verb_number (ha→han) | 68 | 0.87 | 0.42 | **0.91** | 0.79 |
| nonword (gobeirno) | 142 | **0.99** | 0.80 | 0.98 | 0.93 |
| drop_clause | 80 | 0.81 | 0.39 | 0.54 | **1.00** |
| swap_content | 150 | 0.97 | 0.68 | **0.99** | **0.99** |

## What it says
1. **Form errors: mean surprisal already works when comparing two versions.** It scores 0.87–0.99, and the probe adds little (it wins only on verb number). It's cheap and available on both runtimes, since Ollama returns `logprobs` (checked on v0.40.3).
2. **Meaning errors: the hub check is the one that works.** Cross-lingual alignment in layers 6–23 caught **every** dropped clause (1.00), where the grammar probe was at chance (0.54). That is exactly the Opus-MT failure in research/13, so it's the natural adequacy gate for immersion's sentence and full-text stages.
3. **No signal is a good *absolute* grammaticality judge** (AUC ≤ 0.70). In product terms: use these to **rank candidates** (generate 2–3 replies or translations and keep the best), not to accept or reject a single one.

## Caveats before trusting this
- **Self-scoring bias.** These are human sentences with injected errors. The model's *own* errors ("Tieneis", "como el prometí") were sampled by the model, so it gave them non-trivial probability. Surprisal from the same model may miss exactly those. Next test: real failures from `eval/results/vosotros_rate-*.json`, hand-labelled, scored by the same model and by a second one.
- **The corruptions are easy.** A swapped letter or a cut clause is far cruder than a 4B model's actual mistakes.
- **Length.** drop_clause shortens the sentence, which moves mean surprisal by itself; the 0.81 may partly reflect that.
- **One model.** Repeat on Gemma 3 4B (on Colab).

## Colab rerun, 2026-10-13 (`colab_quality.py`, L4, full-precision HF weights, 95% bootstrap CIs)
This fixes the MLX run's flaws. The meaning corruptions are now fluent and length-preserving (negation, number, entity, antonym), and the length baseline sits at chance on them (0.50–0.59). Pairs are capped at 400 per type, and EsCoLA train is used in full. Raw results: `colab_out/*.json`.

| clean ranked higher | Qwen3-4B surprisal | Qwen3-4B hub | Gemma 3 4B surprisal | Gemma 3 4B hub |
|---|---|---|---|---|
| gender | **0.94** [.91,.96] | 0.71 | 0.85 [.81,.88] | 0.47 |
| verb_number | 0.92 | 0.84 | 0.91 | 0.61 |
| nonword | 0.99 | 0.93 | 0.97 | 0.90 |
| negation | 0.90 [.87,.93] | **0.95** [.93,.97] | 0.81 [.78,.85] | 0.81 |
| number | 0.83 [.79,.87] | **0.92** [.89,.95] | 0.78 | 0.91 |
| entity | 0.86 | **0.93** | 0.84 | 0.93 |
| antonym | 0.89 [.86,.92] | **0.93** [.91,.96] | 0.87 | 0.76 |
| EsCoLA AUC (probe / surprisal) | 0.728 / 0.647 | | 0.720 / 0.624 | |

- **Meaning:** Qwen's hub check (layers 6–30) is the best meaning signal: 0.92–0.95, above its own surprisal, with non-overlapping CIs on number and negation.
- **Qwen's surprisal is more sensitive to broken Spanish than Gemma's.** Gender 0.94 vs 0.85 and negation 0.90 vs 0.81, both with non-overlapping CIs. That is mild evidence that Qwen's Spanish knowledge is stronger. It measures *judging* Spanish, not *producing* it.
- **Gemma's hub is undefined, not just weak.** Its retrieval curve is flat (peak 0.92), so the 95%-of-peak rule selected layers 1–33, nearly all of them, and averaging dilutes the signal. Gemma's hub numbers understate what a per-layer choice would find. Picking the hub layer on held-out pairs is the fix.
- The EsCoLA probe beats surprisal on both models (0.72–0.73 vs 0.62–0.65). The layer is chosen on dev, so the probe numbers are slightly optimistic.
