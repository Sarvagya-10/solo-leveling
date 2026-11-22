"""Deterministic spaced-revision scheduling.

Rules
-----
* Studying a topic on calendar day ``D`` creates ONE revision cycle with four
  events due on ``D+1``, ``D+3``, ``D+7`` and ``D+21`` (stages R1–R4).
* A topic has at most one *active* cycle. Studying it again while a cycle is
  active does not create duplicates; once all four stages are done the next
  study session starts a fresh cycle. ``(topic_id, anchor_date)`` is unique.
* Revisions are completed only by an explicit user action, never implicitly,
  never before their due date, and strictly in stage order. Overdue revisions
  stay pending (and visible) until completed.
* Due dates are fixed at scheduling time; completing late does not shift the
  remaining stages, so the schedule is reproducible from the anchor date alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from shogun.db.models import ProgressAudit, RevisionCycle, RevisionEvent, Topic, TopicProgress
from shogun.services.errors import ConflictError, NotFoundError, ValidationError
from shogun.timeutil import add_days, utcnow

REVISION_OFFSETS: tuple[int, ...] = (1, 3, 7, 21)


@dataclass(frozen=True)
class PlannedRevision:
    stage: int
    offset_days: int
    due_date: date


def plan_revision_dates(anchor: date) -> list[PlannedRevision]:
    """Pure schedule for a study day: R1..R4 at +1, +3, +7, +21 calendar days."""
    return [
        PlannedRevision(stage=i, offset_days=off, due_date=add_days(anchor, off))
        for i, off in enumerate(REVISION_OFFSETS, start=1)
    ]


def active_cycle(session: Session, topic_id: int) -> RevisionCycle | None:
    return session.scalars(
        select(RevisionCycle)
        .where(RevisionCycle.topic_id == topic_id, RevisionCycle.status == "active")
        .order_by(RevisionCycle.anchor_date.desc())
    ).first()


def latest_cycle(session: Session, topic_id: int) -> RevisionCycle | None:
    return session.scalars(
        select(RevisionCycle)
        .where(RevisionCycle.topic_id == topic_id)
        .order_by(RevisionCycle.anchor_date.desc(), RevisionCycle.id.desc())
    ).first()


def ensure_cycle(
    session: Session, topic_id: int, anchor_date: date, source_log_id: int | None = None
) -> RevisionCycle | None:
    """Create a revision cycle for a study day unless one is already active.

    Returns the new cycle, or ``None`` when scheduling was skipped to avoid
    duplicates.
    """
    if active_cycle(session, topic_id) is not None:
        return None
    exists = session.scalar(
        select(func.count(RevisionCycle.id)).where(
            RevisionCycle.topic_id == topic_id, RevisionCycle.anchor_date == anchor_date
        )
    )
    if exists:
        return None
    cycle = RevisionCycle(topic_id=topic_id, anchor_date=anchor_date, source_log_id=source_log_id)
    for plan in plan_revision_dates(anchor_date):
        cycle.events.append(
            RevisionEvent(
                topic_id=topic_id, stage=plan.stage, offset_days=plan.offset_days, due_date=plan.due_date
            )
        )
    session.add(cycle)
    session.flush()
    progress = session.scalar(select(TopicProgress).where(TopicProgress.topic_id == topic_id))
    if progress is not None and progress.revision_stage != 0:
        _audit(session, topic_id, "revision_stage", progress.revision_stage, 0, anchor_date,
               "New revision cycle started")
        progress.revision_stage = 0
    return cycle


def _audit(session: Session, topic_id: int, field: str, old: object, new: object, on: date, reason: str) -> None:
    session.add(
        ProgressAudit(
            topic_id=topic_id, field=field, old_value=None if old is None else str(old),
            new_value=None if new is None else str(new), source="revision", reason=reason, effective_date=on,
        )
    )


def _get_event(session: Session, event_id: int) -> RevisionEvent:
    event = session.get(RevisionEvent, event_id)
    if event is None:
        raise NotFoundError(f"Revision #{event_id} not found")
    return event


def complete_revision(
    session: Session,
    event_id: int,
    on_date: date,
    *,
    minutes: int | None = None,
    confidence: int | None = None,
    notes: str | None = None,
) -> RevisionEvent:
    event = _get_event(session, event_id)
    if event.status == "completed":
        raise ConflictError(f"R{event.stage} is already completed")
    if on_date < event.due_date:
        raise ConflictError(f"R{event.stage} is not due until {event.due_date.isoformat()}")
    if minutes is not None and not 0 <= minutes <= 1440:
        raise ValidationError("Minutes must be between 0 and 1440")
    if confidence is not None and not 1 <= confidence <= 5:
        raise ValidationError("Confidence must be between 1 and 5")
    cycle = event.cycle
    for other in cycle.events:
        if other.stage < event.stage and other.status != "completed":
            raise ConflictError(f"Complete R{other.stage} before R{event.stage}")
    event.status = "completed"
    event.completed_at = utcnow()
    event.completed_on = on_date
    event.minutes = minutes
    event.confidence = confidence
    event.notes = (notes or "").strip() or None
    progress = session.scalar(select(TopicProgress).where(TopicProgress.topic_id == event.topic_id))
    if progress is not None:
        _audit(session, event.topic_id, "revision_stage", progress.revision_stage, event.stage, on_date,
               f"R{event.stage} completed")
        progress.revision_stage = event.stage
    if all(e.status == "completed" for e in cycle.events):
        cycle.status = "completed"
        cycle.completed_at = utcnow()
    session.flush()
    return event


def undo_revision(session: Session, event_id: int) -> date:
    """Revert the most recent completion in a cycle (to fix a mistaken click).

    Returns the date the completion had been recorded on (so XP can be re-synced).
    """
    event = _get_event(session, event_id)
    if event.status != "completed" or event.completed_on is None:
        raise ConflictError("Only a completed revision can be undone")
    cycle = event.cycle
    if any(e.stage > event.stage and e.status == "completed" for e in cycle.events):
        raise ConflictError("Undo later stages first")
    was_on = event.completed_on
    event.status = "pending"
    event.completed_at = None
    event.completed_on = None
    event.minutes = None
    event.confidence = None
    cycle.status = "active"
    cycle.completed_at = None
    progress = session.scalar(select(TopicProgress).where(TopicProgress.topic_id == event.topic_id))
    if progress is not None:
        _audit(session, event.topic_id, "revision_stage", progress.revision_stage, event.stage - 1, was_on,
               f"R{event.stage} completion undone")
        progress.revision_stage = event.stage - 1
    session.flush()
    return was_on


# --------------------------------------------------------------------------- queries
def _pending_query():  # type: ignore[no-untyped-def]
    return (
        select(RevisionEvent)
        .options(joinedload(RevisionEvent.topic).joinedload(Topic.subject))
        .where(RevisionEvent.status == "pending")
    )


def due_today(session: Session, today: date) -> list[RevisionEvent]:
    return list(session.scalars(_pending_query().where(RevisionEvent.due_date == today)
                                .order_by(RevisionEvent.stage, RevisionEvent.topic_id)))


def overdue(session: Session, today: date) -> list[RevisionEvent]:
    return list(session.scalars(_pending_query().where(RevisionEvent.due_date < today)
                                .order_by(RevisionEvent.due_date, RevisionEvent.stage)))


def upcoming(session: Session, today: date, days: int = 30) -> list[RevisionEvent]:
    return list(session.scalars(
        _pending_query()
        .where(RevisionEvent.due_date > today, RevisionEvent.due_date <= add_days(today, days))
        .order_by(RevisionEvent.due_date, RevisionEvent.stage)
    ))


def completed_between(session: Session, start: date, end: date) -> list[RevisionEvent]:
    return list(session.scalars(
        select(RevisionEvent)
        .options(joinedload(RevisionEvent.topic))
        .where(RevisionEvent.status == "completed", RevisionEvent.completed_on >= start,
               RevisionEvent.completed_on <= end)
        .order_by(RevisionEvent.completed_on.desc())
    ))


def events_between(session: Session, start: date, end: date) -> list[RevisionEvent]:
    return list(session.scalars(
        select(RevisionEvent)
        .options(joinedload(RevisionEvent.topic).joinedload(Topic.subject))
        .where(RevisionEvent.due_date >= start, RevisionEvent.due_date <= end)
        .order_by(RevisionEvent.due_date, RevisionEvent.stage)
    ))


def latest_cycle_events(session: Session) -> dict[int, list[RevisionEvent]]:
    """topic_id -> events of that topic's most recent cycle."""
    cycles = session.scalars(
        select(RevisionCycle).options(joinedload(RevisionCycle.events))
        .order_by(RevisionCycle.topic_id, RevisionCycle.anchor_date, RevisionCycle.id)
    ).unique()
    latest: dict[int, RevisionCycle] = {}
    for cycle in cycles:
        latest[cycle.topic_id] = cycle
    return {tid: list(c.events) for tid, c in latest.items()}
