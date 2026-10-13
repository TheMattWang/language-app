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
