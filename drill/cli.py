"""Command-line drill loop for English->Spanish production practice.

Three commands:

    python3 -m drill import data/es/peninsular_contrast.jsonl
    python3 -m drill review --deck peninsular_contrast --limit 20
    python3 -m drill stats

The review loop shows an English prompt, takes typed Spanish, grades it
deterministically (see `drill.grader`) and reschedules with SM-2 (see
`drill.scheduler`).

Grading maps onto scheduler grades automatically so the user never has to
self-assess -- self-grading is the main way spaced repetition degrades into
recognition practice.  The mapping is deliberately generous, because a
false reject is far more costly than a false accept here: being told your
correct Spanish is wrong is what makes people stop using the tool.
"""

from __future__ import annotations

import argparse
import functools
import json
import random
import re
import select
import sqlite3
import statistics
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from drill import cloze, export, packs, scenario, speech, store
from drill.grader import DEFAULT_REJECT_REASON, Verdict, grade as grade_attempt
from drill.scheduler import Grade, SchedState, review as reschedule

# --- presentation -----------------------------------------------------------

# Raw escape sequences. These are never referenced directly outside this
# block -- everything downstream uses the module-level BOLD/DIM/... names
# below, which `_set_color()` resolves once per command invocation.
_ESC_BOLD = "\033[1m"
_ESC_DIM = "\033[2m"
_ESC_GREEN = "\033[32m"
_ESC_YELLOW = "\033[33m"
_ESC_RED = "\033[31m"
_ESC_CYAN = "\033[36m"
_ESC_RESET = "\033[0m"

# Resolved per-invocation by `_set_color()`. Start disabled (empty strings)
# so any output produced before a command calls `_set_color()` -- there
# shouldn't be any, but this is the safe default -- never leaks ANSI.
BOLD = DIM = GREEN = YELLOW = RED = CYAN = RESET = ""


def _color(enabled: bool):
    if enabled:
        return lambda s, c: f"{c}{s}{RESET}"
    return lambda s, c: s


def _set_color(no_color: bool):
    """Decide whether colour is on for this invocation and resolve the
    module-level BOLD/DIM/GREEN/YELLOW/RED/CYAN/RESET constants accordingly.

    This is the single choke point every command must call, first thing,
    before printing anything. QA found that most output interpolated the
    raw escape constants directly into f-strings, bypassing the `_color()`
    gate entirely -- so `--no-color` suppressed almost nothing, and piping
    to a file embedded literal ESC bytes. Rather than patch every one of
    those call sites individually, the constants themselves now become
    empty strings when colour is off, so every existing
    `f"{DIM}...{RESET}"` site is automatically ANSI-free with no changes
    needed there.

    Colour is on only when stdout is a real TTY *and* `--no-color` wasn't
    passed -- never on a pipe/redirect/capture, regardless of the flag.
    Returns the `c(text, code)` gate for call sites that already use it.
    """
    global BOLD, DIM, GREEN, YELLOW, RED, CYAN, RESET
    enabled = sys.stdout.isatty() and not no_color
    if enabled:
        BOLD, DIM, GREEN, YELLOW, RED, CYAN, RESET = (
            _ESC_BOLD, _ESC_DIM, _ESC_GREEN, _ESC_YELLOW, _ESC_RED, _ESC_CYAN, _ESC_RESET,
        )
    else:
        BOLD = DIM = GREEN = YELLOW = RED = CYAN = RESET = ""
    return _color(enabled)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Verdict layer -> scheduler grade.  L2 is a clean hit; L3/L4 were accepted
# but with a wobble, so they come back sooner; anything rejected is AGAIN.
_LAYER_GRADE: dict[str, Grade] = {
    "L2_exact": Grade.GOOD,
    "L3_accent": Grade.HARD,
    "L4_close": Grade.HARD,
}


def _verdict_to_grade(v: Verdict) -> Grade:
    if not v.accepted:
        return Grade.AGAIN
    return _LAYER_GRADE.get(v.layer, Grade.GOOD)


def _to_sched_state(row: store.SchedRow) -> SchedState:
    return SchedState(
        due_at=row.due_at,
        interval_days=row.interval_days,
        ease=row.ease,
        reps=row.reps,
        lapses=row.lapses,
        state=row.state,
        last_reviewed_at=row.last_reviewed_at,
    )


def _to_sched_row(card_id: str, s: SchedState) -> store.SchedRow:
    return store.SchedRow(
        card_id=card_id,
        due_at=s.due_at,
        interval_days=s.interval_days,
        ease=s.ease,
        reps=s.reps,
        lapses=s.lapses,
        state=s.state,
        last_reviewed_at=s.last_reviewed_at,
    )


def _fmt_interval(days: float) -> str:
    if days < 1 / 24:
        return f"{max(1, round(days * 24 * 60))} min"
    if days < 1:
        return f"{days * 24:.0f} h"
    return f"{days:.0f} d"


# --- numeric flag validation -------------------------------------------------
#
# Single shared helper for every `--limit`/`--count`/`--rounds`/`--max`/
# `--days`/`--min-attempts` style flag across `review`, `daily`, `listen`,
# `sprint`, `weak`, `export`. QA found these accepting nonsense (negative
# SQLite `LIMIT`s becoming "unlimited", negative Python slices silently
# dropping trailing items, `0` read as "nothing requested" when it should
# mean "nothing due"/"no seen cards", etc). Wired in two places for the
# same reason: as an argparse `type=` (so the CLI's own repro path fails
# fast at parse time with a usable message) and as `_validate` inside the
# command functions themselves (so a hand-built `argparse.Namespace` that
# skips argparse's own parsing -- exactly how this test suite, and
# presumably any future caller, exercises these functions -- can't still
# reach the old `IndexError`/bad-`LIMIT` path).


def _positive(name: str, value, *, minimum: int = 1, maximum: int = 1_000_000) -> int:
    """Parse `value` as an int and enforce `value >= minimum`.

    `name` is the argparse dest (underscores), converted to the flag's
    dashed spelling for the message, e.g. "min_attempts" -> "--min-attempts".
    Raises `argparse.ArgumentTypeError` -- valid both as an argparse `type=`
    (argparse turns it into a parse-time error naming the flag) and as a
    plain exception `_validate` below catches and reports the same way.
    """
    flag = f"--{name.replace('_', '-')}"
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(f"{flag} must be an integer (got {value!r})")
    if n < minimum:
        raise argparse.ArgumentTypeError(f"{flag} must be >= {minimum} (got {n})")
    # Bounded above as well: an int wider than 64 bits reaches SQLite and
    # comes back as OverflowError from inside a query -- a traceback where
    # every other bad value gets a one-line argparse message.
    if n > maximum:
        raise argparse.ArgumentTypeError(f"{flag} must be <= {maximum} (got {n})")
    return n


def _validate(
    args: argparse.Namespace,
    name: str,
    *,
    minimum: int = 1,
    maximum: int = 1_000_000,
    optional: bool = False,
) -> bool:
    """Validate `args.<name>` in place via `_positive`, printing one line
    to stderr and returning False on bad input instead of raising deep
    inside a query or a slice. `optional=True` skips validation when the
    flag is `None` (not supplied) -- `daily --new` and `weak --days` derive
    a default rather than requiring a number.
    """
    value = getattr(args, name)
    if optional and value is None:
        return True
    try:
        setattr(args, name, _positive(name, value, minimum=minimum, maximum=maximum))
        return True
    except argparse.ArgumentTypeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return False


# --- first-run bootstrap -----------------------------------------------------


def _bootstrap_if_empty(conn: sqlite3.Connection) -> None:
    """First-run convenience: if the database has zero cards at all (not
    just none due), auto-import the bundled decks for the learner's dialect
    so `daily`/`review`/`listen`/`sprint` are usable immediately with no
    manual `drill import` step first.

    The pack is resolved relative to this package's own location
    (`drill/cli.py`'s parent's parent), not the working directory, so it
    works no matter where the CLI is invoked from. `store.import_jsonl`
    no-ops (no rows written) on any file whose objects lack the
    `deck`/`kind`/`accept` shape, so a stray non-card file in the pack is
    silently skipped rather than imported or crashing.
    """
    total = conn.execute("SELECT COUNT(*) FROM card").fetchone()[0]
    if total > 0:
        return
    _import_pack(conn, store.get_dialect(conn), announce="First run: auto-imported")


def _import_pack(conn: sqlite3.Connection, variety: str, *, announce: str) -> list[str]:
    """Import the bundled decks that serve `variety`; return their names."""
    pack = packs.load(root=Path(__file__).resolve().parent.parent / "data")
    if not pack.path.is_dir():
        print(
            "No cards yet, and no bundled data/ directory found. Import a deck first:\n"
            f"  python3 -m drill import data/{packs.DEFAULT_LANGUAGE}/<deck>.jsonl"
        )
        return []

    imported: list[str] = []
    for path in pack.deck_paths(variety):
        result = store.import_jsonl(conn, path, variety=variety)
        if result.errors:
            continue  # not a card deck (wrong schema) -- skip silently
        store.remove_cards(conn, result.skipped)
        if result.added or result.updated:
            imported.append(path.stem)

    if imported:
        print(f"{announce} bundled deck(s): {', '.join(imported)}\n")
    elif conn.execute("SELECT 1 FROM card LIMIT 1").fetchone() is None:
        print(
            f"No cards yet, and no bundled decks found in {pack.path}. Import one first:\n"
            f"  python3 -m drill import data/{pack.language}/<deck>.jsonl"
        )
    return imported


def _deck_names(conn: sqlite3.Connection) -> list[str]:
    """Distinct deck names actually present in the DB, sorted."""
    return [r[0] for r in conn.execute("SELECT DISTINCT deck FROM card ORDER BY deck").fetchall()]


def _report_no_cards(conn: sqlite3.Connection, deck: str | None) -> None:
    """Print the right "nothing here" message when a queue came back empty
    because the requested deck itself has no cards.

    QA found `--deck <nonexistent>` reusing the generic "No cards yet" line
    even on a 460-card database -- misleading, since the database is not
    empty, that one deck name just doesn't match anything. When a specific
    deck was requested and the database as a whole is non-empty, say so and
    list the real deck names instead.
    """
    if deck is not None:
        overall = store.deck_stats(conn, None)
        if overall.get("total", 0) > 0:
            names = _deck_names(conn)
            print(f"No deck named {deck!r}. Decks in this database: {', '.join(names)}.")
            return
    print("No cards yet. Import a deck first:")
    print("  python3 -m drill import data/es/<deck>.jsonl")


def _unknown_deck(conn: sqlite3.Connection, deck: str | None) -> bool:
    """True (having said so) when `deck` matches nothing in a non-empty DB.

    `review`/`daily`/`listen` already say this via `_report_no_cards`; the
    read-only reports used to print an all-zero table instead, which reads
    as "you have no history" rather than "that deck does not exist".
    """
    if deck is None:
        return False
    if store.deck_stats(conn, None).get("total", 0) == 0:
        return False
    if deck in _deck_names(conn):
        return False
    names = ", ".join(_deck_names(conn))
    print(f"No deck named {deck!r}. Decks in this database: {names}.")
    return True


# --- commands ---------------------------------------------------------------


_DIALECT_LABELS = {"es-ES": "Spain", "es-419": "Latin America"}


def _parse_goal_date(text: str) -> date | None:
    """`YYYY-MM-DD` -> date; blank or `none` -> None. Raises ValueError."""
    text = text.strip().lower()
    if text in ("", "none"):
        return None
    return date.fromisoformat(text)


def cmd_setup(args: argparse.Namespace) -> int:
    """Choose a dialect and an optional goal date, then import the decks
    for that dialect. Safe to re-run: changing the dialect re-imports, and
    removes the cards the new dialect doesn't serve.

    Flags answer without prompting; any question a flag doesn't answer is
    asked interactively when stdin is a terminal, and otherwise keeps its
    current value.
    """
    _set_color(getattr(args, "no_color", False))
    conn = store.connect(args.db)
    interactive = sys.stdin.isatty()
    old_dialect = store.get_dialect(conn)

    new_dialect = args.dialect
    if new_dialect is None and interactive:
        print("Which Spanish do you want to learn?")
        print("  1) Spain (vosotros, coche, móvil)")
        print("  2) Latin America (ustedes, carro, celular)")
        default = "2" if old_dialect == "es-419" else "1"
        try:
            choice = input(f"  [{default}] > ").strip() or default
        except EOFError:
            choice = default
        new_dialect = {"1": "es-ES", "2": "es-419"}.get(choice)
        if new_dialect is None:
            print(f"Not an option: {choice!r}", file=sys.stderr)
            return 2
    new_dialect = new_dialect or old_dialect

    goal_changed = False
    goal: date | None = None
    if args.goal_date is not None:
        try:
            goal = _parse_goal_date(args.goal_date)
        except ValueError:
            print(f"Goal date must be YYYY-MM-DD or 'none', got {args.goal_date!r}", file=sys.stderr)
            return 2
        goal_changed = True
    elif interactive:
        print("Studying toward a date (a trip, an exam)? Enter YYYY-MM-DD, or leave blank.")
        try:
            raw = input("  > ")
        except EOFError:
            raw = ""
        try:
            goal = _parse_goal_date(raw)
        except ValueError:
            print(f"Goal date must be YYYY-MM-DD, got {raw!r}", file=sys.stderr)
            return 2
        goal_changed = True

    if goal_changed:
        if goal is not None and goal <= _now().date():
            print(f"Goal date {goal} is not in the future.", file=sys.stderr)
            return 2
        store.set_setting(conn, store.SETTING_GOAL_DATE, goal.isoformat() if goal else None)
    store.set_setting(conn, store.SETTING_DIALECT, new_dialect)

    has_cards = conn.execute("SELECT 1 FROM card LIMIT 1").fetchone() is not None
    if not has_cards or new_dialect != old_dialect:
        _import_pack(conn, new_dialect, announce="Imported")

    current_goal = store.goal_horizon(conn)
    print(f"Dialect: {_DIALECT_LABELS.get(new_dialect, new_dialect)}")
    print(f"Goal date: {current_goal.date() if current_goal else 'none (steady pace)'}")
    print("Next: python3 -m drill daily")
    conn.close()
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    _set_color(getattr(args, "no_color", False))
    conn = store.connect(args.db)
    total_added = total_updated = total_unchanged = 0
    all_errors: list[str] = []
    had_failure = False
    paths = [Path(p) for p in args.paths]
    if not paths:
        print("nothing to import", file=sys.stderr)
        return 1
    for path in paths:
        if not path.exists():
            print(f"missing: {path}", file=sys.stderr)
            all_errors.append(f"{path}: not found")
            had_failure = True
            continue
        try:
            result = store.import_jsonl(conn, path)
        except OSError as exc:
            print(f"unreadable: {path}: {exc}", file=sys.stderr)
            all_errors.append(f"{path}: {exc}")
            had_failure = True
            continue
        total_added += result.added
        total_updated += result.updated
        total_unchanged += result.unchanged
        all_errors.extend(f"{path}: {e}" for e in result.errors)
        print(
            f"{path.name}: +{result.added} new, "
            f"{result.updated} updated, {result.unchanged} unchanged"
        )
    if all_errors:
        print(f"\n{len(all_errors)} problem(s):", file=sys.stderr)
        for e in all_errors[:20]:
            print(f"  {e}", file=sys.stderr)
        if len(all_errors) > 20:
            print(f"  ... and {len(all_errors) - 20} more", file=sys.stderr)
    conn.close()
    # Non-zero exit iff a requested file was missing or unreadable -- so a
    # script chaining `import` calls can detect that failure -- but not for
    # in-file schema/content errors (`result.errors`), which are reported
    # but were already tolerated as non-fatal (e.g. one bad line among many
    # good ones, or a non-card file skipped with a warning).
    return 1 if had_failure else 0


def _grade_and_reschedule(
    conn: sqlite3.Connection,
    card: store.Card,
    row: store.SchedRow,
    attempt: str,
    now: datetime,
    latency_ms: int | None,
) -> tuple[Verdict, SchedState]:
    """Grade `attempt` against `card`, persist the schedule update and the
    review log, and return the verdict plus the new schedule state.

    Shared by `_run_review_loop` and `cmd_listen` so grading + persistence
    -- the part that must never drift between the typing and listening
    drills -- lives in exactly one place.
    """
    verdict = grade_attempt(
        attempt,
        accept=card.accept,
        reject=card.reject,
        reject_reason=card.reject_reason or DEFAULT_REJECT_REASON,
    )
    sched_grade = _verdict_to_grade(verdict)

    before = row.interval_days
    next_state = reschedule(
        _to_sched_state(row), sched_grade, now, horizon=store.goal_horizon(conn)
    )
    store.save_sched(conn, _to_sched_row(card.card_id, next_state))
    store.record_review(
        conn,
        card_id=card.card_id,
        reviewed_at=now,
        grade=int(sched_grade),
        latency_ms=latency_ms,
        raw_text=attempt,
        accepted=verdict.accepted,
        layer=verdict.layer,
        interval_before=before,
        interval_after=next_state.interval_days,
    )
    conn.commit()
    return verdict, next_state


def _run_review_loop(
    conn: sqlite3.Connection,
    queue: Sequence[tuple[store.Card, store.SchedRow]],
    now: datetime,
    c,
) -> tuple[int, int]:
    """Drive the interactive prompt/grade/reschedule loop over `queue`.

    Shared by `cmd_review` and `cmd_daily` so the review experience -- and
    its scoring -- stays identical regardless of how the queue was built.
    """
    correct = 0
    seen = 0
    try:
        for card, row in queue:
            seen += 1
            is_cz = cloze.is_cloze(card.kind)
            cz = cloze.parse(card.prompt_en) if is_cz else None
            if cz is not None:
                print(f"{DIM}[{seen}/{len(queue)}]{RESET} {c(cloze.render_question(cz), BOLD)}")
                if cz.meaning_en:
                    print(f"  {DIM}{cz.meaning_en}{RESET}")
            else:
                print(f"{DIM}[{seen}/{len(queue)}]{RESET} {c(card.prompt_en, BOLD)}")
            started = time.monotonic()
            try:
                attempt = input("  > ").strip()
            except EOFError:
                print("\nstopping.")
                break
            latency_ms = int((time.monotonic() - started) * 1000)

            verdict, next_state = _grade_and_reschedule(conn, card, row, attempt, now, latency_ms)

            if verdict.accepted:
                correct += 1
                mark = c("✓", GREEN)
            else:
                mark = c("✗", RED)
            print(f"  {mark} {verdict.reason}")
            if verdict.detail:
                print(f"    {c(verdict.detail, YELLOW)}")
            if cz is not None:
                filled = cloze.render_filled(cz, attempt if verdict.accepted else card.accept[0])
                print(f"    {c(filled, CYAN)}")
            elif not verdict.accepted:
                print(f"    {c(card.accept[0], CYAN)}")
            if card.note:
                print(f"    {DIM}{card.note}{RESET}")

            print(f"    {DIM}next in {_fmt_interval(next_state.interval_days)}{RESET}\n")
    except KeyboardInterrupt:
        print("\n\nstopped.")

    return correct, seen


def cmd_review(args: argparse.Namespace) -> int:
    if not _validate(args, "limit"):
        return 2
    c = _set_color(getattr(args, "no_color", False))
    conn = store.connect(args.db)
    _bootstrap_if_empty(conn)
    now = _now()
    queue = store.due_cards(conn, now, deck=args.deck, limit=args.limit)

    if not queue:
        stats = store.deck_stats(conn, args.deck)
        if stats.get("total", 0) == 0:
            _report_no_cards(conn, args.deck)
        else:
            print(c("Nothing due. ¡Vale!", GREEN))
            print(f"{DIM}{stats['total']} cards, {stats['new']} still new{RESET}")
        conn.close()
        return 0

    print(f"{len(queue)} card(s) due. {DIM}Ctrl-C to stop; progress is saved.{RESET}\n")

    correct, seen = _run_review_loop(conn, queue, now, c)

    if seen:
        pct = 100.0 * correct / seen
        print(f"{correct}/{seen} correct ({pct:.0f}%)")
    conn.close()
    return 0


def cmd_daily(args: argparse.Namespace) -> int:
    if not _validate(args, "max") or not _validate(args, "new", minimum=0, optional=True):
        return 2
    c = _set_color(getattr(args, "no_color", False))
    conn = store.connect(args.db)
    _bootstrap_if_empty(conn)
    now = _now()
    new_per_day = args.new
    derived = new_per_day is None
    if derived:
        new_per_day = store.suggested_new_per_day(
            conn, now, horizon=store.goal_horizon(conn), deck=args.deck
        )
    queue = store.daily_queue(
        conn, now, deck=args.deck, new_per_day=new_per_day, max_cards=args.max
    )

    if not queue.items:
        stats = store.deck_stats(conn, args.deck)
        if stats.get("total", 0) == 0:
            _report_no_cards(conn, args.deck)
        else:
            print(c("Nothing to do right now. ¡Vale!", GREEN))
        conn.close()
        return 0

    reviews_in_queue = len(queue.items) - queue.new_introduced
    plan = f"Today: {reviews_in_queue} reviews + {queue.new_introduced} new ({args.max} max)"
    if queue.backlog > 0:
        plan += f" · {queue.backlog} in backlog"
    print(plan)
    print(f"{DIM}Ctrl-C to stop; progress is saved.{RESET}\n")

    correct, seen = _run_review_loop(conn, list(queue.items), now, c)

    if seen:
        pct = 100.0 * correct / seen
        print(f"{correct}/{seen} correct ({pct:.0f}%)")
    if queue.backlog > 0:
        print(f"{DIM}{queue.backlog} review(s) left in backlog -- run `drill daily` again to clear it.{RESET}")
    conn.close()
    return 0


def cmd_listen(args: argparse.Namespace) -> int:
    """Listening/dictation drill: the card's first accept form is spoken,
    the learner types what they heard, and the same `grade()` used by
    `review`/`daily` scores it -- so every existing deck is drillable for
    listening with no new content. See docs/SURVIVAL.md §8: parsing
    Spanish fired at you is the harder half of the real failure mode.
    """
    if not speech.is_available():
        print(
            "No Peninsular Spanish voice found for `say`. Listening mode needs "
            f"one of: {', '.join(speech.PENINSULAR_VOICES)} (es_ES). Install one "
            "under System Settings > Accessibility > Spoken Content, or use "
            "`drill review` / `drill daily` instead.",
            file=sys.stderr,
        )
        return 1

    if not _validate(args, "limit"):
        return 2
    c = _set_color(getattr(args, "no_color", False))
    conn = store.connect(args.db)
    _bootstrap_if_empty(conn)
    now = _now()
    queue = store.daily_queue(
        conn, now, deck=args.deck, new_per_day=args.limit, max_cards=args.limit
    )
    items = list(queue.items)

    if not items:
        stats = store.deck_stats(conn, args.deck)
        if stats.get("total", 0) == 0:
            _report_no_cards(conn, args.deck)
        else:
            print(c("Nothing due. ¡Vale!", GREEN))
        conn.close()
        return 0

    print(
        f"{len(items)} card(s) due. {DIM}'r' to replay (up to {args.replays}x); "
        f"Ctrl-C to stop, progress is saved.{RESET}\n"
    )

    correct = 0
    seen = 0
    try:
        for card, row in items:
            seen += 1
            target = card.accept[0]
            replays_left = args.replays
            print(f"{DIM}[{seen}/{len(items)}]{RESET} {c('🔊 escucha...', BOLD)}")
            speech.speak(target, rate=args.rate)

            started = time.monotonic()
            attempt: str | None = None
            while True:
                try:
                    raw = input("  > ").strip()
                except EOFError:
                    print("\nstopping.")
                    raw = None
                if raw is None:
                    break
                if raw.lower() == "r":
                    if replays_left > 0:
                        replays_left -= 1
                        speech.speak(target, rate=args.rate)
                    else:
                        print(f"    {DIM}no replays left.{RESET}")
                    continue
                attempt = raw
                break
            if attempt is None:
                break
            latency_ms = int((time.monotonic() - started) * 1000)

            verdict, next_state = _grade_and_reschedule(conn, card, row, attempt, now, latency_ms)

            if verdict.accepted:
                correct += 1
                mark = c("✓", GREEN)
            else:
                mark = c("✗", RED)
            print(f"  {mark} {verdict.reason}")
            if verdict.detail:
                print(f"    {c(verdict.detail, YELLOW)}")
            if not verdict.accepted:
                print(f"    {c(target, CYAN)}")
            # Revealed only now -- showing it before grading turns dictation
            # back into translation.
            print(f"    {DIM}{card.prompt_en}{RESET}")
            if card.note:
                print(f"    {DIM}{card.note}{RESET}")
            print(f"    {DIM}next in {_fmt_interval(next_state.interval_days)}{RESET}\n")
    except KeyboardInterrupt:
        print("\n\nstopped.")

    if seen:
        pct = 100.0 * correct / seen
        print(f"{correct}/{seen} correct ({pct:.0f}%)")
    conn.close()
    return 0


def cmd_scene(args: argparse.Namespace) -> int:
    """Multi-turn conversation drill: the NPC speaks a line, you answer,
    the NPC speaks the next line -- a sequence rather than an isolated
    card. This is the closest surviving thing to the forcing-function
    idea: you don't leave the scenario until you produce the Spanish.

    Writes nothing to the database -- no review rows, no schedule
    changes. Scenarios are not cards and must not corrupt SRS state.
    """
    c = _set_color(getattr(args, "no_color", False))
    if args.file is None:
        args.file = packs.load().scenarios_path
    scenarios, errors = scenario.load(args.file)
    for e in errors[:20]:
        print(f"warning: {e}", file=sys.stderr)

    if args.list:
        if not scenarios:
            print(f"No scenarios found in {args.file}.", file=sys.stderr)
            return 1
        for s in scenarios:
            print(f"{c(s.scenario_id, BOLD):<18}{s.title:<32}{len(s.turns)} turn(s)")
        return 0

    if not scenarios:
        print(f"No scenarios found in {args.file}.", file=sys.stderr)
        return 1

    if args.id is not None:
        chosen = next((s for s in scenarios if s.scenario_id == args.id), None)
        if chosen is None:
            print(f"error: no scenario with id {args.id!r}", file=sys.stderr)
            return 1
    else:
        chosen = random.choice(scenarios)

    speak_lines = args.speak and speech.is_available()

    print(f"{DIM}Practice only -- nothing here is scheduled or logged to your review history.{RESET}\n")
    print(f"{c(chosen.title, BOLD)} {DIM}({chosen.scenario_id}){RESET}")
    print(f"{chosen.situation_en}\n")

    dialogue: list[tuple[str, str]] = []
    passed = 0
    first_attempt_hits = 0
    seen = 0

    try:
        for i, t in enumerate(chosen.turns, 1):
            print(f"{DIM}[{i}/{len(chosen.turns)}]{RESET} {c(t.npc_es, CYAN)}")
            if speak_lines:
                speech.speak(t.npc_es)

            turn_passed = False
            stopped = False
            for attempt_num in range(1, args.max_attempts + 1):
                try:
                    attempt = input("  > ").strip()
                except EOFError:
                    print("\nstopping.")
                    stopped = True
                    break

                verdict = grade_attempt(attempt, accept=t.accept, reject=t.reject)
                if verdict.accepted:
                    print(f"  {c('✓', GREEN)} {verdict.reason}")
                    if attempt_num == 1:
                        first_attempt_hits += 1
                    turn_passed = True
                    break

                print(f"  {c('✗', RED)} {verdict.reason}")
                if attempt_num == 1:
                    print(f"    {c(t.goal_en, YELLOW)}")
                elif attempt_num == 2 and t.hint:
                    print(f"    {c(t.hint, YELLOW)}")

            if stopped:
                break

            seen = i
            if turn_passed:
                passed += 1
            else:
                print(f"    {c('answer:', DIM)} {c(t.accept[0], CYAN)}")
            dialogue.append((t.npc_es, t.accept[0]))
            print()
    except KeyboardInterrupt:
        print("\n\nstopped.")

    if seen:
        pct = 100.0 * first_attempt_hits / seen
        print(f"{passed}/{seen} turn(s) passed, {pct:.0f}% first-attempt")
    if dialogue:
        print(f"\n{BOLD}How it should have gone{RESET}")
        for npc_es, correct_es in dialogue:
            print(f"  {DIM}NPC:{RESET} {npc_es}")
            print(f"  {DIM}Tú: {RESET}{correct_es}")

    return 0


def _row_to_card(row: sqlite3.Row) -> store.Card:
    """Same shape as `store._row_to_card` -- kept local rather than reaching
    into store's private helper, since sprint's candidate query needs a
    filter (`sched.state != 'new'`, no attempt-count floor) none of store's
    public helpers expose."""
    return store.Card(
        card_id=row["card_id"],
        deck=row["deck"],
        kind=row["kind"],
        prompt_en=row["prompt_en"],
        accept=tuple(json.loads(row["accept_json"])),
        reject=tuple(json.loads(row["reject_json"])),
        note=row["note"],
        tags=tuple(json.loads(row["tags_json"])),
    )


def _sprint_candidates(conn: sqlite3.Connection, deck: str | None, count: int) -> list[store.Card]:
    """Pick up to `count` already-seen cards (`sched.state != 'new'`),
    ranked slowest-median-latency-first with lowest-accuracy as the
    tiebreak. A card with reviews but no recorded latency sorts as if
    instant, so it never displaces a card with real slow-latency evidence;
    a card with zero reviews (state changed without ever being graded --
    shouldn't happen, but not load-bearing to assume it can't) sorts as if
    perfectly accurate, for the same reason.

    Deliberately does not reuse `store.hardest_cards`: that helper requires
    >=2 review attempts per card, which would silently exclude a
    once-seen card from "already seen" -- the wrong definition for sprint.
    """
    query = (
        "SELECT card.* FROM card JOIN sched ON card.card_id = sched.card_id "
        "WHERE sched.state != 'new'"
    )
    params: list = []
    if deck is not None:
        query += " AND card.deck = ?"
        params.append(deck)

    cards = {row["card_id"]: _row_to_card(row) for row in conn.execute(query, params).fetchall()}
    if not cards:
        return []

    placeholders = ",".join("?" * len(cards))
    review_rows = conn.execute(
        f"SELECT card_id, accepted, latency_ms FROM review WHERE card_id IN ({placeholders})",
        list(cards.keys()),
    ).fetchall()

    attempts: dict[str, int] = {}
    misses: dict[str, int] = {}
    latencies: dict[str, list[int]] = {}
    for r in review_rows:
        cid = r["card_id"]
        attempts[cid] = attempts.get(cid, 0) + 1
        if not r["accepted"]:
            misses[cid] = misses.get(cid, 0) + 1
        if r["latency_ms"] is not None:
            latencies.setdefault(cid, []).append(r["latency_ms"])

    def sort_key(cid: str) -> tuple[float, float]:
        n = attempts.get(cid, 0)
        accuracy = (n - misses.get(cid, 0)) / n if n else 1.0
        lat = latencies.get(cid)
        median_latency = statistics.median(lat) if lat else 0.0
        return (-median_latency, accuracy)

    ordered = sorted(cards.keys(), key=sort_key)
    return [cards[cid] for cid in ordered[:count]]


def _read_with_deadline(limit_s: float) -> tuple[str | None, int]:
    """Read one line with a `limit_s` deadline, returning (answer, elapsed_ms).

    `answer` is None on timeout. Uses `select.select` on stdin -- never
    `signal.alarm`, never a thread -- so a slow answer times out cleanly
    without disturbing the main thread's state. When stdin is not a TTY
    (tests, pipes, CI) there is nothing to select on usefully, so this
    falls back to a plain untimed `input()` and still records real latency;
    that keeps the command testable and non-hanging without faking a
    timeout that never really threatened to happen.
    """
    started = time.monotonic()
    if not sys.stdin.isatty():
        try:
            line = input()
        except EOFError:
            line = ""
        return line.strip(), int((time.monotonic() - started) * 1000)

    ready, _, _ = select.select([sys.stdin], [], [], max(0.0, limit_s))
    if not ready:
        # Anything typed but not submitted belongs to the round that just
        # expired. Left buffered, it prepends onto the next round's answer
        # and is graded against a different card.
        try:
            import termios

            termios.tcflush(sys.stdin, termios.TCIFLUSH)
        except Exception:
            pass
        return None, int(limit_s * 1000)
    line = sys.stdin.readline()
    if line == "":  # EOF on a real TTY fd, e.g. piped-in Ctrl-D
        return None, int((time.monotonic() - started) * 1000)
    return line.strip(), int((time.monotonic() - started) * 1000)


def cmd_sprint(args: argparse.Namespace) -> int:
    """4/3/2 fluency drill (research/01-pedagogy.md §5 #9): the same cards,
    repeated under a shrinking time limit, to train retrieval speed rather
    than knowledge. Deliberately does not touch scheduling -- see the note
    printed below -- so it is safe to run as often as wanted.
    """
    if not _validate(args, "count") or not _validate(args, "rounds"):
        return 2
    c = _set_color(getattr(args, "no_color", False))
    conn = store.connect(args.db)
    _bootstrap_if_empty(conn)

    cards = _sprint_candidates(conn, args.deck, args.count)
    if not cards:
        print(
            "No seen cards yet to sprint on. Sprint mode drills retrieval speed on "
            "material you already know -- run `drill review` or `drill daily` first, "
            "then come back."
        )
        conn.close()
        return 0

    if len(cards) < args.count:
        print(
            f"{DIM}Only {len(cards)} seen card(s) available (asked for {args.count}) -- "
            f"sprinting with what you've got rather than padding with unseen material.{RESET}"
        )

    rng = random.Random(args.seed)
    print(
        f"{BOLD}Sprint{RESET}: {len(cards)} card(s) x {args.rounds} round(s). "
        f"{DIM}Practice only -- nothing here is scheduled or logged to your review history.{RESET}\n"
    )

    round_summaries: list[tuple[int, float, int, int, float | None]] = []

    for round_no in range(1, args.rounds + 1):
        limit_s = max(2.0, args.start - args.step * (round_no - 1))
        order = list(cards)
        rng.shuffle(order)

        print(f"{c(f'Round {round_no}', BOLD)} -- {limit_s:g}s per card")
        correct = 0
        latencies: list[int] = []
        for i, card in enumerate(order, start=1):
            print(f"  {DIM}[{i}/{len(order)}]{RESET} {card.prompt_en}")
            answer, elapsed_ms = _read_with_deadline(limit_s)
            latencies.append(elapsed_ms)
            if answer is None:
                print(f"    {c('timeout', RED)} -- {c(card.accept[0], CYAN)}")
                continue
            verdict = grade_attempt(
                answer,
                accept=card.accept,
                reject=card.reject,
                reject_reason=card.reject_reason or DEFAULT_REJECT_REASON,
            )
            if verdict.accepted:
                correct += 1
                print(f"    {c('correct', GREEN)}")
            else:
                print(f"    {c('miss', RED)} -- {c(card.accept[0], CYAN)}")

        median_ms = statistics.median(latencies) if latencies else None
        round_summaries.append((round_no, limit_s, correct, len(order), median_ms))
        median_str = f"{median_ms / 1000:.1f}s" if median_ms is not None else "n/a"
        print(f"  {correct}/{len(order)} correct, median {median_str}\n")

    print(f"{BOLD}Summary{RESET}")
    print(f"  {'round':<7}{'limit':>7}{'score':>8}{'median':>9}")
    for round_no, limit_s, correct, seen_n, median_ms in round_summaries:
        median_str = f"{median_ms / 1000:.1f}s" if median_ms is not None else "n/a"
        print(f"  {round_no:<7}{limit_s:>6g}s{f'{correct}/{seen_n}':>8}{median_str:>9}")

    first_median = round_summaries[0][4]
    last_median = round_summaries[-1][4]
    if first_median is not None and last_median is not None:
        delta_s = (first_median - last_median) / 1000
        if delta_s > 0:
            print(f"\nFaster: median dropped {delta_s:.1f}s from round 1 to round {args.rounds}.")
        elif delta_s < 0:
            print(
                f"\nSlower: median rose {-delta_s:.1f}s from round 1 to round {args.rounds} -- "
                "that's the honest read, not encouragement."
            )
        else:
            print(f"\nNo change in median response time between round 1 and round {args.rounds}.")

    conn.close()
    return 0


def _load_existing_cards(path: Path) -> list[dict]:
    """Best-effort parse of a card JSONL file. Malformed lines are skipped --
    this is only used to compute the next id and check for collisions, not
    to validate the file."""
    if not path.exists():
        return []
    cards = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            cards.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return cards


def _next_card_id(prefix: str, existing: list[dict]) -> str:
    """<prefix>-NNN, scanning `existing` for the highest existing number
    under that prefix so ids never collide on repeated runs."""
    highest = 0
    needle = f"{prefix}-"
    for c in existing:
        cid = str(c.get("id", ""))
        if cid.startswith(needle):
            suffix = cid[len(needle):]
            if suffix.isdigit():
                highest = max(highest, int(suffix))
    return f"{prefix}-{highest + 1:03d}"


def _offending_reject(verdict: Verdict, reject: Sequence[str]) -> str | None:
    """Pull the reject entry that made a card reject its own accept form,
    from the grader's L1_banned detail message (`«word» es de ...`)."""
    if not verdict.detail:
        return None
    m = re.search(r"«([^»]+)»", verdict.detail)
    if not m:
        return None
    word = m.group(1)
    for r in reject:
        if r.strip() == word:
            return r
    return word


def _prompt_add_interactive() -> tuple[str, list[str], list[str], str | None, list[str]]:
    prompt_en = input("English prompt: ").strip()
    first_accept = input("Spanish answer: ").strip()
    accept = [first_accept] if first_accept else []
    print("Additional accepted forms (blank line to finish):")
    while True:
        extra = input("  + ").strip()
        if not extra:
            break
        accept.append(extra)
    print("Forms to reject, e.g. a LatAm word (blank line to finish):")
    reject: list[str] = []
    while True:
        bad = input("  - ").strip()
        if not bad:
            break
        reject.append(bad)
    note = input("Note (optional): ").strip() or None
    tags_raw = input("Tags, comma-separated (optional): ").strip()
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
    return prompt_en, accept, reject, note, tags


def cmd_add(args: argparse.Namespace) -> int:
    """Capture a single card from a tutor session and drop it straight into
    the drillable deck -- see docs/TUTOR.md: a correction not turned into a
    card is a correction made again in Spain."""
    _set_color(getattr(args, "no_color", False))
    if args.prompt is not None:
        prompt_en = args.prompt.strip()
        accept = [a.strip() for a in (args.accept or []) if a.strip()]
        reject = [r.strip() for r in (args.reject or []) if r.strip()]
        note = args.note.strip() if args.note else None
        tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
    else:
        try:
            prompt_en, accept, reject, note, tags = _prompt_add_interactive()
        except EOFError:
            print("\nstopping.")
            return 1

    if not prompt_en:
        print("error: prompt cannot be empty", file=sys.stderr)
        return 1
    if not (args.deck or "").strip():
        print("error: --deck cannot be empty", file=sys.stderr)
        return 1
    if not accept:
        print("error: at least one accepted form is required", file=sys.stderr)
        return 1

    verdict = grade_attempt(accept[0], accept=accept, reject=reject)
    if not verdict.accepted:
        print(
            f"error: this card rejects its own answer ({verdict.layer}): {verdict.reason}",
            file=sys.stderr,
        )
        if verdict.layer == "L1_banned":
            offending = _offending_reject(verdict, reject)
            if offending is not None:
                print(
                    f"  the reject entry {offending!r} also matches the accept "
                    "form -- the card would be unanswerable. Remove or fix it.",
                    file=sys.stderr,
                )
        return 1

    deck = args.deck
    file_path = Path(args.file)
    prefix = deck[:2].lower()

    existing = _load_existing_cards(file_path)
    existing_ids = {c.get("id") for c in existing}
    card_id = _next_card_id(prefix, existing)
    if card_id in existing_ids:
        print(f"error: id {card_id!r} already exists in {file_path}", file=sys.stderr)
        return 1

    if any(c.get("prompt_en") == prompt_en for c in existing):
        print(
            f"warning: a card with prompt_en {prompt_en!r} already exists in "
            f"{file_path} -- adding anyway",
            file=sys.stderr,
        )

    card_obj = {
        "id": card_id,
        "deck": deck,
        "kind": "production",
        "prompt_en": prompt_en,
        "accept": accept,
        "reject": reject,
        "note": note,
        "tags": tags,
    }

    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(card_obj, ensure_ascii=False) + "\n")

    conn = store.connect(args.db)
    result = store.import_jsonl(conn, file_path)
    conn.close()

    print(f"{BOLD}{card_id}{RESET} added to {DIM}{deck}{RESET} ({file_path})")
    print(f"  {prompt_en}")
    print(f"  {DIM}accept:{RESET} {', '.join(accept)}")
    if reject:
        print(f"  {DIM}reject:{RESET} {', '.join(reject)}")
    if note:
        print(f"  {DIM}note:{RESET} {note}")
    if tags:
        print(f"  {DIM}tags:{RESET} {', '.join(tags)}")
    print(f"  imported: +{result.added} new, {result.updated} updated, {result.unchanged} unchanged")
    return 0


def _deck_accuracy(conn: sqlite3.Connection, deck: str | None) -> float | None:
    """accepted/total over the `review` table, scoped to `deck` if given.

    `docs/PROGRAM.md` names ">=85% accuracy" as a checkpoint, but `stats`
    never showed it. Returns None when there have been zero reviews, so
    the caller can print `--` rather than `0%` -- `0%` reads as "you are
    failing," while `--` correctly reads as "no data yet."
    """
    query = "SELECT COUNT(*) AS total, SUM(CASE WHEN accepted THEN 1 ELSE 0 END) AS accepted FROM review"
    params: list = []
    if deck is not None:
        query = (
            "SELECT COUNT(*) AS total, SUM(CASE WHEN review.accepted THEN 1 ELSE 0 END) AS accepted "
            "FROM review JOIN card ON review.card_id = card.card_id WHERE card.deck = ?"
        )
        params.append(deck)
    row = conn.execute(query, params).fetchone()
    total = row["total"] or 0
    if total == 0:
        return None
    accepted = row["accepted"] or 0
    return 100.0 * accepted / total


def cmd_stats(args: argparse.Namespace) -> int:
    _set_color(getattr(args, "no_color", False))
    conn = store.connect(args.db)
    if _unknown_deck(conn, args.deck):
        return 1
    s = store.deck_stats(conn, args.deck)
    label = args.deck or "all decks"
    print(f"{BOLD}{label}{RESET}")
    for key in ("total", "new", "learning", "review", "lapsed", "due_now"):
        print(f"  {key:>9}: {s.get(key, 0)}")
    accuracy = _deck_accuracy(conn, args.deck)
    acc_str = "--" if accuracy is None else f"{accuracy:.0f}%"
    print(f"  {'accuracy':>9}: {acc_str}")
    conn.close()
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """Write a personalised offline markdown sheet: weak tags, hardest
    cards, and register traps, built from the learner's own review
    history -- for the plane, with no laptop. See `drill.export`."""
    if not _validate(args, "limit") or not _validate(args, "min_attempts", minimum=0):
        return 2
    _set_color(getattr(args, "no_color", False))
    conn = store.connect(args.db)
    if _unknown_deck(conn, args.deck):
        return 1
    now = _now()

    doc = export.build_markdown(
        conn,
        deck=args.deck,
        limit=args.limit,
        min_attempts=args.min_attempts,
        now=now,
    )

    weak = export._weak_tags(conn, args.deck)
    failing = export._failing_cards(conn, args.deck, args.limit, args.min_attempts)
    trampas = export._trampas_cards(conn, args.deck)
    conn.close()

    out_path: Path = args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")

    print(f"{BOLD}{out_path}{RESET}")
    print(
        f"  {len(weak)} weak tag(s), {len(failing)} missed card(s), "
        f"{len(trampas)} trampa(s)"
    )
    return 0


def cmd_weak(args: argparse.Namespace) -> int:
    if not _validate(args, "limit") or not _validate(args, "days", optional=True):
        return 2
    _set_color(getattr(args, "no_color", False))
    conn = store.connect(args.db)
    if _unknown_deck(conn, args.deck):
        return 1
    since = _now() - timedelta(days=args.days) if args.days else None
    tag_stats = store.tag_performance(conn, deck=args.deck, since=since)
    hard_cards = store.hardest_cards(conn, deck=args.deck, limit=args.limit)

    label = args.deck or "all decks"
    window = f"last {args.days}d" if args.days else "all history"
    print(f"{BOLD}Weak areas -- {label} ({window}){RESET}\n")

    eligible = [t for t in tag_stats if t.attempts >= 3]
    hidden = len(tag_stats) - len(eligible)
    # Only the weakest few are actionable. Printing all ~30 tags turns a
    # priority list back into a data dump, which is what it exists to avoid.
    shown = eligible[: args.limit]

    print(f"{BOLD}Weakest tags{RESET}")
    if not eligible:
        print(f"  {DIM}Not enough review history yet (need >=3 attempts per tag).{RESET}")
    else:
        print(f"  {'tag':<20}{'acc':>6}  {'correct/attempts':>17}  {'cards':>6}")
        for t in shown:
            acc_pct = f"{t.accuracy * 100:.0f}%"
            ratio = f"{t.correct}/{t.attempts}"
            print(f"  {t.tag:<20}{acc_pct:>6}  {ratio:>17}  {t.cards:>6}")
        if len(eligible) > len(shown):
            print(f"  {DIM}({len(eligible) - len(shown)} more; --limit to see them){RESET}")
        if hidden:
            print(f"  {DIM}({hidden} tag(s) hidden for lack of data: fewer than 3 attempts){RESET}")

    print(f"\n{BOLD}Hardest cards{RESET}")
    if not hard_cards:
        print(f"  {DIM}Not enough review history yet (need >=2 attempts per card).{RESET}")
    else:
        for card, attempts, misses in hard_cards:
            prompt = card.prompt_en
            if len(prompt) > 40:
                prompt = prompt[:37] + "..."
            ratio = f"{misses}/{attempts}"
            print(f"  {prompt:<40}  {ratio:>6}  {card.accept[0]}")

    print()
    if len(eligible) >= 2:
        worst_two = [t.tag for t in eligible[:2]]
        print(f"Tell your tutor: focus on {', '.join(worst_two)}.")
    elif len(eligible) == 1:
        print(f"Tell your tutor: focus on {eligible[0].tag} (not enough data yet for a second tag).")
    else:
        print("Not enough review history yet to tell your tutor anything useful -- keep drilling.")

    conn.close()
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    try:
        from drill.app import run
    except ImportError as exc:  # tkinter absent from some Python builds
        print(f"desktop app unavailable: {exc}", file=sys.stderr)
        print("tkinter is missing from this Python. Use `drill review` instead.", file=sys.stderr)
        return 1
    return run(db_path=args.db, deck=args.deck, limit=args.limit, new_per_day=args.new)


def cmd_probe(args: argparse.Namespace) -> int:
    """Run the adversarial probes against a local model and print pass rates.

    Exit 0 when every probe meets `--min-pass`, 1 when one doesn't, 3 when
    the model can't be reached.
    """
    from drill import llm, probes

    _set_color(getattr(args, "no_color", False))
    variety = args.dialect or store.get_dialect(store.connect(args.db))
    try:
        results = probes.run(
            variety=variety, samples=args.samples, backend=args.backend, model=args.model
        )
    except llm.LLMUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 3

    model = args.model or llm.DEFAULT_MODELS[args.backend]
    print(f"{model} via {args.backend}, {variety}, {args.samples} sample(s) per probe\n")
    ok = True
    for r in results:
        passed = r.pass_rate >= args.min_pass
        ok = ok and passed
        colour = GREEN if passed else RED
        median = sorted(r.seconds)[len(r.seconds) // 2]
        print(f"  {colour}{r.pass_rate:4.0%}{RESET}  {r.probe.name:<12} median {median:.2f}s")
        if args.verbose or not passed:
            for text, why in zip(r.replies, r.failures):
                mark = "ok" if not why else "; ".join(why)
                print(f"        [{mark}] {text[:160]!r}")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="drill", description="Spanish production drill")
    p.add_argument("--db", type=Path, default=store.DEFAULT_DB, help="database path")
    # Global so every subcommand accepts `--no-color` (QA P1: argparse used
    # to reject it on stats/weak/export/add/import, and it only worked
    # before the subcommand name via this top-level flag). Also kept on
    # each subparser below -- both `drill --no-color <cmd>` and
    # `drill <cmd> --no-color` work; argparse never lets a subparser's own
    # default clobber a value already set by the top-level parser.
    p.add_argument("--no-color", action="store_true", help="disable ANSI colour output")
    sub = p.add_subparsers(dest="cmd", required=True)

    pst = sub.add_parser("setup", help="choose your dialect and an optional goal date")
    pst.add_argument("--dialect", choices=store.DIALECTS, default=None)
    pst.add_argument("--goal-date", default=None, help="YYYY-MM-DD, or 'none' to clear")
    pst.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS)
    pst.set_defaults(func=cmd_setup)

    pp = sub.add_parser("probe", help="test a local model against the adversarial probes")
    pp.add_argument("--backend", choices=("ollama", "mlx"), default="ollama")
    pp.add_argument("--model", default=None)
    pp.add_argument("--dialect", choices=store.DIALECTS, default=None)
    pp.add_argument("--samples", type=functools.partial(_positive, "samples"), default=5)
    pp.add_argument("--min-pass", type=float, default=0.8)
    pp.add_argument("-v", "--verbose", action="store_true", help="show every reply")
    pp.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS)
    pp.set_defaults(func=cmd_probe)

    pi = sub.add_parser("import", help="import card JSONL files")
    pi.add_argument("paths", nargs="+")
    pi.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS)
    pi.set_defaults(func=cmd_import)

    pr = sub.add_parser("review", help="review due cards")
    pr.add_argument("--deck", default=None)
    pr.add_argument("--limit", type=functools.partial(_positive, "limit"), default=20)
    pr.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS)
    pr.set_defaults(func=cmd_review)

    pa = sub.add_parser("add", help="capture a new card (interactive, or via flags)")
    pa.add_argument("--prompt", default=None, help="English prompt (omit for interactive mode)")
    pa.add_argument("--accept", action="append", default=None, help="an accepted Spanish form; repeatable")
    pa.add_argument("--reject", action="append", default=None, help="a form to reject; repeatable")
    pa.add_argument("--note", default=None)
    pa.add_argument("--tags", default=None, help="comma-separated tags")
    pa.add_argument("--deck", default="mine")
    pa.add_argument("--file", type=Path, default=Path("data/mine.jsonl"))
    pa.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS)
    pa.set_defaults(func=cmd_add)

    ps = sub.add_parser("stats", help="show deck counts")
    ps.add_argument("--deck", default=None)
    ps.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS)
    ps.set_defaults(func=cmd_stats)

    pg = sub.add_parser("gui", help="open the desktop app")
    pg.add_argument("--deck", default=None)
    pg.add_argument("--limit", type=int, default=40)
    pg.add_argument("--new", type=int, default=None,
                    help="new cards per day (default: derived from days left)")
    pg.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS)
    pg.set_defaults(func=cmd_gui)

    pe = sub.add_parser("export", help="write a personalised offline markdown sheet of weak material")
    pe.add_argument("--deck", default=None)
    pe.add_argument("--out", type=Path, default=Path("docs/MIS_FALLOS.md"))
    pe.add_argument("--limit", type=functools.partial(_positive, "limit"), default=60,
                    help="max missed cards to include")
    # min_attempts legitimately allows 0: "no attempts floor," still only
    # ever includes cards missed >=1 time (see export._failing_cards).
    pe.add_argument("--min-attempts", type=functools.partial(_positive, "min_attempts", minimum=0),
                    default=2, help="min attempts for a card to be included")
    pe.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS)
    pe.set_defaults(func=cmd_export)

    pw = sub.add_parser("weak", help="weak-area analytics: what to drill, what to tell your tutor")
    pw.add_argument("--deck", default=None)
    pw.add_argument("--days", type=functools.partial(_positive, "days"), default=None)
    pw.add_argument("--limit", type=functools.partial(_positive, "limit"), default=10)
    pw.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS)
    pw.set_defaults(func=cmd_weak)

    pd = sub.add_parser("daily", help="daily-paced review: caps new cards/day, reviews always first")
    pd.add_argument("--deck", default=None)
    # new legitimately allows 0: "introduce no new cards today," reviews only.
    pd.add_argument("--new", type=functools.partial(_positive, "new", minimum=0), default=None,
                    help="new cards per day (default: derived from days left)")
    pd.add_argument("--max", type=functools.partial(_positive, "max"), default=40,
                    help="max cards in a single session")
    pd.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS)
    pd.set_defaults(func=cmd_daily)

    pl = sub.add_parser("listen", help="listening/dictation drill: hear it, type it")
    pl.add_argument("--deck", default=None)
    pl.add_argument("--limit", type=functools.partial(_positive, "limit"), default=20)
    pl.add_argument("--rate", type=int, default=180, help="words per minute")
    pl.add_argument("--replays", type=int, default=3, help="replays allowed per card")
    pl.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS)
    pl.set_defaults(func=cmd_listen)

    psp = sub.add_parser(
        "sprint",
        help="timed 4/3/2 fluency drill: same cards, shrinking time limit; never reschedules",
    )
    psp.add_argument("--deck", default=None)
    psp.add_argument("--count", type=functools.partial(_positive, "count"), default=10,
                     help="number of already-seen cards to sprint on")
    psp.add_argument("--rounds", type=functools.partial(_positive, "rounds"), default=3)
    psp.add_argument("--start", type=float, default=8.0, help="seconds per card in round 1")
    psp.add_argument("--step", type=float, default=2.0, help="seconds shaved off each round, floored at 2s")
    psp.add_argument("--seed", type=int, default=None, help="shuffle seed (default: system entropy)")
    psp.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS)
    psp.set_defaults(func=cmd_sprint)

    psc = sub.add_parser(
        "scene",
        help="multi-turn conversation drill: NPC speaks, you answer, in sequence",
    )
    psc.add_argument("--id", default=None, help="scenario id, e.g. sc-001 (random if omitted)")
    psc.add_argument("--list", action="store_true", help="list available scenarios and exit")
    psc.add_argument("--speak", action="store_true", help="speak NPC lines aloud")
    psc.add_argument("--max-attempts", type=int, default=3, dest="max_attempts")
    psc.add_argument("--file", type=Path, default=None, help="scenario JSONL (default: the bundled pack's)")
    psc.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS)
    psc.set_defaults(func=cmd_scene)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        # Backstop. Commands that need to save progress catch this
        # themselves first; this only keeps Ctrl-C from ever looking like
        # a crash in one that doesn't.
        print()
        print("Stopped.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
