# QA Sweep 2 — `drill` CLI + GUI surfaces

All testing done against throwaway DBs under a session scratch directory
(never `~/.langapp/drill.db`). Real DB mtime verified unchanged before/after
(`1789628532` / Sep 17 02:02:12 2026, both ends). `python3 -m pytest` — 239
passed, clean.

## Re-verification of `docs/QA_REPORT.md` findings

| Finding (sweep 1) | Status | Evidence |
|---|---|---|
| `sprint --rounds 0`/negative → `IndexError` traceback (P0) | **FIXED** | Now rejected by the shared `_positive`/`_validate` helper (`drill/cli.py:125-159`, wired as an argparse `type=` at `cli.py:1180`). `sprint --rounds 0` → clean `usage:`+`error: --rounds must be >= 1 (got 0)`, exit 2. |
| `add` EOF at first prompt → `EOFError` traceback (P0) | **FIXED** | `cmd_add` (`cli.py:874-889`) now wraps `_prompt_add_interactive()` in `try/except EOFError`, prints `"\nstopping."`, exit 1. |
| `sprint --count 0` false "no seen cards" (P1) | **FIXED** | `--count 0` now rejected at parse time (exit 2), never reaches the "no seen cards" message path. |
| `--limit 0` on `review`/`daily`/`listen` → false "Nothing due" (P1) | **FIXED** | Same shared validator; `--limit 0` rejected at parse time on all three. |
| `--limit -5` on `review`/`listen` silently unlimited (P1) | **FIXED** | Same validator; any negative `--limit` rejected at parse time, exit 2. |
| `daily --max -5` wrong backlog arithmetic (P1) | **FIXED** | `--max` negative/zero now rejected before reaching the backlog computation. |
| `export --limit -3`/`--min-attempts 0` unbounded (P2) | **FIXED** | Both flags now routed through `_positive`; `--min-attempts 0` and `--limit -3` both rejected, exit 2. |
| `weak --limit -1` drops last tag (P2) | **FIXED** | `--limit` now validated >= 1 at parse time. |
| `sprint --count -3` drops last 3 seen cards (P2) | **FIXED** | `--count` validated >= 1 at parse time. |
| `weak --days -5` future cutoff (P2) | **FIXED** | `--days` validated >= 1 at parse time (`optional=True` only skips when unset). |
| `import` of `data/*.jsonl` throws 8 errors on `scenarios.jsonl` (P2) | **FIXED** | `import data/*.jsonl` now prints one clear line (`data/scenarios.jsonl: not a card deck (looks like a different schema); skipped`), imports exactly **460** cards across the 5 real decks, creates no `smoke` deck. Verified by direct row count and `SELECT deck, COUNT(*) FROM card GROUP BY deck`. |
| `--deck <nonexistent>` reuses "No cards yet" message (P2) | **NOT FIXED** | Still reproduces verbatim on a 460-card DB — see row below. |
| `import` of a missing file returns exit 0 (P2) | **NOT FIXED** | Still reproduces verbatim — see row below. |

**sprint/scene "writes nothing" promise**: re-verified via exact before/after
row-content diff (not just row counts) on both `review` and `sched` tables,
across a real multi-round `sprint` run (including a seen-card DB so it
actually executes rounds, not just an early "no seen cards" exit) and a
multi-turn `scene` run. Diff count: **0** in every case. (An earlier
`hash()`-based comparison attempt produced a false positive — Python
randomizes string `hash()` per-process by default, so two separate `python3
-c` invocations hash identical content differently. Not a product defect;
noted here so the methodology mistake isn't repeated.)

## New defects found

| Surface | Input | Expected | Actual | Severity |
|---|---|---|---|---|
| `review`/`daily`/`listen`/`scene`/`sprint`/`add`/`weak`/`stats`/`export` | stdout piped (non-TTY), or `--no-color` passed | No ANSI escape bytes reach stdout | The "Ctrl-C to stop" / `[N/M]` / deck-stats / hint / summary lines are built from the raw `DIM`/`BOLD`/`RESET` string constants (`\033[2m`/`\033[0m`) interpolated directly into f-strings, bypassing the `c()` colour-gate that checks `sys.stdout.isatty() and not args.no_color`. Every command still emits literal `ESC[2m...ESC[0m` around most of its output even non-interactively and even with `--no-color`. Additionally `stats`, `weak`, `export`, `add`, `import` don't accept `--no-color` at all (`unrecognized arguments: --no-color`, exit 2) — there's no way to suppress color on those five commands short of stripping ANSI yourself. | **P1** |
| | Repro: `python3 -m drill --db /tmp/x.db daily --no-color < /dev/null \| cat -v` — shows `^[[2mCtrl-C to stop; progress is saved.^[[0m` despite `--no-color`. Also `python3 -m drill --db /tmp/x.db stats --no-color` → `error: unrecognized arguments: --no-color`. | | | |
| GUI `DrillApp` | Finish the queue (`_finish()`) or hit an empty deck (`_show_empty()`) — both call `self.entry.pack_forget()` — then switch the deck picker to a deck that has due cards | The answer entry box reappears so the new card is answerable | `_show_card()` (`drill/app.py:272-299`) never calls `self.entry.pack(...)`; it only calls `.delete()`/`.config()`/`.focus_set()` on the entry. Once the entry has been unpacked, it stays unpacked (`winfo_manager()` returns `''`) even after a fresh, non-empty queue loads and a card is displayed — the user sees the prompt but has no visible input field. Only a full app restart recovers it. | **P1** |
| | Repro (headless, mirrors `tests/test_app.py`'s `root.withdraw()` pattern): create deck `alpha` (1 card) + deck `beta` (1 card); open on `alpha`; answer + advance to trigger `_finish()`; `app.deck_picker.set("beta"); app._on_deck_change()`; assert `app.entry.winfo_manager() == "pack"` — fails, returns `""`. | | | |
| `review`/`daily`/`listen` | `--deck nope_deck` on a 460-card DB (deck just doesn't exist / has 0 cards) | A message that distinguishes "empty DB" from "this deck has nothing" | Still prints `"No cards yet. Import a deck first: python -m drill import data/<deck>.jsonl"` — misleading on a DB with 460 cards in 5 other decks. Unchanged from sweep 1; not part of the "fixed" set despite the report title implying prior findings were resolved. | **P2 (carried over, unfixed)** |
| | Repro: `python3 -m drill --db /tmp/seeded.db review --deck nope_deck` | | | |
| `import` | A missing path among the args | Nonzero exit so a script can detect the failure | Still prints `missing: <path>` + lists it under `problem(s)` to stderr but `cmd_import` (`cli.py:214-243`) unconditionally `return 0`s. Unchanged from sweep 1. | **P2 (carried over, unfixed)** |
| | Repro: `python3 -m drill --db /tmp/x.db import data/does_not_exist.jsonl; echo $?` → prints the error, exit `0`. | | | |

### Minimal pytest bodies for the two new confirmed defects

```python
# tests/test_cli.py (or similar) -- ANSI leaks past --no-color / non-TTY
def test_daily_no_color_emits_no_ansi(tmp_path, monkeypatch):
    import io, subprocess, sys
    db = tmp_path / "x.db"
    out = subprocess.run(
        [sys.executable, "-m", "drill", "--db", str(db), "daily", "--no-color"],
        input="", capture_output=True, text=True,
    )
    assert "\x1b[" not in out.stdout, out.stdout
```

```python
# tests/test_app.py -- entry never re-packed after finish + deck switch
def test_entry_repacks_after_finish_and_deck_switch(tmp_path):
    import json, tkinter as tk
    from drill import store
    from drill.app import DrillApp

    for name, word in (("alpha", "hola"), ("beta", "adios")):
        deck = tmp_path / f"{name}.jsonl"
        deck.write_text(json.dumps({
            "id": f"{name}1", "deck": name, "kind": "production",
            "prompt_en": name, "accept": [word], "reject": [], "note": None, "tags": [],
        }))
        conn = store.connect(tmp_path / "t.db")
        store.import_jsonl(conn, deck)
        conn.close()

    root = tk.Tk()
    root.withdraw()
    app = DrillApp(root, tmp_path / "t.db", deck="alpha", limit=10)
    app.entry.insert(0, "hola")
    app._on_enter()  # submit
    app._on_enter()  # advance -> _finish(), pack_forget()
    app._refresh_deck_choices()
    app.deck_picker.set("beta")
    app._on_deck_change()
    assert len(app.queue) == 1
    assert app.entry.winfo_manager() == "pack", "entry stayed hidden after switching to a populated deck"
    app.close()
    root.destroy()
```

## Other surfaces exercised, no new defects

- Every command x {no args, `--help`, `--bogus-flag`}: all clean `usage:`/`error:` on stderr, exit 2, no tracebacks (`import`, `daily`, `review`, `stats`, `weak`, `listen`, `scene`, `sprint`, `add`, `export`, `gui`).
- First-run bootstrap on a totally empty DB: auto-imports the 5 bundled decks (460 cards), starts `daily` immediately, no manual `import` step needed.
- `scene --id nope-999`, `scene --file <missing>`: clean one-line errors, exit 1, no traceback.
- `speech.py` (`drill/speech.py`): confirmed `subprocess.Popen`/`subprocess.run` always called with an argument list (`[SAY_BIN, "-v", v, "-r", str(rate), text]`), never `shell=True`. Shell-metacharacter answers (`; rm -rf /`, backticks, `$(id)`) pass straight through as literal `argv[4]` text to `say` — never shell-interpreted.
- GUI: Ctrl-1..9 accent insertion works and returns focus to the entry (`_insert`); Tab toggling mid-feedback (`awaiting_next=True`) switches drill/progress views without crashing or losing feedback state; constructed cleanly against both a populated and an empty DB, matching sweep 1.
- `--limit`/`--count`/`--rounds`/`--max`/`--days`/`--min-attempts` abc (non-numeric): clean argparse type error, exit 2 (unchanged, still correct).

## Summary

**4 defects found this sweep: 0 P0, 2 P1, 2 P2** (both P2s are sweep-1
findings that were reported as part of the fix set but remain unfixed in
source — flagged explicitly above so they aren't silently dropped).

10 of the 12 sweep-1 defects (both P0s and all P1/P2 negative-number rows,
plus the `import data/*.jsonl` happy-path row) are confirmed fixed by
direct repro. The `sprint`/`scene` no-write promise was independently
re-verified via full row-content diffs, not just counts.
