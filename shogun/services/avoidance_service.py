"""Daily NOT-TO-DO compliance (private).

Each (rule, day) is ``complied``, ``violated`` or ``missing`` (no entry).
Missing data is never treated as success: compliance % = complied / applicable,
and a missing day breaks a clean streak. This data is never sent to any AI
provider and is excluded from CSV exports unless explicitly included.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from shogun.db.models import AvoidanceEntry, AvoidanceRule
from shogun.services.errors import NotFoundError, ValidationError
from shogun.timeutil import date_range

STATUSES = ("complied", "violated")


def list_rules(session: Session, *, active_only: bool = True) -> list[AvoidanceRule]:
    stmt = select(AvoidanceRule).order_by(AvoidanceRule.sort_order, AvoidanceRule.id)
    if active_only:
        stmt = stmt.where(AvoidanceRule.active.is_(True))
    return list(session.scalars(stmt))


def set_status(session: Session, rule_id: int, on_date: date, status: str, notes: str | None, *,
               today: date) -> AvoidanceEntry:
    if status not in STATUSES:
        raise ValidationError("Status must be complied or violated")
    if on_date > today:
        raise ValidationError("Cannot log a future date")
    if session.get(AvoidanceRule, rule_id) is None:
        raise NotFoundError("Rule not found")
    entry = session.scalar(select(AvoidanceEntry).where(AvoidanceEntry.rule_id == rule_id,
                                                        AvoidanceEntry.entry_date == on_date))
    if entry is None:
        entry = AvoidanceEntry(rule_id=rule_id, entry_date=on_date, status=status)
        session.add(entry)
    entry.status = status
    entry.notes = (notes or "").strip() or None
    session.flush()
    return entry


def clear_status(session: Session, rule_id: int, on_date: date) -> None:
    entry = session.scalar(select(AvoidanceEntry).where(AvoidanceEntry.rule_id == rule_id,
                                                        AvoidanceEntry.entry_date == on_date))
    if entry is not None:
        session.delete(entry)
        session.flush()


def entries_between(session: Session, start: date, end: date) -> dict[tuple[int, date], AvoidanceEntry]:
    rows = session.scalars(select(AvoidanceEntry).where(AvoidanceEntry.entry_date >= start,
                                                        AvoidanceEntry.entry_date <= end))
    return {(e.rule_id, e.entry_date): e for e in rows}


@dataclass
class ComplianceDay:
    day: date
    applicable: int
    complied: int
    violated: int
    missing: int

    @property
    def compliance_pct(self) -> float:
        return round(100.0 * self.complied / self.applicable, 1) if self.applicable else 0.0

    @property
    def logged_compliance_pct(self) -> float | None:
        logged = self.complied + self.violated
        return round(100.0 * self.complied / logged, 1) if logged else None


def daily_compliance(session: Session, start: date, end: date) -> list[ComplianceDay]:
    rules = list_rules(session)
    entries = entries_between(session, start, end)
    out = []
    for day in date_range(start, end):
        states = [entries[(r.id, day)].status if (r.id, day) in entries else "missing" for r in rules]
        out.append(ComplianceDay(day, len(rules), states.count("complied"), states.count("violated"),
                                 states.count("missing")))
    return out


def rule_streak(session: Session, rule_id: int, end: date) -> int:
    """Consecutive complied days ending at ``end`` (or yesterday if today is unlogged)."""
    entries = {e.entry_date: e.status for e in session.scalars(
        select(AvoidanceEntry).where(AvoidanceEntry.rule_id == rule_id))}
    day = end if end in entries else end - timedelta(days=1)
    streak = 0
    while entries.get(day) == "complied":
        streak += 1
        day -= timedelta(days=1)
    return streak


def full_compliance_streak(session: Session, end: date) -> int:
    """Consecutive days on which every active rule was logged as complied."""
    rules = list_rules(session)
    if not rules:
        return 0
    day = end
    days = daily_compliance(session, end - timedelta(days=400), end)
    by_day = {d.day: d for d in days}
    if by_day[end].missing == by_day[end].applicable:
        day = end - timedelta(days=1)
    streak = 0
    while day in by_day and by_day[day].complied == by_day[day].applicable:
        streak += 1
        day -= timedelta(days=1)
    return streak
