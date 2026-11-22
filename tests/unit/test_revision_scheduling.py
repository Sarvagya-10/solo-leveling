from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select

from shogun.db.models import RevisionCycle, RevisionEvent
from shogun.services import progress_service, revision_service, study_log_service
from shogun.services.errors import ConflictError, ValidationError
from shogun.services.study_log_service import StudyEntryInput
from tests.conftest import topic_id

D = date(2026, 11, 10)


def log(db, code, on, status="in_progress", minutes=60, today=None, **kw):
    return study_log_service.log_study(
        db, on, [StudyEntryInput(topic_id=topic_id(db, code), minutes=minutes, status=status, **kw)],
        today=today or on,
    )


def test_plan_offsets_are_1_3_7_21():
    plan = revision_service.plan_revision_dates(D)
    assert [p.offset_days for p in plan] == [1, 3, 7, 21]
    assert [p.due_date for p in plan] == [date(2026, 11, 11), date(2026, 11, 13), date(2026, 11, 17),
                                          date(2026, 12, 1)]


@pytest.mark.parametrize(
    "anchor,expected",
    [
        (date(2026, 12, 31), [date(2027, 1, 1), date(2027, 1, 3), date(2027, 1, 7), date(2027, 1, 21)]),
        (date(2028, 2, 28), [date(2028, 2, 29), date(2028, 3, 2), date(2028, 3, 6), date(2028, 3, 20)]),
        (date(2027, 2, 28), [date(2027, 3, 1), date(2027, 3, 3), date(2027, 3, 7), date(2027, 3, 21)]),
        (date(2026, 1, 31), [date(2026, 2, 1), date(2026, 2, 3), date(2026, 2, 7), date(2026, 2, 21)]),
    ],
)
def test_calendar_boundaries(anchor, expected):
    assert [p.due_date for p in revision_service.plan_revision_dates(anchor)] == expected


def test_logging_schedules_four_revisions(db):
    result = log(db, "DA.2.12", D)
    assert len(result.scheduled) == 1
    events = db.scalars(select(RevisionEvent).order_by(RevisionEvent.stage)).all()
    assert [(e.stage, e.due_date) for e in events] == [
        (1, date(2026, 11, 11)), (2, date(2026, 11, 13)), (3, date(2026, 11, 17)), (4, date(2026, 12, 1)),
    ]
    assert all(e.status == "pending" for e in events)


def test_no_duplicate_scheduling_same_day_or_while_active(db):
    log(db, "DA.2.12", D)
    second = log(db, "DA.2.12", D)
    third = log(db, "DA.2.12", date(2026, 11, 12), today=date(2026, 11, 12))
    assert second.scheduled == [] and third.scheduled == []
    assert db.scalar(select(func.count(RevisionCycle.id))) == 1
    assert db.scalar(select(func.count(RevisionEvent.id))) == 4


def test_ensure_cycle_is_idempotent_for_same_anchor(db):
    tid = topic_id(db, "DA.1.08")
    assert revision_service.ensure_cycle(db, tid, D) is not None
    assert revision_service.ensure_cycle(db, tid, D) is None


def test_new_cycle_after_previous_completed(db):
    log(db, "DA.3.04", D)
    events = db.scalars(select(RevisionEvent).order_by(RevisionEvent.stage)).all()
    for e in events:
        revision_service.complete_revision(db, e.id, e.due_date)
    cycle = db.scalar(select(RevisionCycle))
    assert cycle.status == "completed"
    again = log(db, "DA.3.04", date(2026, 12, 5), today=date(2026, 12, 5))
    assert len(again.scheduled) == 1
    assert db.scalar(select(func.count(RevisionCycle.id))) == 2


def test_revision_not_completed_silently_and_not_before_due(db):
    log(db, "DA.2.12", D)
    r1 = db.scalar(select(RevisionEvent).where(RevisionEvent.stage == 1))
    # Nothing completes on its own, even long after the due date.
    assert revision_service.overdue(db, date(2026, 11, 30))[0].id == r1.id
    with pytest.raises(ConflictError, match="not due"):
        revision_service.complete_revision(db, r1.id, D)


def test_revisions_complete_in_order_and_update_stage(db):
    log(db, "DA.2.12", D)
    tid = topic_id(db, "DA.2.12")
    events = {e.stage: e for e in db.scalars(select(RevisionEvent))}
    with pytest.raises(ConflictError, match="Complete R1"):
        revision_service.complete_revision(db, events[2].id, date(2026, 11, 13))
    revision_service.complete_revision(db, events[1].id, date(2026, 11, 11), minutes=20, confidence=4)
    row = next(r for r in progress_service.topic_rows(db, "DA") if r.topic_id == tid)
    assert row.revision_stage == 1
    assert row.revisions[1].completed_on == date(2026, 11, 11)
    with pytest.raises(ConflictError, match="already"):
        revision_service.complete_revision(db, events[1].id, date(2026, 11, 11))


def test_overdue_completion_keeps_original_due_dates(db):
    log(db, "DA.2.12", D)
    events = {e.stage: e for e in db.scalars(select(RevisionEvent))}
    revision_service.complete_revision(db, events[1].id, date(2026, 11, 20))
    assert events[2].due_date == date(2026, 11, 13)


def test_undo_revision(db):
    log(db, "DA.2.12", D)
    events = {e.stage: e for e in db.scalars(select(RevisionEvent))}
    revision_service.complete_revision(db, events[1].id, date(2026, 11, 11))
    revision_service.complete_revision(db, events[2].id, date(2026, 11, 13))
    with pytest.raises(ConflictError):
        revision_service.undo_revision(db, events[1].id)
    assert revision_service.undo_revision(db, events[2].id) == date(2026, 11, 13)
    assert events[2].status == "pending"


def test_queues(db):
    log(db, "DA.2.12", D)
    log(db, "DA.1.08", date(2026, 11, 12), today=date(2026, 11, 12))
    today = date(2026, 11, 13)
    due = revision_service.due_today(db, today)
    over = revision_service.overdue(db, today)
    upcoming = revision_service.upcoming(db, today, days=30)
    assert [(e.topic.code, e.stage) for e in due] == [("DA.2.12", 2), ("DA.1.08", 1)] or \
        sorted((e.topic.code, e.stage) for e in due) == [("DA.1.08", 1), ("DA.2.12", 2)]
    assert [(e.topic.code, e.stage) for e in over] == [("DA.2.12", 1)]
    assert all(e.due_date > today for e in upcoming)


def test_future_and_invalid_logs_rejected(db):
    with pytest.raises(ValidationError, match="future"):
        log(db, "DA.2.12", date(2026, 11, 11), today=D)
    with pytest.raises(ValidationError, match="exceed"):
        log(db, "DA.2.12", D, pyq_attempted=2, pyq_correct=3)
    with pytest.raises(ValidationError, match="minutes or PYQs"):
        log(db, "DA.2.12", D, minutes=0)


def test_delete_log_removes_untouched_cycle(db):
    res = log(db, "DA.2.12", D)
    study_log_service.delete_study_log(db, res.log_ids[0])
    assert db.scalar(select(func.count(RevisionCycle.id))) == 0
    row = next(r for r in progress_service.topic_rows(db, "DA") if r.code == "DA.2.12")
    assert row.total_minutes == 0 and row.first_studied_on is None
