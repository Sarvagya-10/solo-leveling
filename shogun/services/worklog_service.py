"""Finance and Research daily work logs (independently tracked).

A day *meets target* when the summed duration of that domain's logs is at
least the configured target (default 60 minutes each).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from shogun.db.models import Project, WorkLog
from shogun.services import settings_service
from shogun.services.defaults import FINANCE_PROJECT
from shogun.services.errors import NotFoundError, ValidationError
from shogun.timeutil import date_range

DOMAINS = ("finance", "research")
TARGET_KEY = {"finance": "finance_target_minutes", "research": "research_target_minutes"}


@dataclass
class WorkLogInput:
    domain: str
    log_date: date
    duration_minutes: int
    what_done: str
    research_direction: str | None = None
    next_steps: str | None = None
    project_name: str | None = None
    tags: str | None = None
    milestone: str | None = None
    outputs: str | None = None
    references_text: str | None = None


def _clean(value: str | None) -> str | None:
    return (value or "").strip() or None


def get_or_create_project(session: Session, domain: str, name: str | None) -> Project | None:
    clean = _clean(name)
    if clean is None:
        return None
    if len(clean) > 120:
        raise ValidationError("Project name is too long (max 120 characters)")
    project = session.scalar(select(Project).where(Project.domain == domain, func.lower(Project.name) == clean.lower()))
    if project is None:
        project = Project(domain=domain, name=clean)
        session.add(project)
        session.flush()
    return project


def add_log(session: Session, data: WorkLogInput, *, today: date) -> WorkLog:
    if data.domain not in DOMAINS:
        raise ValidationError("Unknown domain")
    if data.log_date > today:
        raise ValidationError("Cannot log work for a future date")
    if not isinstance(data.duration_minutes, int) or not 1 <= data.duration_minutes <= 1440:
        raise ValidationError("Duration must be between 1 and 1440 minutes")
    if len((data.what_done or "").strip()) < 3:
        raise ValidationError("Describe what was done (at least 3 characters)")
    tags = ",".join(t.strip() for t in (data.tags or "").split(",") if t.strip()) or None
    if tags and len(tags) > 200:
        raise ValidationError("Tags are too long (max 200 characters)")
    project_name = data.project_name
    if data.domain == "finance":  # finance has exactly one project and no tags
        project_name, tags = FINANCE_PROJECT, None
    project = get_or_create_project(session, data.domain, project_name)
    log = WorkLog(
        domain=data.domain, log_date=data.log_date, duration_minutes=data.duration_minutes,
        project_id=project.id if project else None, tags=tags, what_done=data.what_done.strip(),
        research_direction=_clean(data.research_direction), next_steps=_clean(data.next_steps),
        milestone=_clean(data.milestone), outputs=_clean(data.outputs), references_text=_clean(data.references_text),
    )
    session.add(log)
    session.flush()
    return log


def delete_log(session: Session, log_id: int) -> date:
    log = session.get(WorkLog, log_id)
    if log is None:
        raise NotFoundError("Log not found")
    day = log.log_date
    session.delete(log)
    session.flush()
    return day


def list_logs(session: Session, domain: str, *, search: str | None = None, project_id: int | None = None,
              limit: int = 500) -> list[WorkLog]:
    stmt = (select(WorkLog).options(joinedload(WorkLog.project)).where(WorkLog.domain == domain)
            .order_by(WorkLog.log_date.desc(), WorkLog.id.desc()).limit(limit))
    if project_id:
        stmt = stmt.where(WorkLog.project_id == project_id)
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(
            WorkLog.what_done.ilike(like) | WorkLog.research_direction.ilike(like) | WorkLog.next_steps.ilike(like)
            | WorkLog.tags.ilike(like) | WorkLog.milestone.ilike(like) | WorkLog.outputs.ilike(like)
        )
    return list(session.scalars(stmt))


def projects(session: Session, domain: str) -> list[Project]:
    return list(session.scalars(select(Project).where(Project.domain == domain).order_by(Project.name)))


def target_minutes(session: Session, domain: str) -> int:
    return int(settings_service.get_setting(session, TARGET_KEY[domain]))


def daily_minutes(session: Session, domain: str, start: date, end: date) -> dict[date, int]:
    rows = session.execute(
        select(WorkLog.log_date, func.sum(WorkLog.duration_minutes))
        .where(WorkLog.domain == domain, WorkLog.log_date >= start, WorkLog.log_date <= end)
        .group_by(WorkLog.log_date)
    )
    return {d: int(m) for d, m in rows}


@dataclass
class WorkSummary:
    target: int
    days_logged: int
    days_met: int
    total_minutes: int
    current_streak: int
    completion_pct: float


def summary(session: Session, domain: str, start: date, end: date) -> WorkSummary:
    target = target_minutes(session, domain)
    minutes = daily_minutes(session, domain, start, end)
    days = list(date_range(start, end))
    met = [d for d in days if minutes.get(d, 0) >= target]
    streak = 0
    for d in reversed(days):
        if minutes.get(d, 0) >= target:
            streak += 1
        elif d == end:
            continue  # today not done yet doesn't break the streak
        else:
            break
    return WorkSummary(target=target, days_logged=len(minutes), days_met=len(met),
                       total_minutes=sum(minutes.values()), current_streak=streak,
                       completion_pct=round(100.0 * len(met) / len(days), 1) if days else 0.0)
