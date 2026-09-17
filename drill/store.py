"""Persistence + JSONL import for the Spanish drill tool.

Owns the SQLite schema (see schema.sql), card import, scheduling state
storage, and review logging. All datetimes stored in the DB are
timezone-aware UTC, serialized via .isoformat() and parsed with
datetime.fromisoformat().
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

DEFAULT_DB = Path.home() / ".langapp" / "drill.db"

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
    "grammar_repair": 3,
}
_DEFAULT_DECK_RANK = 2



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


def import_jsonl(conn: sqlite3.Connection, path: Path) -> ImportResult:
    """Upsert cards from a JSONL file. Safely re-runnable. One transaction."""
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines()

    added = 0
    updated = 0
    unchanged = 0
    errors: list[str] = []

    now_iso = _iso(datetime.now(timezone.utc))

    conn.execute("BEGIN")
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

    return ImportResult(added=added, updated=updated, unchanged=unchanged, errors=tuple(errors))


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
    picked: list[tuple[Card, SchedRow]] = []
    while len(picked) < budget and any(by_deck[d] for d in decks):
        for d in decks:
            if len(picked) >= budget:
                break
            if by_deck[d]:
                picked.append(by_deck[d].pop(0))
    return picked


def new_cards_introduced_today(
    conn: sqlite3.Connection, now: datetime, *, deck: str | None = None
) -> int:
    """Count of distinct cards whose earliest-ever review falls on `now`'s UTC day.

    A card is "introduced" the day it is first reviewed, not the day it was
    imported -- `MIN(reviewed_at)` per card_id is the source of truth.
    """
    day_start = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

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
    new_per_day: int = 25,
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
        tags = json.loads(row["tags_json"])
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
