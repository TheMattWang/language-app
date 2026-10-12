# 09 — System-wide Immersion

Context: "drill" (~/dev/language-app) is a free, fully local language-learning app. Spanish comes first, in either the Spain or the LatAm variety, and the design has to leave room for more languages. Inference runs on local LLMs (Ollama, MLX), the codebase is Python, and the target machine is an M3 MacBook Air, 16GB, fanless. This doc evaluates **system-wide immersion**: while the user reads anything on their Mac, some English words or phrases are swapped into Spanish in context, at a density adapted to the user's level. Research date 2026-10-12 (macOS 26 Tahoe is current). Confidence tags [well-established] / [contested] / [speculative] apply to pedagogy claims. UNVERIFIED means no source was found this session.

**Precedent.** An earlier immersion idea worked at the app-locale layer: `defaults write com.google.Chrome AppleLanguages -array es-ES es`. It failed on 2026-09-14, and Chrome's UI stayed in English (`docs/00-constraints.md`). The feature in this doc works one layer down, at the text content itself. It does not depend on any app honoring a locale override, and it affects the text the user actually reads rather than menu chrome.

---

**TL;DR**

- **Feasible on macOS, with real seams.**
  - The Accessibility API (AX) gives text plus screen rectangles for native apps, Safari and Electron. Chrome's web content is off by default and forcing it on has side effects.
  - Screen capture + Vision OCR covers everything, but costs ~100–300 ms per recognition (anecdotal). It needs Screen Recording permission, which since Sequoia comes with periodic re-prompts.
  - Input methods and Services cannot read displayed text.
  - Any AX-based app is barred from the Mac App Store sandbox, so it ships as Developer ID + notarized.
- **Nobody ships system-wide word swapping.**
  - Every word-swap product found is a browser extension, usually cloud-based and account-based. Toucan is now Babbel's free funnel product.
  - Phrase Flip is the only local one. It swaps sentences, not words, and only in the browser.
  - Paid incumbents in adjacent reading layers charge ~$6–15/mo. Local inference removes the per-swap cost that forces cloud tools to meter usage, which is the economic case for drill being free and local.
- **Pedagogy is modest.**
  - Controlled studies show real but short-lived receptive vocabulary gains. Broccoli (N=58) beat time-matched memorization short-term and tied it at 1–4 weeks, at ~30% vs 20% chance.
  - No study varies density as an independent variable.
  - Swaps teach meaning recognition, not grammar or production. They are a vocabulary on-ramp feeding the input→pushed-output cycle in `01-pedagogy.md`, not immersion in Swain's sense.
- **Recommendation:** a shared Python core (word selection, density, learner state, local model) behind a native-messaging host. The front ends are an AX-first overlay for native apps, an MV3 extension for Chrome, and OCR only on a hotkey. If AX coverage measures badly on the Air, fall back to extension-only. See Verdict.

---

## 1. macOS mechanisms: AX is the backbone, OCR the gap-filler, IMK a dead end

### 1.1 Accessibility API (AXUIElement): cheapest, most precise, uneven coverage

- **What it gives.** Text plus per-range screen rectangles. The standard route reads `AXVisibleCharacterRange`, then calls `kAXBoundsForRangeParameterizedAttribute` on each word range. That yields screen coordinates for an overlay without OCR. Per-app reliability is UNVERIFIED, and no latency numbers were found.
- **Prior art.** screenpipe uses the AX tree as its "Primary — used for every capture" path and falls back to Vision OCR only "when accessibility is empty" ([screenpipe architecture](https://docs.screenpipe.com/architecture)).
- **Coverage tiers (inferred, partly UNVERIFIED):**

| Surface | AX text available? | Cost / caveat |
|---|---|---|
| Native AppKit (TextEdit, Mail, Notes), Safari `AXWebArea` | Yes, natively | Inferred, not measured |
| Electron (Slack, VS Code, Discord, Obsidian, Notion) | Only after setting `AXManualAccessibility` via `AXUIElementSetAttributeValue` | Documented mechanism ([Electron docs](https://www.electronjs.org/docs/latest/tutorial/accessibility)); performance not documented |
| Chrome web content | "Off by default and enabled automatically on-demand" ([Chromium a11y overview](https://chromium.googlesource.com/chromium/src/+/HEAD/docs/accessibility/overview.md)). Third parties must set `AXEnhancedUserInterface` or launch with `--force-renderer-accessibility` | Setting it "breaks window positioning with window managers like Magnet" ([Apple forum 659755](https://developer.apple.com/forums/thread/659755)). Electron added `AXManualAccessibility` because forcing it is "a problematic approach" ([electron PR #7206](https://github.com/electron/electron/pull/7206)). Chromium actively retunes its enablement heuristics ([commit](https://chromium.googlesource.com/chromium/src/+/34d5b59a67da7b0ea1a3eb90835467eb63e7262e)). Whether Chrome honors `AXManualAccessibility`: UNVERIFIED |
| Firefox, Preview/PDF, Terminal/iTerm2 | UNVERIFIED | No source found |

- **Never write `AXValue`.** It would edit the user's real document, touching undo history, saves and sync. Replacement has to be visual, via a click-through overlay.
- **Sandbox.** Apple DTS: "the Accessibility APIs are not supported in sandboxed apps" ([forum 756130](https://developer.apple.com/forums/thread/756130)). Developers report that `AXIsProcessTrusted` always returns false when sandboxed ([forum 810677](https://developer.apple.com/forums/thread/810677)). One DTS reply suggests partial access ([forum 794253](https://developer.apple.com/forums/thread/794253)). Either way, AX means no Mac App Store.
- **Cost.** AX calls are synchronous cross-process IPC. Walking a large tree (Slack, a long Chrome page) from Python adds interpreter overhead on top. Use `AXObserver` notifications (value changed, focus changed, scroll/bounds changed) instead of polling. No measured numbers exist; UNVERIFIED.

### 1.2 Screen capture + Vision OCR + overlay: universal coverage at a price

- **Coverage.** Everything visible, including remote desktops, canvas apps and games.
- **Latency.** Anecdotally "roughly 100 to 300 milliseconds" per recognition ([blakecrosley.com](https://blakecrosley.com/blog/vision-framework-built-in)). FreezeText reports "typically under 0.3 seconds" at highest accuracy ([FreezeText](https://store.juergenkoller.software/en/apps/freezetext/manual/technical-details)). There are no rigorous `.fast` vs `.accurate` M-series benchmarks.
- **CPU and thermals: no Air numbers exist.**
  - screenpipe reports "~5-10%" CPU and "~600 MB" RAM on a **MacBook Pro M3 (32 GB)** ([architecture](https://docs.screenpipe.com/architecture)), and 5–15% on its about page ([screenpi.pe/about](https://screenpi.pe/about)).
  - That figure comes from event-driven capture (app switch, click/scroll, typing pause, ~5 s idle fallback), not continuous capture.
  - One user report cites >100% CPU / >10 GB RAM ([third-party summary](https://luci.memories.ai/blog/fix-screenpipe-high-cpu-usage)).
  - A fanless Air throttles under sustained load, so these numbers do not transfer and have to be measured.
- **macOS 26 Vision bugs.**
  - Memory grows ~3–15 MB per `.accurate` call on 26.2 ([forum 815812](https://developer.apple.com/forums/thread/815812)).
  - `.accurate` fails to load in a helper process on Apple silicon ([forum 824639](https://developer.apple.com/forums/thread/824639)).
  - Both matter for an always-on helper.
- **Permission friction.**
  - Sequoia moved from weekly to monthly "Allow For One Month" re-authorization, with no permanent opt-out ([9to5Mac](https://9to5mac.com/2024/08/14/macos-sequoia-screen-recording-prompt-monthly/), [TidBITS](https://tidbits.com/2024/08/19/apple-reduces-excessive-sequoia-permission-requests-shifts-to-monthly)).
  - Deprecated capture APIs trigger alerts, so use ScreenCaptureKit ([9to5Mac](https://9to5mac.com/2024/10/07/macos-sequoia-screen-recording-popups/)).
  - The persistent-capture entitlement is apply-for and meant for screen-sharing products ([forum 778616](https://developer.apple.com/forums/thread/778616)). A language app is unlikely to qualify (inference).
  - **Tahoe 26 re-prompt behavior: UNVERIFIED.**
- **Self-capture.** Exclude drill's own overlay with `SCContentFilter(display:excludingApplications:exceptingWindows:)` ([WWDC22 10156](https://developer.apple.com/videos/play/wwdc2022/10156/)). `NSWindow.sharingType = .none` is unreliable ([forum 808016](https://developer.apple.com/forums/thread/808016)).
- **Overlay mechanics (general AppKit, UNVERIFIED here):**
  - A borderless transparent `NSWindow` with `ignoresMouseEvents = true`, a high window level, and `.canJoinAllSpaces/.fullScreenAuxiliary/.stationary`.
  - Hide the overlay while scrolling and re-render once scrolling settles. Otherwise labels drift until the next pass.

### 1.3 Input methods and Services: not viable

- IMK sees only the text being composed. Services receives only an explicit selection. Neither reads displayed text (inference; no Apple doc fetched).
- Easydict, the leading open-source macOS translator, confirms the pattern: Accessibility for selection, Screen Recording for OCR, not IMK ([Easydict README](https://github.com/tisfeng/Easydict/blob/main/README_EN.md)).
- Role: at most an opt-in "translate selection" extra.

### 1.4 Distribution and the PyObjC-vs-Swift question

- **Gatekeeper.**
  - Sequoia 15.1 removed the Control-click "Open" override. Unsigned apps now need System Settings → Privacy & Security → "Open Anyway" ([Macworld](https://www.macworld.com/article/2457844/what-to-do-when-you-cant-open-an-app-you-just-installed-in-macos-sequoia.html)).
  - For anyone but the owner, that means Developer ID + notarization. The Apple Developer Program costs US$99/yr per a third-party guide ([stefanvd](https://www.stefanvd.net/blog/?p=572)); not verified on apple.com.
- **TCC identity.**
  - Grants attach to code signature, bundle ID and path. Ad-hoc rebuilds lose them, and a grant to a shared interpreter covers every script that interpreter runs ([OpenClaw docs](https://docs.openclaw.ai/platforms/mac/permissions)).
  - Running `python app.py` from Terminal typically makes Terminal the "responsible process", so Terminal gets Accessibility/Screen Recording. That over-grant is a privacy smell.
  - Tahoe 26.1 hides non-bundled executables from the Screen Recording list while still letting them capture ([forum 807898](https://developer.apple.com/forums/thread/807898)).
- **PyObjC can do all of it.** It wraps HIServices (AX), Vision, ScreenCaptureKit and InputMethodKit, though not VisionKit ([PyObjC API notes](https://pyobjc.readthedocs.io/en/latest/apinotes.html)).
- **Swift is the lower-risk shell.** ScreenCaptureKit's async callbacks and overlay lifecycle are awkward in Python, and TCC needs a stable signed bundle.
  - **Recommended split:** a small signed Swift helper (AX observe, rect lookup, overlay, optional SCK+Vision) talks over local IPC to the Python core, which owns word selection, density, learner state and Ollama/MLX.
  - This revisits the cancelled v0's "No Swift" line (`docs/00-constraints.md`). That constraint was about trip-deadline scope and no longer binds.

## 2. Windows is comparable, Linux is X11-only in practice

- **Windows: roughly as feasible as macOS, arguably easier.**
  - UI Automation: `IUIAutomationTextRange::GetBoundingRectangles` returns per-line rects. For a single word, narrow the range to that word first ([Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/api/uiautomationclient/nf-uiautomationclient-iuiautomationtextrange-getboundingrectangles)).
  - Chrome turned on native UIA by default in Chrome 138, replacing a laggy MSAA emulation layer ([Chrome blog](https://developer.chrome.com/blog/windows-uia-support-update)).
  - The OS ships `Windows.Media.Ocr` with word-level boxes ([OcrEngine](https://learn.microsoft.com/en-us/uwp/api/windows.media.ocr.ocrengine)).
  - `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` cleanly hides the overlay from drill's own capture ([docs](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowdisplayaffinity)).
  - No TCC-style permission gate was found (UNVERIFIED as an absolute). UIPI still blocks reading elevated windows (UNVERIFIED).
  - Python bindings exist (comtypes/`uiautomation`/pywinauto, winrt OCR), but maintenance status is UNVERIFIED.
  - Per-word rects in Chrome's TextPattern are unconfirmed.
- **Linux: X11 is moderate. Wayland is hard to infeasible.**
  - Under Wayland, AT-SPI returns only window-relative coordinates ([at-spi2-core #14](https://gitlab.gnome.org/GNOME/at-spi2-core/issues/14), [freedesktop wiki](https://wiki.freedesktop.org/www/Accessibility/Wayland/)).
  - Capture needs a user-approved portal.
  - Always-on-top click-through overlays need layer-shell, which "is not supported on Gnome-on-Wayland" ([gtk-layer-shell](https://awesome.ecosyste.ms/projects/github.com%2Fwmww%2Fgtk-layer-shell)). GNOME would need a Shell extension ([GNOME Discourse](https://discourse.gnome.org/t/supporting-third-party-accessibility-software-on-gnome-wayland/38214)).
  - Chromium/Electron reportedly expose an empty AT-SPI tree without `--force-renderer-accessibility`. That claim is medium confidence, from a third-party doc ([tessl](https://tessl.io/registry/testland/at-spi-linux)).
  - There is no OS OCR, so Linux would need Tesseract (accuracy and latency UNVERIFIED).
  - **Linux = browser extension only.**
- **Relative difficulty:** Windows ≈ macOS < Linux/X11 ≪ Linux/Wayland. The cross-platform constant is the browser extension.

## 3. Prior art: browser-scoped, cloud-metered, and nobody does system-wide

| Product | What it does | Local? | Price / model |
|---|---|---|---|
| **Toucan by Babbel** | Swaps words/phrases on web pages, 11 languages; claims 750k+ users ([jointoucan.com](https://jointoucan.com/)) | No. Account required; Babbel's policy covers clickstream and ad-impression data, processed "on European servers" ([Babbel privacy](https://www.babbel.com/legal/privacy)) | Free since Babbel's Sept 2023 acquisition, as "a gateway to Babbel's premium features" ([press release](https://babbel.com/press/en-us/releases/keep-learning-while-browsing-babbel-to-integrate-toucan-browser-extension)) |
| **Lingoku** | Level-aware swaps of ~10% of text ([korben.info](https://korben.info/en/lingoku-extension-japanese-learning-while-browsing.html)) | No (AI quota) | Free tier "500 points per day", paid AI features; price UNVERIFIED |
| **Fluent Tab** (Firefox) | User-set replacement of 1–30% of words ([AMO](https://addons.mozilla.org/addon/fluent-tab/)) | UNVERIFIED | UNVERIFIED |
| **Fluent** (fluent.co) | Swaps selected words, resurfaces them across sites until learned ([Daily Hive](https://dailyhive.com/toronto/fluent-language-chrome-extension)) | UNVERIFIED | 2026 status UNVERIFIED |
| **Vocabo** | Word replacement; claims "completely free", no account ([vocabo.io](https://www.vocabo.io/toucan-alternative)) | Not stated | Free |
| **illa-helper** (OSS, MIT, ~2.9k★) | LLM picks level-appropriate words; 1–100% ratio; lazy per-paragraph ([GitHub](https://github.com/xiao-zaiyi/illa-helper)) | BYO cloud key. Ollama not mentioned; only possible via a generic OpenAI-compatible endpoint (UNVERIFIED) | Free |
| **Phrase Flip** (Mac App Store) | Swaps *sentences* with an intensity setting; browser only; macOS 26+ ([App Store](https://apps.apple.com/app/phrase-flip/id6759987963)) | **Yes.** Apple Translation framework, "no API keys or servers" | Free |
| LingQ / Readlang / Language Reactor / Migaku / Immersive Translate | L2 reading or subtitle layers, not L1 word-swap | No | LingQ $14.99/mo; Readlang $6/mo; Language Reactor ~$5.95/mo; Migaku $10/mo; Immersive Translate Pro $9.99/mo ([lexirise](https://lexirise.app/blog/article/free-lingq-alternative), [practy](https://practy.app/language-reactor-pricing), [App Store](https://apps.apple.com/app/id6447957425)). Secondary sources; 2026 prices UNVERIFIED |
| **Easydict** (OSS, GPL-3.0) | System-wide *full* translation of selection/OCR, supports Ollama ([GitHub](https://github.com/tisfeng/Easydict)) | Can be | Free. Proves the permissions path; is not a learning tool |

- **Toucan's documented weakness is sense errors.**
  - A user reports "back" (meaning behind) rendered as *espalda* instead of *atrás* ([Edge listing](https://microsoftedge.microsoft.com/addons/detail/ljbocbkhabkbkedlhmppmpfajejdkoei)).
  - A 2026 review reports swapped link text breaking hyperlinks ([extensionindex](https://extensionindex.com/extensions/toucan-babbel-language-learning)).
  - Context-aware sense selection is exactly where a local LLM adds value.
- **The economic argument.** Cloud tools pay per swap, so they meter (Lingoku's points), monetize attention (Toucan's clickstream and funnel), or charge $6–15/mo. Local inference has near-zero marginal cost on hardware the user already owns. **A paid or cloud incumbent's existence is a reason for drill to be free and local, not a reason to skip the feature.**
- **The open gap.** No product found combines system-wide coverage, word-level context-aware swaps, a local model, and no account.
- **Diglot weave lineage** (Blair/Power-Glide, BYU diglot readers) has no current commercial app ([BYU ETD 4762](https://scholarsarchive.byu.edu/etd/4762)).

## 4. Pedagogy: real but small receptive gains, density unstudied

### 4.1 What the evidence shows

- **Diglot weave itself is under-tested.** [contested / weak evidence]
  - The direct evidence is small BYU theses and two non-randomized Indonesian classroom comparisons.
  - Aoyama (2005): 81 students learned the meanings of about 21 words, with ~.73 one-week retention, but had no non-diglot control ([BYU ETD 538](https://scholarsarchive.byu.edu/etd/538)).
  - Katemba & Sitompul (2018): intact classes, N=74, beat STAD at p=0.035 ([UNAI](https://jurnal.unai.edu/index.php/isc/article/view/1488)).
  - Burling's 1968/1978 proposals were not fetched (UNVERIFIED). A "Christensen et al. 2007" diglot study could not be located.
- **The macaronic NLP/HCI line is the rigorous evidence.** [well-established that some learning occurs; contested that it beats explicit study long-term]
  - **Broccoli** (Aydin et al., WWW 2020; randomized, counterbalanced, within-subject, N=58, Finnish; [arXiv](https://arxiv.org/abs/2104.07941)):
    - Short-term retention significantly beat time-matched table memorization.
    - At 1–4 weeks (n=32) there was no difference: ~30% correct vs a 20% chance baseline.
    - Each word got only 7 massed exposures.
    - Reading slowed **199→163 wpm (−18%)** at a density the authors called higher than real use would need.
  - **Renduchintala et al. EMNLP 2019** ([D19-1679](https://aclanthology.org/D19-1679/)):
    - Choosing *guessable* tokens raised comprehension of swapped open-class words: Spanish 0.80 vs 0.61 random, German 0.79 vs 0.38.
    - Beginners translated >30 of 71 seen word types on an immediate quiz.
    - There was no delayed test.
  - **ALOE** (CHI 2011): ~50 French words over 2 months. Abstract only ([DOI](https://doi.org/10.1145/1978942.1979414)).
- **Baseline comparison.** [well-established]
  - Incidental pick-up from reading is 17% immediate and 15% delayed (meta-analysis, 24 studies, N=2,771; [Webb et al. 2023](https://todoele.net/bibliografia/how-effective-second-language-incidental-vocabulary-learning-meta-analysis)).
  - Glossed reading is ~45%/33% vs ~27%/20% unglossed. **Multiple-choice "guess then check" glosses are the most effective** ([Yanagisawa et al. 2020](https://cambridge.org/core/journals/studies-in-second-language-acquisition/article/how-do-different-forms-of-glossing-contribute-to-l2-vocabulary-learning-from-reading/38124150D59DF3039EE1FF5AE88FE922)).
  - Robust knowledge needs ~10+ encounters ([Webb 2007, via ERIC](https://files.eric.ed.gov/fulltext/EJ1044345.pdf)); the exact count is contested.

### 4.2 Density: weakest evidence in the doc

- **No study manipulates replacement density as an independent variable, and no product publishes an evidence-based density.**
- The coverage literature gives a bound, not a rule:
  - Comprehension falls roughly linearly with unknown-word density, with no threshold ([Schmitt, Jiang & Grabe 2011](https://www.lextutor.ca/cover/papers/schmitt_etal_2011.pdf)).
  - 98% coverage is the conventional comfortable-reading target and 95% the minimum.
  - Hu & Nation's 98% was extrapolated, not tested, and only partly replicated by Kremmel et al. 2023 ([AILA abstract](https://aila2021.dryfta.com/program/abstract-archive/abstract/public/416/unknown-vocabulary-density-reading-comprehension-and-the-98-coverage-figure-replicating-hu-nation-2000)).
- **Derived starting values (all [speculative]):**
  - **New, never-seen L2 tokens: ≤2% of running tokens** (about 1 per 50 words), **hard ceiling 5%**. This is conservative, because the L1 frame makes swapped words easier to guess than true unknowns.
  - **Already-recalled words** can raise *total* swapped density to ~5–15%.
  - **Control signal:** reading-speed slowdown or reveal rate, targeting **≤10% slowdown**. That number is a heuristic, not a study result.
- **Calibrate on the owner.** Broccoli's −18% at "too dense" is the only measured anchor.

### 4.3 What swaps cannot do, and how it fits `01-pedagogy.md`

- **Swaps train receptive meaning recognition only.** Aoyama, Broccoli and Renduchintala all measured L2→L1 meaning. Renduchintala considers "only simple lexical substitutions." No study measures gender, inflection, collocation or syntax. [well-established gap]
- **The design follows from that:**
  - Swap with the article and inflection where the slot allows ("la mesa", not "mesa").
  - Move to multiword swaps once single words are known.
  - Use guess-then-reveal rather than an always-visible hover. This maps onto the multiple-choice-gloss result (Broccoli's optional click-to-reveal did not change retention, which is mild tension).
  - Schedule swaps by SRS state toward 7–10+ spaced encounters. [speculative]
- **Fit with the research corpus.** `01-pedagogy.md` already establishes that input is necessary but insufficient and production must be forced (Swain). Word swap is weaker than input in Krashen's sense, because the syntax is L1. It is a **vocabulary on-ramp**: words seen in swaps get promoted into real L2 input and forced L1→L2 production tasks. It does not replace those tasks.
- **Word-selection sources.** These come from `05-landscape-content.md`:
  - hermitdave FrequencyWords (CC-BY-SA-4.0) for frequency rank. It is mixed Spain/LatAm, so cross-check variety-specific lexicon (*coche/carro*, *ordenador/computadora*).
  - Kaikki/Wiktionary JSONL for sense inventories and POS.
  - spaCy `es_core_news_*` for lemmatization and agreement.
  - Variety becomes a per-user setting that filters the candidate lexicon.
  - The local LLM's job is **sense disambiguation and inflection in context**: the *espalda/atrás* problem. It picks from dictionary-constrained candidates rather than authoring translations freely, consistent with `05`'s stance that a small local model is not the language authority.

## 5. Browser-extension fallback: highest value per unit of effort

- **Value.**
  - The extension does true in-DOM replacement, so there is no overlay alignment, scroll drift or screen permission.
  - It works on every OS, including Wayland.
  - It covers the browser, which is probably the biggest single reading surface. Share is UNVERIFIED: the only figures are a Google-sponsored "a third of their work day, 2.7 hours" ([infographic](https://services.google.com/fh/files/helpcenter/the_rising_impotance_of_browser_in_enterprise_it_strategies_infographic.pdf)) and a tiny student study.
  - It misses Electron apps (Slack, Notion, VS Code, Obsidian) and native apps. That gap is exactly what the system-wide layer adds.
- **Effort.** Low; this is a well-trodden pattern.
  - An MV3 content script walks text nodes with a TreeWalker, plus a MutationObserver for SPAs and viewport-only processing.
  - Wrap only the chosen word via `splitText` in a `<span data-drill>`. Never rewrite `innerHTML`.
  - Skip `INPUT/TEXTAREA/SELECT`, `[contenteditable]`, `CODE/PRE/KBD`, `SVG/MATH`, `.notranslate`, link text (Toucan's broken-link bug), and drill's own spans.
  - Show the page unmodified, then swap asynchronously once the model returns. Cache results per (word, context hash).
  - Performance on heavy SPAs is unbenchmarked (UNVERIFIED).
- **Talking to the local model.** Make the calls from the service worker; content scripts are bound by the page's same-origin policy ([Chrome network requests](https://developer.chrome.com/docs/extensions/develop/concepts/network-requests)). There are three options:

| Path | How | Friction |
|---|---|---|
| **Native messaging → drill's Python host** (recommended) | `runtime.connectNative("com.drill.host")` keeps one long-lived Python process that owns learner state and calls Ollama/MLX. Messages are length-prefixed JSON, 1 MB host→browser, 64 MiB browser→host. The manifest lists exact extension IDs ([Chrome native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging)) | Installer writes a host manifest per browser and OS (`~/Library/Application Support/Google/Chrome/NativeMessagingHosts/`). Avoids CORS, ports and LNA. Works for MLX, which has no HTTP server by default. Shares state with the AX overlay |
| Direct `fetch` to `http://127.0.0.1:11434` | `host_permissions` for localhost:11434. Ollama allows only `127.0.0.1`/`0.0.0.0` origins by default; extensions need `OLLAMA_ORIGINS=chrome-extension://*,moz-extension://*,safari-web-extension://*` ([Ollama FAQ](https://docs.ollama.com/faq)). Page Assist instead rewrites the Origin header, which breaks some other sites ([Page Assist docs](https://www.mintlify.com/n4ze3m/page-assist/troubleshooting/connection-issues)) | User must set an environment variable; on Linux, `OLLAMA_ORIGINS` must go in the systemd unit ([localaimaster](https://localaimaster.com/blog/ollama-403-forbidden-cors)). Exposed to Chrome **Local Network Access**: the permission prompt launched in Chrome 142, and worker requests need the worker origin to hold the permission ([Chrome LNA blog](https://developer.chrome.com/blog/local-network-access)). Whether extension service workers are exempt is undocumented; Zotero Connector broke until users set the site to "Allow" ([Zotero forums](https://forums.zotero.org/discussion/125333/sharing-my-fix-for-the-zotero-connector-connection-issue)) |
| Chrome built-in AI | Translator API is stable in Chrome 138+ and uses on-device "expert models". Prompt API (Gemini Nano) is stable for extensions since 138 and needs 22 GB free disk plus >4 GB VRAM or 16 GB RAM / 4 cores ([built-in APIs](https://developer.chrome.com/docs/ai/built-in-apis), [get-started](https://developer.chrome.com/docs/ai/get-started)) | Chrome-only, with no level control. A zero-setup tier for users without drill's host. en→es quality unevaluated |

- **Distribution.**
  - Chrome Web Store: a one-time $5 fee, as of 2020 ([Chromium blog](https://blog.chromium.org/2020/03/new-developer-dashboard-and.html)).
  - `<all_urls>` triggers deeper review ([CWS review](https://developer.chrome.com/docs/webstore/review-process)). Use `optional_host_permissions` with per-site grants.
  - Safari web extensions must be wrapped in a native app via Xcode ([WWDC21 10104](https://developer.apple.com/wwdc21/10104/)). The drill Mac app can be that wrapper.
  - Firefox AMO fee: none found (UNVERIFIED).

## 6. Privacy: reading all screen text is acceptable only because nothing leaves the machine

- **What the feature sees.** Everything: messages, banking, health portals, password-adjacent UI.
  - Locally, this is the same exposure screenpipe and Easydict users accept.
  - Through a cloud model it would be indefensible. Toucan's policy does not even say whether page text leaves the browser ([Babbel privacy](https://www.babbel.com/legal/privacy)).
  - Local-only is a precondition for this feature, not a marketing point.
- **macOS mitigations:**
  - **Filtering what is read:**
    - Skip any element with subrole `AXSecureTextField` (semantics UNVERIFIED on macOS 26).
    - Pause all reading while `IsSecureEventInputEnabled()` is true (UNVERIFIED on 26).
    - Exclude apps at the capture layer with SCContentFilter ([SCContentFilter](https://developer.apple.com/tutorials/data/documentation/screencapturekit/sccontentfilter/init(display:including:exceptingwindows:).md)).
  - **Default denylist:** password managers, Keychain Access, banking/finance apps, System Settings, and messaging apps (opt-in). Private browser windows too, though detecting them via AX is UNVERIFIED.
  - **Prefer AX over OCR.** AX reads text from elements and never captures pixels.
  - **Handling and controls:**
    - Keep text in memory only and never persist captured text. Logs hold only word IDs and exposure events, not context sentences.
    - Show a visible "immersion on" indicator and a hotkey pause.
    - Ship a signed bundle so drill gets its own TCC grant instead of Terminal's.
- **Extension mitigations:**
  - Never read form fields or `[contenteditable]`.
  - Leave incognito off (Chrome's default; ref not fetched).
  - Use per-site opt-in plus a default domain denylist (banks, health, tax, webmail compose).
  - Validate `sender.origin` before relaying to the native host ([native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging)).
  - Send the model only the minimal sentence.

## Verdict

**Worth building, but as a vocabulary on-ramp, not as "immersion."** It is technically feasible on macOS, uncontested as a free, local, system-wide product, and pedagogically modest: real short-term receptive gains, roughly parity with explicit study at a few weeks, and nothing for grammar or production. It earns its place only if swapped words feed SRS scheduling and the forced-production loop.

**Recommended v1 mechanism (macOS):**
1. **Core (Python, build first).** A `drill-host` process holds:
   - Candidate word selection: frequency list + Kaikki senses + spaCy, filtered by variety (Spain/LatAm).
   - Learner state: SRS per lemma, with new-token density ≤2%, ceiling 5%, total ≤~15% including known words.
   - Context-aware sense and inflection choice by the local model via Ollama/MLX, constrained to dictionary candidates.
   - A cache keyed on (lemma, context hash).
   - One protocol: length-prefixed JSON over stdio, so the same host serves every front end.
2. **Front end A: Chrome MV3 extension over native messaging.**
   - In-DOM `splitText` spans with guess-then-reveal on click.
   - Skip links, forms, editable regions and code.
   - No `OLLAMA_ORIGINS` and no localhost fetch, so no LNA exposure. Chrome is covered by the extension, not by forcing `AXEnhancedUserInterface`, which has window-manager side effects.
3. **Front end B: system-wide AX overlay.**
   - A small signed Swift helper (Developer ID, notarized, stable bundle ID for TCC) observes the focused window via AXObserver.
   - It reads the visible character range and gets word rects via `kAXBoundsForRangeParameterizedAttribute`.
   - It draws a click-through overlay, hidden during scroll and redrawn on settle. It never writes `AXValue`.
   - Targets: native AppKit apps, Safari, and Electron apps via `AXManualAccessibility`.
   - Privacy: skip secure fields, pause during secure input, apply the default denylist.
4. **OCR only on demand.** A hotkey "immerse this window" runs ScreenCaptureKit (excluding drill's own windows) + Vision `.fast` once, for windows where AX comes back empty. **No continuous OCR on the fanless Air**, given the Screen Recording re-prompts and the unmeasured thermals.

**Fallback.** If AX coverage or rect accuracy on the owner's actual apps measures poorly, or the overlay drifts badly, ship **extension-only**: Chrome MV3, plus a Safari web extension wrapped in the drill app. Both use the same native host. That is Toucan's scope with drill's differentiators: local, no account, context-aware senses, adaptive density. Windows ports via UIA later. Linux stays extension-only.

## Needs measuring

- **AX coverage per app on the owner's Mac.** Measure text retrievable from the visible range, and the accuracy of `kAXBoundsForRangeParameterizedAttribute` word rects, in: Safari, Mail, Notes, Preview (PDF), Slack, VS Code, Obsidian/Notion (with `AXManualAccessibility`), Firefox, Terminal/iTerm2, and Chrome (does `AXManualAccessibility` work, or is `AXEnhancedUserInterface` required?).
- **AX latency and CPU.** Measure a full visible-range read plus N rect calls per focus/scroll event, from Swift and from PyObjC, on the M3 Air.
- **Side effects of forcing Chrome accessibility.** Window-manager breakage, scroll jank and memory, if the extension route is not used for Chrome.
- **OCR on the fanless Air.**
  - Latency of Vision `.fast` vs `.accurate` on a full window.
  - Sustained CPU %, die temperature and throttling onset under event-driven capture.
  - Battery drain per hour against an idle baseline.
  - Whether the macOS 26 `.accurate` memory growth (~3–15 MB/call) reproduces.
- **Tahoe 26 Screen Recording behavior.** Does the monthly "Allow For One Month" re-prompt still fire for a Developer ID app using ScreenCaptureKit? Does a py2app bundle vs a Swift helper keep its TCC grants across rebuilds?
- **Chrome Local Network Access.** Does an MV3 service-worker `fetch` to `127.0.0.1:11434` trigger the Chrome 142+ LNA prompt? Confirm that native messaging avoids it entirely.
- **Native-messaging round trip.** Time from content-script extraction to Python host to Ollama/MLX to swapped span. Check MV3 service-worker idle termination during long generations.
- **Local model swap quality.** Sense-disambiguation accuracy (the *back → espalda/atrás* class) and inflection/article agreement for the candidate Ollama/MLX models, on a hand-labeled en→es set, plus tokens/sec cost per page.
- **Density and slowdown calibration.** Owner's baseline wpm vs wpm at 1%, 2%, 5% new-token density and ~10–15% total. Find the setting that keeps slowdown ≤10%, the heuristic target, against Broccoli's −18%.
- **Retention check.** A delayed (1–4 week) L2→L1 and L1→L2 recall quiz on swapped words, compared with words drilled in Anki only, to test whether the feature earns its complexity for this learner.
- **Overlay UX.** Alignment drift on scroll and zoom, fullscreen Spaces behavior, Retina scaling, and whether hide-on-scroll is tolerable while reading.
