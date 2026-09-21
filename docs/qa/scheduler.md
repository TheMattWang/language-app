# Scheduler / pacing / data-integrity QA

Scope: `drill/scheduler.py` (pure SM-2 + horizon clamp) and the scheduling-relevant
parts of `drill/store.py` (`daily_queue`, `new_cards_introduced_today`,
`suggested_new_per_day`, `_interleave_decks`, `backup_db`, `import_jsonl`,
`save_sched`, `record_review`). All repros run against throwaway SQLite DBs
under `tmp_path` / the OS temp dir — `~/.langapp/drill.db` was never touched.

Everything below was exercised directly (not just read) against the real
460-card deck set in `data/*.jsonl` (100+85+120+75+80 = 460, matching the
idempotency target in the task) plus targeted unit-level repros against
`drill.scheduler` and `drill.store` in isolation.

## Summary

| Severity | Count |
|---|---|
| P0 | 2 |
| P1 | 0 |
| P2 | 2 |
| No defect (verified correct) | 11 |

Worst three: (1) the horizon clamp's own last-resort fallback can schedule a
card **after** the horizon it exists to enforce, when less than ~60s of
runway remains before `DEFAULT_HORIZON`; (2) two connections importing
concurrently crash with `sqlite3.OperationalError: database is locked` and
silently drop the entire second import — SQLite is in WAL mode but no
`busy_timeout` is set, so there's no wait, just an immediate raise; (3) a
naive (tz-unaware) `now` is interpreted as literal-UTC by `store._iso()` but
as system-local-time by `new_cards_introduced_today()`'s `.astimezone()` —
the two disagree by the host's UTC offset for the exact same `now` argument
within one `daily_queue()` call.

## Findings

| # | Scenario | Expected | Actual | Severity |
|---|---|---|---|---|
| 1 | Horizon clamp fallback, `now` within ~60s of `DEFAULT_HORIZON` | Per the module docstring: "the invariant that a clamped review always comes due strictly before the horizon is never broken" | `due_at` lands **after** `DEFAULT_HORIZON` (overshoot up to 59s, growing as remaining→0); at exactly 60s remaining `due_at == horizon` (not strictly before). Card becomes due after the user has already left. | **P0** |
| 2 | Two `sqlite3` connections calling `import_jsonl` concurrently (WAL mode, no `busy_timeout`) | Either both imports succeed (queued) or a documented, catchable contention error | `sqlite3.OperationalError: database is locked` raised uncaught by the losing thread; that import's cards/reviews are never written — 200/400 expected cards imported. Reproduces 3/3 runs, deterministically. | **P0** |
| 3 | `drill.scheduler.review(state, grade, now)` called with a naive `now` (no `horizon` override, so it compares against `DEFAULT_HORIZON`, which is tz-aware) | Either works (treat naive as UTC, matching `store._iso`'s convention) or raises a clear `ValueError` | `TypeError: can't compare offset-naive and offset-aware datetimes`, raised inside `_due_with_horizon`. Not reachable via the shipped CLI/app today (both always pass `datetime.now(timezone.utc)`), but it's the module's public API and has no guard. | **P2** |
| 4 | `store.daily_queue(conn, naive_now, ...)` on a host whose local TZ != UTC | `_iso(now)` (used for the due-card SQL filter) and `new_cards_introduced_today`'s day-boundary math should agree on what "now" and "today" mean | They disagree by exactly the host's UTC offset. `_iso()` treats a naive datetime as literal UTC (`.replace(tzinfo=utc)`); `new_cards_introduced_today` treats the same naive value as system-local via `.astimezone(timezone.utc)`. E.g. on a `TZ=America/Los_Angeles` host, naive `2026-09-21T02:00:00` → `_iso` gives `02:00:00+00:00`, but `.astimezone(utc)` gives `09:00:00+00:00` — a 7h skew in what "today" means for the new-card cap, within the *same* `daily_queue()` call. Also not reachable via the shipped CLI today (same reason as #3), and it doesn't corrupt persisted data — only a transient in-memory queue/count. | **P2** |

### Verified correct (no defect found)

| Scenario | Result |
|---|---|
| Full 13-day simulated run (2026-09-20 → 2026-10-02, one day short of the 2026-10-03 horizon), 460 real cards, ~25% AGAIN rate, days `{3, 7, 8}` skipped entirely, `suggested_new_per_day` re-derived each day | No NaN/negative intervals, ease always in `[1.3, 3.0]`, `reps`/`lapses` monotone non-decreasing per card, no card ever due after horizon while `now < horizon`, no duplicate/lost card in any day's `sched` table or in any single day's `daily_queue` output. See repro below. |
| Skipped days → backlog | Backlog spikes after a skip (3 → 16 → 25/31 after the 2-day skip and near the horizon) but is absorbed within 1–2 days once reviewing resumes; never runs away unboundedly in this 13-day/460-card scenario. `suggested_new_per_day` correctly drops new-card introduction to 0 while backlog is being worked off (reviews are never displaced by new cards, per `daily_queue`'s contract) and correctly ramps back up once backlog clears. Near-horizon backlog growth (day 12: 31) is an inherent consequence of the horizon clamp compressing intervals as departure nears — a real UX property worth knowing about, not a bug. |
| `now` exactly `== DEFAULT_HORIZON` | Clamp correctly disengages (`now >= horizon` branch); unclamped SM-2 interval applied. |
| `now` one second *after* horizon | Clamp disengages; unclamped interval applied. |
| tz-aware non-UTC `now` (e.g. `UTC+9`) fed straight to `drill.scheduler.review` | Pure-datetime arithmetic in `scheduler.py` handles any aware tz correctly; `due_at` matches expected wall-clock offset. |
| `now` "going backwards" (used a decreasing sequence of `now` values across reviews) | No schema constraint depends on monotonic time and `review()`/`save_sched()` don't assert it; no crash, no corrupted invariant observed. |
| `new_per_day=0` | `daily_queue` returns zero new cards, `new_introduced=0`. |
| `new_per_day=1` | Exactly one new card returned. |
| Every card already in `review` state (no `new` cards left) | `daily_queue` returns only due reviews, `new_introduced=0`, no crash; `suggested_new_per_day` returns `floor` (5) as documented. |
| Single-card database | `daily_queue` and `suggested_new_per_day` both behave sanely (1 item, `floor`). |
| `suggested_new_per_day` with `now` past `DEFAULT_HORIZON` and cards still `new` | Returns the documented past-horizon fallback (15, clamped to `[floor, ceiling]`). |
| Backup taken while a write transaction is open on another connection to the same file (WAL) | `backup_db` (via `sqlite3`'s online backup API) returns a snapshot containing only the **committed** state — the uncommitted `UPDATE` is correctly excluded. Row counts match. |
| Backup pruning | `keep=N` leaves exactly the newest `N` `.bak.*` files. |
| Backup failure (unwritable directory) during `import_jsonl`'s auto-backup-before-reimport path | `backup_db` returns `None` (catches internally, never raises) and `import_jsonl` still completes normally — the import is never blocked by a failed backup. |
| Read on one connection concurrent with a large (5000-row) write on another (WAL mode) | No `database is locked`, no error — this is the case WAL mode is actually designed for. Contrast with finding #2 (writer vs. writer). |
| Re-import all 5 real decks 3× in a row | Card count stable at 460 every round; re-importing again after manually promoting 10 cards to `state='review', reps=5` leaves those `sched` rows completely untouched (content-hash-gated upsert only touches `card`, never `sched`, for existing cards). |
| `_interleave_decks` with `budget` far larger than total candidates | Returns all candidates exactly once each, terminates (no infinite loop), no duplication. |

## Repro scripts (runnable)

### Finding #1 — horizon clamp can overshoot the horizon

```python
# python3 -c "..."  (or paste into a scratch file)
from datetime import timedelta
from drill.scheduler import DEFAULT_HORIZON, SchedState, review, Grade

for secs in (1, 30, 59, 60):
    now = DEFAULT_HORIZON - timedelta(seconds=secs)
    s = SchedState(due_at=now, interval_days=30.0, ease=2.5, reps=10, lapses=0,
                    state="review", last_reviewed_at=now - timedelta(days=30))
    r = review(s, Grade.GOOD, now)  # DEFAULT_HORIZON used
    print(secs, r.due_at, "holds:", now < r.due_at < DEFAULT_HORIZON)
# secs=1  -> due_at = horizon + 59s   holds: False
# secs=59 -> due_at = horizon + 1s    holds: False
# secs=60 -> due_at == horizon        holds: False (not strictly before)
```

Root cause, in `_due_with_horizon` (`drill/scheduler.py`): when the 1-day
floor itself would overshoot, the code falls back to
`due = horizon - timedelta(minutes=1)`; if that's still `<= now` (i.e. less
than a minute of runway remains), it falls forward again to
`due = now + timedelta(minutes=1)` — but that final fallback is never
re-checked against `horizon`, so it can (and does) land past it whenever
`remaining < 60s`.

Minimal pytest body:

```python
from datetime import timedelta
from drill.scheduler import DEFAULT_HORIZON, SchedState, Grade, review

def test_horizon_clamp_never_overshoots_horizon_even_with_seconds_of_runway():
    now = DEFAULT_HORIZON - timedelta(seconds=1)
    s = SchedState(
        due_at=now, interval_days=30.0, ease=2.5, reps=10, lapses=0,
        state="review", last_reviewed_at=now - timedelta(days=30),
    )
    result = review(s, Grade.GOOD, now)  # DEFAULT_HORIZON
    assert now < result.due_at < DEFAULT_HORIZON
```

### Finding #2 — concurrent imports crash and lose data

```python
import threading, json, tempfile
from pathlib import Path
from drill import store

tmp = Path(tempfile.mkdtemp())
db_path = tmp / "drill.db"
store.connect(db_path).close()

def make_jsonl(path, ids):
    lines = [json.dumps({"id": f"c{i:04d}", "deck": "d", "kind": "production",
              "prompt_en": f"w{i}", "accept": [f"p{i}"], "reject": [], "note": None,
              "tags": []}) for i in ids]
    path.write_text("\n".join(lines), encoding="utf-8")

p1, p2 = tmp / "a.jsonl", tmp / "b.jsonl"
make_jsonl(p1, range(0, 200))
make_jsonl(p2, range(200, 400))

errors = []
def worker(path):
    try:
        conn = store.connect(db_path)
        store.import_jsonl(conn, path)
        conn.close()
    except Exception as e:
        errors.append((path.name, repr(e)))

t1, t2 = threading.Thread(target=worker, args=(p1,)), threading.Thread(target=worker, args=(p2,))
t1.start(); t2.start(); t1.join(); t2.join()

print(errors)  # [('b.jsonl', "OperationalError('database is locked')")]
conn = store.connect(db_path)
print(conn.execute("SELECT COUNT(*) FROM card").fetchone()[0])  # 200, not 400
```

Minimal pytest body (uses `pytest.raises` to document current — buggy —
behavior; once fixed with a `busy_timeout` PRAGMA, this should be rewritten
to assert both imports succeed and the count is 400):

```python
import threading, json
import pytest
from drill import store

def test_concurrent_imports_do_not_lose_data(tmp_path):
    db_path = tmp_path / "drill.db"
    store.connect(db_path).close()

    def make_jsonl(path, ids):
        lines = [json.dumps({"id": f"c{i:04d}", "deck": "d", "kind": "production",
                  "prompt_en": f"w{i}", "accept": [f"p{i}"], "reject": [], "note": None,
                  "tags": []}) for i in ids]
        path.write_text("\n".join(lines), encoding="utf-8")

    p1, p2 = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    make_jsonl(p1, range(0, 200))
    make_jsonl(p2, range(200, 400))

    errors = []
    def worker(path):
        try:
            conn = store.connect(db_path)
            store.import_jsonl(conn, path)
            conn.close()
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(p,)) for p in (p1, p2)]
    for t in threads: t.start()
    for t in threads: t.join()

    conn = store.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM card").fetchone()[0]
    # Current (buggy) behavior: errors is non-empty and count == 200.
    # Desired behavior once fixed (e.g. PRAGMA busy_timeout set in `connect`):
    assert errors == [], f"concurrent import raised: {errors}"
    assert count == 400
```

Suggested fix direction: set `conn.execute("PRAGMA busy_timeout = 5000")` (or
similar) in `store.connect()` so a contending writer waits instead of
raising immediately — WAL mode already allows one writer + many readers, it
just isn't given any time to wait for the lock.

### Finding #3 — naive `now` crashes `scheduler.review`

```python
from datetime import datetime
from drill.scheduler import new_state, review, Grade

now = datetime(2026, 9, 21)  # naive
s = new_state(now)
review(s, Grade.GOOD, now)  # TypeError: can't compare offset-naive and offset-aware datetimes
```

```python
import pytest
from datetime import datetime
from drill.scheduler import new_state, review, Grade

def test_naive_now_does_not_crash_or_is_explicitly_rejected():
    now = datetime(2026, 9, 21)  # naive
    s = new_state(now)
    with pytest.raises(ValueError):  # documents desired behavior: explicit, not TypeError
        review(s, Grade.GOOD, now)
```

### Finding #4 — naive `now` day-boundary skew between `_iso` and `.astimezone`

```python
# Run with: TZ="America/Los_Angeles" python3 -c "..."
from datetime import datetime, timezone
from drill import store

naive_now = datetime(2026, 9, 21, 2, 0, 0)
print(store._iso(naive_now))                       # 2026-09-21T02:00:00+00:00
print(naive_now.astimezone(timezone.utc))           # 2026-09-21T09:00:00+00:00 (7h skew on a PDT host)
```

```python
import os, subprocess, sys

def test_iso_and_astimezone_agree_on_naive_now_interpretation():
    # Run as a subprocess so TZ actually takes effect (Python caches tzset at import).
    script = (
        "from datetime import datetime, timezone; from drill import store; "
        "n = datetime(2026,9,21,2,0,0); "
        "print(store._iso(n)); print(n.astimezone(timezone.utc).isoformat())"
    )
    env = {**os.environ, "TZ": "America/Los_Angeles"}
    out = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True).stdout
    iso_line, astz_line = out.strip().splitlines()
    assert iso_line.split("+")[0] == astz_line.split("+")[0], (
        f"naive `now` interpreted inconsistently: _iso={iso_line} vs astimezone={astz_line}"
    )
```

## Notes on scope / what was *not* newly found

`tests/test_scheduler.py`, `tests/test_daily.py`, `tests/test_interleave.py`,
`tests/test_backup.py` already cover: graduation path, ease clamping,
lapse accounting, purity of `review()`, `intervals_preview` agreement, the
horizon clamp's *normal* (non-boundary) behavior, new-card capping, backlog
non-displacement, deck-priority interleaving, single-writer backup/prune/
missing-source/unwritable-dir behavior, and the "different schema" import
error path. This report intentionally does not re-litigate those; it targets
the gaps: the horizon clamp's extreme boundary, concurrent writers, naive/
non-UTC `now`, and a full multi-day integration run with skipped days.
