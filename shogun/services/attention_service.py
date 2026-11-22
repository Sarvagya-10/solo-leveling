"""Attention span: deep-focus sessions.

* Multiple sessions per day are allowed.
* Per day we report the LONGEST continuous session and TOTAL deep-work minutes
  as separate metrics.
* Only days with logged sessions produce data points — nothing is prefilled or
  extrapolated. The baseline (default 5 min) and target (default 200 min) are
  reference lines, not data.
* Rolling average = mean of the daily-longest values logged within the
  trailing 7 calendar days (inclusive).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shogun.db.models import AttentionSession
from shogun.services import settings_service
from shogun.services.errors import NotFoundError, ValidationError


def add_session(session: Session, on_date: date, minutes: int, notes: str | None, *, today: date) -> AttentionSession:
    if on_date > today:
        raise ValidationError("Cannot log a future session")
    if not isinstance(minutes, int) or not 1 <= minutes <= 1440:
        raise ValidationError("Session length must be between 1 and 1440 minutes")
    row = AttentionSession(session_date=on_date, minutes=minutes, notes=(notes or "").strip() or None)
    session.add(row)
    session.flush()
    return row


def delete_session(session: Session, session_id: int) -> date:
    row = session.get(AttentionSession, session_id)
    if row is None:
        raise NotFoundError("Session not found")
    day = row.session_date
    session.delete(row)
    session.flush()
    return day


def sessions_on(session: Session, on_date: date) -> list[AttentionSession]:
    return list(session.scalars(select(AttentionSession).where(AttentionSession.session_date == on_date)
                                .order_by(AttentionSession.id)))


@dataclass
class DailyAttention:
    day: date
    longest: int
    total: int
    sessions: int
    rolling_avg: float | None = None


def daily_series(session: Session, start: date | None = None, end: date | None = None) -> list[DailyAttention]:
    stmt = select(AttentionSession.session_date, func.max(AttentionSession.minutes),
                  func.sum(AttentionSession.minutes), func.count(AttentionSession.id))
    if start:
        stmt = stmt.where(AttentionSession.session_date >= start)
    if end:
        stmt = stmt.where(AttentionSession.session_date <= end)
    rows = [DailyAttention(d, int(mx), int(tot), int(n))
            for d, mx, tot, n in session.execute(stmt.group_by(AttentionSession.session_date)
                                                 .order_by(AttentionSession.session_date))]
    for i, row in enumerate(rows):
        window = [r.longest for r in rows[: i + 1] if r.day > row.day - timedelta(days=7)]
        row.rolling_avg = round(sum(window) / len(window), 1)
    return rows


@dataclass
class AttentionSummary:
    baseline: int
    target: int
    personal_best: int | None
    personal_best_on: date | None
    latest_longest: int | None
    latest_day: date | None
    rolling_avg: float | None
    days_logged: int
    total_minutes: int

    @property
    def progress_pct(self) -> float:
        best = self.personal_best or 0
        return round(min(100.0, 100.0 * best / self.target), 1) if self.target else 0.0


def summary(session: Session) -> AttentionSummary:
    series = daily_series(session)
    baseline = int(settings_service.get_setting(session, "attention_baseline_minutes"))
    target = int(settings_service.get_setting(session, "attention_target_minutes"))
    if not series:
        return AttentionSummary(baseline, target, None, None, None, None, None, 0, 0)
    best = max(series, key=lambda r: (r.longest, -r.day.toordinal()))
    last = series[-1]
    return AttentionSummary(
        baseline=baseline, target=target, personal_best=best.longest, personal_best_on=best.day,
        latest_longest=last.longest, latest_day=last.day, rolling_avg=last.rolling_avg,
        days_logged=len(series), total_minutes=sum(r.total for r in series),
    )


def logged_dates(session: Session) -> set[date]:
    return set(session.scalars(select(AttentionSession.session_date).distinct()))
