# 12 — Distribution to Non-Technical Users

> Scope: how a free, fully-local `drill` (today: Python-stdlib CLI + tkinter GUI; planned: local
> LLM conversation partner + system-wide word-swap immersion, Ollama and MLX backends) reaches a
> stranger who clicked a link on X. It covers six things: the hardware they own, install friction
> per packaging route, MLX vs Ollama, model size and hosting, competitor onboarding, and the minimum
> launch package. Pedagogy and the content landscape are in `05-landscape-content.md`. Model
> quality is in `02a-quality-floor.md` / `02b-model-survey.md`. Research date: 2026-10-12.
>
> **Sourcing convention:** [PRIMARY] means the original data owner, vendor docs, or a first-hand
> measurement/API pull. [SECONDARY] means blogs, forums, aggregators or press reporting someone
> else's data. **UNVERIFIED** means a single weak source, a search snippet, or my background knowledge
> with no source fetched this session; treat it as a hypothesis. Lines marked *(estimate)* or
> *(inference)* are the researchers' own arithmetic or reasoning, not something a source measured.

---

## TL;DR

- **The real audience is on Apple Silicon.** About 90% of Steam Macs are Apple Silicon, and macOS 26
  is the last release for Intel Macs. Roughly **29% of Steam Macs still have 8 GB** (the M1/M2/M3
  installed base); every new Mac since late 2024 ships with 16 GB. A 3B Q4 model runs at **~31–49
  tok/s on an 8 GB M1 Air** but swapped in one of two runs. Windows laptops for "normal people" are
  mostly CPU/iGPU-only. There, a 3.8B Q4 model measures **~8–20 tok/s**, which is borderline, and
  Q8 roughly halves that.
- **Install friction is dominated by two things.** First, Python is not usable on a fresh machine:
  macOS has a Command Line Tools shim with an old Tk, and Windows has a Store stub. Second, Gatekeeper on
  macOS 15+ forces unsigned apps through a buried Settings → "Open Anyway" flow with a ~1-hour
  window. **$99/yr Apple notarization is the only clean Mac path.** On Windows, the free Microsoft Store
  MSIX route or ~$9.99/mo Azure Artifact Signing (US/Canada individuals) avoids the hard SmartScreen block.
- **Default to Ollama, not MLX.** Ollama is MIT, cross-platform and HTTP-reachable from stdlib `urllib`. Since **v0.40.0
  (2026-09-25)** it runs supported architectures on MLX automatically on Apple Silicon [PRIMARY,
  surprising, verify on hardware]. At 3–4B dense, MLX and llama.cpp measure roughly tied. Keep `mlx-lm` for
  Matt's own adapter training and as a power-user backend.
- **Model:** a 3–4B instruct model at Q4_K_M is a **~2.0–2.6 GB** download (e.g. `qwen3:4b-instruct-2507`
  2.5 GB). That is **~2.3 min at the US median of 148 Mbps** *(estimate)*. Host a fused fine-tune as GGUF on Hugging
  Face; Ollama pulls `hf.co/<user>/<repo>:Q4_K_M` directly. Ship fused weights, not a LoRA adapter.
  Ollama's adapter support for Qwen3/Gemma 3+ is undocumented.
- **No open-source local-LLM language tutor has traction.** The leader, freelingo, has 167 stars and
  uses Docker, a manual model pull and an account. The open slot is "Toucan that works in every app, offline, free."
- **Launch package:** a notarized Apple-Silicon `.dmg` that opens straight into a working (no-LLM) drill
  session. It detects Ollama, links to its installer, auto-pulls the RAM-appropriate model with a progress bar,
  and drops into a conversation. Add a README with a <30 s demo video, and a requirements line stated up front.

---

## 1. Normal-person hardware in 2026 and what a 3–4B model does on it

### 1a. Apple Silicon is ~90% of active Macs; Intel is a frozen tail

| Signal | Value | Source |
|---|---|---|
| Steam Macs reporting GenuineIntel CPU (Sept 2026) | **10.20%** (−0.88% MoM) | [PRIMARY] [Steam HW Survey (Mac)](https://store.steampowered.com/hwsurvey/?platform=mac) |
| Steam Macs reporting VirtualApple (Apple Silicon running x86 Steam under Rosetta) | 2.30% | same |
| Apple M4 alone, share of Mac "video card" entries | 17.89% | same |
| macOS 26.x / 27.0 on Steam Macs | 26.6.2 35.97%, 27.0.0 9.80%, 26.5.x ~14% | same |
| macOS share of total Steam sample | 1.92% (Windows 95.03%, Linux 3.05%) | [PRIMARY] [Steam HW Survey](https://store.steampowered.com/hwsurvey/) |
| Apple M-series share of 2025 laptop CPU **shipments** | ~18–19% | [SECONDARY / UNVERIFIED, original Mercury report not seen] [MacMagazine](https://macmagazine.com.br/post/2026/01/22/apple-ja-ameaca-posicao-da-amd-no-mercado-de-chips-para-laptops-mostra-pesquisa/) |

Apple said at WWDC 2025 that **macOS Tahoe 26 is the last release for Intel Macs**. Only four Intel
models are supported, and macOS 27 requires Apple Silicon ([SECONDARY] [Six Colors](https://sixcolors.com/post/2025/06/macos-tahoe-is-the-last-release-to-support-intel/);
[PetaPixel](https://petapixel.com/2025/06/10/macos-26-tahoe-is-the-end-of-the-road-for-intel-macs/)).
*(Inference)* Steam users skew toward newer Macs, so the Intel share among all active Macs is
probably somewhat above 10%. It is still a shrinking tail with no Metal LLM path worth targeting. No
installed-base telemetry outside Steam (Jamf, Mozilla) was found.

### 1b. RAM: one Mac in three or four is still on 8 GB

| Population (Sept 2026) | 8 GB | 16 GB | 24 GB | 32 GB |
|---|---|---|---|---|
| Steam, Mac only | **28.66%** | 43.55% | 11.31% | 5.37% |
| Steam, all platforms | 6.47% | 37.82% | — | 42.22% |

Source: [PRIMARY] [Steam HW Survey](https://store.steampowered.com/hwsurvey/?platform=mac).
Apple raised base RAM on the M2/M3 MacBook Air to 16 GB at the end of October 2024, and **no new Mac sold by Apple since has
less than 16 GB** ([SECONDARY] [Six Colors](https://sixcolors.com/post/2024/10/16gb-for-everyone-macbook-air-joins-the-ram-upgrade-party/);
[MacTech](https://www.mactech.com/2024/10/30/macbook-air-lineup-now-comes-with-16gb-of-ram)). The 8 GB
cohort is therefore the M1/M2/M3 installed base, and it shrinks only as people replace machines.

**Bias flag:** the all-platform 6.47% 8 GB figure is a gamer population. Budget "normal person"
Windows laptops are not represented, and no 2025–26 OEM base-RAM data (IDC/Canalys) was found. The
claim that the Copilot+ PC spec requires 16 GB is **UNVERIFIED** here.

### 1c. Windows: assume no usable GPU

There is no clean 2025–26 figure for "share of Windows laptops without a discrete GPU." Proxies:

- On Steam (gamer-skewed), the listed integrated-GPU entries sum to **~8.5%** *(researcher's arithmetic
  over listed entries; no combined total is published)* ([PRIMARY] [Steam](https://store.steampowered.com/hwsurvey/)).
  This is a floor.
- JPR (via secondary report): Intel holds **~56% of the total PC GPU market including integrated graphics**
  ([SECONDARY] [tech-insider.org](https://tech-insider.org/nvidia-90-percent-gpu-market-share-shipments-2026/)).
- Copilot+-compatible laptops were **<10% of shipments in Q3 2024** ([SECONDARY] [Tom's Hardware / Canalys](https://www.tomshardware.com/laptops/copilot-pcs-represent-only-a-tiny-fraction-of-laptop-sales-compatible-laptops-accounted-for-less-than-10-percent-of-total-shipments-in-3q24)).
  Canalys's 40%-of-2025 "AI-capable PC" figure was a forecast, not an actual ([SECONDARY] [Light Reading](https://www.lightreading.com/ai-machine-learning/ai-capable-pcs-forecast-to-make-up-40-of-global-pc-shipments-in-2025-canalys)).

*(Inference)* Non-gamer Windows laptops are overwhelmingly iGPU-only. NPUs are not on the mainstream
Ollama/llama.cpp path and the installed base is small. Plan for CPU or iGPU-via-Vulkan inference. Ollama
enables Vulkan by default on Windows/Linux when the backend is installed ([PRIMARY] [docs.ollama.com/gpu](https://docs.ollama.com/gpu)).

### 1d. Measured throughput for 3–4B models

| Machine | Model / quant | Gen tok/s | Notes / source |
|---|---|---|---|
| **8 GB M1 Air**, Ollama/Metal | llama3.2:3b Q4_K_M | **48.55** | 2,333 MB resident; **swapped in one of two same-day runs** (30,168 swapout pages). [PRIMARY, single blog run] [AgenticWire 2026-08-16](https://www.agenticwire.news/article/run-local-llm-8gb-ram) |
| 8 GB M1 Air | phi3:mini 3.8B Q4_0 | **31.13** | 3,624 MB resident. Same source |
| 8 GB M1 Air | mistral:7b Q4_K_M | 9.64 | 8k-token prompt → 21 s to respond (small models 1–4 s). Same source |
| M1 8-core GPU | LLaMA-2 **7B** Q8_0 / Q4_0 | 7.91 / 14.15 | PP512 ~117 tok/s. [PRIMARY] [llama.cpp #4167](https://github.com/ggml-org/llama.cpp/discussions/4167) |
| M2 / M3 / M4 10-core | LLaMA-2 7B Q4_0 | 21.91 / 21.34 / 24.11 | same |
| Ryzen 7 7840U, **CPU only** | phi3:3.8b (~Q4) | **9.54–19.74** | Two users on the same chip, 2× spread (RAM, power mode, Ollama version). [PRIMARY, user-posted] [Framework Community](https://community.frame.work/t/llm-benchmark-amd-7840u/49351) |
| Intel Core i5-1240P, CPU only | phi3:3.8b (~Q4) | **8.17** | Ollama 0.1.38, 2024. Same thread |
| i7-12700 desktop, CPU | Phi-4 Mini 3.8B Q4_K_M | 12 | **UNVERIFIED**: no RAM or method given, and the article makes a doubtful AVX-512 claim. [PromptQuorum](https://www.promptquorum.com/local-llms/best-cpu-only-llm) |

**Caution on the headline Mac number:** 48.55 tok/s for a ~2 GB model is above a naive bandwidth
ceiling (M1 68 GB/s ÷ ~2 GB ≈ 34 tok/s, *researcher's arithmetic*), so treat it as optimistic or
measured on a short generation. Scaling the #4167 7B numbers by model size gives *(estimate)*
**~25 tok/s at 3B Q4 and ~15–17 at 3B Q8 on a base M1**, and ~35–40 / ~25 on M2/M3. Prompt processing
of roughly 200+ tok/s on M1 *(estimate)* means a 1–2k-token system prompt plus history costs several seconds
before the first token. For a chat app that matters more than decode speed.

**Memory headroom on 8 GB:** llama.cpp/Ollama treat Metal's `recommendedMaxWorkingSetSize` as the
GPU ceiling, which is commonly ~75% of RAM ([SECONDARY] [Medium](https://medium.com/@michael.hannecke/tuning-llama-cpp-on-apple-silicon-843f37a6c3dc)).
No 8 GB-specific value was found. *(Inference)* A 3B Q4 model (~2–2.5 GB resident with KV cache) fits. 3–4B Q8
(~3.5–4.5 GB) technically fits but competes with macOS and a browser and will likely swap.

| Tier | 3–4B Q4_K_M | 3–4B Q8_0 | Confidence *(researchers' assessment)* |
|---|---|---|---|
| 8 GB M1/M2 Air | yes, well above 10 tok/s (~25–49) | ~15 tok/s est., swap risk | medium / low |
| 16 GB+ Apple Silicon | yes, large margin | yes (~15–25 est.) | medium |
| Windows CPU-only, Zen 4 / DDR5 | ~10–20 | borderline (~half of Q4) | low–medium |
| Windows CPU-only, Intel U/P-series or older | borderline/no (~8) | no | low |
| Intel Mac | no data, likely <10 | no | very low |

**Tension with the quality floor.** `02a` sets the floor at instruction-tuned ≥3B, finds Q8 "effectively
free for Spanish" and says "4-bit is a real risk below ~7B." The hardware says 8 GB Macs and CPU-only
Windows need Q4. The two constraints together squeeze 8 GB users into **3–4B Q4, the riskiest
viable cell**. The fallback suggested in the competitor notes, "1.5–2B on 8 GB", is **below the floor** (`02a`: everything ≤1.7B is at
chance on EsCoLA) and should be rejected. Q4-vs-Q8 Spanish quality at 3–4B is the single most
important thing to measure before launch.

---

## 2. Install friction: four packaging routes compared

### 2a. The Python problem rules out "just run the script" for normal people

On a fresh Mac, `/usr/bin/python3` "links to a usually older and incomplete version of Python" used by
Apple's developer tools ([PRIMARY] [docs.python.org](https://docs.python.org/3/using/mac.html)). It is a
shim that prompts to install Command Line Tools ([PRIMARY-ish] [Apple Dev Forums 652014](https://developer.apple.com/forums/thread/652014)).
Historically it is paired with Tk 8.5, which shows deprecation warnings and a laggy UI ([SECONDARY, 2017–18] [python-forum.io](https://python-forum.io/thread-7113.html);
[bugs.python.org](https://bugs.python.org/msg331783)). The Tk version in the 2026 CLT is **UNVERIFIED**. On
Windows, `python.exe` is an App Execution Alias stub that opens the Microsoft Store ([SECONDARY] [elevenforum](https://www.elevenforum.com/t/what-are-python-exe-and-python3-exe-and-why-do-they-appear-to-point-to-app-installer.24886)).
*(Inference)* Today's `bin/Drill.command` double-click path hits the CLT prompt on a fresh Mac.

### 2b. Route comparison

| Route | User steps (fresh Mac) | Cost to Matt | Main risks |
|---|---|---|---|
| **(a) Install Ollama, then pip/uv + run script** | Install Python *or* uv, install Ollama, open Terminal, paste command | $0 | Terminal step plus two installs. tkinter under uv-managed Python on macOS is **UNVERIFIED**. `uvx --from git+https://… drill` runs a tool from a git URL ([PRIMARY] [uv docs](https://docs.astral.sh/uv/guides/tools/)). Fine for developers, a wall for everyone else |
| **(b) Bundled Python .app/.dmg** (PyInstaller / py2app / Briefcase) + model on first run | Download DMG, drag, open, (install Ollama), wait for pull | $99/yr Apple | Universal2 needs a universal2 Python and wheels. `lipo`-merged builds don't work ([PRIMARY] [PyInstaller](https://pyinstaller.org/en/stable/feature-notes.html)). PyInstaller ad-hoc signs by default and supports `--codesign-identity` with hardened runtime, but its docs don't cover notarization. Briefcase "manages signing and notarization" ([PRIMARY] [docs.python.org](https://docs.python.org/3/using/mac.html)), but **Briefcase + tkinter support is unconfirmed**. Bundle size is **unmeasured** |
| **(c) Bundle llama.cpp / MLX in the app** | Same as (b) with no Ollama step | $99/yr + build work | A static Metal `llama-server` is ~20 MB ([SECONDARY, single-maintainer build] [HF batiai](https://huggingface.co/batiai/llamacpp-server-macos)). You then own model download, resume, per-platform GPU builds, and updates. MLX bundle size is unknown, and MLX is Mac-only |
| **(d) Tauri / Electron shell** | Same as (b) | $99/yr + **GUI rewrite** | Hello-world size is ~3 MB (Tauri) vs ~62–96 MB (Electron) ([SECONDARY] [pkgpulse](https://www.pkgpulse.com/guides/electron-vs-tauri-2026); [levminer](https://www.levminer.com/blog/tauri-vs-electron)). It still needs a Python or llama sidecar and still needs signing. No benefit for a stdlib+tkinter app |

The python.org macOS installer is universal2 and ships "a macOS-native version of Tk" ([PRIMARY]
[docs.python.org](https://docs.python.org/3/using/mac.html)). *(Inference)* Route (b) should therefore build
from a python.org Python, or from an arm64-only Python if Intel is out of scope, which removes the universal2 trap.

### 2c. Signing and notarization costs

| Platform / route | Cost | User experience | Source |
|---|---|---|---|
| Apple Developer ID + notarization | **$99/yr**. Fee waivers cover nonprofits, education and government, **not individuals** | Clean double-click | [PRIMARY] [Apple enroll](https://developer.apple.com/programs/enroll/) |
| Free Apple account | $0 | Xcode "Personal Team" only (7-day provisioning), no Developer ID | [PRIMARY] [Apple memberships](https://developer.apple.com/support/compare-memberships/) |
| Microsoft Store MSIX | **Free** account; Microsoft re-signs | **No SmartScreen warnings** | [PRIMARY] [MS Learn, 2026-08-29](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options) |
| Azure Artifact Signing | **~$9.99/mo**. **Individuals: USA/Canada only**; validation takes a few business days | Reputation still builds over time | same |
| OV cert | $150–300/yr, key on HSM/token | Warns until reputation accrues | same |
| EV cert | $400+/yr | **Same as OV for SmartScreen now** | same |
| SignPath Foundation | Free for qualifying OSS (eligibility not fetched) | OV-level | same |
| Unsigned EXE | $0 | **Strong SmartScreen block** | same |

SmartScreen reputation is per file hash, so each new build starts at zero, although a consistent
signing identity carries publisher reputation ([PRIMARY] [MS Learn](https://learn.microsoft.com/et-ee/windows/apps/package-and-deploy/smartscreen-reputation)).
Microsoft confirms EV no longer grants instant reputation. Sources disagree on when that changed (March vs
August 2024). *(Inference)* Matt is a US individual, so the minimum to sign on both platforms is
$99 + ~$120/yr. Alternatively, $99 + the free Store route.

### 2d. What an unsigned app costs in users

On macOS Sequoia and later, **control-click → Open no longer bypasses Gatekeeper** for non-notarized
apps ([SECONDARY] [Cult of Mac](https://www.cultofmac.com/864843/macos-sequoia-removes-handy-shortcut-bypass-gatekeeper-security/);
[AppleInsider](https://appleinsider.com/inside/macos-sequoia/tips/whats-changed-in-runtime-protection-for-macos-sequoia)).
Apple's current support page (version selector shows macOS 27) describes the remaining path. The user tries to open
the app, goes to System Settings → Privacy & Security, and clicks **"Open Anyway"**. The button is "only
available for about an hour" after the attempt. The user then enters their login password. Apple warns in the same place that this
is a common malware vector ([PRIMARY] [Apple support](https://support.apple.com/guide/mac-help/open-a-mac-app-from-an-unknown-developer-mh40616/mac)).
*(Inference)* For a stranger from X this is the single largest drop-off point in route (b). Note that the
competitor notes' suggestion to "document the right-click-Open step" is **out of date**: that step no
longer works on macOS 15+.

**Homebrew is not a loophole.** Homebrew 5.0.0 (2025-11-12) deprecated casks without codesigning
and the `--no-quarantine` flag, and announced it would **"disable all Homebrew/homebrew-cask casks that fail
Gatekeeper checks in September 2026"** ([PRIMARY] [brew.sh 5.0.0](https://brew.sh/2025/11/12/homebrew-5.0.0/)).
A cask in March 2026 showed "will be disabled on 2026-09-01" ([SECONDARY] [CopyQ #3498 mirror](https://goodfirstissue.org/hluk/CopyQ/issues/3498)).
**Whether the disablement actually happened on schedule is unconfirmed**, since no post-deadline source was found. The same
release moves Intel to Tier 3 from Sep 2026 and stops running on Intel at all from Sep 2027. A browser
download quarantines files while `curl | sh` does not. That is well-known behavior but **UNVERIFIED** this session.
winget and Scoop were not researched.

### 2e. Can a free app talk to Ollama and degrade gracefully when it's missing? Yes.

Ollama exposes an unauthenticated HTTP API on `localhost:11434` ([PRIMARY] [ollama api.md](https://github.com/ollama/ollama/blob/main/docs/api.md)):

- `GET /api/version` tells you whether it is running.
- `GET /api/tags` lists pulled models with quantization details.
- `POST /api/pull` streams NDJSON progress (`total`/`completed` per layer). Cancelled pulls resume.
- `POST /api/chat` handles the conversation.

All of this is reachable with stdlib `urllib` + `json`, so drill's zero-dependency rule survives. Ollama is
**MIT** ([PRIMARY] [LICENSE](https://github.com/ollama/ollama/blob/main/LICENSE)), so pointing users at it is
unproblematic. MIT does not cover the name or logo, and Ollama's trademark policy was not checked.

Prior art for detection:

- Page Assist auto-detects 127.0.0.1:11434 and shows a "Direct Connection Error" when it can't reach it ([SECONDARY] [Page Assist docs mirror](https://www.mintlify.com/n4ze3m/page-assist/troubleshooting/connection-issues)).
- ollama-python's README shows the auto-pull idiom of catching a 404 and calling `pull` ([PRIMARY] [ollama-python](https://github.com/ollama/ollama-python)).

Ollama's own constraints become drill's system requirements:

- **macOS Sonoma 14+**. Intel Macs run CPU-only ([PRIMARY] [Ollama macOS docs](https://docs.ollama.com/macos)).
- The macOS app asks to create a CLI link in `/usr/local/bin`.
- The Windows installer runs without admin rights ([PRIMARY] [Ollama Windows docs](https://docs.ollama.com/windows)).
- Official installer download sizes were **not found**.

*(Inference)* Because drill is not a browser, the CORS/`OLLAMA_ORIGINS` issues that hit browser extensions do not apply.

---

## 3. MLX vs Ollama for end users: Ollama by default, MLX underneath it

**The surprising fact.** Ollama's **v0.40.0 (2026-09-25)** release notes say "model architectures supported by the
MLX runtime will automatically run on MLX", adding gemma4, qwen3.6 and qwen3.5 ([PRIMARY] [Ollama releases](https://github.com/ollama/ollama/releases)).
This followed the 0.19 MLX preview (2026-03-30), whose MoE benchmark showed decode at **112 vs 58 tok/s** against the
llama.cpp path ([PRIMARY] [Ollama blog](https://ollama.com/blog/mlx)). Latest stable is v0.40.3 (2026-10-11).

Sources conflict on whether MLX auto-activates only on 32 GB+ Macs. One guide says so ([SECONDARY]
[switchingtomac](https://www.switchingtomac.com/ollama-mlx-mac-setup-guide/)). The blog only puts the
*preview model* at >32 GB, and small `-mlx` tags such as `qwen3.5:4b-mlx` (4.0 GB) exist ([PRIMARY] [ollama qwen3.5 tags](https://ollama.com/library/qwen3.5/tags)).
**Verify on an 8 GB Mac** which engine a given tag actually uses.

**At drill's size, MLX buys almost nothing.** At 3B, an M4 Max measured llama.cpp Q4_K_M at **85 tok/s
vs MLX 4-bit at 88**. The same comparison calls 1B–7B "tied within noise", with MLX leading only at 14B+
([SECONDARY, method unclear] [local-llm.net](https://www.local-llm.net/compare/llama-cpp-vs-mlx/)).
The big MLX wins are on MoE models: 131.8 vs 72 tok/s for Qwen3.5-35B-A3B ([SECONDARY] [terminalbytes](https://terminalbytes.com/ollama-vs-llama-cpp-vs-mlx-mac-2026/)).
Claims of "30–50% faster" ([SECONDARY, UNVERIFIED] [codersera](https://codersera.com/blog/lm-studio-complete-guide-2026/amp/))
conflict with the 3B measurement.

**Shipping MLX directly costs portability.**

- `mlx` 0.32.3 (2026-09-29) has macOS wheels for **ARM64 only, macOS 14+** ([PRIMARY] [PyPI mlx](https://pypi.org/project/mlx/#files)).
- It now also has Linux CUDA/CPU wheels, but no Intel Mac.
- The real install footprint of `mlx-lm` (Metal library plus transformers deps) is **unmeasured**.

| Backend | Role in drill | Why |
|---|---|---|
| **Ollama** (default) | Every platform | One install covers macOS, Windows and Linux. MLX on Apple Silicon for supported architectures, Vulkan/CUDA/ROCm elsewhere ([PRIMARY] [docs.ollama.com/gpu](https://docs.ollama.com/gpu)). Handles pull, resume and model storage. drill ships no ML dependencies |
| **LM Studio** (auto-detect) | Use if already running on `:1234` | OpenAI-compatible server and MIT `lms` CLI ([PRIMARY] [lmstudio.ai/docs/cli](https://lmstudio.ai/docs/cli)). The app itself is closed source, so drill can't install or depend on it |
| **mlx-lm** | Matt's training/eval loop; opt-in power-user backend | Mac-only, extra Python deps, ~0–5% speed at 3–4B *(inference from the tie above)* |
| **Apple Foundation Models** | Experimental, maybe later | ~3B on-device model with 2-bit QAT and LoRA support ([PRIMARY] [Apple ML Research](https://machinelearning.apple.com/research/apple-foundation-models-tech-report-2025)). Spanish is reportedly supported ([SECONDARY] [Natasha the Robot](https://www.natashatherobot.com/p/apple-foundation-models)). It is **Swift-only**, needs Apple Intelligence on, and is unavailable if the *system* language is unsupported ([PRIMARY-ish] [Apple forums 805378](https://developer.apple.com/forums/thread/805378)). Spanish quality against the `02a` floor is unmeasured |

*(Inference)* Write drill's backend as an **OpenAI-compatible HTTP client with a configurable base
URL**. Ollama (`/v1`), LM Studio (`:1234/v1`) and `mlx_lm.server` then share one code path, and
auto-detection just probes known ports. Always set `options.num_ctx` and `keep_alive` explicitly. The
Modelfile default `num_ctx` is 2048 ([PRIMARY] [docs.ollama.com/modelfile](https://docs.ollama.com/modelfile)),
and newer servers may override it (**UNVERIFIED**).

---

## 4. Model size, hosting and the first-run experience

### 4a. Download sizes (Ollama library, as displayed; [PRIMARY])

| Tag | Q4_K_M | Q8_0 | Notes |
|---|---|---|---|
| `llama3.2:3b-instruct` | **2.0 GB** | 3.4 GB | Llama community license (custom terms) |
| `qwen3:4b-instruct-2507` | **2.5 GB** | 4.3 GB | Text-only, 256K ctx. Smallest high-quality candidate |
| `phi4-mini:3.8b` | 2.5 GB | 4.1 GB | License believed MIT, **UNVERIFIED** |
| `qwen3.5:4b` (vision) | 3.3 GB | 5.2 GB | Has `4b-mlx` 4.0 GB, the only candidate with a first-party Ollama MLX build |
| `gemma3:4b` | 3.4 GB | 5.0 GB | Gemma Terms: notice + use-policy pass-through |
| `gemma4:e4b` | **6.6 GB** | 9.0 GB | Too big for 8 GB machines and a 5-minute budget |

Sources: [qwen3](https://ollama.com/library/qwen3/tags), [qwen3.5](https://ollama.com/library/qwen3.5/tags),
[gemma3](https://ollama.com/library/gemma3/tags), [gemma4](https://ollama.com/library/gemma4/tags),
[llama3.2](https://ollama.com/library/llama3.2/tags), [phi4-mini](https://ollama.com/library/phi4-mini/tags).
On Hugging Face, the MLX 4-bit `mlx-community/Qwen3-4B-Instruct-2507-4bit` is **2.28 GB** ([PRIMARY] [HF](https://huggingface.co/mlx-community/Qwen3-4B-Instruct-2507-4bit/tree/main)).

**Licenses.** Gemma 1–3 terms require redistributors to pass through the use restrictions, ship the
agreement and include a NOTICE file ([PRIMARY] [ai.google.dev/gemma/terms](https://ai.google.dev/gemma/terms)).
**Gemma 4 reportedly moved to Apache 2.0** on 2026-04-02. This is [SECONDARY] and consistent across [Slashdot](https://tech.slashdot.org/story/26/04/02/1735238/google-announces-gemma-4-open-ai-models-switches-to-apache-20-license)
and [implicator.ai](https://www.implicator.ai/google-releases-gemma-4-under-apache-2-0-dropping-its-custom-ai-license/).
The terms page links a `/gemma/apache_2` page [PRIMARY], but the license text itself was not read, so **verify before
relying on it**. Qwen's Apache-2.0 status is widely reported but **was not confirmed per-repo**.

**Quality cross-check.** `02a` flags Qwen3 *thinking-mode* variants as bad for parseable output. The
`-instruct-2507` tag is the non-thinking instruct release by name, which is plausible but should be confirmed in `02b`'s eval.

### 4b. Adapter: ship fused weights, not a LoRA

Ollama's documented `ADAPTER` support covers Llama, Mistral and Gemma 1/2. Qwen3 and Gemma 3+ appear only
under general import, not adapters ([PRIMARY page, read via search summary] [docs.ollama.com/import](https://docs.ollama.com/import)).
The current Modelfile page has **no ADAPTER section at all** ([PRIMARY] [docs.ollama.com/modelfile](https://docs.ollama.com/modelfile)).
Ollama's MLX blog promises "an easier import path for custom fine-tuned models" with no date. *(Inference)* Train
with mlx-lm, fuse, convert to GGUF, quantize to Q4_K_M (plus Q8_0 for 16 GB+), and publish as a standalone
model. That costs a full ~2.5 GB download instead of a LoRA of "tens of MB" (**UNVERIFIED** order-of-magnitude
estimate), but it works on every backend. The `mlx_lm.lora` / `mlx_lm.fuse` command names are **UNVERIFIED** this session.

### 4c. Hosting: Hugging Face, with Ollama pulling from it directly

- **Hugging Face storage.** Free HF public storage is "best-effort", with no published bandwidth or egress cap. Files are served via
CloudFront, and HF asks that anything "beyond the first few gigabytes" offer genuine value ([PRIMARY] [HF storage limits](https://huggingface.co/docs/hub/storage-limits)).
A single 2–4 GB quant is well within norms.
- **Direct pulls.** `ollama run hf.co/{user}/{repo}:{quant}` defaults to Q4_K_M when present. A
`template`, `system` and `params` file can live in the repo ([PRIMARY] [HF docs: Ollama](https://huggingface.co/docs/hub/ollama)),
so drill's persona and chat template travel with the weights and users need no ollama.com account.
- **Ollama registry.** Mirroring via `ollama push user/model` is optional. Its cost and limits for publishers were **not confirmed**.

**Download time** *(researcher's arithmetic; decimal GB, no overhead)*. The US median fixed download is 148.2 Mbps
([SECONDARY, UNVERIFIED; Ookla page not fetched] [pong.com](https://www.pong.com/blog/internet-speed-statistics-2026)).
Miami's median is 113.51 Mbps ([SECONDARY] [Light Reading](https://www.lightreading.com/broadband/miami-broadband-speed-is-slowest-among-us-cities-ookla)).

| Size | 148 Mbps | 113.5 Mbps | 25 Mbps *(assumed slow link)* |
|---|---|---|---|
| 2.0 GB | ~1.8 min | ~2.3 min | ~10.7 min |
| 2.5 GB | **~2.3 min** | ~2.9 min | ~13.3 min |
| 3.3 GB | ~3.0 min | ~3.9 min | ~17.6 min |
| 6.6 GB | ~5.9 min | ~7.8 min | ~35 min |

Medians for Spanish-learner geographies (Latin America, Spain) were not gathered.

### 4d. First-run pattern

Ollama v0.34.2 added a shared first-run setup for its macOS/Windows apps, and v0.40.2 keeps model-upgrade
backups on disk ([PRIMARY] [Ollama releases](https://github.com/ollama/ollama/releases)). LM Studio's
first run recommends models by RAM with a fit indicator ([SECONDARY, third-party guides] [hongkiat](https://hongkiat.com/blog/local-llm-setup-optimization-lm-studio)).
Jan puts a RAM→model-size table in its README: 8 GB → 3B, 16 GB → 7B ([PRIMARY] [Jan README](https://github.com/janhq/jan)).

*(Inference)* drill's first run should go:

1. Probe `:11434`, then `:1234`.
2. Read RAM and pick the default: Q4_K_M on 8 GB, with Q8_0 offered on 16 GB+.
3. Show the exact size and time ("2.5 GB, about 2–3 minutes").
4. Check `shutil.disk_usage` for about 2× the model size, because Ollama keeps upgrade backups.
5. Stream `/api/pull` into a tkinter progressbar, and retry on failure, which resumes from completed blobs.
6. Warm up with one short generation.
7. Open into a conversation.

**Keep the existing SRS and scripted scenes usable during the pull.** The stranger is learning
from second 30, not waiting.

---

## 5. Competitors and what lands on launch

### 5a. No local-LLM language tutor has traction

Star counts were pulled live from the GitHub API on 2026-10-12 [PRIMARY].

| Project | Stars | Install / onboarding | Lesson for drill |
|---|---|---|---|
| Anki | 31,961 | Native installers; mobile | Breakout OSS learning tools ship **prebuilt binaries** |
| LLPlayer | 4,354 | Windows-only release EXE; needs .NET 10 and VC++ redist (crashes on ASR without it); 6 setup steps; **demo video in README** ([README](https://github.com/umlx5h/LLPlayer)) | Visual demo works; prerequisites hurt |
| LibreLingo | 2,636 | Web | — |
| **freelingo** | **167** | `git clone`, edit `.env`, **manual** `ollama pull gemma4:e4b`, `docker compose up`, register an account (first user becomes admin), placement test; voice needs an NVIDIA GPU; **no screenshots** ([README](https://github.com/artcc/freelingo)) | The closest OSS competitor, and a checklist of what not to do |
| Discute / OllamaTutor / tokori | 90 / 9 / 3 | Various | — |
| Spanish-specific local tutors (spanish-tutor-pi, local-voice-spanish-tutor, miguelito, …) | **0 each** | Telegram bots, scripts | The niche is empty |

Closed-source comparisons:

- **Toucan** swaps a few English words per page into the target language. It is browser-only (Chrome/Edge per
Babbel support; sources conflict on Firefox), cloud-based, and freemium. It raised a $4.5M seed and became part of Babbel ([SECONDARY]
[Babbel support](https://support.babbel.com/hc/en-gb/articles/18269893246738-Toucan-browser-extension);
[BuiltIn LA](https://www.builtinla.com/articles/toucan-raises-4m-seed-round-language-learning-browser-extension)).
- **Language Reactor** has ~4.2–4.3★ from ~53–54k ratings, with complaints about reliability, not onboarding ([SECONDARY] [Chrome Web Store](https://chrome.google.com/webstore/detail/language-reactor/detail/language-reactor/hoombieeljmmljlkjmnheibnpciblicm)).

*(Inference)* "A Toucan that works in every app, offline, free" is a crisp, unoccupied framing. Toucan's
current status inside Babbel was not verified.

### 5b. What competitors got right, and the failure everyone repeats

Anki's recurring complaint is the **empty start**. One user was "confused about what to do when first trying Anki,
since it comes completely empty". Another wrote, "I have spent more time learning HOW to create the decks I need than to
actually study with them!" Anki's developer replied "Your points are valid" but said "there are not enough
hours in the day" ([PRIMARY forum] [AnkiWeb](https://forums.ankiweb.net/t/it-is-nearly-impossible-to-recommend-this-app/32576);
[onboarding decks](https://forums.ankiweb.net/t/revisiting-onboarding-decks-and-tutorials/43692)).

The successes require **zero content setup**:

- Toucan works on pages you already read ([SECONDARY] [Ghacks](https://www.ghacks.net/?p=179499)).
- Language Reactor works on Netflix/YouTube.

The second failure is **hidden prerequisites**: LLPlayer's runtimes, freelingo's Docker, GPU and manual pull.

drill already has the fix for the first failure: 455 cards and eight scenarios ship in the box (README).

### 5c. What lands on HN, and by analogy on X

All points and comment counts are from the HN Algolia API [PRIMARY].

- **Show HN: Ollama – Run LLMs on your Mac**: 284 points, 94 comments, 2023-07-20 ([HN](https://news.ycombinator.com/item?id=36802582)).
Praise centered on "not having to spend one second mucking with Python" and "Precompiled for Mac." Friction
centered on **8 GB Macs going OOM** (the maintainer said the 7B default needs "at least 16GB") and **"why does it want admin
/ launch at login?"** Ollama now has 182,892 stars.
- "Ollama for X" framings keep working:
  - OWhisper: 289 points ([HN](https://news.ycombinator.com/item?id=44901853))
  - Cactus: 231 points ([HN](https://news.ycombinator.com/item?id=44524544))
  - "Trolling SMS spammers with Ollama": 318 points ([HN](https://news.ycombinator.com/item?id=42796496))
- Language-learning Show HNs succeed on a **novel mechanic with a one-line hook** and fail as generic "AI tutor":
  - LangSeed, "Learning a Language Using Only Words You Know": 84 points ([HN](https://news.ycombinator.com/item?id=46274287))
  - SubSmith: 78 points ([HN](https://news.ycombinator.com/item?id=49476894))
  - "Built a conversational language learning app with … LLMs": 2 points ([HN](https://news.ycombinator.com/item?id=45811484))
  - In the LangSeed thread, one commenter asked for mostly-target-language text with ~5% unknowns, which is close to drill's immersion idea.
- A strong concept is not enough on its own. The llamafile 0.10.0 relaunch got 7 points ([HN](https://news.ycombinator.com/item?id=47444794)).

READMEs and launch advice:

- **Ollama's README** order is tagline → one-line install per OS → `ollama run` → API, with no GIF ([PRIMARY] [README](https://github.com/ollama/ollama)).
- **Jan's README** (44,915 stars) leads with an installation table, then **System Requirements** (8 GB → 3B) ([PRIMARY] [README](https://github.com/janhq/jan)).
- **Practitioner advice:** use a plain, specific title. The **repo is the landing page**. Include images, since people scan. Never ask for upvotes ([SECONDARY] [Lucas da Costa](https://www.lucasfcosta.com/blog/hn-launch)).

*(Inference)* Ollama and Jan can skip a demo because everyone understands a chat box. drill's word swap is
novel and needs a video. X itself could not be searched, so X advice is **by analogy to HN**.

---

## 6. Minimum viable launch package: X link → first conversation in under 5 minutes

The 5-minute budget below is *(estimate)*. No competitor's time-to-first-conversation was measured,
and drill's must be timed on a clean macOS account before posting.

| Step | What the stranger does | Budget | Basis |
|---|---|---|---|
| 1 | Taps X post: a <30 s screen recording of a real Spanish exchange + immersion swapping words in a real app, then the repo link | 0:30 | Visual-mechanic inference (§5c) |
| 2 | README first screen: one-line pitch, demo, **"Requires: Mac with Apple Silicon, macOS 14+, 8 GB+ RAM, ~3 GB free"**, big Download button | 0:20 | Jan/Ollama pattern; Ollama's macOS 14 floor ([PRIMARY](https://docs.ollama.com/macos)) |
| 3 | Downloads **notarized** `drill.dmg`, drags, opens. No Settings detour | 0:40 | Gatekeeper (§2d); DMG size **unmeasured** |
| 4 | drill opens **into a working session** (scripted café scene / SRS), no account | 0:10 | Anki empty-start lesson (§5b) |
| 5 | Banner: "Conversation partner needs Ollama (free) → Get it". If Ollama is already running, skip to 6 | ~1:00 | `/api/version` probe; Ollama installer size **unknown** |
| 6 | drill picks the model by RAM and pulls ~2.5 GB with a progress bar while the user keeps drilling | ~2:20 at US median | §4c arithmetic |
| 7 | First warm-up generation, then the conversation opens | 0:10–0:20 | First-token latency **unmeasured** |
| | **Total** | **~5:00–5:20** with no Ollama; **~4:00** with Ollama already installed | *(estimate)* |

The budget only works because step 6 overlaps with useful activity. *(Inference)* The X audience for a local-LLM
tool is disproportionately likely to have Ollama already, which makes them the fastest cohort.

Other parts of the package *(inference unless cited)*:

- **Doctor screen plus a README Troubleshooting section.** Cover these cases:
  - Ollama not running or port 11434 busy
  - Pull stalled, so retry, which resumes
  - 8 GB swap, so close the browser or switch to a lighter model
  - Immersion permissions
- **Immersion is opt-in, after the first conversation.** A system-wide word swap will need macOS
  Accessibility and/or Screen Recording permission. That requirement is an *inference*: the permission model was not researched. It is the analogue of Ollama's "why admin?"
  complaint. Explain the permission before triggering it, and never put it on the path to the first conversation.
  *(Inference, UNVERIFIED)* TCC permissions attach to a stable signed app identity, which is another reason to
  ship a signed `.app` rather than a script run by a generic Python.
- **Developer path:** one line in the README for people who want source, `uvx --from git+https://github.com/<user>/drill drill`
  ([PRIMARY] [uv docs](https://docs.astral.sh/uv/guides/tools/)). This is secondary, and tkinter under uv is **untested**.
- **Posts.**
  - X: lead with the video, then "runs 100% on your Mac, no account, no cloud, free", then **one honest measured
    tok/s and time-to-first-token on a base M1/M2 Air**, then the link.
  - Show HN: use a plain title such as "Show HN: drill – a Spanish conversation partner that runs entirely on your Mac."
  - Pre-answer "why not just Ollama + a prompt?" with deterministic grading, Peninsular register enforcement and immersion, and state RAM
    needs up front (Ollama's 8 GB OOM lesson).
- **Positioning line:** freelingo needs Docker, an account and a GPU for voice. The Spanish local tutors on GitHub
  have 0 stars. Toucan is browser-only and cloud.

---

## Verdict

**Packaging for v1: a signed, notarized, arm64 `.app` in a `.dmg`.** Build it with PyInstaller on a python.org Python. Pay the $99/yr. Without notarization, the macOS 15+ "Open Anyway" flow kills the
non-technical funnel, and Homebrew is closing the cask loophole. Briefcase is the fallback only if
it is confirmed to handle tkinter. No Tauri/Electron, and no rewrite.

**Runtime default: Ollama over HTTP, using stdlib only.** Use LM Studio if it is detected. If neither is present, show a clear "Get
Ollama" step, and the app stays fully usable without an LLM. Do not bundle llama.cpp or MLX in v1. Build the client
OpenAI-compatible so bundling `llama-server` later is a drop-in if measured Ollama-install drop-off is
high. MLX reaches users through Ollama's engine. `mlx-lm` stays as Matt's training and eval tool and an opt-in
backend, never the default.

**Model: one fused Spanish-tuned 3–4B instruct model hosted as GGUF on Hugging Face.** The leading candidate is `qwen3:4b-instruct-2507`-class at 2.5 GB.
Use **Q4_K_M on 8 GB and Q8_0 on 16 GB+**. Never ship below 3B, per `02a`. Ship fused weights, not adapters.

**Platforms: Apple Silicon macOS 14+ only for v1.** That covers ~90% of Macs, and the 8 GB cohort is supported at
Q4. **Intel Macs are out**: macOS is frozen at 26, Homebrew drops Intel in 2027, and there is no throughput data. **Windows is
out for v1** and becomes v2 via the free Microsoft Store MSIX route. CPU-only laptops sit at a borderline
~8–20 tok/s at Q4 on top of the Q4 Spanish-quality risk, and SmartScreen and signing are a separate project. **Linux** gets the
developer `uvx` path only, unsupported.

**Launch: the DMG, the <30 s demo video, the requirements line, and a measured M1/M2 Air number, all on the day of the X post.**

---

## Needs measuring

1. **Q4_K_M vs Q8_0 Spanish quality at 3–4B** on drill's hand eval (`02a` flags 4-bit as risky below 7B).
   This decides whether 8 GB Macs get a real product.
2. **On a base 8 GB M1/M2 Air:** decode tok/s, prompt-processing tok/s, and **time-to-first-token** with
   drill's real system prompt and history, plus swap behavior with a browser open. Also confirm which tags run on Ollama's
   MLX engine there (verify the v0.40 MLX claim and any 32 GB gating).
3. **Cold install timing:** X link → first conversation on a fresh macOS user account, with and without Ollama
   pre-installed. Check it against the 5:00 budget.
4. **Artifact sizes:** the notarized PyInstaller tkinter `.dmg`, plus the current Ollama macOS/Windows installers.
5. **tkinter correctness:** inside the PyInstaller bundle (python.org Tk), and under uv-managed Python for the developer path.
6. **Immersion permissions:** which TCC permissions the system-wide word swap needs, and whether they persist
   across app updates for a signed app.
7. **Licenses, read first-hand:** the Gemma 4 Apache-2.0 text, the Qwen3 per-repo license, the Llama 3.2 terms if used,
   and Ollama trademark guidance for naming it in the UI.
8. **Homebrew:** whether the September 2026 cask disablement happened. Also research winget and Scoop requirements before the Windows v2.
9. **Windows CPU-only reality check (for v2):** 3–4B Q4 tok/s and time-to-first-token on a typical 8 GB Intel
   U-series laptop with single-channel RAM.
