"""Daily GATE/GA study logging.

A daily log entry records topic, minutes, PYQs attempted/correct and the
user-reported mastery status. Saving entries automatically:

1. updates topic progress (minutes, first/last studied, coverage — forward only),
2. schedules a revision cycle (+1/+3/+7/+21) unless one is already active,
3. leaves an audit trail for every progress change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from shogun.db.models import COVERAGE_STATES, RevisionCycle, StudyLog, Subject, Topic, TopicProgress
from shogun.services import progress_service, revision_service
from shogun.services.errors import NotFoundError, ValidationError


@dataclass
class StudyEntryInput:
    topic_id: int
    minutes: int
    pyq_attempted: int = 0
    pyq_correct: int = 0
    status: str = "in_progress"
    notes: str | None = None


@dataclass
class ScheduledInfo:
    topic_id: int
    topic_name: str
    due_dates: list[date]


@dataclass
class LogResult:
    log_ids: list[int] = field(default_factory=list)
    scheduled: list[ScheduledInfo] = field(default_factory=list)
    already_scheduled: list[str] = field(default_factory=list)
    coverage_raised: list[str] = field(default_factory=list)


def validate_entry(entry: StudyEntryInput) -> None:
    if not isinstance(entry.minutes, int) or not 0 <= entry.minutes <= 1440:
        raise ValidationError("Minutes must be a whole number between 0 and 1440")
    if entry.pyq_attempted < 0 or entry.pyq_correct < 0:
        raise ValidationError("Question counts cannot be negative")
    if entry.pyq_correct > entry.pyq_attempted:
        raise ValidationError("Correct PYQs cannot exceed PYQs attempted")
    if entry.pyq_attempted > 500:
        raise ValidationError("PYQs attempted looks too large (max 500 per entry)")
    if entry.status not in COVERAGE_STATES:
        raise ValidationError(f"Invalid mastery status: {entry.status}")
    if entry.minutes == 0 and entry.pyq_attempted == 0:
        raise ValidationError("An entry needs study minutes or PYQs attempted")


def minutes_logged_on(session: Session, on_date: date) -> int:
    return int(session.scalar(
        select(func.coalesce(func.sum(StudyLog.minutes), 0)).where(StudyLog.log_date == on_date)
    ) or 0)


def log_study(session: Session, on_date: date, entries: list[StudyEntryInput], *, today: date) -> LogResult:
    if not entries:
        raise ValidationError("Select at least one topic")
    if on_date > today:
        raise ValidationError("Cannot log study for a future date")
    topic_ids = [e.topic_id for e in entries]
    if len(topic_ids) != len(set(topic_ids)):
        raise ValidationError("Each topic can appear only once per submission")
    for entry in entries:
        validate_entry(entry)
    if minutes_logged_on(session, on_date) + sum(e.minutes for e in entries) > 1440:
        raise ValidationError("Total study minutes for a day cannot exceed 1440")

    topics = {t.id: t for t in session.scalars(select(Topic).where(Topic.id.in_(topic_ids)))}
    result = LogResult()
    for entry in entries:
        topic = topics.get(entry.topic_id)
        if topic is None or not topic.is_active:
            raise NotFoundError(f"Topic #{entry.topic_id} not found")
        log = StudyLog(
            log_date=on_date, topic_id=topic.id, minutes=entry.minutes, pyq_attempted=entry.pyq_attempted,
            pyq_correct=entry.pyq_correct, reported_status=entry.status,
            notes=(entry.notes or "").strip() or None,
        )
        session.add(log)
        session.flush()
        result.log_ids.append(log.id)

        prog = session.scalar(select(TopicProgress).where(TopicProgress.topic_id == topic.id))
        assert prog is not None
        prog.total_minutes += entry.minutes
        if prog.first_studied_on is None or on_date < prog.first_studied_on:
            prog.first_studied_on = on_date
        if prog.last_studied_on is None or on_date > prog.last_studied_on:
            prog.last_studied_on = on_date
        if progress_service.raise_coverage(session, topic.id, entry.status, on_date):
            result.coverage_raised.append(topic.name)

        cycle = revision_service.ensure_cycle(session, topic.id, on_date, source_log_id=log.id)
        if cycle is not None:
            result.scheduled.append(ScheduledInfo(topic.id, topic.name, [e.due_date for e in cycle.events]))
        else:
            result.already_scheduled.append(topic.name)
    session.flush()
    return result


def delete_study_log(session: Session, log_id: int) -> date:
    """Delete a log entry. Returns its date (so dependent metrics/XP can be re-synced).

    Revision cycles created by this entry are removed only if none of their
    revisions were completed; otherwise the history is kept.
    """
    log = session.get(StudyLog, log_id)
    if log is None:
        raise NotFoundError(f"Log #{log_id} not found")
    on_date, topic_id = log.log_date, log.topic_id
    cycles = session.scalars(select(RevisionCycle).where(RevisionCycle.source_log_id == log_id)).all()
    for cycle in cycles:
        if all(e.status == "pending" for e in cycle.events):
            session.delete(cycle)
    session.delete(log)
    session.flush()
    progress_service.recompute_topic_activity(session, topic_id)
    return on_date


def logs_between(session: Session, start: date, end: date, paper: str | None = None) -> list[StudyLog]:
    stmt = (
        select(StudyLog).options(joinedload(StudyLog.topic).joinedload(Topic.subject))
        .where(StudyLog.log_date >= start, StudyLog.log_date <= end)
        .order_by(StudyLog.log_date.desc(), StudyLog.id.desc())
    )
    if paper:
        stmt = stmt.join(Topic, Topic.id == StudyLog.topic_id).join(Subject).where(Subject.paper == paper)
    return list(session.scalars(stmt).unique())


def daily_totals(session: Session, start: date, end: date, paper: str | None = None) -> dict[date, dict[str, int]]:
    stmt = (
        select(StudyLog.log_date, func.sum(StudyLog.minutes), func.sum(StudyLog.pyq_attempted),
               func.sum(StudyLog.pyq_correct), func.count(func.distinct(StudyLog.topic_id)))
        .where(StudyLog.log_date >= start, StudyLog.log_date <= end)
        .group_by(StudyLog.log_date)
    )
    if paper:
        stmt = stmt.join(Topic, Topic.id == StudyLog.topic_id).join(Subject).where(Subject.paper == paper)
    return {
        d: {"minutes": int(m or 0), "pyq_attempted": int(a or 0), "pyq_correct": int(c or 0), "topics": int(t or 0)}
        for d, m, a, c, t in session.execute(stmt)
    }


def study_dates(session: Session) -> list[date]:
    return list(session.scalars(select(StudyLog.log_date).distinct().order_by(StudyLog.log_date)))
