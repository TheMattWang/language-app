# Adaptation & RL for the Local-SLM Spanish Tutor

**Scope**: what "the model adapts to the user" should mean, what's feasible on an M3 Air, and what to build now vs. later.

---

## TL;DR — read this before anything else

**No RL. No weight adaptation. Not in v0, probably not in v1 either.** Trip is under three weeks out, the whole thing runs offline on one Mac for one user. Every form of "adaptation" that involves training anything (LoRA, DPO, GRPO, bandit exploration with real regret) needs either a population to amortize exploration/variance over, or a data volume this app cannot produce in three weeks, or both. The one thing that *is* justified now, and is the single highest-leverage thing to get right before the trip, is **instrumentation**: logging every decision so that if adaptation is ever worth building, you don't have to re-collect a corpus from a live user first. Get the logging schema wrong now and it's the one mistake you can't undo later — get it right and you've paid a near-zero cost today for full optionality later.

Concretely: v0 adaptation = a persistent in-context learner profile + a deterministic forgetting-curve scheduler (FSRS-style). Zero training. This is not a watered-down version of "the real thing" — per the research below, it's what the evidence says actually works at N=1, full stop, not just what's expedient given the timeline.

---

## 1. Decomposing "RL to adapt to the user"

The phrase conflates four different problems. Treating them as one is the root cause of over-scoping this.

### (a) Curriculum / item selection — *which* exercise next
This is a policy problem over a small discrete action space (which vocab item, which grammar point, which scenario), not a weights problem. It's naturally framed as a contextual bandit or, more simply, a scheduling heuristic. **Does it need RL?** In principle yes — it's textbook contextual-bandit territory (LinUCB, Thompson sampling have real production use in ed-tech at scale). **In practice, no, not at N=1.** Bandits earn their keep by exploring efficiently across many users' shared latent structure so that one user's "wasted" exploratory pull is compensated by another user's informative one. With one real user, every exploratory action is a exercise wasted on the only person you're trying to help, and there's no population to amortize the cost against. A deterministic forgetting-curve scheduler (FSRS) plus a weighted round-robin over below-target-accuracy skills gets ~90% of the value with zero exploration cost. **Verdict: no RL, use FSRS + heuristics.**

### (b) Difficulty calibration — speech rate, lexical complexity, error tolerance
This is closer to a control problem than an RL problem: given an ability estimate and a target success-rate band (see §3, the "85% rule" caveats), adjust a small number of continuous/ordinal knobs. A single online-updated scalar (Elo-style ability estimate) with a proportional controller ("if success rate over last N items > upper band, increase difficulty; if below lower band, decrease") is fully sufficient and trivially identifiable from one user's binary response stream — unlike full IRT, which needs a population to separate item difficulty from learner ability. **Verdict: no RL, use a 1-parameter online ability estimate + a simple controller, with difficulty *priors* seeded from corpus/CEFR data, not fit from scratch.**

### (c) Model weight adaptation — actually fine-tuning the SLM (LoRA/DPO/GRPO)
This is the one people mean when they say "RL to adapt the model," and it's the hardest and least justified of the four. Per §4 and §5 below: LoRA/QLoRA is *mechanically* feasible on an M3 Air for models up to ~3B comfortably (7B-4bit is a stretch, not comfortable, on a fanless 16GB machine already running the inference server), and wall-clock is not the bottleneck — a few hundred examples trains in under an hour. But data volume is the bottleneck, and more fundamentally: nothing in the literature shows fine-tuning beating a well-maintained in-context profile at N=1, and there's real risk of tiny-dataset overfitting (memorizing conversational idiosyncrasies, not learning generalizable tutoring competence) and of quietly degrading base capabilities with no clean way to detect it before it's live in front of the one user who matters. **Verdict: not now. Revisit only per the roadmap trigger in §9 — and even then, prompting/profile-based adaptation is the thing to disprove first, not skip past.**

### (d) Memory/personalization without training — retrieval, persistent learner-state, structured user profile in context
This is the highest-leverage, lowest-risk lever available, and it is underrated relative to (c) precisely because it isn't "RL" and therefore doesn't feel like it's solving the stated problem. It's fully inspectable, instantly correctable (edit a paragraph, not retrain a model), versionable, and reversible. **Verdict: this is where v0's "adaptation" budget should go — a structured, growing learner-state document (mastered/struggling items with evidence, error taxonomy, register preference, pacing preference) fed into the tutor's context every turn, maintained by simple deterministic update rules, not learned.**

**Overall verdict on the decomposition**: (a) and (b) are solved by classical scheduling/control, not RL. (c) is real RL/fine-tuning territory but is unjustified at this data scale and timeline. (d) is not RL at all and is where the actual user-visible adaptation should live in v0/v1. The instinct "this needs RL" is真 wrong for three of the four sub-problems and premature for the fourth.

---

## 2. Knowledge tracing / learner modeling at N=1

- **BKT** (Bayesian Knowledge Tracing) is a per-skill HMM with four params — P(L₀) initial mastery, P(T) transition/learn rate, P(G) guess, P(S) slip — updated via Bayes' rule per observation. It needs a skill→item map (Q-matrix) and, critically, needs population-fit priors on (T,G,S) to avoid degenerate fits (e.g. guess→1 explaining everything). Not viable to fit from scratch per skill at N=1.
- **DKT/SAKT/AKT** (deep sequence models over interaction streams) need thousands of students and tens of thousands of interactions to learn item embeddings; benchmark datasets run 4K–780K students ([arxiv.org/pdf/2401.16832](https://arxiv.org/pdf/2401.16832)). **Flatly not viable at N=1** — no population to amortize the embedding table over.
- **Duolingo's Half-Life Regression** (Settles & Meeder, ACL 2016, [PDF](https://research.duolingo.com/papers/settles.acl16.pdf), [code](https://github.com/duolingo/halflife-regression)): models memory half-life as `h_θ(x) = 2^(θ·x)` and recall probability as `p = 2^(−Δ/h)`, where Δ = time since last review and x = feature vector (correct/incorrect counts on the lexeme, lexeme-tag one-hots). Fit via regularized regression on 13M learning traces; beat fixed-interval (Leitner/Pimsleur) baselines by 45%+ error reduction, +12% engagement in A/B test. The θ weights need a population to fit — but the *functional form* (exponential forgetting curve on simple counts) is exactly the right shape for a single user once seeded with sane defaults.
- **FSRS** (Free Spaced Repetition Scheduler, [open-spaced-repetition/free-spaced-repetition-scheduler](https://github.com/open-spaced-repetition/free-spaced-repetition-scheduler)) is the practical off-the-shelf answer to N=1 cold start. It models Difficulty D, Stability S ("days to decay to 90% retrievability"), and Retrievability `R(t,S) = (1 + t/(9S))^(−1)`, updated per review outcome (Again/Hard/Good/Easy). It ships with a **population-fit default parameter set** so it works reasonably from review #1 for any user, then optionally refits personalized weights via gradient descent once enough history accumulates (community guidance: trust personalized fits above ~500–1,000 reviews, fall back toward defaults below that). This is production-hardened — it's been Anki's default scheduler since v23.10 (2023) — not a research toy.
- **IRT (1PL/2PL/3PL) and Elo-based difficulty**: jointly estimate item difficulty and learner ability from a response matrix. Item-difficulty parameters are only identifiable with many learners rated on the same items — a single user's stream can't separate "this word is hard" from "I am bad at this word." Duolingo's production model ("Birdbrain") is IRT-inspired and updates both sides jointly, but only because it has ~1.25B exercises/day of population data. For a single-user app: fix item difficulty from external priors (CEFR frequency lists, cognate status, morphological complexity) and let only the ability side — a single scalar — update online via a 1-parameter Elo-style rule. That direction *is* N=1-tractable.

**Practical recommendation**: FSRS (or an HLR-style exponential half-life model) for *when* to review, seeded with public defaults, refit personalized stability/difficulty only after ~500+ reviews accumulate. Static, corpus-seeded difficulty priors + a 1-parameter online ability estimate for *what difficulty* to serve. No BKT, no DKT, no learned IRT. This mirrors what Duolingo itself ran before it had the population scale to justify anything fancier.

---

## 3. Bandits for exercise selection, and the "85% rule"

Contextual bandits (LinUCB, Thompson sampling) are real, used in production ed-tech — e.g. Disjoint/Hybrid LinUCB on ASSISTments, contextual Thompson sampling for skill-gain optimization ([INFORMS 2025](https://doi.org/10.1287/ited.2025.0174)) — but always in platforms with thousands of students, where exploration cost is pooled across the population.

**The 85% rule** (Wilson, Cohen et al., *Nature Communications* 2019, [paper](https://www.nature.com/articles/s41467-019-12552-4)) is narrower than the popular framing suggests: it's a derivation that for **stochastic-gradient-descent training on binary classification** (idealized perceptron-style tasks), the error rate maximizing the *rate of learning* converges to ≈15.87% error / ≈85% accuracy. It formalizes ZPD/desirable-difficulty intuition mathematically, but the specific 85.5% number is an artifact of that toy model's loss/noise assumptions — it has not been shown to transfer literally to human episodic/declarative memory tasks like vocab recall or grammar production, which have entirely different learning dynamics (spacing, retrieval practice, interference) from gradient descent on a loss surface. **Use it as directional inspiration for a target band (roughly 80–90%, consistent with Bjork's desirable-difficulty literature and observed practitioner behavior), not as a calibrated point target.**

**Delayed/sparse reward**: true reward (retention at next scheduled review) arrives hours to weeks later. The literature response is batched/frozen-history bandits — freeze the policy within a batch, update at batch boundaries using resolved rewards ([batched contextual bandits](https://www.emergentmind.com/topics/batched-contextual-bandit-learning)); delay costs are additive (not catastrophic) in stochastic, non-adversarial settings, which this is. Credit assignment across multiple same-session exposures to a skill is genuinely ambiguous — the practical industry fix is to *not* solve it exactly: use immediate in-session correctness/latency as a surrogate reward for online selection, and periodically recalibrate against true delayed retention offline, rather than doing exact temporal credit assignment. A full MDP/long-horizon RL formulation is overkill here.

**Verdict**: at N=1, a contextual bandit is the wrong tool — no population to amortize exploration regret against, and every exploratory pull is a wasted exercise for the one learner. A deterministic heuristic (FSRS-driven spacing + weighted round-robin over below-target skills + occasional novelty injection) captures ~90% of the value with zero cold-start regret and full interpretability. Reserve bandit machinery for a future multi-user version, if one ever exists.

---

## 4. On-device fine-tuning feasibility on the M3 Air (16GB)

- **Tooling**: `mlx_lm.lora` is the training entrypoint (QLoRA activates automatically against a pre-quantized checkpoint); `mlx_lm.fuse` merges adapters back, optionally dequantizing. ([mlx-lm LORA.md](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/LORA.md))
- **Memory** (extrapolated from M2/M3 Max benchmarks, no M3-Air-specific published numbers exist): 7B full fine-tune ≈28GB (out of the question), 7B LoRA on fp16 base ≈14GB (leaves almost nothing for OS + inference server — not comfortable, borderline OOM-risk on a fanless 16GB machine), 7B QLoRA ≈7GB peak (survivable but tight alongside a running app). 3B QLoRA is comfortable. ≤1.5B is trivial, >10GB headroom remains. Treat **7B-4bit as the practical ceiling, not a comfortable one** — tighter than commonly-quoted "16GB fine-tunes 8B" claims once macOS + Metal driver overhead + a resident inference server + no thermal headroom (fanless) are accounted for. M3 Air's memory bandwidth (~100GB/s) is roughly 3–4x lower than M2/M3 Max (~400GB/s), so expect proportionally slower wall-clock than published Max benchmarks.
- **Overnight feasibility**: a 1.5–3B QLoRA run over 200–1,000 examples (~50k–300k tokens) for a few epochs is a few-thousand-step job — plausibly **20–60 minutes**, not 8 hours. **Wall-clock is not the bottleneck. Data volume is.** You'd be overnight-fine-tuning on noise, not compute-limited.
- **Continual/online LoRA**: no established single-device recipe exists for low-signal, low-forgetting-tolerance updates. Ingredients exist in isolation — replay buffers (~100 samples/task as a practical baseline), orthogonal-subspace methods (OLoRA), dual fast/slow EMA-merged adapters — but assembling them into a working per-user, session-over-session update loop would be research-grade engineering, not integrating an existing recipe. One relevant finding: "LoRA Learns Less and Forgets Less" ([arXiv:2405.09673](https://arxiv.org/abs/2405.09673)) — LoRA forgets less than full fine-tuning by construction, but by the same low-rank constraint, it also *learns* less, so a low-rank adapter trained on N=1 data may be too weak to encode anything useful before forgetting is even the binding concern.
- **Tiny-dataset overfitting**: memorization dominates below roughly 50 examples per concept in narrow single-concept LoRA studies; generalization emerges above that. A tutoring-persona adapter needs breadth across hundreds of distinct linguistic phenomena, so a few-hundred-example budget is thin *per phenomenon* even though it looks adequate in aggregate. Expect memorization of conversational idiosyncrasies over genuine linguistic-competence transfer.
- **The core question — does weight adaptation beat a good in-context profile, at N=1?** **No, and not close.** A few hundred noisy interaction turns is plenty to write ~500 words of structured, high-fidelity learner state (error taxonomy, mastered/struggling items with evidence, register preference) — but is not enough to move weights in a direction that generalizes rather than overfits. An in-context profile is inspectable, instantly correctable, versionable, and reversible; a bad LoRA merge silently degrades the tutor with no easy way to detect it before it's in front of the one user who matters. Running a training loop on the same fanless machine that must also serve low-latency conversational inference adds thermal/scheduling contention for zero demonstrated quality win. The ICL-vs-fine-tuning-for-personalization literature is genuinely mixed at small N, and nothing shows fine-tuning beating a well-maintained profile at N=1. **Treat weight adaptation as a waste of effort for v0/v1.**

---

## 5. Preference/RL methods: what would the pairs even be, and does GRPO fit

- **DPO/ORPO/SimPO** need *paired* preference data (chosen vs. rejected response to the same prompt) — expensive to generate from a single live user, since it requires presenting two competing tutor responses and getting a comparative judgment. **KTO** needs only unpaired binary signal (thumbs up/down, or here: "learner recalled it later" vs. didn't), which maps far more naturally onto passively-generated feedback. Tooling is no longer the blocker: `mlx-lm-lora` and `mlx-tune` support DPO/ORPO/GRPO/KTO/PPO natively on Apple Silicon ([mlx-lm-lora on PyPI](https://pypi.org/project/mlx-lm-lora/), [ARahim3/mlx-tune](https://github.com/ARahim3/mlx-tune)) — this is runnable, not vaporware, *if* the data existed.
- **GRPO/RLVR fit**: GRPO's advantage estimate is computed by normalizing reward *within a group of rollouts for the same prompt* (no critic network), which is why it pairs well with sparse, rule-based verifiable rewards. This app does have a plausible verifiable reward — did the learner later recall/produce the target correctly — which is structurally the right *shape* of signal for GRPO. But published GRPO work uses groups of 32–128 rollouts per prompt (G=2 is the bare theoretical minimum, and even that is high-variance). A single user doing one session a day produces ~10–50 exercise turns, not 32–128 rollouts *of the same tutoring decision* — sampling that many candidate tutor responses to the same state and discarding all but one is both slow (each rollout is a real conversation turn with a real human) and reward is necessarily delayed (measured at the next spaced review), which weakens credit assignment further in a single-trajectory-per-day regime. **Verdict: right shape, wrong data volume. This is a "wait for infrastructure/data" idea, not a v1 idea.**
- **Reward hacking, concretely**:
  - A tutor rewarded on "learner later succeeded" degenerates toward presenting only what the learner half-knows already, or leaking the answer into the question — direct analogue of reward-model overoptimization documented broadly in RLHF (see the "feature-level exploitation" bucket in [Lilian Weng's reward hacking survey](https://lilianweng.github.io/posts/2024-11-28-reward-hacking/)).
  - A model rewarded on engagement/self-reported satisfaction becomes sycophantic — Anthropic's ["Towards Understanding Sycophancy in Language Models"](https://arxiv.org/abs/2310.13548) found sycophancy arises *directly from* human-preference training data, since "matches what the user wants to hear" is predictive of approval even when wrong. A tutor optimized on session length or self-reported enjoyment will over-praise and soften correction.
  - Tutoring-specific: reward tied to "user said thanks" → praise inflation; reward tied to latency/turns-to-completion → skipping explanation steps; reward tied to "did not disengage" → avoiding genuinely difficult material, which directly undermines the desirable-difficulty premise the whole scheduling design depends on.

---

## 6. Reward signal design

What's actually measurable in this app, assessed for gameability and lag:

| Signal | Leading/lagging | Noise | Gameability |
|---|---|---|---|
| Recall success at next scheduled review (FSRS grade) | Leading, but delayed (hours–weeks) | Low-moderate | **High** — trivially maximized by making everything easy |
| In-session error rate / correctness | Leading, immediate | Moderate | High if used alone (same failure mode as above) |
| Response latency | Immediate | High (confounded by typing speed, distraction) | Moderate — rewards rushing, not correction |
| Self-report (confidence, satisfaction) | Immediate | High, biased | **Very high** — direct sycophancy channel |
| Pronunciation/production score | Leading, needs ASR pipeline | Moderate-high | Moderate — gameable by lowering the acceptance bar |
| Session length | Lagging | Moderate | High — padded with easy filler |
| Voluntary return (opened app next day/week) | Best true lagging indicator of value | Very sparse (1 bit/day) | Low, but nearly unusable as a training signal at N=1 due to sparsity and long horizon |

**Proposed composite, and what to explicitly exclude**: use retention-at-scheduled-review (the FSRS-style grade) as the *only* signal that feeds any optimized objective (scheduler tuning, or a future GRPO-style tutor-policy reward), and **gate it against a difficulty-band constraint** — reject/penalize any policy change that pushes the rolling success rate outside the ~80–90% target band, specifically to block the "make everything easy" hack described above. Track self-report satisfaction, session length, and voluntary return as **dashboard-only guardrail metrics**, monitored for divergence from retention (a policy that raises satisfaction while retention flatlines or drops is a hacking alarm), never as inputs to an optimized reward. This is the standard defense against Goodhart's law here: the moment a lagging, easily-gamed metric becomes a training signal, it stops measuring what you want.

---

## 7. Prior art

**Validated, real precedent**:
- RL for *pedagogical policy / curriculum sequencing* in intelligent tutoring systems is decades-old, peer-reviewed research (POMDP-formulated tutoring, deep-RL pedagogical policy induction) — e.g. [NSF: Leveraging Deep RL for Pedagogical Policy Induction](https://par.nsf.gov/biblio/10136494), [MC-CPO 2026](https://arxiv.org/html/2604.04251), [POMDP vs MDP pedagogical strategies](https://link.springer.com/chapter/10.1007/978-3-319-93846-2_61). This matches the item-selection/bandit framing in §1(a) and §3 — **not** RL on the LLM's weights.
- RL for spaced-repetition scheduling itself: **DRL-SRS** (2024, [MDPI](https://www.mdpi.com/2076-3417/14/13/5591)) frames interval scheduling as deep RL on top of a half-life-style memory model — directly relevant prior art for the reward design in §6.
- Duolingo's actual production system, by their own account, does **not** use ML/RL for pedagogical decisions ("what to teach"): curriculum is linguist-designed and locked; ML only touches *when/how often* a word resurfaces (Elo/spaced-repetition-style scheduling), and GPT-4-class calls are used for on-demand explanation generation as a stateless API, not adapted per-user ([OpenAI/Duolingo case study](https://openai.com/index/duolingo/); "gets us from zero to ninety-five percent... hand-tuning the last five percent"). This is a strong, concrete data point from the company with the most production experience in exactly this space, and it agrees with §1's decomposition: bandit/scheduling problems get ML, the generative model does not get adapted per-user.
- Contextual bandits in ed-tech are real and used at scale (ASSISTments LinUCB variants, [survey](https://www.researchgate.net/publication/352332265_Multi-armed_Bandit_Algorithms_for_Adaptive_Learning_A_Survey); [2025 Thompson-sampling skill-gain paper](https://doi.org/10.1287/ited.2025.0174)) — always at thousand-plus-student scale.

**Theoretically plausible, unvalidated**:
- RL (DPO/GRPO/etc.) to personalize a small on-device LLM's *weights* to one individual user's tutoring interactions — no papers or products found doing this specifically. Closest adjacent work is on-device federated/collaborative fine-tuning across *many* users ([arxiv.org/pdf/2404.09753](https://arxiv.org/pdf/2404.09753)) and single-device continual SFT via self-distillation ([SLM-Online-SDFT](https://lin826.github.io/SLM-Online-SDFT/)) — both plain fine-tuning objectives, not preference RL, both targeting general personalization, not pedagogy. **This niche is genuinely unexplored** — that absence is itself the finding, not a gap in the literature search.

**Overall**: the gap between "GRPO/DPO could in principle train a tutor policy on a verifiable recall signal" and "anyone has shown this beats simpler methods" is currently unfilled by any published result. Everything validated at production scale routes adaptation through scheduling/curriculum-sequencing ML, never through weight updates to the generative model.

---

## 8. Instrumentation spec — what to log from day 1

This is the actual v0 deliverable for this track. The cost of logging this now is near-zero (it's mostly fields already available at decision time); the cost of *not* logging it is that any future adaptation work — bandit, offline RL, DPO pair mining, or just a retrospective "did the scheduler actually work" analysis — starts by re-collecting a corpus from a live user, which is slow and can't recover data already lost. Every deterministic v0 decision (FSRS scheduling, difficulty controller, profile update) should still emit a full decision record, even though no learning happens against it yet — this is what makes offline evaluation of *future* policies possible without having run them live.

The key idea driving several fields below: **off-policy evaluation (OPE) and offline RL require knowing the probability the logging policy assigned to the action it took, and what the alternatives were — not just which action was taken.** A log of "presented item X, learner got it right" cannot be used to ask "would a different scheduler have done better," because there's no way to reweight the sample toward what a counterfactual policy would have chosen (importance sampling / doubly robust estimators need `π(a|s)` from the logging policy). This is exactly the class of information that is impossible to reconstruct retroactively — get it now.

### 8.1 Decision event (emitted every time an item/exercise is selected)

```
decision_id            : uuid
timestamp              : ISO8601
session_id             : uuid
user_id                : constant (single user, but keep the field — cheap future-proofing)

# What was chosen
item_id                : stable id, persists across schema/content versions
item_type              : vocab | grammar_point | scenario | free_conversation
skill_tags             : [tag, ...]           # for skill-level rollups later

# Scheduler/policy state AT DECISION TIME (not after)
policy_version         : string/hash          # which scheduler logic made this call
scheduler_state        : {
  fsrs_stability        : float | null
  fsrs_difficulty       : float | null
  fsrs_retrievability   : float | null
  days_since_last_review: float | null
  ability_estimate      : float               # the 1-param online Elo-style estimate
  rolling_success_rate  : float               # last-N window, for difficulty-band check
}

# WHY this item, over the alternatives — the counterfactual/propensity record
selection_reason       : due_for_review | weak_skill_weighted | novelty_injection
                          | explicit_user_request | cold_start_default
candidate_set          : [                    # every item that COULD have been shown
  { item_id, score, selection_probability }, ...
]
propensity_score       : float                # P(this item | scheduler_state) under
                                               # the CURRENT policy — required for IPS/DR OPE
explore_flag           : bool
explore_mechanism      : none | epsilon_greedy | thompson_sample | forced_novelty
explore_param          : float | null         # e.g. epsilon value, or the sampled draw

# Difficulty knobs set for this turn
difficulty_settings    : { speech_rate, lexical_level, error_tolerance }
```

### 8.2 Interaction/outcome event (emitted after the learner responds)

```
decision_id            : uuid            # foreign key to §8.1
turn_id                : uuid
timestamp              : ISO8601
latency_ms             : int
learner_response_raw   : string
grade                  : again | hard | good | easy   # FSRS-style, or binary correct/incorrect
error_type             : taxonomy tag | null           # e.g. subjunctive_mood, gender_agreement
hints_used             : int
self_reported_confidence: int | null      # if collected — log it, don't optimize on it (§6)
```

### 8.3 Generation event (what the tutor model actually produced)

```
decision_id            : uuid
model_id               : base model + quantization + adapter version (or "none")
prompt_template_version: string/hash
learner_profile_snapshot_hash: string     # hash of the in-context profile used THIS turn
full_prompt             : string          # for future DPO/KTO pair mining
full_response           : string
```

### 8.4 Delayed-outcome linkage (retention ground truth)

```
review_event_id        : uuid
original_decision_id   : uuid            # links back to when the item was first taught/reviewed
item_id                : same stable id as §8.1
delta_days              : float           # time since previous exposure
grade                   : again | hard | good | easy
```

Requires `item_id`/skill IDs to be **stable across content-schema versions** — if the vocab list or grammar taxonomy gets restructured later, keep a mapping table rather than renumbering, or every retention curve breaks.

### 8.5 Session/engagement events (guardrail metrics only, per §6 — never feed into an optimized reward)

```
session_id, start, end, item_count, voluntary_return_next_day (bool),
self_report_satisfaction (if asked)
```

### What this buys later, concretely
- **Offline policy evaluation** of a hypothetical bandit/RL scheduler against the historical log, using importance sampling weighted by `propensity_score`, without deploying it live first.
- **DPO/KTO pair mining** later, since `full_prompt`/`full_response` + outcome are already paired — no need to instrument a new logging pipeline retroactively if §5's calculus ever changes (e.g., if a future multi-user version makes GRPO's rollout-volume problem go away).
- A clean audit trail to detect the reward-hacking failure modes in §5–6 (`rolling_success_rate` drifting up while `voluntary_return` drifts down is the concrete tripwire).

---

## 9. Staged roadmap

**v0 (now, pre-trip, <3 weeks)** — No RL, no weight training, no bandits.
- Deterministic FSRS-based (or HLR-shaped) review scheduler, seeded with public defaults.
- Static difficulty priors (CEFR/frequency-seeded) + single online ability scalar with a proportional controller targeting ~80–90% success.
- Persistent in-context learner-state profile, updated by deterministic rules after each session (not learned).
- Full instrumentation per §8, wired in from the first real interaction, even though nothing consumes `propensity_score` yet.

**v1 (after real usage data exists — weeks to months, once FSRS has enough reviews to refit personalized stability/difficulty, roughly 500+ reviews)**
- Refit personalized FSRS parameters from logged data (still no RL — this is closed-form/gradient-descent regression on accumulated reviews, same family as HLR).
- Optionally introduce a *very* conservative exploration mechanism (e.g. epsilon-greedy novelty injection, logged with full propensity per §8) if — and only if — the deterministic scheduler shows a measurable plateau (rolling success rate stuck outside band despite controller adjustment, or stagnant retention curves) that a policy change might fix. This is still not "RL" in the training sense — it's structured logging to make a future offline evaluation meaningful.
- Do **not** touch model weights in this stage.

**v2 (only with concrete evidence, not a calendar date)** — the trigger, stated explicitly:
- Enough logged sessions exist (from this user over an extended period, or from additional users if the app grows) that an **offline evaluation using the §8 logs** shows a plausible alternative scheduling/difficulty policy would have outperformed the deterministic one — evaluated via importance sampling on historical `propensity_score`, not by guessing.
- *Separately*, only consider LoRA/DPO/KTO weight adaptation if a controlled test shows the in-context profile has hit a ceiling that more context/better retrieval can't fix, and even then, budget it as an experiment to disprove (does the adapter measurably beat the profile-only baseline on held-out sessions?), not a default upgrade path.
- GRPO-style tutor-policy RL on a verifiable recall reward stays off the table until rollout volume is within an order of magnitude of what published GRPO work actually uses (tens of rollouts per decision) — which realistically means a multi-user setting, not a personal app.

---

## 10. Where this could fail or be a waste of effort

- **The instrumentation itself could be premature optimization** if the app never gets enough sustained usage to accumulate the 500+ reviews FSRS personalization needs, let alone the volume any RL method needs — in which case all the logging infrastructure serves an analysis that never happens. The mitigating factor: the marginal cost of the schema in §8 is small relative to building the app at all, and having it costs nothing if unused, whereas not having it is unrecoverable.
- **The "verifiable reward" (recall success) is less clean than it looks.** Recall at next review is confounded by whether the learner reviewed elsewhere (outside the app), forgot for reasons unrelated to the tutor's teaching quality (unrelated life interference), or guessed correctly. At N=1 there's no way to average this noise out across users — every confound lands directly on the one signal you have.
- **The difficulty-band target (80–90%) is borrowed from a different domain than it's being applied to** (SGD-on-classifiers, not human declarative memory) — treat it as a heuristic prior to be validated against this user's actual retention curves, not a number to defend.
- **A structured in-context profile can rot** just as models can be mis-tuned — if the deterministic update rules for the profile are wrong (e.g., over-weighting one bad session, or never pruning stale "struggling with X" entries after mastery), the failure mode looks like the model "not adapting" when the real bug is in the profile-maintenance logic, not in the absence of RL. Debugging this is easier than debugging a bad LoRA merge, but it isn't free, and it's worth treating profile-update logic with the same scrutiny as a training loop.
- **Building the bandit/RL machinery anyway, out of a sense that "adaptation" isn't real without it**, is the single biggest risk to the timeline. Everything in §§1–7 points the same direction: at N=1, in three weeks, offline, the marginal engineering cost of RL infrastructure buys approximately zero measurable improvement over a good scheduler and a good profile, and it introduces real risk (silent model degradation, wasted exploration on the one user, thermal/scheduling contention with the inference server) for that zero.
