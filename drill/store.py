"""Persistence + JSONL import for the Spanish drill tool.

Owns the SQLite schema (see schema.sql), card import, scheduling state
storage, and review logging. All datetimes stored in the DB are
timezone-aware UTC, serialized via .isoformat() and parsed with
datetime.fromisoformat().
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from drill import dialect

_CARD_KEYS = ("deck", "kind", "accept")

DEFAULT_DB = Path.home() / ".langapp" / "drill.db"

# New cards a day when there is no goal date to pace against.
SUSTAINABLE_NEW_PER_DAY = 15

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

_VALID_KINDS = ("production", "cloze", "contrast")

# Order in which decks enter circulation when new cards are introduced.
# Chosen for a trip, not for linguistic tidiness: phrases you can deploy at a
# counter beat register, and register beats grammar. Unlisted decks sort in
# the middle. Only affects the ORDER of introduction, never whether a card is
# eventually seen.
DECK_PRIORITY: dict[str, int] = {
    "travel_production": 0,
    "numbers_listening": 1,
    "peninsular_contrast": 1,
    "cloze_grammar": 2,
    "grammar_repair": 3,
}
_DEFAULT_DECK_RANK = 2

# Slots per rotation by priority rank. Higher-priority decks appear more often,
# so a reduced daily rate degrades in usefulness order instead of uniformly.
_DECK_WEIGHTS: dict[int, int] = {0: 3, 1: 2, 2: 1, 3: 1}



# Cards carry why a rejected form is wrong as a reserved tag rather than a
# column: the DB has no migration runner, so adding a column to `card`
# breaks every existing install (docs/qa/store_durability.md, P1-4).
WHY_TAG_PREFIX = "why:"


@dataclass(frozen=True)
class Card:
    card_id: str
    deck: str
    kind: str
    prompt_en: str
    accept: tuple[str, ...]
    reject: tuple[str, ...]
    note: str | None
    tags: tuple[str, ...]

    @property
    def reject_reason(self) -> str | None:
        """The card's `why:` category, or None when it carries no tag.

        None lets the grader apply its own default rather than having one
        guessed here -- a card with no stated reason must not be assumed to
        be a regionalism, which is the bug this whole mechanism exists to
        fix.
        """
        for tag in self.tags:
            if tag.startswith(WHY_TAG_PREFIX):
                return tag[len(WHY_TAG_PREFIX):] or None
        return None

    @property
    def display_tags(self) -> tuple[str, ...]:
        """Tags fit to show the learner: `why:` entries are grading
        metadata, and on the GUI card face they would sit under the prompt
        as a hint before the answer is typed."""
        return tuple(t for t in self.tags if not t.startswith(WHY_TAG_PREFIX))


@dataclass(frozen=True)
class SchedRow:
    card_id: str
    due_at: datetime
    interval_days: float
    ease: float
    reps: int
    lapses: int
    state: str
    last_reviewed_at: datetime | None


@dataclass(frozen=True)
class DailyQueue:
    items: tuple[tuple[Card, SchedRow], ...]
    due_reviews: int
    new_introduced: int
    new_remaining: int
    backlog: int


@dataclass(frozen=True)
class ImportResult:
    added: int
    updated: int
    unchanged: int
    errors: tuple[str, ...]
    # Card ids not served for the requested variety (see drill.dialect).
    skipped: tuple[str, ...] = ()


@dataclass(frozen=True)
class TagStat:
    tag: str
    attempts: int
    correct: int
    accuracy: float
    cards: int
    lapses: int
    median_latency_ms: int | None


def connect(db_path: Path = DEFAULT_DB) -> sqlite3.Connection:
    """Open (and initialize) the drill database. Idempotent."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    # WAL allows one writer; without a timeout the loser of a race fails
    # instantly and its whole import is dropped. Concurrent imports are
    # reachable in practice -- the desktop app holds a connection open while
    # the user runs a command in a terminal.
    conn.execute("PRAGMA busy_timeout = 5000")

    schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    conn.commit()
    return conn


def _content_hash(
    kind: str,
    prompt_en: str,
    accept: Sequence[str],
    reject: Sequence[str],
    note: str | None = None,
    tags: Sequence[str] = (),
    deck: str = "",
) -> str:
    """Fingerprint every field an edit can touch.

    `note`, `tags` and `deck` are included deliberately: the hash is what
    decides whether a re-import is a no-op, so any field left out of it is a
    field that can never be edited once the card has been imported once.
    """
    payload = json.dumps(
        {
            "kind": kind,
            "prompt_en": prompt_en,
            "accept": list(accept),
            "reject": list(reject),
            "note": note,
            "tags": list(tags),
            "deck": deck,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _iso(dt: datetime) -> str:
    """Serialize as UTC ISO-8601.

    Due-date comparisons are done as string comparisons in SQL, which is
    only correct while every stored timestamp shares one offset. Converting
    here (rather than trusting callers) is what makes that safe; a naive
    datetime is treated as UTC rather than silently sorting wrong.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).isoformat()
    return dt.astimezone(timezone.utc).isoformat()


def _row_to_card(row: sqlite3.Row) -> Card:
    return Card(
        card_id=row["card_id"],
        deck=row["deck"],
        kind=row["kind"],
        prompt_en=row["prompt_en"],
        accept=tuple(json.loads(row["accept_json"])),
        reject=tuple(json.loads(row["reject_json"])),
        note=row["note"],
        tags=tuple(json.loads(row["tags_json"])),
    )


def _row_to_sched(row: sqlite3.Row, *, prefix: str = "") -> SchedRow:
    last_reviewed_raw = row[f"{prefix}last_reviewed_at"]
    return SchedRow(
        card_id=row["card_id"],
        due_at=datetime.fromisoformat(row[f"{prefix}due_at"]),
        interval_days=row[f"{prefix}interval_days"],
        ease=row[f"{prefix}ease"],
        reps=row[f"{prefix}reps"],
        lapses=row[f"{prefix}lapses"],
        state=row[f"{prefix}state"],
        last_reviewed_at=datetime.fromisoformat(last_reviewed_raw) if last_reviewed_raw else None,
    )


def backup_db(db_path: Path, *, keep: int = 5) -> Path | None:
    """Snapshot `db_path` to a timestamped `.bak.<UTC timestamp>` sibling.

    Uses sqlite3's online backup API so a snapshot taken while a connection
    is open (WAL mode included) is still consistent, rather than a raw file
    copy that could grab a torn write. Prunes older backups, keeping only
    the newest `keep`. Never raises -- a failed backup must not block the
    write it's protecting -- so any error (missing source, unwritable
    directory, etc.) results in `None` instead of a traceback.
    """
    try:
        db_path = Path(db_path)
        if not db_path.exists():
            return None

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        dest_path = db_path.parent / f"{db_path.name}.bak.{timestamp}"

        source = sqlite3.connect(str(db_path))
        try:
            dest = sqlite3.connect(str(dest_path))
            try:
                source.backup(dest)
            finally:
                dest.close()
        finally:
            source.close()

        if keep >= 0:
            pattern = f"{db_path.name}.bak.*"
            backups = sorted(
                db_path.parent.glob(pattern), key=lambda p: p.name, reverse=True
            )
            for stale in backups[keep:]:
                stale.unlink(missing_ok=True)

        # Pruning can delete the snapshot just taken (keep=0). Returning its
        # path anyway would tell a caller checking for non-None that it has a
        # backup it does not have.
        return dest_path if dest_path.exists() else None
    except Exception:
        return None


def import_jsonl(
    conn: sqlite3.Connection, path: Path, *, variety: str | None = None
) -> ImportResult:
    """Upsert cards from a JSONL file. Safely re-runnable. One transaction.

    With `variety`, each card's answer lists are resolved for it and cards
    not served for it are left out and reported in `skipped`
    (see drill.dialect). Without it, cards import exactly as authored.
    """
    path = Path(path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        return ImportResult(
            added=0,
            updated=0,
            unchanged=0,
            errors=(f"{path.name}: not valid UTF-8 ({exc.reason} at byte {exc.start})",),
        )
    except OSError as exc:
        return ImportResult(added=0, updated=0, unchanged=0, errors=(f"{path.name}: {exc.strerror}",))

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        try:
            first_obj = json.loads(line)
        except json.JSONDecodeError:
            first_obj = None
        # `none of` rather than `not all of`: a card missing one field is a
        # bad row to report per-line, not a reason to drop the whole file.
        if isinstance(first_obj, dict) and not any(k in first_obj for k in _CARD_KEYS):
            return ImportResult(
                added=0,
                updated=0,
                unchanged=0,
                errors=("not a card deck (looks like a different schema); skipped",),
            )
        break

    has_reviews = conn.execute("SELECT 1 FROM review LIMIT 1").fetchone() is not None
    if has_reviews:
        for row in conn.execute("PRAGMA database_list").fetchall():
            # seq, name, file -- positional, since callers may not set
            # row_factory = sqlite3.Row on the connection they pass in.
            if row[1] == "main":
                db_file = row[2]
                if db_file:
                    backup_db(Path(db_file))
                break

    added = 0
    updated = 0
    unchanged = 0
    errors: list[str] = []
    skipped: list[str] = []

    now_iso = _iso(datetime.now(timezone.utc))

    # BEGIN IMMEDIATE, not a plain BEGIN: a deferred transaction takes its
    # read snapshot at the first statement, so two concurrent importers pin
    # conflicting snapshots and the loser dies on SQLITE_BUSY_SNAPSHOT --
    # which busy_timeout cannot retry, because it is a conflict, not a wait.
    # Taking the write lock up front makes the second importer queue instead.
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.cursor()
        for lineno, raw_line in enumerate(lines, start=1):
            line = raw_line.strip()
            if not line:
                continue

            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"line {lineno}: invalid JSON: {exc}")
                continue

            try:
                if not isinstance(obj, dict):
                    raise ValueError("card must be a JSON object")
                card_id = obj["id"]
                deck = obj["deck"]
                kind = obj["kind"]
                prompt_en = obj["prompt_en"]
                accept = obj["accept"]
                if kind not in _VALID_KINDS:
                    raise ValueError(f"invalid kind: {kind!r}")
                if not isinstance(accept, list) or len(accept) == 0:
                    raise ValueError("accept must be a non-empty list")
                reject = obj.get("reject", [])
                note = obj.get("note")
                tags = obj.get("tags", [])
            except (KeyError, ValueError) as exc:
                errors.append(f"line {lineno}: {exc}")
                continue

            if variety is not None:
                resolved = dialect.resolve(obj, accept, reject, variety)
                if resolved is None:
                    skipped.append(card_id)
                    continue
                accept, reject = resolved

            content_hash = _content_hash(kind, prompt_en, accept, reject, note, tags, deck)

            cur.execute("SELECT content_hash FROM card WHERE card_id = ?", (card_id,))
            existing = cur.fetchone()

            if existing is None:
                cur.execute(
                    "INSERT INTO card(card_id, deck, kind, prompt_en, accept_json, reject_json, "
                    "note, tags_json, content_hash, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        card_id,
                        deck,
                        kind,
                        prompt_en,
                        json.dumps(accept),
                        json.dumps(reject),
                        note,
                        json.dumps(tags),
                        content_hash,
                        now_iso,
                    ),
                )
                cur.execute(
                    "INSERT INTO sched(card_id, due_at, interval_days, ease, reps, lapses, state, "
                    "last_reviewed_at) VALUES (?,?,?,?,?,?,?,?)",
                    (card_id, now_iso, 0.0, 2.5, 0, 0, "new", None),
                )
                added += 1
            elif existing["content_hash"] == content_hash:
                unchanged += 1
            else:
                cur.execute(
                    "UPDATE card SET deck=?, kind=?, prompt_en=?, accept_json=?, reject_json=?, "
                    "note=?, tags_json=?, content_hash=? WHERE card_id=?",
                    (
                        deck,
                        kind,
                        prompt_en,
                        json.dumps(accept),
                        json.dumps(reject),
                        note,
                        json.dumps(tags),
                        content_hash,
                        card_id,
                    ),
                )
                updated += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return ImportResult(
        added=added, updated=updated, unchanged=unchanged,
        errors=tuple(errors), skipped=tuple(skipped),
    )


def due_cards(
    conn: sqlite3.Connection, now: datetime, deck: str | None = None, limit: int = 20
) -> list[tuple[Card, SchedRow]]:
    query = (
        "SELECT card.*, sched.due_at AS sc_due_at, sched.interval_days AS sc_interval_days, "
        "sched.ease AS sc_ease, sched.reps AS sc_reps, sched.lapses AS sc_lapses, "
        "sched.state AS sc_state, sched.last_reviewed_at AS sc_last_reviewed_at "
        "FROM card JOIN sched ON card.card_id = sched.card_id "
        "WHERE sched.due_at <= ?"
    )
    params: list = [_iso(now)]
    if deck is not None:
        query += " AND card.deck = ?"
        params.append(deck)
    query += (
        " ORDER BY (CASE WHEN sched.state = 'new' THEN 1 ELSE 0 END) ASC, sched.due_at ASC LIMIT ?"
    )
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    results: list[tuple[Card, SchedRow]] = []
    for row in rows:
        card = _row_to_card(row)
        sched = _row_to_sched(row, prefix="sc_")
        results.append((card, sched))
    return results


def _interleave_decks(
    candidates: list[tuple[Card, SchedRow]], budget: int
) -> list[tuple[Card, SchedRow]]:
    """Pick `budget` new cards, round-robin across decks.

    Two reasons not to just take the first `budget` by id. Alphabetical order
    puts `gr-*` (grammar) ahead of `tv-*` (travel), which is backwards before
    a trip. And draining one deck at a time would leave a whole deck
    un-introduced until the final days, where the departure clamp gives it
    almost no repetitions.

    Round-robin in DECK_PRIORITY order means every deck starts on day one and
    they finish at roughly the same time, and it interleaves material rather
    than blocking it -- which is also the better way to practise.
    """
    if budget <= 0:
        return []

    by_deck: dict[str, list[tuple[Card, SchedRow]]] = {}
    for item in candidates:
        by_deck.setdefault(item[0].deck, []).append(item)

    decks = sorted(by_deck, key=lambda d: (DECK_PRIORITY.get(d, _DEFAULT_DECK_RANK), d))

    # Weighted round-robin, not flat. A flat rotation interleaves nicely but
    # degrades wrongly: lowering the daily rate thins every deck equally, so
    # cutting to 20/day costs as much travel vocabulary as grammar. Weighting
    # by priority means the decks you need at a counter keep their share and
    # the optional ones absorb the loss -- while everything still starts on
    # day one, which is what the interleaving was for.
    cycle: list[str] = []
    for d in decks:
        cycle.extend([d] * _DECK_WEIGHTS.get(DECK_PRIORITY.get(d, _DEFAULT_DECK_RANK), 1))

    picked: list[tuple[Card, SchedRow]] = []
    while len(picked) < budget and any(by_deck[d] for d in decks):
        for d in cycle:
            if len(picked) >= budget:
                break
            if by_deck[d]:
                picked.append(by_deck[d].pop(0))
    return picked


def suggested_new_per_day(
    conn: sqlite3.Connection,
    now: datetime,
    *,
    horizon: datetime | None = None,
    deck: str | None = None,
    floor: int = 5,
    ceiling: int = 40,
) -> int:
    """How many new cards a day it takes to finish the collection in time.

    Hard-coding this number went wrong three times: every deck added makes
    the arithmetic tighter, and the failure is silent -- the last cards are
    simply never introduced before the goal date. Deriving it from the
    remaining cards and the remaining days means adding a deck re-paces the
    plan automatically.

    Clamped to [floor, ceiling]: a ceiling because there is a limit to what
    fits in one sitting, a floor so the tool never stops introducing
    material. With no goal date (`horizon=None`), or once it has passed,
    there is no deadline to pace against, so it settles at a sustainable
    default.
    """
    if horizon is None:
        return min(ceiling, max(floor, SUSTAINABLE_NEW_PER_DAY))

    q = "SELECT COUNT(*) AS n FROM sched JOIN card USING (card_id) WHERE sched.state = 'new'"
    params: list = []
    if deck is not None:
        q += " AND card.deck = ?"
        params.append(deck)
    remaining = conn.execute(q, params).fetchone()["n"]
    if remaining <= 0:
        return floor

    days_left = (horizon - now).total_seconds() / 86400.0
    if days_left <= 0:
        return min(ceiling, max(floor, SUSTAINABLE_NEW_PER_DAY))

    needed = math.ceil(remaining / max(1.0, days_left))
    return min(ceiling, max(floor, needed))


def new_cards_introduced_today(
    conn: sqlite3.Connection, now: datetime, *, deck: str | None = None
) -> int:
    """Count of distinct cards whose earliest-ever review falls on `now`'s UTC day.

    A card is "introduced" the day it is first reviewed, not the day it was
    imported -- `MIN(reviewed_at)` per card_id is the source of truth.
    """
    # Local midnight, not UTC midnight. A Pacific-time user drilling at 6pm
    # is already into the next UTC day, so a UTC boundary silently granted a
    # second full allowance of new cards partway through the evening.
    local_now = now.astimezone()
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_start = local_start.astimezone(timezone.utc)
    day_end = (local_start + timedelta(days=1)).astimezone(timezone.utc)

    query = "SELECT review.card_id AS card_id, MIN(review.reviewed_at) AS first_reviewed_at FROM review"
    params: list = []
    if deck is not None:
        query += " JOIN card ON review.card_id = card.card_id WHERE card.deck = ?"
        params.append(deck)
    query += " GROUP BY review.card_id"

    count = 0
    for row in conn.execute(query, params).fetchall():
        first_reviewed_at = datetime.fromisoformat(row["first_reviewed_at"])
        if day_start <= first_reviewed_at < day_end:
            count += 1
    return count


def daily_queue(
    conn: sqlite3.Connection,
    now: datetime,
    *,
    deck: str | None = None,
    new_per_day: int = 30,
    max_cards: int = 40,
) -> DailyQueue:
    """Build a daily-paced review queue: due reviews first, then capped new cards.

    Reviews (state != 'new', due_at <= now) are never displaced by the
    new-card cap -- they're selected in full, oldest due first, and only
    `max_cards` can truncate them (recorded as `backlog`). New cards fill
    whatever room is left, capped by `new_per_day` minus however many new
    cards were already introduced today, ordered by card_id so the deck is
    introduced in authoring order.
    """
    review_query = (
        "SELECT card.*, sched.due_at AS sc_due_at, sched.interval_days AS sc_interval_days, "
        "sched.ease AS sc_ease, sched.reps AS sc_reps, sched.lapses AS sc_lapses, "
        "sched.state AS sc_state, sched.last_reviewed_at AS sc_last_reviewed_at "
        "FROM card JOIN sched ON card.card_id = sched.card_id "
        "WHERE sched.state != 'new' AND sched.due_at <= ?"
    )
    review_params: list = [_iso(now)]
    if deck is not None:
        review_query += " AND card.deck = ?"
        review_params.append(deck)
    review_query += " ORDER BY sched.due_at ASC"

    reviews = [
        (_row_to_card(row), _row_to_sched(row, prefix="sc_"))
        for row in conn.execute(review_query, review_params).fetchall()
    ]
    due_reviews = len(reviews)

    # The daily budget is GLOBAL, deliberately not scoped to `deck`. `deck`
    # says which cards may be offered; it must not say how many count against
    # today's cap. Scoping the count lets the GUI's deck picker spend the
    # budget once per deck -- 20 on "Todas", then another 14 on grammar, then
    # another 13 on travel, which is the 300-card wall again by another route.
    introduced_today = new_cards_introduced_today(conn, now)
    new_budget = max(0, new_per_day - introduced_today)

    new_cards: list[tuple[Card, SchedRow]] = []
    if new_budget > 0:
        new_query = (
            "SELECT card.*, sched.due_at AS sc_due_at, sched.interval_days AS sc_interval_days, "
            "sched.ease AS sc_ease, sched.reps AS sc_reps, sched.lapses AS sc_lapses, "
            "sched.state AS sc_state, sched.last_reviewed_at AS sc_last_reviewed_at "
            "FROM card JOIN sched ON card.card_id = sched.card_id "
            "WHERE sched.state = 'new' AND sched.due_at <= ?"
        )
        new_params: list = [_iso(now)]
        if deck is not None:
            new_query += " AND card.deck = ?"
            new_params.append(deck)
        new_query += " ORDER BY card.card_id ASC"
        candidates = [
            (_row_to_card(row), _row_to_sched(row, prefix="sc_"))
            for row in conn.execute(new_query, new_params).fetchall()
        ]
        new_cards = _interleave_decks(candidates, new_budget)

    if due_reviews > max_cards:
        backlog = due_reviews - max_cards
        selected_reviews = reviews[:max_cards]
        selected_new: list[tuple[Card, SchedRow]] = []
    else:
        backlog = 0
        selected_reviews = reviews
        remaining_capacity = max_cards - due_reviews
        selected_new = new_cards[:remaining_capacity] if remaining_capacity > 0 else []

    new_introduced = len(selected_new)
    new_remaining = new_budget - new_introduced

    return DailyQueue(
        items=tuple(selected_reviews + selected_new),
        due_reviews=due_reviews,
        new_introduced=new_introduced,
        new_remaining=new_remaining,
        backlog=backlog,
    )


def get_card(conn: sqlite3.Connection, card_id: str) -> Card | None:
    row = conn.execute("SELECT * FROM card WHERE card_id = ?", (card_id,)).fetchone()
    if row is None:
        return None
    return _row_to_card(row)


def get_sched(conn: sqlite3.Connection, card_id: str) -> SchedRow | None:
    row = conn.execute("SELECT * FROM sched WHERE card_id = ?", (card_id,)).fetchone()
    if row is None:
        return None
    return _row_to_sched(row)


def save_sched(conn: sqlite3.Connection, row: SchedRow) -> None:
    conn.execute(
        "INSERT INTO sched(card_id, due_at, interval_days, ease, reps, lapses, state, "
        "last_reviewed_at) VALUES (?,?,?,?,?,?,?,?) "
        "ON CONFLICT(card_id) DO UPDATE SET due_at=excluded.due_at, "
        "interval_days=excluded.interval_days, ease=excluded.ease, reps=excluded.reps, "
        "lapses=excluded.lapses, state=excluded.state, last_reviewed_at=excluded.last_reviewed_at",
        (
            row.card_id,
            _iso(row.due_at),
            row.interval_days,
            row.ease,
            row.reps,
            row.lapses,
            row.state,
            _iso(row.last_reviewed_at) if row.last_reviewed_at else None,
        ),
    )
    conn.commit()


def record_review(
    conn: sqlite3.Connection,
    *,
    card_id: str,
    reviewed_at: datetime,
    grade: int,
    latency_ms: int | None,
    raw_text: str | None,
    accepted: bool,
    layer: str | None,
    interval_before: float,
    interval_after: float,
) -> None:
    conn.execute(
        "INSERT INTO review(card_id, reviewed_at, grade, latency_ms, raw_text, accepted, layer, "
        "interval_before, interval_after) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            card_id,
            _iso(reviewed_at),
            grade,
            latency_ms,
            raw_text,
            int(accepted),
            layer,
            interval_before,
            interval_after,
        ),
    )
    conn.commit()


def deck_stats(conn: sqlite3.Connection, deck: str | None = None) -> dict[str, int]:
    base = "FROM card JOIN sched ON card.card_id = sched.card_id"
    where = ""
    params: list = []
    if deck is not None:
        where = " WHERE card.deck = ?"
        params.append(deck)

    def scalar(extra_clause: str, extra_params: list) -> int:
        joiner = " AND " if where else " WHERE "
        q = f"SELECT COUNT(*) {base}{where}{joiner if extra_clause else ''}{extra_clause}"
        return conn.execute(q, params + extra_params).fetchone()[0]

    total = scalar("", [])
    new_count = scalar("sched.state = ?", ["new"])
    learning_count = scalar("sched.state = ?", ["learning"])
    review_count = scalar("sched.state = ?", ["review"])
    lapsed_count = scalar("sched.state = ?", ["lapsed"])
    due_now = scalar("sched.due_at <= ?", [_iso(datetime.now(timezone.utc))])

    return {
        "total": total,
        "new": new_count,
        "learning": learning_count,
        "review": review_count,
        "due_now": due_now,
        "lapsed": lapsed_count,
    }


def tag_performance(
    conn: sqlite3.Connection, *, deck: str | None = None, since: datetime | None = None
) -> list[TagStat]:
    """Per-tag accuracy, one row per tag carried by any matching card.

    A review counts toward every tag on its card. `tags_json` is expanded in
    Python (not SQL) since it's a JSON array. `cards` and `lapses` are
    computed over all matching cards regardless of `since`; `attempts`,
    `correct`, and `median_latency_ms` are computed only over reviews within
    `since` (if given). Tags with zero attempts still appear -- callers that
    want to hide thin data (e.g. the CLI) filter on `attempts`.
    """
    card_query = (
        "SELECT card.card_id AS card_id, card.tags_json AS tags_json, "
        "sched.lapses AS lapses FROM card JOIN sched ON card.card_id = sched.card_id"
    )
    card_params: list = []
    if deck is not None:
        card_query += " WHERE card.deck = ?"
        card_params.append(deck)

    card_tags: dict[str, list[str]] = {}
    tag_cards: dict[str, set[str]] = {}
    tag_lapses: dict[str, int] = {}
    for row in conn.execute(card_query, card_params).fetchall():
        card_id = row["card_id"]
        # `why:` entries say why a rejected form is wrong; they are not
        # topics, and "weakest tags" listing `why:meaning` would be noise.
        tags = [t for t in json.loads(row["tags_json"]) if not t.startswith(WHY_TAG_PREFIX)]
        card_tags[card_id] = tags
        for tag in tags:
            tag_cards.setdefault(tag, set()).add(card_id)
            tag_lapses[tag] = tag_lapses.get(tag, 0) + row["lapses"]

    review_query = (
        "SELECT review.card_id AS card_id, review.accepted AS accepted, "
        "review.latency_ms AS latency_ms FROM review "
        "JOIN card ON review.card_id = card.card_id"
    )
    review_clauses: list[str] = []
    review_params: list = []
    if deck is not None:
        review_clauses.append("card.deck = ?")
        review_params.append(deck)
    if since is not None:
        review_clauses.append("review.reviewed_at >= ?")
        review_params.append(_iso(since))
    if review_clauses:
        review_query += " WHERE " + " AND ".join(review_clauses)

    tag_attempts: dict[str, int] = {}
    tag_correct: dict[str, int] = {}
    tag_latencies: dict[str, list[int]] = {}
    for row in conn.execute(review_query, review_params).fetchall():
        tags = card_tags.get(row["card_id"], [])
        for tag in tags:
            tag_attempts[tag] = tag_attempts.get(tag, 0) + 1
            if row["accepted"]:
                tag_correct[tag] = tag_correct.get(tag, 0) + 1
            if row["latency_ms"] is not None:
                tag_latencies.setdefault(tag, []).append(row["latency_ms"])

    stats: list[TagStat] = []
    for tag, cards in tag_cards.items():
        attempts = tag_attempts.get(tag, 0)
        correct = tag_correct.get(tag, 0)
        accuracy = correct / attempts if attempts > 0 else 0.0
        latencies = tag_latencies.get(tag)
        median_latency_ms = int(round(statistics.median(latencies))) if latencies else None
        stats.append(
            TagStat(
                tag=tag,
                attempts=attempts,
                correct=correct,
                accuracy=accuracy,
                cards=len(cards),
                lapses=tag_lapses.get(tag, 0),
                median_latency_ms=median_latency_ms,
            )
        )

    stats.sort(key=lambda t: (t.accuracy, -t.attempts))
    return stats


def hardest_cards(
    conn: sqlite3.Connection, *, deck: str | None = None, limit: int = 10
) -> list[tuple[Card, int, int]]:
    """(card, attempts, misses) for cards with >=2 attempts, worst first."""
    query = (
        "SELECT card.*, COUNT(review.review_id) AS attempts, "
        "SUM(CASE WHEN review.accepted = 0 THEN 1 ELSE 0 END) AS misses "
        "FROM card JOIN review ON card.card_id = review.card_id"
    )
    params: list = []
    if deck is not None:
        query += " WHERE card.deck = ?"
        params.append(deck)
    query += (
        " GROUP BY card.card_id HAVING COUNT(review.review_id) >= 2"
        " ORDER BY misses DESC, "
        "(CAST(attempts - misses AS REAL) / attempts) ASC LIMIT ?"
    )
    params.append(limit)

    results: list[tuple[Card, int, int]] = []
    for row in conn.execute(query, params).fetchall():
        card = _row_to_card(row)
        results.append((card, row["attempts"], row["misses"]))
    return results


# --- settings ----------------------------------------------------------------
# Learner choices made at `drill setup`. A key-value table rather than
# columns: `CREATE TABLE IF NOT EXISTS` reaches existing installs, a new
# column would not (there is no migration runner).

SETTING_GOAL_DATE = "goal_date"  # ISO date, e.g. "2026-12-20"; absent = none
SETTING_DIALECT = "dialect"      # one of DIALECTS
DIALECTS = ("es-ES", "es-419")
DEFAULT_DIALECT = "es-ES"


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str | None) -> None:
    """Store `value` under `key`; None deletes the key."""
    with conn:
        if value is None:
            conn.execute("DELETE FROM setting WHERE key = ?", (key,))
        else:
            conn.execute(
                "INSERT INTO setting(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )


def remove_cards(conn: sqlite3.Connection, card_ids: Sequence[str]) -> int:
    """Delete cards (and, by cascade, their schedule and reviews); return
    how many existed. Used when a dialect change stops serving a card."""
    if not card_ids:
        return 0
    with conn:
        n = 0
        for card_id in card_ids:
            n += conn.execute("DELETE FROM card WHERE card_id = ?", (card_id,)).rowcount
    return n


def goal_horizon(conn: sqlite3.Connection) -> datetime | None:
    """The goal date as a UTC midnight datetime, or None when none is set.

    A malformed stored value is treated as no goal rather than raised: the
    worst outcome is unclamped scheduling, never a session that won't start.
    """
    raw = get_setting(conn, SETTING_GOAL_DATE)
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def get_dialect(conn: sqlite3.Connection) -> str:
    value = get_setting(conn, SETTING_DIALECT, DEFAULT_DIALECT)
    return value if value in DIALECTS else DEFAULT_DIALECT
