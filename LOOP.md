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
- `interp/quality/colab_quality.py`: full-scale rerun with length-preserving meaning corruptions
  (negation/number/entity/antonym), a length baseline column, bootstrap CIs, two models.
  First T4 run died at the Colab session ceiling before saving anything. Fixed (92e1cca):
  `interp/quality/colab_run.sh MODEL [GPU]` runs one model per session, saves after every stage,
  pulls partials to `interp/quality/colab_out/` each poll, and stops the session when done.
  **Running now (retry):** Qwen/Qwen3-4B-Instruct-2507 on T4 (first retry got `Service Unavailable` assigning a T4,
  then a local DNS blip; runner now exits 2 when no GPU is assigned — T4 stayed unavailable, so Matt chose L4 on 2026-10-13). **Running now on L4:** Qwen then Gemma, sequentially. Then: unsloth/gemma-3-4b-it (fp16 on T4 may NaN;
  the script skips it if so — then rerun on L4, which has bf16).

## Open decisions for Matt
- Gemma 3 4B vs Qwen3-4B-2507 as the conversation model (decide on the Colab quality results).
- qwen2.5:3b is research-licensed: must not ship as `drill/llm.py`'s default.
