# 06 — Measured baseline on the actual machine

Run 2026-09-12 on Matt's M3 Air (16GB, 10 GPU cores, fanless), Ollama, models already
on disk. This track is **measurement, not literature** — it exists to settle cross-track
question #1 with numbers instead of reading. Scripts in the session scratchpad
(`bench/llm_bench.py`, `bench/quality_probe.py`).

## TL;DR

1. **Latency is not the problem.** A full conversational turn from a 3B model takes
   **0.81s wall**; a 1.5B takes **0.35s**. The LLM was assumed to be the thing that
   killed the local-voice-partner dream. It isn't. The remaining budget belongs almost
   entirely to ASR + TTS, and track 03 should be told it has ~1.5s to play with, not ~0.5s.
2. **Register discipline is the real problem.** All three viable models **failed the
   vosotros probe** despite an explicit system-prompt instruction *and* an explicit
   in-context cue ("Somos dos"). Peninsular Spanish cannot be obtained by asking for it.
3. **Character breaks are frequent and they are fatal to the product thesis.** The app's
   whole premise is that the learner *cannot exit* into English. Every model tested
   offered an exit within five turns.
4. **These models are not a trustworthy source of Spanish.** They emit ungrammatical and
   invented Spanish often enough that a learner would absorb errors from them.

---

## 1. Latency

Realistic setup, not a cold one-shot: system prompt + 7 prior turns of a tapas-bar
scenario (~300 prompt tokens), `num_predict=60`, `num_ctx=2048`. Median of 3 runs
after a discarded warm-up.

| model | TTFT (prefill) | decode tok/s | out tok | gen s | **wall s** |
|---|---|---|---|---|---|
| qwen2.5:0.5b | 0.008 | 152.3 | 25 | 0.16 | **0.24** |
| qwen2.5:1.5b | 0.014 | 77.9 | 21 | 0.28 | **0.35** |
| llama3.2:1b | 0.018 | 60.0 | 27 | 0.46 | **0.56** |
| gemma2:2b | 0.027 | 36.9 | 13 | 0.36 | **0.64** |
| llama3.2:3b | 0.030 | 30.2 | 24 | 0.71 | **0.81** |
| qwen3.5:2b | 0.566 | 21.3 | 60 | 2.81 | **4.10** |

**Prefill is free** at this context size — 8–30ms for ~300 tokens. Long scenario
histories are affordable; there is no reason to aggressively truncate context for speed.

**Decode tok/s tracks model size as bandwidth-bound theory predicts** (~100GB/s on base
M3). Nothing anomalous, so the numbers should extrapolate: a 7–8B Q4 would land around
12–15 tok/s, i.e. ~2s per turn — the upper edge of tolerable, and that is *before*
speech. **7B+ is likely out** for the live conversational loop regardless of quality.

### The reasoning-model trap

`qwen3.5:2b` returned an **empty reply** at `num_predict=60` and took 4.1s. It spent the
entire token budget on internal reasoning and never reached the visible answer. For a
latency-bound conversational partner, reasoning models are disqualified by construction —
their whole value proposition is spending tokens before answering, and here tokens are
the budget. Either disable thinking explicitly or do not select these models.

## 2. Quality probes

Five adversarial probes against the tapas-bar persona, system-prompted to use **vosotros**,
stay in Spanish, never break character, and reformulate learner errors rather than
correcting them explicitly.

### 2.1 vosotros — **failed by all three models**

Prompt: *"Somos dos. Que nos recomiendas para compartir?"* — first-person plural, the
clearest possible cue to answer in vosotros.

| model | reply | verdict |
|---|---|---|
| llama3.2:3b | "…¿**Quieres** algo para acompañarlas?" | tú, not vosotros |
| qwen2.5:1.5b | "**Nos sugeriría** unas tapas…" | wrong person entirely |
| gemma2:2b | "¿qué **te** parece las croquetas…?" | tú, and `te parece` + plural noun disagrees |

This is the single most important result in this file. The instruction was explicit, the
context cue was explicit, and all three ignored it. Peninsular register is not reliably
promptable at this scale.

Note gemma2:2b *did* produce `os gustaría` and `venga` spontaneously on other probes —
so the forms are in the model; they just are not under instruction control. That
distinction matters: it means the fix is decoding/verification, not a bigger model.

### 2.2 Character breaks — the product-critical failure

The forcing function only works if English is not an available exit. Every model offered one:

- **qwen2.5:1.5b** dropped the persona completely when the learner said "I don't know how
  to say this in Spanish": *"Claro, puedo ayudarte con español. ¿Cómo te llamas y qué te
  gustaría que dijeras en inglés…?"* — it stopped being a waiter and became a language
  tutor offering to work in English. Worst possible response to exactly the moment the
  learner most needs to be held in Spanish.
- **gemma2:2b** appended a parenthetical English translation: *"¿Me puede decir en qué
  ayuda?\n\n(Can you tell me what you need help with?)"* — unprompted subtitling. The
  learner will read the English and stop parsing the Spanish.
- **llama3.2:3b** code-switched a single English word into otherwise-Spanish output:
  *"¿Quieres que te dé **directions**?"*

It also drifted person mid-scenario — `tú` in one turn, `usted` ("¿Qué es lo que no
**entiende**, amigo?") in the next. Inconsistent address is worse for a learner than
consistently-wrong address, since the learner is trying to acquire the pattern.

### 2.3 Peninsular vs Latin American vocabulary

Probe used two LatAm markers (`agarrar`, `carro`) to see whether the model is pulled
out of Peninsular register by the learner's own word choice.

- **gemma2:2b — best.** Answered with `coche`, `parking`, and the Peninsular discourse
  marker `venga`. Held register against the pull.
- **llama3.2:3b — leaked.** `estacionamiento` (LatAm) where Peninsular wants `aparcamiento`.
- **qwen2.5:1.5b — misunderstood.** Read `carro` as a hotel luggage cart: *"¿En qué momento
  podrías pedir el carrito del hotel?"*

**Ranking here is the inverse of model size**, which is worth noting: parameter count did
not predict Peninsular fidelity.

### 2.4 Spanish that is simply wrong

Errors a learner would absorb:

- llama3.2:3b: *"una copa tinto"* (missing `de`), *"la cuenta es la factura"* (conflates
  a restaurant bill with a formal invoice).
- qwen2.5:1.5b: *"alcachofas con salchichón"* and *"guisado de ternera"* offered as
  *"tapas tradicionales madrileñas"* — invented menu, not Madrid tapas canon.
  Also *"La cuenta, señora."* — asserts the learner's gender with no evidence.
- gemma2:2b: *"¿Cuánto os gustaría pagar?"* ("how much would you like to pay?") in
  response to a bill request — fluent, correct Spanish, nonsensical pragmatics.

## 3. What this implies for the architecture

**The bet that needs to change: the model is the conversational engine, not the language
authority.** Freeform generation is fast enough but not correct enough to be the thing a
learner imitates.

Concretely, for synthesis to absorb:

- **Content should be sourced or templated, not generated.** This answers cross-track
  question #5 ahead of 05/02: the vocabulary, the menu, the register, and the phrases the
  learner is exposed to should come from vetted content. Let the model handle *turn-taking
  and flexibility within constrained bounds*, which is what it is actually good at.
- **Register needs enforcement outside the model.** Cheap and worth prototyping: a
  post-generation validator that regex-checks for vosotros forms, LatAm lexical items
  (`carro`, `estacionamiento`, `agarrar`, `computadora`, `jugo`, `papa`), English tokens,
  and parenthetical translations — and regenerates on failure. At 0.35–0.81s a turn,
  **there is latency headroom to regenerate once or twice and still stay conversational.**
  This is the main practical use of the speed surplus.
- **Character-break prevention is a feature, not a prompt.** The "I don't know how to say
  this" moment is the highest-value moment in the entire app — it is precisely the forcing
  function firing. It must be handled by designed application logic (scaffold in Spanish,
  offer a circumlocution, let the character not understand English), never left to the
  model's discretion.
- **Give track 03 a bigger budget.** If the target turnaround is ~1.5–2.0s end-to-end and
  the LLM takes 0.35–0.81s, ASR + TTS + VAD may consume ~1.0–1.5s. That is a materially
  easier speech problem than was assumed and may re-open options (larger Whisper, better TTS)
  that would otherwise have been ruled out on latency.

## 4. What this run did NOT test

Named so it does not get mistaken for settled:

- **Thermals / sustained load.** Single turns on a cold fanless machine. A 20-minute
  session with ASR + LLM + TTS all resident is the real thermal question, untested here.
- **Memory under the full stack.** Only the LLM was resident. The RAM zero-sum
  (cross-track question #2) is unmeasured.
- **Ollama vs MLX.** Ollama numbers only, because that is what was installed. MLX may be
  faster; given the LLM is already not the bottleneck, this is now a **low-priority**
  question rather than a blocking one.
- **Quantization effects.** Used whatever quant Ollama ships by default per model; did not
  isolate quality-vs-quant, which matters more now that quality — not speed — is the
  binding constraint.
- **Models not on disk.** No Qwen3-4B, Ministral, Phi-4, or Spanish-specific (Salamandra/
  ALIA) models were tested — those are track 02's brief. **Track 02's candidates should be
  re-run through `quality_probe.py`**, since the vosotros/character-break probes discriminate
  far better between models than any published benchmark will.

## 5. Reusable artifact

`quality_probe.py` should move into the repo as the project's first eval harness. The five
probes (`vosotros`, `l2_errors`, `breakdown`, `es_LA_trap`, `recovery`) are a genuine
model-selection gate: they separated three models that all look equivalent on paper, and
`breakdown` in particular tests the exact behaviour the product depends on.
