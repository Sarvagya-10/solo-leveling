"""Topic progress: derived statuses, syllabus tables, overrides with audit trail.

Definitions (shown verbatim in the UI)
--------------------------------------
* **Knowledge coverage** — ``not_started`` / ``in_progress`` / ``mastered``.
  Raised by daily logs (never silently lowered); changeable manually with an
  audited reason.
* **PYQ mastery** — ``mastered`` when correct PYQs ≥ target (default 10),
  ``in_progress`` once any PYQ is attempted, else ``not_started``. Counts =
  self-reported daily-log PYQs + in-app attempts on official PYQs. Accuracy =
  correct / attempted. Manual override is audited.
* **Overall status** — ``mastered`` when coverage AND PYQ mastery are mastered;
  ``in_progress`` when either has started; else ``not_started``. Manual
  override is audited.
* **War eligibility** — coverage mastered (rule ``coverage_mastered``), or
  additionally PYQ mastery met (rule ``coverage_and_pyq``).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from shogun.db.models import (
    COVERAGE_STATES,
    ProgressAudit,
    Question,
    QuestionAttempt,
    RevisionEvent,
    StudyLog,
    Subject,
    Topic,
    TopicProgress,
)
from shogun.services import revision_service, settings_service
from shogun.services.errors import NotFoundError, ValidationError

STATUS_RANK = {s: i for i, s in enumerate(COVERAGE_STATES)}
STATUS_LABEL = {"not_started": "Not started", "in_progress": "In progress", "mastered": "Mastered"}


def derive_pyq_status(attempted: int, correct: int, target: int, override: bool | None = None) -> str:
    if override is True:
        return "mastered"
    if override is None and correct >= target:
        return "mastered"
    return "in_progress" if attempted > 0 else "not_started"


def derive_overall(coverage: str, pyq_status: str, override: str | None = None) -> str:
    if override:
        return override
    if coverage == "mastered" and pyq_status == "mastered":
        return "mastered"
    if coverage != "not_started" or pyq_status != "not_started":
        return "in_progress"
    return "not_started"


def is_war_eligible(coverage: str, pyq_status: str, rule: str) -> bool:
    if coverage != "mastered":
        return False
    if rule == "coverage_and_pyq":
        return pyq_status == "mastered"
    return True


def accuracy(attempted: int, correct: int) -> float | None:
    return round(100.0 * correct / attempted, 1) if attempted else None


@dataclass
class RevisionCell:
    stage: int
    due_date: date
    status: str
    completed_on: date | None
    event_id: int


@dataclass
class TopicRow:
    topic_id: int
    code: str
    name: str
    paper: str
    subject_code: str
    subject_name: str
    group_label: str | None
    source_phrase: str
    coverage_status: str
    pyq_attempted: int
    pyq_correct: int
    pyq_logged_attempted: int
    pyq_inapp_attempted: int
    pyq_target: int
    pyq_target_is_custom: bool
    pyq_status: str
    pyq_override: bool | None
    overall_status: str
    status_override: str | None
    revision_stage: int
    revisions: dict[int, RevisionCell] = field(default_factory=dict)
    total_minutes: int = 0
    first_studied_on: date | None = None
    last_studied_on: date | None = None
    coverage_mastered_on: date | None = None
    notes: str | None = None
    updated_at: datetime | None = None
    war_eligible: bool = False

    @property
    def pyq_accuracy(self) -> float | None:
        return accuracy(self.pyq_attempted, self.pyq_correct)


def _logged_pyq(session: Session) -> dict[int, tuple[int, int]]:
    rows = session.execute(
        select(StudyLog.topic_id, func.sum(StudyLog.pyq_attempted), func.sum(StudyLog.pyq_correct))
        .group_by(StudyLog.topic_id)
    )
    return {tid: (int(a or 0), int(c or 0)) for tid, a, c in rows}


def _inapp_pyq(session: Session) -> dict[int, tuple[int, int]]:
    rows = session.execute(
        select(Question.primary_topic_id, func.count(QuestionAttempt.id),
               func.sum(case((QuestionAttempt.is_correct.is_(True), 1), else_=0)))
        .join(Question, Question.id == QuestionAttempt.question_id)
        .where(Question.source_type == "official_pyq")
        .group_by(Question.primary_topic_id)
    )
    return {tid: (int(a or 0), int(c or 0)) for tid, a, c in rows}


def topic_rows(session: Session, paper: str | None = None, *, include_inactive: bool = False) -> list[TopicRow]:
    default_target = int(settings_service.get_setting(session, "pyq_target_default"))
    rule = str(settings_service.get_setting(session, "war_eligibility_rule"))
    logged = _logged_pyq(session)
    inapp = _inapp_pyq(session)
    cycles = revision_service.latest_cycle_events(session)

    stmt = (
        select(Topic, Subject, TopicProgress)
        .join(Subject, Subject.id == Topic.subject_id)
        .join(TopicProgress, TopicProgress.topic_id == Topic.id)
        .order_by(Subject.sort_order, Topic.sort_order)
    )
    if paper:
        stmt = stmt.where(Subject.paper == paper)
    if not include_inactive:
        stmt = stmt.where(Topic.is_active.is_(True))

    rows: list[TopicRow] = []
    for topic, subject, prog in session.execute(stmt):
        la, lc = logged.get(topic.id, (0, 0))
        ia, ic = inapp.get(topic.id, (0, 0))
        attempted, correct = la + ia, lc + ic
        target = prog.pyq_target or default_target
        pyq_status = derive_pyq_status(attempted, correct, target, prog.pyq_mastery_override)
        overall = derive_overall(prog.coverage_status, pyq_status, prog.status_override)
        revisions = {
            e.stage: RevisionCell(e.stage, e.due_date, e.status, e.completed_on, e.id)
            for e in cycles.get(topic.id, [])
        }
        rows.append(TopicRow(
            topic_id=topic.id, code=topic.code, name=topic.name, paper=subject.paper,
            subject_code=subject.code, subject_name=subject.name, group_label=topic.group_label,
            source_phrase=topic.source_phrase, coverage_status=prog.coverage_status,
            pyq_attempted=attempted, pyq_correct=correct, pyq_logged_attempted=la, pyq_inapp_attempted=ia,
            pyq_target=target, pyq_target_is_custom=prog.pyq_target is not None, pyq_status=pyq_status,
            pyq_override=prog.pyq_mastery_override, overall_status=overall,
            status_override=prog.status_override, revision_stage=prog.revision_stage, revisions=revisions,
            total_minutes=prog.total_minutes, first_studied_on=prog.first_studied_on,
            last_studied_on=prog.last_studied_on, coverage_mastered_on=prog.coverage_mastered_on,
            notes=prog.notes, updated_at=prog.updated_at,
            war_eligible=is_war_eligible(prog.coverage_status, pyq_status, rule),
        ))
    return rows


@dataclass
class SubjectSummary:
    subject_code: str
    subject_name: str
    paper: str
    total: int
    coverage: dict[str, int]
    pyq_mastered: int
    overall_mastered: int
    pyq_attempted: int
    pyq_correct: int
    minutes: int

    @property
    def coverage_pct(self) -> float:
        return round(100.0 * self.coverage.get("mastered", 0) / self.total, 1) if self.total else 0.0

    @property
    def started_pct(self) -> float:
        started = self.coverage.get("in_progress", 0) + self.coverage.get("mastered", 0)
        return round(100.0 * started / self.total, 1) if self.total else 0.0


def subject_summaries(rows: list[TopicRow]) -> list[SubjectSummary]:
    grouped: dict[str, list[TopicRow]] = defaultdict(list)
    order: list[str] = []
    for r in rows:
        if r.subject_code not in grouped:
            order.append(r.subject_code)
        grouped[r.subject_code].append(r)
    out = []
    for code in order:
        items = grouped[code]
        cov = {s: sum(1 for r in items if r.coverage_status == s) for s in COVERAGE_STATES}
        out.append(SubjectSummary(
            subject_code=code, subject_name=items[0].subject_name, paper=items[0].paper, total=len(items),
            coverage=cov, pyq_mastered=sum(1 for r in items if r.pyq_status == "mastered"),
            overall_mastered=sum(1 for r in items if r.overall_status == "mastered"),
            pyq_attempted=sum(r.pyq_attempted for r in items), pyq_correct=sum(r.pyq_correct for r in items),
            minutes=sum(r.total_minutes for r in items),
        ))
    return out


# --------------------------------------------------------------------------- mutations
def _progress(session: Session, topic_id: int) -> TopicProgress:
    prog = session.scalar(select(TopicProgress).where(TopicProgress.topic_id == topic_id))
    if prog is None:
        raise NotFoundError(f"Topic #{topic_id} has no progress record")
    return prog


def record_audit(session: Session, topic_id: int, field_name: str, old: object, new: object, *,
                 source: str, on_date: date, reason: str | None = None) -> None:
    session.add(ProgressAudit(
        topic_id=topic_id, field=field_name, old_value=None if old is None else str(old),
        new_value=None if new is None else str(new), source=source, reason=reason, effective_date=on_date,
    ))


def raise_coverage(session: Session, topic_id: int, reported: str, on_date: date) -> bool:
    """Apply a log-reported coverage status; only ever moves forward. Returns True if changed."""
    if reported not in STATUS_RANK:
        raise ValidationError(f"Invalid status: {reported}")
    prog = _progress(session, topic_id)
    if STATUS_RANK[reported] <= STATUS_RANK[prog.coverage_status]:
        return False
    record_audit(session, topic_id, "coverage_status", prog.coverage_status, reported, source="log",
                 on_date=on_date, reason="Reported in daily GATE log")
    prog.coverage_status = reported
    if reported == "mastered":
        prog.coverage_mastered_on = on_date
    return True


def _require_reason(reason: str | None) -> str:
    cleaned = (reason or "").strip()
    if len(cleaned) < 3:
        raise ValidationError("A reason (at least 3 characters) is required for manual overrides")
    return cleaned


def override_coverage(session: Session, topic_id: int, new_status: str, reason: str, on_date: date) -> None:
    if new_status not in STATUS_RANK:
        raise ValidationError(f"Invalid status: {new_status}")
    why = _require_reason(reason)
    prog = _progress(session, topic_id)
    if prog.coverage_status == new_status:
        return
    record_audit(session, topic_id, "coverage_status", prog.coverage_status, new_status, source="override",
                 on_date=on_date, reason=why)
    prog.coverage_status = new_status
    prog.coverage_mastered_on = on_date if new_status == "mastered" else None
    session.flush()


def override_pyq_mastery(session: Session, topic_id: int, value: bool | None, reason: str, on_date: date) -> None:
    why = _require_reason(reason)
    prog = _progress(session, topic_id)
    if prog.pyq_mastery_override == value:
        return
    record_audit(session, topic_id, "pyq_mastery_override", prog.pyq_mastery_override, value,
                 source="override", on_date=on_date, reason=why)
    prog.pyq_mastery_override = value
    session.flush()


def override_status(session: Session, topic_id: int, value: str | None, reason: str, on_date: date) -> None:
    if value is not None and value not in STATUS_RANK:
        raise ValidationError(f"Invalid status: {value}")
    why = _require_reason(reason)
    prog = _progress(session, topic_id)
    if prog.status_override == value:
        return
    record_audit(session, topic_id, "status_override", prog.status_override, value, source="override",
                 on_date=on_date, reason=why)
    prog.status_override = value
    session.flush()


def set_pyq_target(session: Session, topic_id: int, target: int | None, reason: str, on_date: date) -> None:
    if target is not None and not 1 <= target <= 500:
        raise ValidationError("PYQ target must be between 1 and 500")
    why = _require_reason(reason)
    prog = _progress(session, topic_id)
    if prog.pyq_target == target:
        return
    record_audit(session, topic_id, "pyq_target", prog.pyq_target, target, source="override",
                 on_date=on_date, reason=why)
    prog.pyq_target = target
    session.flush()


def set_notes(session: Session, topic_id: int, notes: str | None) -> None:
    prog = _progress(session, topic_id)
    prog.notes = (notes or "").strip() or None
    session.flush()


def audit_log(session: Session, topic_id: int | None = None, limit: int = 200) -> list[ProgressAudit]:
    stmt = select(ProgressAudit).order_by(ProgressAudit.created_at.desc(), ProgressAudit.id.desc()).limit(limit)
    if topic_id is not None:
        stmt = stmt.where(ProgressAudit.topic_id == topic_id)
    return list(session.scalars(stmt))


def recompute_topic_activity(session: Session, topic_id: int) -> None:
    """Recompute minutes and first/last studied dates from the remaining logs."""
    prog = _progress(session, topic_id)
    total, first, last = session.execute(
        select(func.coalesce(func.sum(StudyLog.minutes), 0), func.min(StudyLog.log_date),
               func.max(StudyLog.log_date)).where(StudyLog.topic_id == topic_id)
    ).one()
    prog.total_minutes = int(total or 0)
    prog.first_studied_on = first
    prog.last_studied_on = last
    session.flush()


def coverage_timeline(session: Session, start: date, end: date, paper: str = "DA") -> list[dict[str, object]]:
    """Per-day cumulative counts: topics started (first studied) and topics mastered (from history)."""
    from shogun.timeutil import date_range

    topic_ids = set(session.scalars(
        select(Topic.id).join(Subject).where(Subject.paper == paper, Topic.is_active.is_(True))
    ))
    total = len(topic_ids)
    first_dates = dict(session.execute(
        select(StudyLog.topic_id, func.min(StudyLog.log_date)).group_by(StudyLog.topic_id)
    ).all())
    changes: dict[int, list[tuple[date, int, str | None]]] = defaultdict(list)
    for a in session.scalars(
        select(ProgressAudit).where(ProgressAudit.field == "coverage_status")
        .order_by(ProgressAudit.effective_date, ProgressAudit.id)
    ):
        if a.topic_id in topic_ids:
            changes[a.topic_id].append((a.effective_date, a.id, a.new_value))
    out: list[dict[str, object]] = []
    for day in date_range(start, end):
        started = sum(1 for tid in topic_ids if first_dates.get(tid) is not None and first_dates[tid] <= day)
        mastered = 0
        for tid in topic_ids:
            state = None
            for eff, _id, new in changes.get(tid, []):
                if eff <= day:
                    state = new
            if state == "mastered":
                mastered += 1
        out.append({
            "date": day, "started": started, "mastered": mastered, "total": total,
            "mastered_pct": round(100.0 * mastered / total, 1) if total else 0.0,
            "started_pct": round(100.0 * started / total, 1) if total else 0.0,
        })
    return out


def revisions_pending_for_topic(session: Session, topic_id: int) -> list[RevisionEvent]:
    return list(session.scalars(
        select(RevisionEvent).where(RevisionEvent.topic_id == topic_id, RevisionEvent.status == "pending")
        .order_by(RevisionEvent.due_date)
    ))
