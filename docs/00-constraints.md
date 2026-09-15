# Locked constraints (2026-09-12)

Answered by Matt at kickoff. These override any generic recommendation in `research/`.

| Constraint | Value | Consequence |
|---|---|---|
| **Trip** | Departs for Spain in **< 3 weeks** (so ~2026-10-03 at the latest) | Ruthless MVP. One forcing-function loop that works end to end. **No RL in v0.** Adaptation is deferred, but logging for it is not. |
| **Device** | **Mac only** (M3 Air, 16GB, fanless) | Python. Full MLX access. No Swift, no iOS build, no phone port in scope. Practice happens at the hotel/airbnb/plane, not on the street. |
| **Level** | **Unknown** | A CEFR placement probe is **step one of the product**, not a nice-to-have. The app must place him before it can pressure him. |
| **Offline** | Hard requirement | Everything ships local: model weights, ASR, TTS, content. Assume zero connectivity in Spain. |
| **Variety** | Peninsular / Castilian | vosotros, distinción (θ), Spain lexicon and pragmatics. |

## What this means for scope

**In v0:**
- CEFR placement probe (spoken, ~5 min, produces a starting level + weak-area profile)
- One voice loop: VAD → ASR → local SLM → TTS, low enough latency to feel like a conversation
- Scenario engine with genuine exit conditions (you resolve the situation in Spanish or you don't leave)
- Utterance logging with audio, designed so offline adaptation is possible later
- Travel-survival scenario set: airport, hotel check-in, bar/tapas, pharmacy, directions, trains, problems (lost bag, wrong charge)

**Explicitly out of v0:**
- Any weight-level adaptation / LoRA / DPO / GRPO
- Bandit or RL item selection (a fixed heuristic scheduler is fine)
- iPhone anything
- Multiplayer, accounts, sync, polish
