# Language geometry

**Question:** where does a model keep *which language it's in*, as opposed to *what's being said*? And is a variety (Spain vs Latin American Spanish) a small language, a style, or a handful of word-level features?

**Why it matters (the optimize hook):** drill's conversation partner needs to speak a chosen variety reliably, and small models don't (`research/06`, `14`). If variety lives in a few layers along a few directions, we can steer or fine-tune just those layers instead of the whole model. That's the `interp → optimize what's load-bearing` loop on a real product. Long term it has to cover *every* language, so the harness is language-agnostic: NTREX-128 gives the same 1,997 sentences in 128 languages, including regional variants (spa/spa-MX, por/por-BR, fra/fra-CA, eng-GB/US/IN).

## What's run (worked first pass)
`language_geometry.py` measures four things layer by layer, on the mean-pooled residual stream (`capture.py` works for any mlx-lm model):

| | Measures | Fundamental |
|---|---|---|
| A | linear probe: which of 15 languages? (held-out sentences) | linear readability = something the model can use with one direction |
| B | translation retrieval en→X after per-language centering | meaning is shared across languages once you subtract the language mean |
| C | between-language variance / total | an R² for "language explains the geometry" |
| D | Spain vs LatAm probe on **minimal pairs**, tested on **held-out words** | controlled contrast: only the variety marker differs |
| E | does the es variety direction also separate pt/pt-BR, fr/fr-CA, en-GB/US? | exploratory: is there a shared "European vs American variety" axis? |

**Confound to remember:** NTREX's spa and spa-MX are *independent translations* (15/1997 lines identical). So comparing them conflates variety with translator style, which is why D uses minimal pairs. E uses NTREX anyway and is labelled exploratory for that reason.

**Expected picture** (Wendler et al. 2024, *Do Llamas Work in English?*): language identity is strong in early and late layers, while meaning converges in the middle (a "semantic hub"). Check whether this model shows it.

## First results — Qwen3-4B-Instruct-2507 (4-bit MLX), n=150/language, 2026-10-12
`results.json`, `language_geometry.png`. One run, one model, one seed.

- **C is the informative curve, not A.** Language explains 53% of variance at layer 0, falls to **0.22 at layer 10**, stays about 0.24 through layer 18, then climbs to 0.78 by the last layer. That's the U-shape of a semantic hub.
- **B agrees.** Translation retrieval is **0.93–0.95 from layer 6 to about 23** and drops at both ends. Layer 0 already gets 0.78, because news text shares names and numbers across languages, so the pooled tokens alone retrieve the translation. That's a floor to remember, not a finding.
- **A is saturated (1.00 at every layer, layer 0 included)**, because scripts and tokens give the language away at the embedding layer. A 15-way language probe is too easy to show anything. To learn something, make it harder: close pairs like es/pt/it, or code-switched text.
- **D: the vosotros/ustedes probe is 1.00 from layer 0**, so it detects the *token* (`-éis/-áis` subwords are shared across verbs, so held-out verbs don't help), not an abstract feature. **The lexical probe on held-out words is near chance** (0.29–0.75, noisy, with only 5 held-out words). So this design hasn't found a "Spain vocabulary" direction that generalizes across words.
- **Lexical vs address directions:** cosine is about 0.0–0.15 at every layer. Weakly related at most.
- **E (shared Europe-vs-Americas axis):** 57% es, 63% pt, 55% fr, which is near chance. en-GB vs en-US came out at 9%, i.e. *opposite*. Both are confounded by translator style.
- **Correction:** a 10-sentence pilot looked like "variety is a late-layer feature" and "a shared axis at 70%". At n=150 neither holds. Those were noise.

**The design fix the results point to:** pool only the positions *after* the variety marker, not the marker token itself. "Chicos, ¿de verdad queréis **eso?**" asks whether the model carries "this is a vosotros context" forward into later tokens, which is what it would need in order to *produce* vosotros later (agreement on `os`, `vuestro`). If that downstream signal exists and generalizes to held-out verbs, it's the direction worth steering. If it doesn't, variety is mostly token-local.

## Your turn — the causal half
A probe only shows the information is *there*. It doesn't show the model *uses* it. Next:

1. **Activation patching on the address pairs.** Run "Chicos, ¿de verdad queréis eso?" and the `quieren` version. Then patch the residual stream at layer L from one run into the other and watch the logit difference for the next vosotros/ustedes-dependent token. A good target is a continuation that has to agree, like a clitic `os`/`les`. Which layers carry it causally?
2. **Steering.** Add `α · d` (d = the D difference-of-means direction at the best layer) during *generation* with the waiter prompt from `eval/vosotros_rate.py`. Does the vosotros rate move? At what α does the Spanish break? This is the training-free fix `research/14` §3 proposes, and it's MLX-only at runtime (wrap `model.layers[i]` like `capture._Tap` does, but *add* instead of record).
3. **Lexical vs address.** D reports the cosine between the "Spain vocabulary" direction and the "vosotros" direction. If they're near-orthogonal, "variety" is several features, not one axis, and a single steering vector won't cover it.

Long runs go on Colab (MLX doesn't run there: use the HF/PyTorch weights of the same model and register forward hooks).
