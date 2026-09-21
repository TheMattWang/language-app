# QA Report — `drill` CLI

All testing was done against throwaway DB copies (`cp ~/.langapp/drill.db /tmp/qa.db`,
plus `/tmp/empty.db`, `/tmp/reallyempty.db`, `/tmp/alldone.db`), never the real
database. `sprint` and `scene` were verified not to write to `review`/`sched`
(row-count + full-table hash snapshot before/after both runs were identical).
The existing `pytest` suite (212 tests) passes clean and confirms the grader
never rejects correct Peninsular/vosotros Spanish on the shipped decks — no
independent false-reject was found either, so there is no P0 on that axis.

## Defects

| Command | Input | Expected | Actual | Severity |
|---|---|---|---|---|
| `sprint` | `--rounds 0` or negative | Reject the flag, or a clean no-op message | Uncaught `IndexError: list index out of range` traceback, exit 1, after printing a partial "Summary" table | **P0** |
| | Repro: `python3 -m drill --db /tmp/qa.db sprint --rounds 0` | | | |
| `add` (interactive) | Ctrl-D / EOF at the first prompt (or any prompt) | Same graceful "stopping." handling as `review`/`daily`/`listen`/`scene` | Uncaught `EOFError: EOF when reading a line` traceback, exit 1. `_prompt_add_interactive` in `drill/cli.py` never catches `EOFError`, unlike every other interactive loop | **P0** |
| | Repro: `printf '' \| python3 -m drill --db /tmp/qa.db add` | | | |
| `sprint` | `--count 0` on a DB with 8+ already-seen cards | A message reflecting that 0 cards were requested, or just an empty/no-op sprint | `"No seen cards yet to sprint on. ... run drill review or drill daily first"` — false; seen cards exist, `--count 0` just sliced them to nothing | **P1** |
| | Repro: `python3 -m drill --db /tmp/qa.db sprint --count 0` (after some review history) | | | |
| `review` / `daily` / `listen` | `--limit 0` on a DB with cards due | A message indicating N cards are due but 0 were requested/shown | `review --limit 0`: `"Nothing due. ¡Vale!"` — false, 466 cards were due; the flag just capped the SQL `LIMIT` to 0 | **P1** |
| | Repro: `python3 -m drill --db /tmp/qa.db review --limit 0` | | | |
| `review` / `listen` | `--limit -5` (or any negative) with cards due | Rejected as invalid, or clamped to 0 | Returns **every** due card — SQLite treats `LIMIT -5` as "no limit," so a negative limit silently means unlimited instead of erroring | **P1** |
| | Repro: `printf '' \| python3 -m drill --db /tmp/qa.db review --limit -5` | | | |
| `export` | `--limit -3` with 14+ missed cards, `--min-attempts 0` | Rejected, or clamped/treated like 0 | Same `LIMIT`-goes-negative-means-unlimited behavior; shows all 14 rather than capping | **P2** |
| | Repro: `python3 -m drill --db /tmp/qa.db export --out /tmp/x.md --limit -3 --min-attempts 0` | | | |
| `weak` | `--limit -1` | Rejected, or clamped to 0 | Silently drops the *last* eligible tag (Python `list[:-1]` slicing) instead of erroring — confusing, not what "-1" means to a user | **P2** |
| | Repro: `python3 -m drill --db /tmp/qa.db weak --limit -1` | | | |
| `sprint` | `--count -3` | Rejected, or clamped to 0 | Silently drops the last 3 seen cards (`ordered[:-3]`) rather than treating -3 as invalid | **P2** |
| | Repro: `python3 -m drill --db /tmp/qa.db sprint --count -3` | | | |
| `daily` | `--max -5` | Rejected, or clamped to 0 | Runs a live review session; reports `"19 in backlog"` computed as `due_reviews - (-5)`, i.e. adds 5 instead of subtracting — backlog count is arithmetically wrong (should read ~5 skipped, not 19) | **P1** |
| | Repro: `printf '' \| python3 -m drill --db /tmp/qa.db daily --max -5` | | | |
| `weak` | `--days -5` | Rejected, or treated as 0/unlimited with an honest label | Label prints `"last -5d"` and the cutoff becomes 5 days in the **future** (`now - timedelta(days=-5)`), so it silently filters out all real review history and reports "not enough history" even though history exists | **P2** |
| | Repro: `python3 -m drill --db /tmp/qa.db weak --days -5` | | | |
| `review` / `daily` / `listen` | `--deck <nonexistent>` on a DB that has cards (just none in that deck) | A message distinguishing "this deck doesn't exist / has no cards" from "the database is empty" | All three print `"No cards yet. Import a deck first: python -m drill import data/<deck>.jsonl"` — misleading when the DB has hundreds of cards in *other* decks; reads as "you haven't imported anything" | **P2** |
| | Repro: `python3 -m drill --db /tmp/qa.db review --deck nope_deck` | | | |
| `import` | A nonexistent path among the args (e.g. `data/does_not_exist.jsonl`) | Nonzero exit code so a caller/script can detect the failed import | Prints `missing: <path>` and lists it under "problem(s)" to stderr, but still returns exit code 0 | **P2** |
| | Repro: `python3 -m drill --db /tmp/qa.db import data/does_not_exist.jsonl` | | | |
| `import` | The README's own documented boring path: `python3 -m drill import data/*.jsonl` | Clean import, since this is the exact command the README tells a new user to run | Emits 8 errors (`line N: 'deck'`) because `data/scenarios.jsonl` matches the glob but uses a different schema (no `deck` field) that `import` doesn't understand — the documented "happy path" is not actually clean | **P2** |
| | Repro: `python3 -m drill --db /tmp/qa.db import data/*.jsonl` | | | |

## Clean

- `import`: re-importing the same deck twice is correctly idempotent (`+0 new, N unchanged`); duplicate ids within a single file resolve last-line-wins with no crash; missing `--file`-style bad paths handled without traceback.
- `stats`, `weak`, `listen`, `review`, `daily` all handle a completely empty DB and a DB where every card is not-yet-due ("all done for today") cleanly — correct counts, no crashes, no misleading "nothing due" claims in that specific scenario.
- `scene --list`, `scene --id <bad>`, `scene --file <missing>` all fail cleanly with a sensible message and exit 1.
- `sprint` and `scene` genuinely never touch `review`/`sched` — verified by hashing both tables before/after a full run of each with mixed right/wrong/EOF answers.
- The grader/CLI/GUI (`DrillApp` via direct widget calls, window withdrawn) never crash on empty, whitespace-only, 5000-char, emoji, or shell-metacharacter (`; rm -rf /`, `` `id` ``, `$(id)`) input — all are safely graded as non-matches (or L0_empty) and never shelled out.
- `add`'s self-rejection guard (accept form that's also banned by its own reject list) correctly blocks the card from being saved, with a clear reproduction of which reject entry is at fault.
- vosotros/register enforcement spot-checked directly (`tenéis` vs `tienen`, accent-folded `teneis`, case-folded `Tenéis`, full-sentence forms) — all graded correctly; no false "your correct Spanish is wrong."
- `argparse` type validation (`--limit abc`) fails cleanly with exit 2, no traceback.
- GUI (`DrillApp`) constructs cleanly against both a populated and a totally empty DB.

## Summary

**13 defects found: 2 P0, 4 P1, 7 P2.**

- P0 (2): `sprint --rounds 0`/negative crashes with `IndexError`; `add` (interactive) crashes with `EOFError` on Ctrl-D at any prompt.
- P1 (4): `sprint --count 0` claims no seen cards exist when they do; `--limit 0` on `review`/`daily`/`listen` claims "Nothing due" when cards are due; `--limit -5` on `review`/`listen` silently returns every due card instead of erroring; `daily --max -5` reports an arithmetically wrong backlog count.
- P2 (7): negative `--limit` on `export` returns unbounded results; negative `--limit` on `weak` silently drops the last eligible tag; negative `--count` on `sprint` silently drops the last N seen cards; negative `--days` on `weak` produces a future cutoff and a nonsensical `"last -5d"` label; a nonexistent `--deck` on `review`/`daily`/`listen` reuses the "No cards yet, import a deck" message even when the DB has hundreds of cards in other decks; `import` of a missing file returns exit code 0 despite reporting an error; the README's own documented `drill import data/*.jsonl` throws 8 errors because it picks up `scenarios.jsonl`, which uses an incompatible schema.

**Top three to fix first:**
1. `sprint --rounds 0`/negative crashing with an uncaught `IndexError` (P0) — trivial bad input, immediate traceback.
2. `add` (interactive) crashing on Ctrl-D/EOF at any prompt (P0) — every other interactive command in this tool handles this gracefully; `add` is the one path that doesn't, and it's a normal terminal interaction, not an edge case.
3. The negative/zero `--limit`/`--count`/`--max`/`--days` family across `review`, `daily`, `listen`, `sprint`, `weak`, `export` (collectively P1/P2) — one shared validation helper (reject or clamp negatives before they reach SQL `LIMIT` or Python slicing) would fix ~7 of the 13 rows at once, including the two P1 "false claim" messages (`--limit 0` → "Nothing due" when cards exist; `sprint --count 0` → "No seen cards yet" when they do).
