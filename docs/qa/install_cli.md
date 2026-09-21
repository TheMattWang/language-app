# QA: fresh-install path and full CLI surface

Tested as a first-time user who reads only `README.md` and `docs/RUNBOOK.md`. Method:
repo copied to a scratch dir, `HOME` pointed at a scratch fakehome (no `--db`/env override
exists other than the global `--db` flag), `python3 --version` on this machine is 3.10.10
(matches `requires-python = ">=3.10"`). The real `~/.langapp/drill.db` was never opened —
verified unchanged at the end (mtime `Sep 20 21:09:49 2026`, md5 `10d1127589a56d3e...`,
before == after).

## P1 — huge `--limit`/similar int crashes with a raw traceback (`review`, `export`, `weak`)

```
python3 -m drill review --limit 999999999999999999999
```
Expected: the same clean `argparse` rejection seen for `0`, `-1`, `abc` (all three produce
`drill review: error: argument --limit: --limit must be ... (got ...)`, exit 2). `_positive()`
validates type and sign but not magnitude, so an absurdly large-but-syntactically-valid int
sails through argparse and only fails later, inside SQLite:

```
File ".../drill/store.py", line 381, in due_cards
    rows = conn.execute(query, params).fetchall()
OverflowError: Python int too large to convert to SQLite INTEGER
```
Exit code is 1 (non-zero, so the "every failure exits non-zero" invariant holds), but the
output is a full Python traceback, not a message — the same class of problem the RUNBOOK
implicitly promises not to show a first-time user. Reproduces identically in:
- `drill review --limit <huge>` → `drill/store.py:381` (`due_cards`)
- `drill export --limit <huge>` → `drill/export.py:96` (`_failing_cards`)
- `drill weak --limit <huge>` → `drill/store.py:789` (`hardest_cards`)

`drill listen --limit <huge>` and `drill sprint --count/--rounds <huge>` do **not** crash —
they degrade gracefully (limited by actual card count, or by "no seen cards yet"). Fix:
clamp `_positive()`'s upper bound (e.g. reject anything above the total card count, or a
fixed sane ceiling like 100000) so the same friendly argparse error fires for all three.

## P1 — Ctrl-C during `sprint` produces a raw traceback (not the "stopped." message every other interactive command gives)

`daily`, `review`, `listen`, and `scene` all wrap their interactive loop in
`try: ... except KeyboardInterrupt: print("\n\nstopped.")` (`drill/cli.py` lines ~410, 581,
676). `cmd_sprint` (`drill/cli.py:790-874`) has no such wrapper. Reproduced by sending
SIGINT mid-round after one seen card existed:

```
Traceback (most recent call last):
  ...
  File ".../drill/cli.py", line 836, in cmd_sprint
    answer, elapsed_ms = _read_with_deadline(limit_s)
  File ".../drill/cli.py", line ...
KeyboardInterrupt
```
The child process is killed by the signal itself (not a clean `sys.exit`). Not a data-loss
risk — `sprint` deliberately never writes to the schedule/review tables (confirmed by
inspection and by DB row counts before/after) — but it is the one interactive command where
Ctrl-C looks like a crash instead of "stopped." Fix: wrap the round loop in the same
`except KeyboardInterrupt` pattern as the other four commands.

## P2 — `README.md`/`RUNBOOK.md` card and test counts are stale

Actual card counts in a clean checkout (`wc -l` / JSON-validated, `data/scenarios.jsonl`
excluded as it's not a deck):

| Deck | README claims | Actual |
|---|---|---|
| `travel_production.jsonl` | 100 | 100 |
| `numbers_listening.jsonl` | 85 | 85 |
| `peninsular_contrast.jsonl` | **120** | **115** |
| `cloze_grammar.jsonl` | 75 | 75 |
| `grammar_repair.jsonl` | 80 | 80 |
| **Total** | **460** | **455** |

`python3 -m drill stats` after a clean `import data/*.jsonl` reports **455 new**, not the
460 the README's headline and the RUNBOOK's `daily` pacing math both use. Also,
`README.md`'s `## Layout` claims "**212 tests**"; `pytest --collect-only -q` on this
checkout collects **277**. None of this breaks anything, but the RUNBOOK's "~36 new
cards/day" and "`--new 20` thins ~200 of 460" figures are built on the wrong base (should
be ~35/day off 455, ~195/455 thinned) — worth a find-and-replace pass, and either fixing
`peninsular_contrast.jsonl`'s count or regenerating it to reach 120.

## P2 — `--deck <wrong-case-or-nonexistent>` fails silently on `stats`, `weak`, `export`

`cmd_review`/`cmd_daily`/`cmd_listen` all call `_report_no_cards()`, which — per a comment
in `drill/cli.py:257` referencing an earlier QA fix — detects a bad `--deck` value against a
non-empty DB and prints `No deck named 'X'. Decks in this database: ...`. `cmd_stats`,
`cmd_weak`, and `cmd_export` never call it, so the exact same mistake (a deck name typed in
the wrong case, e.g. `TRAVEL_PRODUCTION` instead of `travel_production` — deck matching is
case-sensitive) silently returns an all-zero table / "0 weak tag(s), 0 missed card(s)" /
"not enough history" instead of saying the name doesn't match. Exit code is 0 in all three
cases (arguably correct for "ran fine, found nothing" but indistinguishable from "you have
genuinely reviewed nothing yet"). Reproduced:
```
python3 -m drill stats --deck TRAVEL_PRODUCTION   # exit 0, all-zero table, no warning
python3 -m drill weak  --deck TRAVEL_PRODUCTION   # exit 0, "not enough history", no warning
python3 -m drill export --deck TRAVEL_PRODUCTION  # exit 0, 0/0/0, no warning
```
Fix: route these three through `_report_no_cards`-equivalent logic too, or at minimum have
`deck_stats`/`export`/`weak` warn when a `--deck` filter matches zero rows in an otherwise
non-empty DB.

## P2 — misleading `N/M correct` line when a session ends via Ctrl-D/EOF before the first card is graded

`_run_review_loop` (`drill/cli.py:359-413`) increments `seen` *before* calling `input()`,
then `break`s on `EOFError` without ever calling `_grade_and_reschedule`. A session where
the very first card hits EOF reports `0/1 correct (0%)` even though zero attempts were
actually graded or written to the `review` table (verified: `review` row count unchanged).
Confusing, not harmful — but "0/1" reads as "you answered and got it wrong," not "you
quit before answering." Same pattern would show `N/(N+1)` for any EOF that lands mid-session.
Minor: only count a card as `seen` once an answer (or explicit timeout, for sprint) was
actually graded.

## Notes / non-findings (probed, confirmed fine)

- **Cold start (P0-priority check): works well.** `python3 -m drill daily` against a
  nonexistent DB (`--db`, or a fresh `$HOME`) auto-imports all five bundled decks and runs
  immediately, exit 0, printing `First run: auto-imported bundled deck(s): ...`. Bootstrap
  resolves the bundled `data/` dir via `Path(__file__).resolve().parent.parent`, not `cwd`,
  so it's correct regardless of invocation directory (confirmed by reading
  `drill/cli.py:202-245`).
- **`--db` override exists** (global flag, must precede the subcommand — `drill --db PATH
  <cmd>`, not `drill <cmd> --db PATH`; the latter exits 2 "unrecognized arguments"). Neither
  README nor RUNBOOK document it, but the task's "say so loudly as P1 if there is no
  override" doesn't apply since one exists. Worth a one-line mention in RUNBOOK for anyone
  who wants to test without touching `~/.langapp/drill.db`, but low priority since the
  target user never needs it.
- No env-var DB override exists (only `--db`).
- **Ctrl-C / progress-saving for `daily`/`review`/`listen`: correct, no data loss.**
  Verified directly: reviewed 2 cards, `review` table had 2 rows; ran `daily`, answered 1
  card, sent SIGINT mid-second-card — process printed `stopped.`, exited 0, and the `review`
  table had exactly 3 rows (the interrupted card was not partially written). Each card is
  graded, scheduled, and `conn.commit()`ed individually inside the loop, so a P0
  "lose the whole session" bug does not exist here.
- **EOF (closed stdin) on all five interactive commands (`daily`, `review`, `listen`,
  `sprint`, `scene`): no raw `EOFError` traceback anywhere.** Every `input()` call in the
  interactive loops is wrapped; `sprint`'s `_read_with_deadline()` additionally falls back
  to a plain `input()` + caught `EOFError` when stdin isn't a TTY, so piping `/dev/null`
  into any of them degrades to "" answers / a clean "stopping." rather than crashing.
- `--no-color`: color is already `sys.stdout.isatty()`-gated, so piped output has zero ANSI
  bytes with or without the flag; `--no-color` is honored both before and after the
  subcommand (verified via `grep -c $'\x1b'` on captured output — 0 in every case).
- `import`: no-args exits 2 (argparse "required: paths"); missing file, a bare directory,
  and a glob matching nothing all exit 1 with a specific message (`missing:` /
  `unreadable:` / problem summary); `data/scenarios.jsonl` is skipped with a clear
  "not a card deck ... skipped" warning and the run still exits 0 when mixed with valid
  files, 1 when it's the *only* thing missing/wrong. The previously-reported "import of a
  missing file exits 0" bug is fixed — confirmed exit 1.
- `--deck` case sensitivity itself isn't a bug (SQLite `TEXT` comparison is case-sensitive
  by design here) — the bug is the silence, covered above.
- Conflicting flags: `scene --list --id sc-001` silently prefers `--list` (lists and exits
  0, `--id` ignored) — no crash, no argparse conflict; low-severity, not flagged as its own
  item since it's the same "silent flag precedence" flavor as the deck-name issue above but
  causes no confusion in practice (the user gets a scenario list, which is a superset of
  useful info).
- Packaging: `pyproject.toml` is valid; `pip install -e .` into a scratch venv succeeded
  cleanly and produced a working `drill` console script (`drill --help` exit 0). No
  `tomllib`/TOML parsing exists anywhere in `drill/`, so the "3.11+ with fallback" concern
  in the probe doesn't apply — the stated `>=3.10` floor is real and this machine's
  3.10.10 satisfies it with no special-casing needed.
- `bin/Drill.command`: executable (`rwxr-xr-x`), and its `cd "$(dirname "$0")/.." ` path
  resolution works correctly when launched from an unrelated cwd (`/private/tmp`) — verified
  it stayed alive (window opened) and left no orphan process after kill.
- `bin/drill-reminder.sh --always`: ran clean, exit 0, no crash with a cold `$HOME`.
- `bin/com.langapp.drill-reminder.plist.template`: `plutil -lint` reports `OK`. (It has no
  `<!DOCTYPE plist ...>` line before `<plist version="1.0">`, which is unusual for a
  hand-written plist, but macOS's own linter accepts it, so not flagged as a bug.)
- `gui`: imports (`from drill import app`) and constructs (`python3 -m drill gui`) without
  error on this machine (has a display); process stayed alive until explicitly killed, no
  output, no orphaned process afterward.

## Command × surface matrix

| Command | Runs (happy path) | `--help` | Bad args (`--limit 0/-1/abc`, etc.) | Exit codes |
|---|---|---|---|---|
| `import` | ✅ exit 0 | ✅ exit 0 | no-args → 2; missing/dir/empty-glob → 1; scenarios.jsonl → 0 (skipped, warned) | correct throughout |
| `daily` | ✅ exit 0, auto-imports on cold DB | ✅ exit 0 | `--new` 0→ok(0), -1→2, abc→2 | correct |
| `review` | ✅ exit 0 | ✅ exit 0 | `--limit` 0/-1/abc → 2 (clean); huge int → **1 with traceback (P1)** | mostly correct, 1 P1 |
| `gui` | ✅ opens, no crash | ✅ exit 0 | n/a (no validated numeric flags besides `--limit`/`--new`, untested for huge since GUI not scriptable) | correct |
| `listen` | ✅ exit 0 (voice present on this machine) | ✅ exit 0 | `--limit` huge → degrades gracefully, no crash | correct |
| `scene` | ✅ exit 0 | ✅ exit 0 | `--id` bad → 1, clean message; `--list`+`--id` → silently prefers `--list` | correct |
| `sprint` | ✅ exit 0 | ✅ exit 0 | `--count`/`--rounds` huge → degrades gracefully | correct on bad args; **SIGINT → traceback (P1)** |
| `add` | ✅ exit 0 (flags), EOF → clean 1 | ✅ exit 0 | n/a | correct |
| `weak` | ✅ exit 0 | ✅ exit 0 | `--limit` huge → **1 with traceback (P1)**; bad `--deck` → silent 0-result (P2) | mostly correct |
| `stats` | ✅ exit 0 | ✅ exit 0 | bad `--deck` → silent 0-result (P2) | correct (exit-code-wise) |
| `export` | ✅ exit 0, writes `docs/MIS_FALLOS.md` | ✅ exit 0 | `--limit` huge → **1 with traceback (P1)**; bad `--deck` → silent 0-result (P2) | mostly correct |

All 11 `--help` invocations render and exit 0. Every deliberate failure path checked
(missing file, bad numeric flag, no-args, bad scenario id) exits non-zero; the only exit-0
paths that arguably shouldn't be are the three silent-`--deck`-mismatch cases (P2), which
are UX confusion, not exit-code bugs.
