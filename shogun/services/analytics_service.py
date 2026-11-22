"""Execution analytics — transparent daily metrics.

Every metric is defined in :data:`METRIC_DEFINITIONS` (rendered in the UI).
Core principle: an item that was not logged is **not** counted as completed.
It stays in the denominator and is surfaced as *missing data*.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from shogun.db.models import Reflection, RevisionEvent
from shogun.services import (
    avoidance_service,
    habit_service,
    settings_service,
    study_log_service,
    worklog_service,
)
from shogun.timeutil import date_range

METRIC_DEFINITIONS: dict[str, str] = {
    "Study target efficiency": (
        "Completed study targets ÷ applicable study targets for the day. Applicable study targets are: "
        "(1) GATE study minutes ≥ daily target (if target > 0); (2) PYQs attempted ≥ daily PYQ target "
        "(if target > 0); (3) every revision due that day — counted complete only if completed on that day."
    ),
    "Habit completion": (
        "Habits done ÷ active habits. A habit is done when its logged value meets the target. "
        "Unlogged habits count as not done and are flagged as missing."
    ),
    "Not-to-do compliance": (
        "Rules logged as complied ÷ active rules. Unlogged rules are NOT assumed complied; they count "
        "against compliance and are flagged as missing."
    ),
    "Daily execution efficiency": (
        "All completed applicable targets ÷ all applicable targets: study targets + habits + not-to-do rules + "
        "finance target + research target + Adapt reflection. Unlogged items are in the denominator only."
    ),
    "Missing items": "Applicable items with no log at all for that day (shown as markers on the charts).",
    "Cumulative syllabus coverage": (
        "Number of DA topics whose knowledge coverage was 'mastered' as of each day (replayed from the audit "
        "history), and number of topics studied at least once."
    ),
}


@dataclass
class DayMetrics:
    day: date
    study_minutes: int
    study_target: int
    pyq_attempted: int
    pyq_target: int
    revisions_due: int
    revisions_done: int
    study_logged: bool
    study_applicable: int
    study_completed: int
    habits_applicable: int
    habits_done: int
    habits_missing: int
    avoid_applicable: int
    avoid_complied: int
    avoid_violated: int
    avoid_missing: int
    finance_minutes: int
    finance_met: bool
    research_minutes: int
    research_met: bool
    reflection_done: bool

    @staticmethod
    def _pct(num: int, den: int) -> float | None:
        return round(100.0 * num / den, 1) if den else None

    @property
    def study_pct(self) -> float | None:
        return self._pct(self.study_completed, self.study_applicable)

    @property
    def habits_pct(self) -> float | None:
        return self._pct(self.habits_done, self.habits_applicable)

    @property
    def avoid_pct(self) -> float | None:
        return self._pct(self.avoid_complied, self.avoid_applicable)

    @property
    def overall_applicable(self) -> int:
        return self.study_applicable + self.habits_applicable + self.avoid_applicable + 3

    @property
    def overall_completed(self) -> int:
        return (self.study_completed + self.habits_done + self.avoid_complied + int(self.finance_met)
                + int(self.research_met) + int(self.reflection_done))

    @property
    def overall_pct(self) -> float | None:
        return self._pct(self.overall_completed, self.overall_applicable)

    @property
    def missing_items(self) -> int:
        return (self.habits_missing + self.avoid_missing + (0 if self.study_logged else 1)
                + (0 if self.finance_minutes else 1) + (0 if self.research_minutes else 1)
                + (0 if self.reflection_done else 1))


def daily_metrics(session: Session, start: date, end: date) -> list[DayMetrics]:
    if end < start:
        return []
    settings = settings_service.get_all(session)
    study_target = int(settings["daily_study_target_minutes"])
    pyq_target = int(settings["daily_pyq_target"])
    fin_target = int(settings["finance_target_minutes"])
    res_target = int(settings["research_target_minutes"])

    study = study_log_service.daily_totals(session, start, end)
    habits = {d.day: d for d in habit_service.daily_summary(session, start, end)}
    avoid = {d.day: d for d in avoidance_service.daily_compliance(session, start, end)}
    finance = worklog_service.daily_minutes(session, "finance", start, end)
    research = worklog_service.daily_minutes(session, "research", start, end)
    reflections = set(session.scalars(select(Reflection.entry_date).where(
        Reflection.entry_date >= start, Reflection.entry_date <= end)))
    due: dict[date, list[RevisionEvent]] = defaultdict(list)
    for ev in session.scalars(select(RevisionEvent).where(RevisionEvent.due_date >= start,
                                                          RevisionEvent.due_date <= end)):
        due[ev.due_date].append(ev)

    out = []
    for day in date_range(start, end):
        s = study.get(day, {"minutes": 0, "pyq_attempted": 0})
        rev_due = due.get(day, [])
        rev_done = sum(1 for e in rev_due if e.status == "completed" and e.completed_on == day)
        applicable = (1 if study_target > 0 else 0) + (1 if pyq_target > 0 else 0) + len(rev_due)
        completed = (
            (1 if study_target > 0 and s["minutes"] >= study_target else 0)
            + (1 if pyq_target > 0 and s["pyq_attempted"] >= pyq_target else 0)
            + rev_done
        )
        h, a = habits[day], avoid[day]
        out.append(DayMetrics(
            day=day, study_minutes=s["minutes"], study_target=study_target, pyq_attempted=s["pyq_attempted"],
            pyq_target=pyq_target, revisions_due=len(rev_due), revisions_done=rev_done, study_logged=day in study,
            study_applicable=applicable, study_completed=completed,
            habits_applicable=h.applicable, habits_done=h.done, habits_missing=h.missing,
            avoid_applicable=a.applicable, avoid_complied=a.complied, avoid_violated=a.violated,
            avoid_missing=a.missing,
            finance_minutes=finance.get(day, 0), finance_met=finance.get(day, 0) >= fin_target,
            research_minutes=research.get(day, 0), research_met=research.get(day, 0) >= res_target,
            reflection_done=day in reflections,
        ))
    return out


def averages(metrics: list[DayMetrics]) -> dict[str, float | None]:
    def avg(values: list[float | None]) -> float | None:
        vals = [v for v in values if v is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    return {
        "study": avg([m.study_pct for m in metrics]),
        "habits": avg([m.habits_pct for m in metrics]),
        "avoid": avg([m.avoid_pct for m in metrics]),
        "overall": avg([m.overall_pct for m in metrics]),
        "missing_days": float(sum(1 for m in metrics if m.missing_items > 0)),
    }
