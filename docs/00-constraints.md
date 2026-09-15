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

---

# CANCELLED (2026-09-14)

**The app described above is cancelled. Nothing in it was built.** This file is kept as a record of what was intended and why it stopped.

## What killed it

The whole product rested on one assumption: that macOS per-app language override would flip a browser's UI to Spanish, creating the forcing function. The test was run on 2026-09-14:

```
defaults write com.google.Chrome AppleLanguages -array es-ES es
# full quit + relaunch -> UI stayed in English
```

**It did not work.** The override was applied and reverted cleanly (`defaults delete`, verified); the machine carries no residue.

Recorded precisely, because the failure is not the one the research predicted:

- `Google Chrome.app/Contents/Resources/es.lproj` is a **1.2 KB stub** containing only `InfoPlist.strings` — the Finder-facing app name, not the interface.
- The real Spanish UI is at `Contents/Frameworks/Google Chrome Framework.framework/Versions/147.0.7727.138/Resources/es.lproj/locale.pak` — **711 KB**, distinct from `es_419.lproj` (717 KB).

So the Peninsular assets genuinely ship on disk. This was a **delivery failure, not a missing-asset failure.** A diagnostic ladder existed and was **deliberately not run**: verify no Chrome helper processes survive ⌘Q → `killall -u $USER cfprefsd` → try `-array es` (matching `es.lproj` exactly) → try the System Settings → General → Language & Region → Applications GUI path, which writes the same key and would discriminate "we wrote it wrong" from "Chrome ignores it."

**Decision: not worth chasing with 19 days to departure.** If revived, start from that ladder, not from a rebuild.

## What else the review changed

Three adversarial research agents debated the plan over two rounds on 2026-09-14 before the test result came in. Their findings stand independently of the cancellation:

- The lock would have produced **~30–90 forced sentences** over 19 days; eight tutor half-hours produce **~16,000 words**. A 15–50× volume deficit, conceded by all three.
- Deterministic L0–L3 grading **false-rejects 20–40% of correct** open translations — the fix was content design, not a better judge.
- Stage A QLoRA and Stage B nightly DPO were cut unanimously. **The "Explicitly out of v0" line above is therefore correct as written** and the earlier decision to override it was itself reversed.

## What replaced it

A practice program, not software: recurring Spain-based tutor sessions for volume, Anki for retrieval, and three hand-authored decks covering only what no off-the-shelf deck does — Peninsular/LatAm contrast, vosotros, travel production. See the session plan in `~/.claude/plans/logical-dazzling-boole.md`.

The `research/` corpus (committed at `1a188a5`) is historical. It is sound work and it answered the question it was asked; the question just stopped mattering.
