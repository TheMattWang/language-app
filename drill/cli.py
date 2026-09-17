"""Command-line drill loop for English->Spanish production practice.

Three commands:

    python -m drill import data/peninsular_contrast.jsonl
    python -m drill review --deck peninsular_contrast --limit 20
    python -m drill stats

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
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from drill import store
from drill.grader import Verdict, grade as grade_attempt
from drill.scheduler import Grade, SchedState, review as reschedule

# --- presentation -----------------------------------------------------------

BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
RESET = "\033[0m"


def _color(enabled: bool):
    if enabled:
        return lambda s, c: f"{c}{s}{RESET}"
    return lambda s, c: s


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


# --- commands ---------------------------------------------------------------


def cmd_import(args: argparse.Namespace) -> int:
    conn = store.connect(args.db)
    total_added = total_updated = total_unchanged = 0
    all_errors: list[str] = []
    paths = [Path(p) for p in args.paths]
    if not paths:
        print("nothing to import", file=sys.stderr)
        return 1
    for path in paths:
        if not path.exists():
            print(f"missing: {path}", file=sys.stderr)
            all_errors.append(f"{path}: not found")
            continue
        result = store.import_jsonl(conn, path)
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
    return 0


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
            print(f"{DIM}[{seen}/{len(queue)}]{RESET} {c(card.prompt_en, BOLD)}")
            started = time.monotonic()
            try:
                attempt = input("  > ").strip()
            except EOFError:
                print("\nstopping.")
                break
            latency_ms = int((time.monotonic() - started) * 1000)

            verdict = grade_attempt(attempt, accept=card.accept, reject=card.reject)
            sched_grade = _verdict_to_grade(verdict)

            if verdict.accepted:
                correct += 1
                mark = c("✓", GREEN)
            else:
                mark = c("✗", RED)
            print(f"  {mark} {verdict.reason}")
            if verdict.detail:
                print(f"    {c(verdict.detail, YELLOW)}")
            if not verdict.accepted:
                print(f"    {c(card.accept[0], CYAN)}")
            if card.note:
                print(f"    {DIM}{card.note}{RESET}")

            before = row.interval_days
            next_state = reschedule(_to_sched_state(row), sched_grade, now)
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
            print(f"    {DIM}next in {_fmt_interval(next_state.interval_days)}{RESET}\n")
    except KeyboardInterrupt:
        print("\n\nstopped.")

    return correct, seen


def cmd_review(args: argparse.Namespace) -> int:
    c = _color(sys.stdout.isatty() and not args.no_color)
    conn = store.connect(args.db)
    now = _now()
    queue = store.due_cards(conn, now, deck=args.deck, limit=args.limit)

    if not queue:
        stats = store.deck_stats(conn, args.deck)
        if stats.get("total", 0) == 0:
            print("No cards yet. Import a deck first:")
            print("  python -m drill import data/<deck>.jsonl")
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
    c = _color(sys.stdout.isatty() and not args.no_color)
    conn = store.connect(args.db)
    now = _now()
    queue = store.daily_queue(
        conn, now, deck=args.deck, new_per_day=args.new, max_cards=args.max
    )

    if not queue.items:
        stats = store.deck_stats(conn, args.deck)
        if stats.get("total", 0) == 0:
            print("No cards yet. Import a deck first:")
            print("  python -m drill import data/<deck>.jsonl")
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


def cmd_stats(args: argparse.Namespace) -> int:
    conn = store.connect(args.db)
    s = store.deck_stats(conn, args.deck)
    label = args.deck or "all decks"
    print(f"{BOLD}{label}{RESET}")
    for key in ("total", "new", "learning", "review", "lapsed", "due_now"):
        print(f"  {key:>9}: {s.get(key, 0)}")
    conn.close()
    return 0


def cmd_weak(args: argparse.Namespace) -> int:
    conn = store.connect(args.db)
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="drill", description="Spanish production drill")
    p.add_argument("--db", type=Path, default=store.DEFAULT_DB, help="database path")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("import", help="import card JSONL files")
    pi.add_argument("paths", nargs="+")
    pi.set_defaults(func=cmd_import)

    pr = sub.add_parser("review", help="review due cards")
    pr.add_argument("--deck", default=None)
    pr.add_argument("--limit", type=int, default=20)
    pr.add_argument("--no-color", action="store_true")
    pr.set_defaults(func=cmd_review)

    ps = sub.add_parser("stats", help="show deck counts")
    ps.add_argument("--deck", default=None)
    ps.set_defaults(func=cmd_stats)

    pg = sub.add_parser("gui", help="open the desktop app")
    pg.add_argument("--deck", default=None)
    pg.add_argument("--limit", type=int, default=40)
    pg.add_argument("--new", type=int, default=20, help="new cards to introduce per day")
    pg.set_defaults(func=cmd_gui)

    pw = sub.add_parser("weak", help="weak-area analytics: what to drill, what to tell your tutor")
    pw.add_argument("--deck", default=None)
    pw.add_argument("--days", type=int, default=None)
    pw.add_argument("--limit", type=int, default=10)
    pw.set_defaults(func=cmd_weak)

    pd = sub.add_parser("daily", help="daily-paced review: caps new cards/day, reviews always first")
    pd.add_argument("--deck", default=None)
    pd.add_argument("--new", type=int, default=20, help="new cards to introduce per day")
    pd.add_argument("--max", type=int, default=40, help="max cards in a single session")
    pd.add_argument("--no-color", action="store_true")
    pd.set_defaults(func=cmd_daily)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
