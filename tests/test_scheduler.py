from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest

from drill.scheduler import (
    Grade,
    SchedState,
    intervals_preview,
    new_state,
    review,
)

UTC = timezone.utc

# A goal date for the clamp tests (the original trip date; any date works).
HORIZON = datetime(2026, 10, 3, tzinfo=UTC)


def dt(y: int, m: int, d: int, h: int = 0, mi: int = 0) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=UTC)


FAR_HORIZON = dt(2030, 1, 1)  # keeps the trip clamp out of the way


# --- new -> learning -> review graduation -----------------------------------


def test_new_state_fields() -> None:
    now = dt(2026, 9, 1)
    s = new_state(now)
    assert s.due_at == now
    assert s.interval_days == 0.0
    assert s.ease == 2.5
    assert s.reps == 0
    assert s.lapses == 0
    assert s.state == "new"
    assert s.last_reviewed_at is None


def test_full_graduation_path_good_good() -> None:
    now = dt(2026, 9, 1)
    s = new_state(now)

    s1 = review(s, Grade.GOOD, now, horizon=FAR_HORIZON)
    assert s1.state == "learning"
    assert s1.interval_days == pytest.approx(10 / 1440)
    assert s1.reps == 1
    assert s1.due_at == now + timedelta(minutes=10)

    now2 = s1.due_at
    s2 = review(s1, Grade.GOOD, now2, horizon=FAR_HORIZON)
    assert s2.state == "review"
    assert s2.interval_days == pytest.approx(1.0)
    assert s2.due_at == now2 + timedelta(days=1)
    assert s2.reps == 2


def test_again_resets_learning_step_progress() -> None:
    now = dt(2026, 9, 1)
    s = new_state(now)
    s1 = review(s, Grade.GOOD, now, horizon=FAR_HORIZON)  # -> 10 min step
    s2 = review(s1, Grade.AGAIN, s1.due_at, horizon=FAR_HORIZON)
    assert s2.state == "learning"
    assert s2.interval_days == pytest.approx(1 / 1440)

    # next GOOD is a "first" good again, not a graduation
    s3 = review(s2, Grade.GOOD, s2.due_at, horizon=FAR_HORIZON)
    assert s3.state == "learning"
    assert s3.interval_days == pytest.approx(10 / 1440)


def test_hard_learning_step() -> None:
    now = dt(2026, 9, 1)
    s = new_state(now)
    s1 = review(s, Grade.HARD, now, horizon=FAR_HORIZON)
    assert s1.state == "learning"
    assert s1.interval_days == pytest.approx(5 / 1440)
    assert s1.due_at == now + timedelta(minutes=5)


def test_easy_graduates_immediately() -> None:
    now = dt(2026, 9, 1)
    s = new_state(now)
    s1 = review(s, Grade.EASY, now, horizon=FAR_HORIZON)
    assert s1.state == "review"
    assert s1.interval_days == pytest.approx(2.0)
    assert s1.due_at == now + timedelta(days=2)


# --- ease clamping -----------------------------------------------------------


def test_ease_clamps_at_lower_bound_under_repeated_hard() -> None:
    now = dt(2026, 9, 1)
    s = new_state(now)
    s = review(s, Grade.EASY, now, horizon=FAR_HORIZON)  # graduate to review
    for _ in range(50):
        s = review(s, Grade.HARD, s.due_at, horizon=FAR_HORIZON)
    assert s.ease == pytest.approx(1.3)
    assert s.ease >= 1.3


def test_ease_clamps_at_upper_bound_under_repeated_easy() -> None:
    now = dt(2026, 9, 1)
    s = new_state(now)
    s = review(s, Grade.EASY, now, horizon=FAR_HORIZON)  # graduate to review
    # Interval grows ~3x per EASY review, so keep the count well under the
    # point where it would overflow datetime's year-9999 ceiling.
    for _ in range(10):
        s = review(s, Grade.EASY, s.due_at, horizon=FAR_HORIZON)
    assert s.ease == pytest.approx(3.0)
    assert s.ease <= 3.0


# --- lapses --------------------------------------------------------------


def test_lapse_from_review_resets_and_increments_lapses() -> None:
    now = dt(2026, 9, 1)
    s = new_state(now)
    s = review(s, Grade.EASY, now, horizon=FAR_HORIZON)  # -> review, 2 days
    assert s.lapses == 0

    prev_ease = s.ease
    s2 = review(s, Grade.AGAIN, s.due_at, horizon=FAR_HORIZON)
    assert s2.state == "lapsed"
    assert s2.lapses == 1
    assert s2.interval_days == pytest.approx(10 / 1440)
    assert s2.ease == pytest.approx(max(1.3, prev_ease - 0.20))
    assert s2.due_at == s.due_at + timedelta(minutes=10)
    assert s2.reps == s.reps + 1


def test_repeated_lapses_accumulate() -> None:
    now = dt(2026, 9, 1)
    s = new_state(now)
    s = review(s, Grade.EASY, now, horizon=FAR_HORIZON)
    s = review(s, Grade.AGAIN, s.due_at, horizon=FAR_HORIZON)
    s = review(s, Grade.AGAIN, s.due_at, horizon=FAR_HORIZON)
    assert s.lapses == 2
    assert s.state == "lapsed"


# --- multiplicative growth for a mature card ---------------------------------


def test_intervals_grow_multiplicatively_for_mature_card() -> None:
    now = dt(2026, 9, 1)
    s = SchedState(
        due_at=now,
        interval_days=10.0,
        ease=2.5,
        reps=5,
        lapses=0,
        state="review",
        last_reviewed_at=now - timedelta(days=10),
    )
    s1 = review(s, Grade.GOOD, now, horizon=FAR_HORIZON)
    assert s1.interval_days == pytest.approx(10.0 * 2.5)

    s2 = review(s1, Grade.GOOD, s1.due_at, horizon=FAR_HORIZON)
    assert s2.interval_days == pytest.approx(s1.interval_days * s1.ease)
    assert s2.interval_days > s1.interval_days > s.interval_days


def test_hard_and_easy_multipliers_on_review_card() -> None:
    now = dt(2026, 9, 1)
    s = SchedState(
        due_at=now,
        interval_days=10.0,
        ease=2.5,
        reps=5,
        lapses=0,
        state="review",
        last_reviewed_at=now - timedelta(days=10),
    )
    hard = review(s, Grade.HARD, now, horizon=FAR_HORIZON)
    assert hard.interval_days == pytest.approx(10.0 * 2.5 * 0.6)
    assert hard.ease == pytest.approx(2.35)

    easy = review(s, Grade.EASY, now, horizon=FAR_HORIZON)
    assert easy.interval_days == pytest.approx(10.0 * 2.5 * 1.3)
    assert easy.ease == pytest.approx(2.65)


# --- purity ------------------------------------------------------------------


def test_review_does_not_mutate_input() -> None:
    now = dt(2026, 9, 1)
    s = new_state(now)
    snapshot = copy.deepcopy(s)
    _ = review(s, Grade.GOOD, now, horizon=FAR_HORIZON)
    assert s == snapshot


def test_review_does_not_mutate_input_for_review_card() -> None:
    now = dt(2026, 9, 1)
    s = SchedState(
        due_at=now,
        interval_days=10.0,
        ease=2.5,
        reps=5,
        lapses=1,
        state="review",
        last_reviewed_at=now - timedelta(days=10),
    )
    snapshot = copy.deepcopy(s)
    for grade in Grade:
        _ = review(s, grade, now, horizon=FAR_HORIZON)
        assert s == snapshot


# --- intervals_preview agreement ---------------------------------------------


def test_intervals_preview_agrees_with_review() -> None:
    now = dt(2026, 9, 1)
    s = SchedState(
        due_at=now,
        interval_days=10.0,
        ease=2.5,
        reps=5,
        lapses=0,
        state="review",
        last_reviewed_at=now - timedelta(days=10),
    )
    preview = intervals_preview(s, now, horizon=FAR_HORIZON)
    for grade in Grade:
        actual = review(s, grade, now, horizon=FAR_HORIZON).interval_days
        assert preview[grade] == pytest.approx(actual)


def test_intervals_preview_agrees_with_review_during_learning() -> None:
    now = dt(2026, 9, 1)
    s = new_state(now)
    preview = intervals_preview(s, now, horizon=FAR_HORIZON)
    for grade in Grade:
        actual = review(s, grade, now, horizon=FAR_HORIZON).interval_days
        assert preview[grade] == pytest.approx(actual)


# --- horizon clamp -------------------------------------------------------


def test_no_goal_date_means_no_clamp() -> None:
    now = dt(2026, 9, 20)
    s = SchedState(
        due_at=now, interval_days=30.0, ease=2.5, reps=10, lapses=0,
        state="review", last_reviewed_at=now - timedelta(days=30),
    )
    result = review(s, Grade.GOOD, now)  # horizon=None
    assert result.interval_days == pytest.approx(30.0 * 2.5)
    assert result.due_at == now + timedelta(days=30.0 * 2.5)


def test_horizon_clamp_pulls_mature_card_before_departure() -> None:
    now = dt(2026, 9, 20)
    s = SchedState(
        due_at=now,
        interval_days=30.0,
        ease=2.5,
        reps=10,
        lapses=0,
        state="review",
        last_reviewed_at=now - timedelta(days=30),
    )
    # Unclamped GOOD would be 30 * 2.5 = 75 days out -> way past 2026-10-03.
    result = review(s, Grade.GOOD, now, horizon=HORIZON)
    assert result.due_at < HORIZON
    assert result.due_at > now

    # Roughly half the remaining time (13 days -> ~6.5 days), floored at 1 day.
    remaining = HORIZON - now
    expected = now + remaining / 2
    assert abs((result.due_at - expected).total_seconds()) < 60


def test_horizon_clamp_disengages_once_past_horizon() -> None:
    now = HORIZON + timedelta(days=5)
    s = SchedState(
        due_at=now,
        interval_days=30.0,
        ease=2.5,
        reps=10,
        lapses=0,
        state="review",
        last_reviewed_at=now - timedelta(days=30),
    )
    result = review(s, Grade.GOOD, now, horizon=HORIZON)  # now is past it
    assert result.interval_days == pytest.approx(30.0 * 2.5)
    assert result.due_at == now + timedelta(days=30.0 * 2.5)


def test_horizon_clamp_floor_does_not_overshoot_when_close_to_departure() -> None:
    # Less than a day of runway left: the 1-day floor would itself land
    # past the horizon, so the fallback (just before horizon) must apply.
    now = HORIZON - timedelta(hours=12)
    s = SchedState(
        due_at=now,
        interval_days=30.0,
        ease=2.5,
        reps=10,
        lapses=0,
        state="review",
        last_reviewed_at=now - timedelta(days=30),
    )
    result = review(s, Grade.GOOD, now, horizon=HORIZON)
    assert now < result.due_at < HORIZON


def test_horizon_clamp_never_schedules_past_the_horizon(tmp_path=None) -> None:
    """Inside the final minute the clamp must disengage, not overshoot.

    QA found that with `now` within ~60s of the horizon the last-resort
    fallback produced `now + 1 minute`, landing up to 59s AFTER the horizon
    -- breaking the invariant the clamp exists to enforce.
    """
    from datetime import timedelta as _td

    horizon = HORIZON
    for seconds_before in (3600, 600, 90, 59, 30, 1):
        now = horizon - _td(seconds=seconds_before)
        s = SchedState(
            due_at=now, interval_days=30.0, ease=2.5, reps=5, lapses=0,
            state="review", last_reviewed_at=None,
        )
        nxt = review(s, Grade.GOOD, now, horizon=horizon)
        if seconds_before > 60:
            assert nxt.due_at < horizon, (
                f"{seconds_before}s before horizon -> due {nxt.due_at} is past it"
            )
        else:
            # No runway left to protect; normal SM-2 applies, as after departure.
            assert nxt.due_at > now
