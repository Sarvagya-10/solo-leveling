"""Daily habits with configurable targets.

Each (habit, day) is one of three states — never assumed:

* ``done``     an entry exists and value ≥ target
* ``not_done`` an entry exists and value < target (explicitly logged)
* ``missing``  no entry for that day

``check`` habits store 1 (done) or 0 (not done). ``numeric`` habits store the
measured amount (e.g. water in litres).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from shogun.db.models import Habit, HabitEntry
from shogun.services.errors import NotFoundError, ValidationError
from shogun.timeutil import date_range


def list_habits(session: Session, *, active_only: bool = True) -> list[Habit]:
    stmt = select(Habit).order_by(Habit.sort_order, Habit.id)
    if active_only:
        stmt = stmt.where(Habit.active.is_(True))
    return list(session.scalars(stmt))


def _habit(session: Session, habit_id: int) -> Habit:
    habit = session.get(Habit, habit_id)
    if habit is None:
        raise NotFoundError("Habit not found")
    return habit


def entry_state(habit: Habit, entry: HabitEntry | None) -> str:
    if entry is None:
        return "missing"
    return "done" if entry.value >= habit.target_value else "not_done"


def upsert_entry(session: Session, habit_id: int, on_date: date, value: float, notes: str | None, *,
                 today: date) -> HabitEntry:
    habit = _habit(session, habit_id)
    if on_date > today:
        raise ValidationError("Cannot log habits for a future date")
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{habit.name}: value must be a number") from exc
    if value < 0:
        raise ValidationError(f"{habit.name}: value cannot be negative")
    if habit.kind == "check" and value not in (0.0, 1.0):
        raise ValidationError(f"{habit.name}: choose done or not done")
    if habit.kind == "numeric" and value > 10000:
        raise ValidationError(f"{habit.name}: value looks too large")
    entry = session.scalar(select(HabitEntry).where(HabitEntry.habit_id == habit_id, HabitEntry.entry_date == on_date))
    if entry is None:
        entry = HabitEntry(habit_id=habit_id, entry_date=on_date, value=value)
        session.add(entry)
    entry.value = value
    entry.notes = (notes or "").strip() or None
    session.flush()
    return entry


def clear_entry(session: Session, habit_id: int, on_date: date) -> None:
    entry = session.scalar(select(HabitEntry).where(HabitEntry.habit_id == habit_id, HabitEntry.entry_date == on_date))
    if entry is not None:
        session.delete(entry)
        session.flush()


def entries_between(session: Session, start: date, end: date) -> dict[tuple[int, date], HabitEntry]:
    rows = session.scalars(select(HabitEntry).where(HabitEntry.entry_date >= start, HabitEntry.entry_date <= end))
    return {(e.habit_id, e.entry_date): e for e in rows}


@dataclass
class HabitDay:
    day: date
    applicable: int
    done: int
    not_done: int
    missing: int

    @property
    def completion_pct(self) -> float:
        return round(100.0 * self.done / self.applicable, 1) if self.applicable else 0.0


def daily_summary(session: Session, start: date, end: date) -> list[HabitDay]:
    habits = list_habits(session)
    entries = entries_between(session, start, end)
    out = []
    for day in date_range(start, end):
        states = [entry_state(h, entries.get((h.id, day))) for h in habits]
        out.append(HabitDay(day, len(habits), states.count("done"), states.count("not_done"), states.count("missing")))
    return out


def update_habit(session: Session, habit_id: int, *, name: str | None = None, target: float | None = None,
                 unit: str | None = None, active: bool | None = None) -> Habit:
    habit = _habit(session, habit_id)
    if name is not None:
        if not name.strip():
            raise ValidationError("Habit name cannot be empty")
        habit.name = name.strip()[:80]
    if target is not None:
        if habit.kind == "check":
            target = 1.0
        if target <= 0:
            raise ValidationError("Target must be greater than 0")
        habit.target_value = float(target)
    if unit is not None and habit.kind == "numeric":
        habit.unit = unit.strip()[:20] or None
    if active is not None:
        habit.active = active
    session.flush()
    return habit


def add_habit(session: Session, name: str, kind: str, target: float, unit: str | None) -> Habit:
    if kind not in ("check", "numeric"):
        raise ValidationError("Habit kind must be check or numeric")
    clean = (name or "").strip()
    if not clean:
        raise ValidationError("Habit name cannot be empty")
    key = "custom_" + "".join(c if c.isalnum() else "_" for c in clean.lower())[:30]
    if session.scalar(select(Habit.id).where(Habit.key == key)):
        raise ValidationError("A habit with this name already exists")
    if kind == "check":
        target, unit = 1.0, None
    elif target <= 0:
        raise ValidationError("Target must be greater than 0")
    order = len(list_habits(session, active_only=False)) + 1
    habit = Habit(key=key, name=clean[:80], kind=kind, unit=(unit or "").strip() or None,
                  target_value=float(target), sort_order=order)
    session.add(habit)
    session.flush()
    return habit


def habit_streak(session: Session, habit: Habit, end: date) -> int:
    """Consecutive days ending at ``end`` (or the day before, if today is not logged yet) with the habit done."""
    entries = {e.entry_date: e for e in session.scalars(select(HabitEntry).where(HabitEntry.habit_id == habit.id))}
    day, streak = end, 0
    if entry_state(habit, entries.get(day)) == "missing":
        day = date.fromordinal(day.toordinal() - 1)
    while entry_state(habit, entries.get(day)) == "done":
        streak += 1
        day = date.fromordinal(day.toordinal() - 1)
    return streak
