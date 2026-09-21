# QA: `drill/store.py` — persistence, durability, data-loss

Scope: import idempotency/mutation, `backup_db`, `daily_queue`/`due_cards`/
`suggested_new_per_day`/`_interleave_decks` boundaries, concurrency, schema
integrity, corruption resilience. All probes run against throwaway temp DBs
created by the probe scripts themselves; `~/.langapp/drill.db` was never
touched. Repro scripts referenced below live in the scratchpad
(`qa/probe1_import.py` .. `qa/probe6_migration.py`) and are plain, runnable
`python3 <script>.py` files (no pytest dependency).

Today's date for boundary tests: 2026-09-20. `DEFAULT_HORIZON` (departure)
is 2026-10-03 (`drill/scheduler.py:55`).

---

## P0

### P0-1 — `busy_timeout=5000` does not prevent concurrent-import failures; the documented mitigation does not hold under the exact scenario it names

**Where:** `drill/store.py:108-118` (`connect`, sets `PRAGMA busy_timeout = 5000`
specifically so that "the loser of a race fails instantly and its whole
import is dropped" doesn't happen — comment at line 110-113) and
`drill/store.py:274-357` (`import_jsonl`, uses a plain `conn.execute("BEGIN")`
— a *deferred* transaction — then does a per-row `SELECT` (existing-row
check) immediately followed by `INSERT`/`UPDATE` inside that same
transaction).

**Observed vs expected:** Expected: two processes importing at the same
moment either serialize (one waits up to 5s for the other, per the
busy_timeout comment) or both succeed. Observed: when two processes call
`import_jsonl` on the same DB at (near-)the same instant, one process's
import fails **immediately** (~1ms, not after waiting near 5000ms) with
`sqlite3.OperationalError: database is locked`, and that exception is
**uncaught** — it propagates out of `import_jsonl` to the caller (the
`except: conn.rollback(); raise` block only rolls back and re-raises). In a
head-to-head repro replicating the exact read-then-write shape import_jsonl
uses, plain `BEGIN` produced a losing writer in **4 of 5 trials**, each
failing in under 2ms — nowhere near the 5-second budget the pragma is
supposed to provide.

**Root cause:** `BEGIN` (deferred) does not take a lock until the first
statement executes, and that first statement here is a `SELECT` — which
pins a read *snapshot* for the whole transaction, in WAL mode, right at
that point. If the other process fully commits its write before this
process's first `INSERT` fires, this process's write is not a simple lock
conflict (`SQLITE_BUSY`, which busy_timeout retries) but a snapshot
conflict (`SQLITE_BUSY_SNAPSHOT`) — retrying the same statement on a stale
snapshot can never succeed, so SQLite (and busy_timeout's retry loop) give
up effectively instantly. Swapping to `conn.execute("BEGIN IMMEDIATE")`
(acquires the write lock *before* any read, so no stale snapshot is ever
pinned) fixed it: **5/5** trials succeeded in the same repro, both writers
completing in ~2ms with no error.

**Why P0 and not P1:** the module's own comment explicitly names this
scenario as expected in production ("the desktop app holds a connection
open while the user runs a command in a terminal") and states the pragma
exists specifically to protect it. It does not. The failure is an unhandled
crash, not silent corruption — `import_jsonl`'s own transaction rolls back
cleanly, so no partial/half-written state and no corruption of existing
review history results from this specific bug — but a user running a
desktop app + CLI import concurrently (the documented use case) will see
the losing side's import crash with a raw traceback essentially every time
there's real overlap, which reads to a user as "the tool broke" on the one
asset they can't regenerate. This was flagged as an open item never
verified; verified here as broken.

**Repro:** `qa/probe4_concurrency.py` (via `store.import_jsonl`, real
multiprocessing) and `qa/probe4b_concurrency_rootcause.py` +
`qa/probe4c_confirm_fix.py` (isolate root cause, confirm `BEGIN IMMEDIATE`
fixes it, 5/5 vs 1/5 trials).

**Suggested fix:** `conn.execute("BEGIN IMMEDIATE")` instead of
`conn.execute("BEGIN")` at `store.py:274`.

---

## P1

### P1-1 — `backup_db(keep=0)` deletes the backup it just made and returns a path to a file that no longer exists

**Where:** `drill/store.py:193-231`, specifically the prune step
(`backups[keep:]`) run *after* the fresh snapshot is written and *before*
the function returns `dest_path`.

**Observed vs expected:** Expected: `backup_db` either protects the
just-made snapshot from its own prune, or documents that `keep=0` means "no
backups." Observed: with `keep=0`, the glob picks up the just-created
backup along with everything else, `backups[0:]` prunes *all* of them
(including the one just made), and the function still returns `dest_path`
pointing at a file that was deleted a few lines earlier —
`dest_path.exists()` is `False`. A caller that checks "did backup_db return
non-None, so I have a safety net" is wrong to assume so at `keep=0`.
`keep=5` (the actual default) is unaffected — only explicit `keep=0` calls
hit this.

**Repro:** `qa/probe2_backup.py`, TEST 3.

**Suggested fix:** prune `backups[keep:]` **excluding** `dest_path`, or special-case `keep <= 0` to skip deleting the just-made file.

### P1-2 — First-line schema mismatch aborts the *entire* import, silently dropping every valid card in the file, with a misleading error message

**Where:** `drill/store.py:239-254`, the pre-scan loop that inspects only
the first non-blank line and, if it parses as a dict missing any of
`deck`/`kind`/`accept`, returns immediately with
`errors=("not a card deck (looks like a different schema); skipped",)` —
without ever opening the transaction or looking at any other line.

**Observed vs expected:** A file whose first card has one missing/typo'd
field (e.g., a `kind` field dropped by a hand-edit) but whose remaining N-1
cards are perfectly valid gets **zero cards imported**, with a message that
says "looks like a different schema" — which is misleading when it is, in
fact, a card deck with one bad line. Contrast: the identical malformed line
in **any other position** in the file is handled per-line — that one line
is skipped, added to `errors`, and every other valid line still imports
(confirmed: `pc-001`/`pc-002` both land, `errors=("line 2: 'kind'",))`).
This inconsistency (position-1 = abort-everything-with-wrong-message,
position-N = skip-just-that-line) is surprising and easy to misdiagnose as
"cards are missing from the DB" when actually the whole file was rejected.

**Repro:** `qa/probe1_import.py`, TEST A vs TEST A2.

**Suggested fix:** either drop the special first-line heuristic and rely
purely on the per-line error path (consistent with the rest of the
function), or, if the "wrong file entirely" guard is wanted, check that
*most/any* lines are missing the required keys rather than only line 1.

### P1-3 — Non-UTF-8 bytes crash `import_jsonl` with an uncaught `UnicodeDecodeError`; every other malformed-input case is caught and reported via `ImportResult.errors`

**Where:** `drill/store.py:236-237` —
`lines = path.read_text(encoding="utf-8").splitlines()` runs before the
try/except that handles per-line JSON errors, and is not itself guarded.

**Observed vs expected:** Expected (based on how every other malformed-input
case in this function behaves — bad JSON, missing fields, empty accept
list, wrong kind): a bad file produces an `ImportResult` with an entry in
`.errors`, and the caller (CLI/GUI) gets a value it can display. Observed:
a file containing any byte sequence invalid as UTF-8 raises
`UnicodeDecodeError` straight out of `import_jsonl`, uncaught. Whether this
surfaces as a raw traceback depends entirely on whether callers wrap
`import_jsonl` in their own try/except — worth confirming in `cli.py`/`app.py`,
but at minimum it's an inconsistency in this module's own error contract.

**Repro:** `qa/probe1_import.py`, TEST E.

**Suggested fix:** decode with `errors="replace"` or catch
`UnicodeDecodeError` and return it as a single-entry `ImportResult.errors`,
consistent with the rest of the function's contract.

### P1-4 — No schema-migration path: `CREATE TABLE IF NOT EXISTS` cannot add a column to an existing DB; a future schema change crashes on the user's only DB with no upgrade

**Where:** `drill/store.py:101-119` (`connect`) `executescript`s
`schema.sql` unconditionally; `drill/schema.sql` uses `CREATE TABLE IF NOT
EXISTS` for all three tables, which is a silent no-op against a table that
already exists, columns included.

**Observed vs expected:** Simulated an "older" `card` table lacking the
`tags_json` column, then called `store.connect()` (as any code path would
on startup) and `store.get_card()`. `connect()` succeeds silently (no
warning that the on-disk schema doesn't match what the code expects);
`get_card()` then fails with an unhandled `IndexError: No item with that
key` the first time it touches the missing column. Nothing in `store.py`
detects a schema-version mismatch or attempts a migration (`ALTER TABLE`,
version pragma, etc.).

**Why this matters for durability specifically:** there is exactly one copy
of the user's review history at `~/.langapp/drill.db`. Today's `schema.sql`
happens to match what's on disk for existing users, so this is currently
latent, not active — but the very next schema change (a new column on
`card`, `sched`, or `review`) will crash every existing install on first
use post-update, with no automated path back to a working state short of
manually editing the DB or restoring from a `backup_db` snapshot (which
itself won't exist unless the user had already triggered an import with
`has_reviews=True` prior to the update).

**Repro:** `qa/probe6_migration.py`.

**Suggested fix:** add a `PRAGMA user_version` (or a `meta` table) check in
`connect()` and an explicit migration step (even a minimal
`ALTER TABLE ... ADD COLUMN` runner) before relying on
`executescript`-as-migration.

---

## P2

- **`_content_hash` covers `deck`/`kind`/`tags`/`note`/`accept`/`reject`/`prompt_en`, so editing any of those and re-importing correctly lands as an `updated` row with `sched` (reps/ease/interval_days/lapses/due_at/last_reviewed_at) fully preserved.** Verified for `accept` edits directly (`tests/test_store.py::test_edit_accept_updates_card_but_preserves_sched`, existing) and confirmed by code inspection that the `UPDATE card SET ...` branch (`store.py:338-353`) never touches the `sched` table. No repro needed beyond the existing test.
- **Changing a card's `id` orphans the old `card`/`sched`/`review` rows rather than losing them.** The old id's rows are never deleted (nothing in `store.py` issues `DELETE FROM card`) and its review history remains queryable by the old id — but it also becomes permanently invisible/unreachable from normal usage once the id is gone from the JSONL source, with no purge mechanism. Not data loss, but unbounded orphan accumulation with no cleanup path. Repro: `qa/probe1_import.py`, TEST B.
- **Duplicate ids within one import file silently resolve "last line wins"** — no error, no warning, `ImportResult.errors` stays empty. Low risk (deck-authoring mistake, not corruption) but worth a lint check upstream in whatever authors decks. Repro: `qa/probe1_import.py`, TEST C.
- **A UTF-8 BOM at the start of a file reliably fails to parse the first line** (`json.loads` raises "Unexpected UTF-8 BOM"), reported correctly via `errors`, rest of the file imports fine. Recoverable (re-export without BOM), just a rough edge. Repro: `qa/probe1_import.py`, TEST D.
- **CRLF line endings, empty files, and blank-lines-only files all behave correctly** (`splitlines()` handles CRLF; empty/blank files import as a clean no-op with `added=updated=unchanged=0` and no error). Repro: `qa/probe1_import.py`, TESTs F/G.
- **`backup_db` produces a genuinely restorable snapshot** — review rows verified intact after restore via the SQLite online backup API — and correctly **never touches the live DB filename** (prune pattern is `{name}.bak.*`, which can't match the live file) and, for `keep>=1`, never deletes the newest backup (pruning is `backups[keep:]` on a descending-sorted list). Concurrency: confirmed the backup API correctly isolates from an in-flight *uncommitted* writer transaction on another connection (backup sees only the last-committed state, not the writer's in-progress uncommitted update) — this part of the durability story is solid. `backup_db` under an unwritable target directory correctly swallows the exception and returns `None` rather than raising. Repros: `qa/probe2_backup.py`, TESTs 1/2/4/5.
- **`daily_queue`'s new-card cap is correctly GLOBAL, not per-deck** — the previously-fixed bug stays fixed: `daily_queue` always calls `new_cards_introduced_today(conn, now)` with no `deck` argument (`store.py:544`), so switching the `deck` filter between calls on the same day does not grant a second allowance. Verified directly: spending a 5-card/day budget on `deck=travel_production` leaves `new_introduced=0` on a subsequent same-day call with `deck=grammar_repair`. Repro: `qa/probe3_queue.py`, TEST 3.
- **Boundary conditions (zero cards, `new_per_day=0`, `max_cards=0`, deck filter matching nothing, horizon already passed, a `now` after departure) all degrade gracefully** — no exceptions, no negative counts, sane defaults (e.g. `suggested_new_per_day` clamps to a flat 15/day once the horizon has passed, regardless of how many cards remain — by design per the docstring, but worth knowing that with a very large remaining backlog past departure the flat value will never catch up; this is a policy choice, not a bug). Timezone-shifted `now` (`America/Los_Angeles` vs UTC) produced identical `due_cards` results as expected, since `_iso()` normalizes every datetime to UTC before comparison. Repros: `qa/probe3_queue.py`, TESTs 1/2/4/5.
- **DST-adjacent day-boundary effect on `new_cards_introduced_today`:** because "today" is defined as the *UTC* calendar day (`store.py:485`, `now.astimezone(timezone.utc).replace(hour=0,...)`), a non-UTC user whose local evening straddles UTC midnight can have the new-card budget reset mid-evening — i.e., two review sessions an hour apart, both "today" from the user's local perspective, can land on different UTC days and each get a fresh `new_per_day` allowance. This is a variant of the same root issue the global-cap fix addressed (the cap resetting when it shouldn't), just via wall-clock/UTC-day boundary instead of deck-filter — worth a deliberate decision (localize the day boundary, or explicitly document UTC-day semantics) rather than leaving it implicit. Not verified as *currently* triggering in this repro (test showed no reset across a 1-hour PT gap that did cross UTC midnight, because the UTC boundary crossed was still within the same query's day window in this particular clock setup — re-run with a `now` closer to the actual UTC-midnight crossing to force it) — flagged for awareness rather than confirmed broken. Repro scaffold: `qa/probe3_queue.py`, TEST 6.
- **`PRAGMA foreign_keys` is set on every `connect()` call** (verified fresh on two separate connections to the same file), so every code path that goes through `store.connect()` (confirmed to be *all* current callers via `grep` across `drill/*.py`) is protected. A raw `sqlite3.connect()` to the same file (bypassing `store.connect()`) does **not** get `foreign_keys=ON` by SQLite's own default — purely informational since nothing in this codebase does that today, but it's the sharp edge to watch if a script/migration ever opens the DB directly. `ON DELETE CASCADE` from `card` to `sched`/`review` does work correctly when foreign keys are enabled — deleting a card row correctly (and silently) cascades away all of that card's review history. Nothing in `store.py` currently issues `DELETE FROM card` (confirmed via grep), so this is latent, but it's a loaded gun for any future "remove a card" feature: enabling the cascade means a card delete is a review-history delete with no confirmation step at the SQL layer. Repros: `qa/probe5_schema_corruption.py`, TESTs 1-4.
- **Corruption resilience is solid where it can be:** a zero-byte DB file is treated as a fresh empty DB (correct SQLite behavior); a garbage-bytes file, a truncated (half-written) valid DB, and a directory where the DB file should be all fail **loudly** with a clear `sqlite3.DatabaseError`/`OperationalError` at `connect()` time rather than silently wiping or reinitializing — good, no silent-data-loss path found here. Repro: `qa/probe5_schema_corruption.py`, TEST 5.

---

## Scripts

All probes are standalone (`python3 <path>`), no pytest needed, and never
touch `~/.langapp/drill.db`:

- `qa/probe1_import.py` — import idempotency, first-line-abort vs per-line-skip, id-rename orphaning, duplicate ids, BOM, non-UTF8, CRLF, empty/blank files, 5x reimport idempotency.
- `qa/probe2_backup.py` — backup/restore round-trip, `keep` pruning correctness, `keep=0` self-deletion bug, unwritable target dir, backup isolation from an uncommitted concurrent writer.
- `qa/probe3_queue.py` — `daily_queue`/`due_cards`/`suggested_new_per_day` boundaries, global-vs-per-deck cap verification, horizon-passed/after-departure, timezone-shifted `now`, DST-adjacent day-boundary scaffold.
- `qa/probe4_concurrency.py` — real multiprocess concurrent imports (same DB, different/same decks), reader-during-writer-transaction hammering.
- `qa/probe4b_concurrency_rootcause.py` / `qa/probe4c_confirm_fix.py` — isolate and confirm the `BEGIN` vs `BEGIN IMMEDIATE` root cause behind P0-1.
- `qa/probe5_schema_corruption.py` — `foreign_keys` per-connection, cascade delete, orphan-row-if-FK-off, zero-byte/garbage/truncated/directory corruption cases.
- `qa/probe6_migration.py` — older-schema DB (missing column) crash-on-use demonstration.
