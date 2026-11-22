"""ADAPT — daily reflection with three mandatory prompts."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from shogun.db.models import Reflection
from shogun.services.errors import NotFoundError, ValidationError

PROMPTS = {
    "went_well": "What went well?",
    "did_not_go_well": "What did not go well?",
    "smallest_step": "Smallest possible step to improve",
}


def upsert(session: Session, on_date: date, went_well: str, did_not_go_well: str, smallest_step: str, *,
           today: date) -> Reflection:
    if on_date > today:
        raise ValidationError("Cannot reflect on a future date")
    values = {"went_well": went_well, "did_not_go_well": did_not_go_well, "smallest_step": smallest_step}
    for key, value in values.items():
        if len((value or "").strip()) < 3:
            raise ValidationError(f"'{PROMPTS[key]}' is required (at least 3 characters)")
        if len(value) > 5000:
            raise ValidationError(f"'{PROMPTS[key]}' is too long (max 5000 characters)")
    row = session.scalar(select(Reflection).where(Reflection.entry_date == on_date))
    if row is None:
        row = Reflection(entry_date=on_date, went_well="", did_not_go_well="", smallest_step="")
        session.add(row)
    row.went_well = went_well.strip()
    row.did_not_go_well = did_not_go_well.strip()
    row.smallest_step = smallest_step.strip()
    session.flush()
    return row


def get(session: Session, on_date: date) -> Reflection | None:
    return session.scalar(select(Reflection).where(Reflection.entry_date == on_date))


def delete(session: Session, reflection_id: int) -> date:
    row = session.get(Reflection, reflection_id)
    if row is None:
        raise NotFoundError("Reflection not found")
    day = row.entry_date
    session.delete(row)
    session.flush()
    return day


def save_ai_suggestion(session: Session, reflection_id: int, suggestion: str | None) -> None:
    row = session.get(Reflection, reflection_id)
    if row is None:
        raise NotFoundError("Reflection not found")
    row.ai_suggestion = (suggestion or "").strip() or None
    session.flush()


def search(session: Session, query: str | None = None, limit: int = 365) -> list[Reflection]:
    stmt = select(Reflection).order_by(Reflection.entry_date.desc()).limit(limit)
    if query and query.strip():
        like = f"%{query.strip()}%"
        stmt = stmt.where(or_(Reflection.went_well.ilike(like), Reflection.did_not_go_well.ilike(like),
                              Reflection.smallest_step.ilike(like)))
    return list(session.scalars(stmt))


def dates(session: Session) -> set[date]:
    return set(session.scalars(select(Reflection.entry_date)))


def streak(session: Session, end: date) -> int:
    have = dates(session)
    day = end if end in have else end - timedelta(days=1)
    count = 0
    while day in have:
        count += 1
        day -= timedelta(days=1)
    return count


def count(session: Session) -> int:
    return int(session.scalar(select(func.count(Reflection.id))) or 0)
