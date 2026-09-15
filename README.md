# language-app (working title)

Spanish practice tool built around one thesis:

> Language decays unless you are purposefully put in situations that **force** you to produce it.

So the app is not a flashcard deck and not a chatbot. It is a **forcing-function generator**:
scenarios you cannot exit without producing Spanish, under time pressure, with honest feedback.

## Constraints (non-negotiable)

- **Fully offline.** Runs on a plane, runs in Spain with no data.
- **Local SLM** as the interlocutor. MacBook Air M3 / 16GB unified / 10 GPU cores / fanless.
- **Peninsular Spanish.** vosotros, distinción, Spain vocabulary and pragmatics.
- **Spoken production first.** Typing is the fallback, not the mode.

## Open design bet

Adapt the tutor to the user over time. "RL" is the ambition; see `research/04-rl-adaptation.md`
for the honest decomposition of which parts actually need RL and which don't.

## Layout

    research/    findings, one file per track (see research/00-INDEX.md)
    docs/        design decisions that survive the research phase
