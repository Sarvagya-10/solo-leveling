"""Time helpers.

Convention used everywhere in the app:

* Instants (``created_at``, ``completed_at`` …) are stored as **naive UTC**
  datetimes.
* Calendar days (``log_date``, ``due_date`` …) are stored as ``date`` values in
  the user's **local** timezone (configurable, default Asia/Kolkata).

All scheduling arithmetic operates on ``date`` objects, so it never depends on
the wall-clock time or on daylight-saving transitions.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo


def utcnow() -> datetime:
    """Current instant as naive UTC (the storage format)."""
    return datetime.now(UTC).replace(tzinfo=None)


def local_now(tz_name: str, *, now_utc: datetime | None = None) -> datetime:
    base = now_utc or utcnow()
    return base.replace(tzinfo=UTC).astimezone(ZoneInfo(tz_name))


def local_today(tz_name: str, *, now_utc: datetime | None = None) -> date:
    """Today's calendar date in the user's timezone."""
    return local_now(tz_name, now_utc=now_utc).date()


def local_date_of(instant_utc: datetime, tz_name: str) -> date:
    """Local calendar date of a stored naive-UTC instant."""
    return instant_utc.replace(tzinfo=UTC).astimezone(ZoneInfo(tz_name)).date()


def to_local_str(instant_utc: datetime | None, tz_name: str, fmt: str = "%Y-%m-%d %H:%M") -> str:
    if instant_utc is None:
        return "—"
    return instant_utc.replace(tzinfo=UTC).astimezone(ZoneInfo(tz_name)).strftime(fmt)


def add_days(day: date, offset: int) -> date:
    return day + timedelta(days=offset)


def date_range(start: date, end: date) -> Iterator[date]:
    """Inclusive range of calendar dates."""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def parse_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)
