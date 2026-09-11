"""Ebbinghaus scheduling.

Ported conceptually from WordReview's `views.py::review_lists`, adapted to
our list-level stage model. Two design choices worth flagging:

1. Delay_Hours = 4: reviews done before 04:00 local time count as the
   previous day. Matches WordReview and is friendly to students who study
   past midnight.

2. list-level "remembered" is derived from the last bit of each word's
   history (i.e. how the user did on THIS pass, not lifetime average).
   Threshold 0.7 balances lenience with progression rigor.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

STAGES: list[int] = [0, 1, 2, 4, 7, 15, 30]
DELAY_HOURS = 4
REMEMBER_THRESHOLD = 0.7
# UTC+8 fixed offset — target user is in China. Fixed offset avoids the
# tzdata dependency on Windows and dodges DST since CST doesn't observe.
LOCAL_TZ = timezone(timedelta(hours=8))


def study_now(reference: datetime | None = None) -> datetime:
    """`now` minus DELAY_HOURS in local tz. Feeds date + due checks so
    pre-dawn sessions still count against yesterday."""
    ref = reference or datetime.now(LOCAL_TZ)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=LOCAL_TZ)
    return ref.astimezone(LOCAL_TZ) - timedelta(hours=DELAY_HOURS)


def study_date(reference: datetime | None = None) -> date:
    return study_now(reference).date()


def next_stage_after(stage: int, remembered: bool) -> int:
    """Any post-review stage is at least 1 so `stage_is_due` correctly
    schedules a +1 day cooldown. Stage 0 is reserved for never-reviewed
    lists (BookList.last_review_date is None). Remember advances one stage;
    forget resets to stage 1 (redo tomorrow after a 1-day cooldown)."""
    if not remembered:
        return 1
    return min(max(stage, 0) + 1, len(STAGES) - 1)


def next_due_from_stage(stage: int, reference: datetime | None = None) -> datetime:
    """When is the review scheduled after landing on `stage` today?"""
    base = study_now(reference)
    days = STAGES[min(stage, len(STAGES) - 1)]
    return base + timedelta(days=days)


def list_remembered_from_histories(histories: list[str]) -> tuple[bool, float]:
    """Aggregate the last bit of each word's history string.

    Returns (remembered, session_rate). session_rate is the proportion of
    words the user got right on this pass — separate from `rate` (which is
    lifetime forget rate).

    Empty histories are treated as "not attempted this pass", excluded
    from denominator so a partial list doesn't get penalized.
    """
    tallies = [1 if h.endswith("1") else 0 for h in histories if h]
    if not tallies:
        return False, 0.0
    session_rate = sum(tallies) / len(tallies)
    return session_rate >= REMEMBER_THRESHOLD, session_rate


def stage_is_due(stage: int, last_review: date | None, today: date) -> bool:
    """Is a list currently due for review under Ebbinghaus?

    - Never-reviewed lists (stage 0, last_review None) are always "available".
    - Otherwise due iff today >= last_review + STAGES[stage].
    """
    if last_review is None:
        return True
    if stage >= len(STAGES):
        return False  # graduated
    delay = STAGES[stage]
    return today >= last_review + timedelta(days=delay)


def days_until_due(stage: int, last_review: date | None, today: date) -> int:
    """Positive = due in N days, 0 = due today, negative = overdue N days."""
    if last_review is None:
        return 0
    if stage >= len(STAGES):
        return 9999
    scheduled = last_review + timedelta(days=STAGES[stage])
    return (scheduled - today).days
