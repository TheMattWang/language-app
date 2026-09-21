# QA: auxiliary practice modes + GUI

Scope: `drill/speech.py`, `drill/scenario.py`, `drill/export.py`, `drill/cloze.py`,
`drill/app.py`, and the `listen`/`scene`/`sprint`/`add`/`export` CLI subcommands.
Existing pytest coverage for these modules (93 tests across
`tests/test_speech.py`, `test_scenario.py`, `test_cloze.py`, `test_export.py`,
`test_sprint.py`, `test_add.py`, `test_app.py`, `test_app_views.py`) is
thorough and all green — this pass focused on gaps not already exercised by
that suite: real subprocess behavior, real markdown rendering, real TTY
semantics, and multi-cycle GUI state.

Method: fresh temp DBs built via `drill import data/*.jsonl` in the
scratchpad dir; `~/.langapp/drill.db` was never opened. `say` was invoked at
most twice with real audio (`listen --limit 2` piped from `/dev/null`, one
card); every other `say` probe used `-o <file>` to a scratch `.aiff` and all
outputs were deleted. All `tk.Tk()` instances were withdrawn/destroyed and no
process was left running (verified via `ps aux` at the end).

---

## P0

None found. Shell-injection surface in `speech.py` is solid: `subprocess.Popen`/`.run`
are always called with an argv list, `shell=True` is never used, and metacharacters
(`;`, `` ` ``, `$(...)`, quotes, newlines) all land as a single inert argv element —
verified directly against `/usr/bin/say` with `hola; rm -rf /tmp/pwned_test`,
`` `touch ...` ``, `$(touch ...)` etc; no file was created.

## P1

1. **`speech.speak()` silently fails (no audio, no error) for any card text
   starting with `-`.** `say` parses its argv with getopt-style flag matching
   and no `--` separator is used before the text argument, so a leading `-`
   is read as an unknown option and `say` exits nonzero with nothing spoken.
   Reproduced directly against `/usr/bin/say`:
   ```
   $ /usr/bin/say -v Mónica -r 180 -o out.aiff -- "unused"
   $ /usr/bin/say -v Mónica -r 180 -o out.aiff "-1 no soy una bandera"
   say: invalid option -- 1
   Usage: say [-v voice] [-o out] [-f in | message]   # rc=1
   ```
   In `speech.speak()` the non-blocking path (`Popen`, the default used by
   both `cmd_listen` and the GUI's replay button) never checks the child's
   exit status, so this returns `True` ("audio was launched") even though
   nothing plays — the failure is invisible to the caller and to the user.
   No shipped card currently starts with `-` (checked all of
   `data/*.jsonl`), but the module's own docstring calls card text "arbitrary
   user/LLM-authored content," and `drill add` has no rule against a leading
   hyphen, so this is one bad accept-form away from a silently-mute card.
   **Fix:** insert `--` before the text argument in the `args` list built in
   `speech.speak()` (`[SAY_BIN, "-v", v, "-r", str(rate), "--", text]`).

2. **`drill.export.build_markdown` does not escape markdown special
   characters in card content, corrupting the rendered sheet.** `*`, `_`,
   `` ` ``, and `|` from `prompt_en`/`accept`/`note`/`reject` are written
   straight into the markdown with no escaping. Repro (values are real card
   fields, not injected control chars):
   ```python
   card = {"accept": ["*muy* bien"], "note": "uses *asterisks* and _underscores_", ...}
   ```
   Rendered through `markdown` (Python-Markdown 3.10):
   ```
   raw:    ***muy* bien** (2/2 fallos)
           > _uses *asterisks* and _underscores__
   html:   <strong><em>muy</em> bien</strong>
           <em>asterisks</em> and _underscores__      # note: stray literal "_" leaks through, unbalanced
   ```
   The learner's own Spanish answer text ("*muy* bien") is not shown
   literally — the asterisks get consumed as emphasis markers instead of
   appearing on the page, and the note wrapper `_{note}_` breaks entirely
   when the note itself contains an underscore (leaving stray literal `_`
   characters in the output). This is exactly the scenario the probe asked
   about (`*`, `_`, `` ` ``, `|`) and the doc's whole purpose — an accurate,
   readable-on-paper record of what the learner actually got wrong — is
   undermined when the content itself silently reshapes on render.
   **Fix:** escape markdown special chars (`\*`, `_`, `` ` ``, `|`, `[`, `]`)
   in any card-derived string before interpolating into `build_markdown`'s
   output, or wrap card content in a construct that doesn't parse emphasis
   (e.g. backtick-fenced spans, escaping backticks separately).

3. **`drill add --deck` accepts an empty/whitespace string with no
   validation**, unlike `--prompt`/`--accept` which are both checked.
   Repro:
   ```
   $ python3 -m drill --db t.db add --prompt "the elevator" --accept "el ascensor" --deck "" --file mine.jsonl
   -001 added to  (mine.jsonl)
   ```
   This writes `{"id": "-001", "deck": "", ...}` to the deck file and DB.
   Two knock-on effects, both reproduced:
   - The card id itself starts with `-` (`-001`), which is fragile anywhere
     an id is later passed as a bare CLI token (argparse treats a bare
     leading-`-` token as an option first).
   - The GUI deck picker (`app.py::_refresh_deck_choices`) shows a blank,
     unlabeled entry in the dropdown next to `Todas`:
     ```
     deck picker values: ['Todas', '', 'cama', 'casa', 'cloze_grammar', ...]
     ```
     — a confusing, un-clickable-looking blank row a real user would not
     know how to select or explain.
   **Fix:** in `cmd_add`, validate `deck.strip()` is non-empty the same way
   `prompt_en` and `accept` are validated, before computing `prefix`/`card_id`.

4. **`sprint`'s per-round timeout does not drain stdin, so keystrokes typed
   during a timed-out round silently bleed into the next round's answer**,
   corrupting grading against a *different* card. `_read_with_deadline` uses
   `select.select` on a real TTY with no `termios.tcflush`, so partial,
   not-yet-Enter-terminated input sitting in the tty line discipline at the
   moment of timeout is still there for the next call's `readline()`.
   Reproduced with a real pty (not the non-TTY `input()` fallback path):
   ```
   round 1 (1.0s deadline): type "partial_from_round1" with NO newline, let it time out
     -> ROUND1 (None, 1000)                          # correctly reported as timeout
   round 2 (1.0s deadline): type "_finished" + Enter
     -> ROUND2 ('partial_from_round1_finished', 454)  # round 1's leftover keystrokes prepended
   ```
   So the answer to round 1's timed-out card is not cleanly "lost, failed, or
   skipped" as the probe's three options assumed — it's *merged into the
   grading of the following card*, which can produce a false miss (garbled
   concatenation) or, by coincidence, a false accept. `sprint` never writes
   review/sched rows (confirmed, so this can't corrupt SRS state), but it
   silently corrupts the sprint's own displayed score/summary for that
   session. **Fix:** flush pending input on timeout, e.g.
   `termios.tcflush(sys.stdin, termios.TCIFLUSH)` (guarded for non-POSIX /
   non-TTY, matching the existing `sys.stdin.isatty()` branch).

5. **`cloze_grammar` card `cz-028` leaks its own answer in the sentence
   itself.** Rendered question (`cloze.render_question`):
   ```
   "Cuando tenía quince años, ___ mucho miedo a la oscuridad."
   ```
   `accept: ["tenía"]` — but "tenía" already appears, unblanked, earlier in
   the same sentence ("Cuando tenía quince años"), so the gap is answerable
   by literally copying a visible word rather than by knowing that "tenía
   miedo" (not "tuve miedo") is the correct imperfect form — defeating the
   grammar point the card's own `note` ("description of past state →
   imperfect") is trying to test. Found by a word-boundary scan of all 75
   `cloze_grammar` cards' rendered questions against their first accept form
   (only 2 of 75 hit; the other, `cz-075` "Tengo ganas ___ verte este fin de
   semana." / accept `"de"`, is a much weaker case — "de" recurs later only
   inside the fixed collocation "fin de semana" and is graded as a common
   function word, so I'm not flagging it as more than a P2 style note).
   **Fix:** content fix in `data/cloze_grammar.jsonl` — reword `cz-028`'s
   setup clause so the target verb form doesn't also appear outside the gap
   (e.g. "De pequeño, ___ mucho miedo a la oscuridad.").

## P2

- `cmd_listen`/`cmd_sprint` accept `--rate` with no bounds checking (unlike
  `--limit`/`--count`/`--rounds`, which go through `_positive`). `say -r`
  with a pathological value (0, negative) isn't validated before reaching
  the subprocess; low risk since `--rate` is not exposed to arbitrary card
  content, only to a human typing a CLI flag.
- Long card text passed to `speech.speak()` non-blocking (`Popen`, used by
  `cmd_listen` and the GUI replay button) has no size guard and no timeout —
  a ~100KB string took over 30s to synthesize when tested blocking
  (`subprocess.run(..., timeout=30)` correctly aborts and returns `False` in
  that path), but the non-blocking `Popen` path used in practice has no
  timeout at all, so a very long accept-form would leave a real `say`
  process (and real audio) running in the background for a long time with
  no way for the app to cancel it. No shipped card is anywhere near this
  long today.
- `cz-075` weak self-leak noted above (function-word recurrence, not a real
  grammar-defeating leak).

## Verified clean (no issues found)

- **`speech.py` shell safety**: argv-list only, `shell=True` never used;
  confirmed no shell interpretation of `;`, `` ` ``, `$(...)`, quotes, or
  embedded newlines against the real `/usr/bin/say` binary.
- **Peninsular voice detection on this machine**: `say -v '?'` lists
  `Mónica` (es_ES) among other Peninsular voices; `speech.available_voice()`
  correctly picks it (first preference, cached). The "no Peninsular voice
  installed" fallback path (`available_voice() -> None`, `is_available() ->
  False`, `cmd_listen` prints a clear stderr message and exits 1, GUI hides
  the 🔊 button and Ctrl-r binding) is already covered by
  `tests/test_speech.py::test_cmd_listen_exits_nonzero_when_tts_unavailable`
  and reasoned through directly — no crash path found.
- **`say` missing entirely**: `SAY_BIN` is a hardcoded absolute path
  (`/usr/bin/say`), so PATH manipulation is moot by construction; a missing
  binary raises `FileNotFoundError`, caught and converted to `None`/`False`
  everywhere (`available_voice`, `speak`) — never propagates.
- **No indefinite hang**: `speak()` is non-blocking by default (`Popen`,
  fire-and-forget) everywhere it's actually called from `cmd_listen`/GUI;
  the only blocking path (`blocking=True`, unused by any in-scope caller)
  has a 30s `subprocess.run` timeout that correctly fires and returns
  `False` (verified against real `say` with oversized text).
- **`scenario.py`**: all 8 shipped scenarios load and validate (parametrized
  test already does this); malformed JSON lines and missing-field lines are
  collected as errors and skipped, never raise; a turn with an empty
  `accept` or a self-rejecting first accept form is caught by `validate()`.
  Grading inside `cmd_scene` uses the exact same `drill.grader.grade` as
  cards/sprint/listen/GUI (single shared import), so Peninsular
  (`reject`-list) enforcement is identical across every mode — confirmed by
  reading the import graph, not just by inspection of one caller.
  `cmd_scene` writes no review/sched rows (already tested; re-verified).
- **`cloze.py` rendering**: across all 75 `cloze_grammar` cards, the gap
  marker is always present, exactly where authored (no mid-word gaps, none
  missing); `render_filled` correctly fills only the first `___` when a
  sentence author (theoretically) used more than one — none of the shipped
  cards actually have `gap_count >= 2`, and none have the gap at the very
  start or end of the sentence, so `cz-028`/`cz-075` above are the *only*
  leak-shaped issues in the deck.
- **`export.py` on zero-history DB**: `build_markdown` on a totally empty
  temp DB (no cards, no reviews) produces valid, honest markdown ("no hay
  suficiente historial...") with no crash, no fabricated data.
- **`add` → re-import round trip**: `cmd_add` appends one line to the deck
  JSONL and then re-imports the *whole file* via `store.import_jsonl`, which
  is a pure upsert keyed on `card_id` (content-hash short-circuits
  unchanged rows) — re-running `drill import` on the same file later neither
  duplicates nor clobbers the added card. Id generation
  (`<deck[:2].lower()>-NNN`) is scoped per-file-per-prefix, not per-deck, so
  two decks sharing a file and a 2-letter prefix (tested: `casa`/`cama` -> `ca-`)
  still get distinct sequential ids with no collision.
- **GUI multi-exhaustion**: ran 3 consecutive full deck-exhaustion cycles in
  one long-lived `DrillApp` instance (finish deck A+B together, switch to an
  empty deck, import fresh cards into decks C then D, exhaust each,
  switching the picker between every cycle) — the entry widget correctly
  re-appears every time a non-empty queue loads and correctly stays hidden
  on `¡Nada pendiente!`/`¡Hecho!`, across all 3 cycles. The prior
  "vanishes-permanently" bug (comment in `app.py::_show_card`) does not
  regress.
- **GUI keybindings**: with the window actually mapped and focus set
  (a withdrawn/unmapped Tk window does not deliver synthetic key events —
  a test-harness gotcha, not an app bug), `Ctrl-1`..`Ctrl-9` each insert the
  correct one of the 9 `ACCENT_CHARS` in order, `Ctrl-r` calls
  `speech.speak()` with the current card's first accept form, and `Tab`
  toggles the progress view exactly once per press (no double-toggle from
  the entry-level and root-level bindings both firing).

---

Every temp DB/script lived under the scratchpad dir; `~/.langapp/drill.db`
was never opened for write. No `tk.Tk()` instance or `say` subprocess was
left running (checked via `ps aux` after each script). One real `say`
playback occurred (`listen --limit 2` with EOF stdin, one card, default
volume) — outside that, all `say` probes wrote to `-o <scratch>.aiff` and
those files were deleted.
