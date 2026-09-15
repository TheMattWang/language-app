"""SM-2-derived spaced-repetition scheduler for a 19-day Spanish drill.

Pure, stdlib-only, no I/O. See ``new_state``, ``review``, and
``intervals_preview`` for the public API.

HORIZON RULE (the one non-standard piece of this module)
----------------------------------------------------------
The user leaves for Spain on 2026-10-03T00:00:00+00:00 (``DEFAULT_HORIZON``).
An interval that would land a card's next review *after* that date is
useless -- the card would never be seen again before the trip.

So every computed interval is passed through a horizon clamp:

* If ``now`` is already at or past ``horizon``, the clamp is a no-op --
  normal SM-2 intervals apply unmodified (the tool stays useful after the
  trip).
* Otherwise, if ``now + interval`` would land after ``horizon``, the
  interval is replaced with roughly *half of the remaining time to the
  horizon* (``(horizon - now) / 2``), floored at 1 day so the clamp
  doesn't degenerate into absurdly short intervals for a card with a lot
  of runway left. In the rare case where less than ~2 days remain before
  the horizon (so the 1-day floor would itself overshoot), the clamp
  falls back to landing 1 minute before the horizon (or 1 minute after
  ``now``, whichever is later) -- the invariant that a clamped review
  always comes due strictly before the horizon is never broken.

The clamped interval (not the original, larger one) is what gets stored
back into ``SchedState.interval_days`` and used as the base for the next
review's multiplicative SM-2 math. This means a card gets pulled into a
tighter, horizon-compressed rhythm once it would otherwise have overshot
the trip, rather than silently reverting to a long interval next time.

LEARNING-STEP ENCODING (implementation note, not part of the public API)
--------------------------------------------------------------------------
``SchedState`` has no dedicated "which learning step am I on" field, so
the in-progress learning step is encoded in ``interval_days`` itself
(as a fraction of a day, e.g. 10 minutes == 10/1440 days) while
``state`` is ``"learning"``. A GOOD grade graduates the card to
``"review"`` only when the card is already sitting at the 10-minute
step (i.e. the *previous* grade was also GOOD) -- any AGAIN or HARD in
between resets the step and the GOOD streak needed to graduate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import IntEnum

__all__ = ["Grade", "SchedState", "new_state", "review", "intervals_preview"]

# --- constants -------------------------------------------------------------

DEFAULT_HORIZON: datetime = datetime(2026, 10, 3, 0, 0, 0, tzinfo=timezone.utc)

MINUTE_DAYS: float = 1.0 / 1440.0

_AGAIN_LEARNING_STEP_DAYS = MINUTE_DAYS * 1
_HARD_LEARNING_STEP_DAYS = MINUTE_DAYS * 5
_GOOD_LEARNING_STEP_DAYS = MINUTE_DAYS * 10
_RELEARN_STEP_DAYS = MINUTE_DAYS * 10

_GRADUATE_GOOD_INTERVAL_DAYS = 1.0
_GRADUATE_EASY_INTERVAL_DAYS = 2.0

_EASE_MIN = 1.3
_EASE_MAX = 3.0
_MIN_INTERVAL_DAYS = MINUTE_DAYS  # 1 minute floor


class Grade(IntEnum):
    AGAIN = 0  # failed
    HARD = 1
    GOOD = 2
    EASY = 3


@dataclass(frozen=True)
class SchedState:
    due_at: datetime
    interval_days: float
    ease: float
    reps: int
    lapses: int
    state: str  # "new" | "learning" | "review" | "lapsed"
    last_reviewed_at: datetime | None


def new_state(now: datetime) -> SchedState:
    """A freshly-introduced card: due immediately, no history."""
    return SchedState(
        due_at=now,
        interval_days=0.0,
        ease=2.5,
        reps=0,
        lapses=0,
        state="new",
        last_reviewed_at=None,
    )


def _clamp_ease(ease: float) -> float:
    return min(_EASE_MAX, max(_EASE_MIN, ease))


def _clamp_interval(days: float) -> float:
    return max(days, _MIN_INTERVAL_DAYS)


def _learning_transition(s: SchedState, grade: Grade) -> tuple[float, str, float]:
    """Handle a review of a "new" or "learning" card.

    Returns (interval_days, new_state_label, new_ease).
    """
    ease = s.ease  # ease is not adjusted during the learning phase
    if grade == Grade.AGAIN:
        return _AGAIN_LEARNING_STEP_DAYS, "learning", ease
    if grade == Grade.HARD:
        return _HARD_LEARNING_STEP_DAYS, "learning", ease
    if grade == Grade.GOOD:
        already_on_good_step = math.isclose(
            s.interval_days, _GOOD_LEARNING_STEP_DAYS, rel_tol=0.0, abs_tol=1e-9
        )
        if already_on_good_step:
            return _GRADUATE_GOOD_INTERVAL_DAYS, "review", ease
        return _GOOD_LEARNING_STEP_DAYS, "learning", ease
    # EASY
    return _GRADUATE_EASY_INTERVAL_DAYS, "review", ease


def _review_transition(s: SchedState, grade: Grade) -> tuple[float, str, float, bool]:
    """Handle a review of a "review" or "lapsed" card.

    Returns (interval_days, new_state_label, new_ease, did_lapse).
    """
    if grade == Grade.AGAIN:
        ease = _clamp_ease(s.ease - 0.20)
        return _RELEARN_STEP_DAYS, "lapsed", ease, True

    if grade == Grade.HARD:
        interval = s.interval_days * s.ease * 0.6
        ease = _clamp_ease(s.ease - 0.15)
    elif grade == Grade.GOOD:
        interval = s.interval_days * s.ease
        ease = s.ease
    else:  # EASY
        interval = s.interval_days * s.ease * 1.3
        ease = _clamp_ease(s.ease + 0.15)

    return _clamp_interval(interval), "review", ease, False


def _due_with_horizon(
    now: datetime, interval_days: float, horizon: datetime
) -> tuple[datetime, float]:
    """Apply the horizon clamp (see module docstring) and return
    (due_at, effective_interval_days)."""
    raw_due = now + timedelta(days=interval_days)

    if now >= horizon or raw_due <= horizon:
        return raw_due, interval_days

    remaining = horizon - now
    remaining_days = remaining.total_seconds() / 86400.0
    clamped_days = max(remaining_days / 2.0, 1.0)
    due = now + timedelta(days=clamped_days)

    if due >= horizon:
        # Less than ~2 days of runway left: the 1-day floor would itself
        # overshoot the horizon. Fall back to landing just before it.
        due = horizon - timedelta(minutes=1)
        if due <= now:
            due = now + timedelta(minutes=1)
        clamped_days = (due - now).total_seconds() / 86400.0

    return due, clamped_days


def review(
    s: SchedState,
    grade: Grade,
    now: datetime,
    *,
    horizon: datetime | None = None,
) -> SchedState:
    """Return the NEXT state after reviewing ``s`` with ``grade`` at ``now``.

    Pure: does not mutate ``s``.
    """
    if horizon is None:
        horizon = DEFAULT_HORIZON

    if s.state in ("new", "learning"):
        interval, next_state, ease = _learning_transition(s, grade)
        did_lapse = False
    else:  # "review" or "lapsed"
        interval, next_state, ease, did_lapse = _review_transition(s, grade)

    interval = _clamp_interval(interval)
    due_at, interval = _due_with_horizon(now, interval, horizon)
    interval = _clamp_interval(interval)

    return SchedState(
        due_at=due_at,
        interval_days=interval,
        ease=ease,
        reps=s.reps + 1,
        lapses=s.lapses + (1 if did_lapse else 0),
        state=next_state,
        last_reviewed_at=now,
    )


def intervals_preview(
    s: SchedState,
    now: datetime,
    *,
    horizon: datetime | None = None,
) -> dict[Grade, float]:
    """interval_days each grade would produce, without committing to one."""
    return {
        grade: review(s, grade, now, horizon=horizon).interval_days
        for grade in Grade
    }
