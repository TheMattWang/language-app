# LOOP — working state (handoff across context compaction)

Updated 2026-10-13. Branch: `product-foundation` (no git remote; nothing pushed).

## Where things stand
- **Product foundation done** (commits ce43b04..fc580ba): `drill setup` (dialect es-ES/es-419, optional goal date),
  data/es/ language pack + manifest, drill/llm.py (Ollama + MLX), drill/register.py (reply validator),
  drill/probes.py + `drill probe`, Ollama-timeout message fix. 384 tests green.
- **Research 09–14 committed.** Decisions so far: Apple Silicon only; immersion = progressive (deck-driven
  word swaps → opus-mt-tc-big for sentence/full-text stages); no fine-tune for vosotros.
- **Vosotros measured** (eval/results/vosotros_rate-*.json, prompt_ablation-*.txt): naming the forms in
  the system prompt is what works — Gemma 3 4B and Qwen3-4B-2507 reach 100%. Quality of the Spanish,
  not address form, is now the open risk.
- **interp/** in this repo: language_geometry (semantic hub layers ~6–23 on Qwen3-4B; vosotros probe
  is token-level), quality (MLX run: surprisal ranks form errors; the "1.00" hub result on dropped
  clauses was mostly a length effect — length-ratio baseline alone scored 0.89).

## In flight
- Colab quality rerun (`interp/quality/colab_run.sh MODEL L4`; results in `interp/quality/colab_out/`).
  **Qwen3-4B-2507 done** (bf16, L4): length baseline at chance on the new fluent meaning corruptions;
  hub check best on meaning (0.92–0.95), surprisal ≈ probe on form (0.90–0.99); EsCoLA probe 0.728
  [.69,.76] beats surprisal 0.647. **Gemma 3 4B:** run 1 lost (session died, download hung; downloads now
  capped at 90s); run 2 failed in the probe SVD — fp16 storage overflowed Gemma's massive activations
  (fixed 14c2bf3: fp32). Run 3 in flight on L4.

## Open decisions for Matt
- Gemma 3 4B vs Qwen3-4B-2507 as the conversation model (decide on the Colab quality results).
- qwen2.5:3b is research-licensed: must not ship as `drill/llm.py`'s default.
