"""SQLAlchemy ORM models.

Timestamps (``*_at``) are naive UTC. Calendar days (``*_date``/``*_on``) are
local dates. See :mod:`shogun.timeutil`.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shogun.db.base import Base
from shogun.timeutil import utcnow

COVERAGE_STATES = ("not_started", "in_progress", "mastered")
_COVERAGE_SQL = "('not_started','in_progress','mastered')"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


# --------------------------------------------------------------------------- syllabus
class Subject(Base):
    __tablename__ = "subjects"
    __table_args__ = (CheckConstraint("paper IN ('DA','GA')", name="paper"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    paper: Mapped[str] = mapped_column(String(4), nullable=False)
    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    section_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    official_text: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    syllabus_version: Mapped[str] = mapped_column(String(40), nullable=False)

    topics: Mapped[list[Topic]] = relationship(back_populates="subject", order_by="Topic.sort_order")


class Topic(Base):
    __tablename__ = "topics"
    __table_args__ = (Index("ix_topics_subject", "subject_id", "sort_order"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_phrase: Mapped[str] = mapped_column(String(300), nullable=False)
    group_label: Mapped[str | None] = mapped_column(String(120))
    context: Mapped[str | None] = mapped_column(String(200))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    syllabus_version: Mapped[str] = mapped_column(String(40), nullable=False)

    subject: Mapped[Subject] = relationship(back_populates="topics")
    progress: Mapped[TopicProgress | None] = relationship(back_populates="topic", uselist=False)


class TopicProgress(TimestampMixin, Base):
    __tablename__ = "topic_progress"
    __table_args__ = (
        CheckConstraint(f"coverage_status IN {_COVERAGE_SQL}", name="coverage_status"),
        CheckConstraint(f"status_override IS NULL OR status_override IN {_COVERAGE_SQL}", name="status_override"),
        CheckConstraint("pyq_target IS NULL OR pyq_target >= 1", name="pyq_target"),
        CheckConstraint("revision_stage BETWEEN 0 AND 4", name="revision_stage"),
        CheckConstraint("total_minutes >= 0", name="total_minutes"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), unique=True, nullable=False)
    coverage_status: Mapped[str] = mapped_column(String(16), nullable=False, default="not_started")
    pyq_target: Mapped[int | None] = mapped_column(Integer)
    pyq_mastery_override: Mapped[bool | None] = mapped_column(Boolean)
    status_override: Mapped[str | None] = mapped_column(String(16))
    notes: Mapped[str | None] = mapped_column(Text)
    total_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_studied_on: Mapped[date | None] = mapped_column(Date)
    last_studied_on: Mapped[date | None] = mapped_column(Date)
    coverage_mastered_on: Mapped[date | None] = mapped_column(Date)
    revision_stage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    topic: Mapped[Topic] = relationship(back_populates="progress")


class ProgressAudit(Base):
    """Audit trail and history of every topic progress change (also feeds coverage-over-time charts)."""

    __tablename__ = "progress_audit"
    __table_args__ = (Index("ix_progress_audit_topic_date", "topic_id", "effective_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), nullable=False)
    field: Mapped[str] = mapped_column(String(40), nullable=False)
    old_value: Mapped[str | None] = mapped_column(String(200))
    new_value: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # log | override | revision | import | system
    reason: Mapped[str | None] = mapped_column(Text)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


# --------------------------------------------------------------------------- study logs & revisions
class StudyLog(TimestampMixin, Base):
    __tablename__ = "study_logs"
    __table_args__ = (
        CheckConstraint("minutes >= 0 AND minutes <= 1440", name="minutes"),
        CheckConstraint("pyq_attempted >= 0", name="pyq_attempted"),
        CheckConstraint("pyq_correct >= 0 AND pyq_correct <= pyq_attempted", name="pyq_correct"),
        CheckConstraint(f"reported_status IN {_COVERAGE_SQL}", name="reported_status"),
        Index("ix_study_logs_date", "log_date"),
        Index("ix_study_logs_topic_date", "topic_id", "log_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    log_date: Mapped[date] = mapped_column(Date, nullable=False)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), nullable=False)
    minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pyq_attempted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pyq_correct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reported_status: Mapped[str] = mapped_column(String(16), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    topic: Mapped[Topic] = relationship()


class RevisionCycle(Base):
    __tablename__ = "revision_cycles"
    __table_args__ = (
        UniqueConstraint("topic_id", "anchor_date", name="uq_revision_cycles_topic_anchor"),
        CheckConstraint("status IN ('active','completed')", name="status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), nullable=False)
    anchor_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_log_id: Mapped[int | None] = mapped_column(ForeignKey("study_logs.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    events: Mapped[list[RevisionEvent]] = relationship(
        back_populates="cycle", order_by="RevisionEvent.stage", cascade="all, delete-orphan"
    )


class RevisionEvent(Base):
    __tablename__ = "revision_events"
    __table_args__ = (
        UniqueConstraint("cycle_id", "stage", name="uq_revision_events_cycle_stage"),
        CheckConstraint("stage BETWEEN 1 AND 4", name="stage"),
        CheckConstraint("status IN ('pending','completed')", name="status"),
        CheckConstraint("confidence IS NULL OR confidence BETWEEN 1 AND 5", name="confidence"),
        Index("ix_revision_events_due_status", "due_date", "status"),
        Index("ix_revision_events_topic", "topic_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("revision_cycles.id", ondelete="CASCADE"), nullable=False)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), nullable=False)
    stage: Mapped[int] = mapped_column(Integer, nullable=False)
    offset_days: Mapped[int] = mapped_column(Integer, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="pending")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_on: Mapped[date | None] = mapped_column(Date)
    minutes: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)

    cycle: Mapped[RevisionCycle] = relationship(back_populates="events")
    topic: Mapped[Topic] = relationship()


# --------------------------------------------------------------------------- question bank
class Question(TimestampMixin, Base):
    __tablename__ = "questions"
    __table_args__ = (
        CheckConstraint("paper IN ('DA','GA')", name="paper"),
        CheckConstraint("source_type IN ('official_pyq','ai_generated','user_practice')", name="source_type"),
        CheckConstraint("verification_status IN ('verified','unverified','rejected')", name="verification"),
        CheckConstraint("qtype IN ('MCQ','MSQ','NAT')", name="qtype"),
        CheckConstraint("marks IN (1,2)", name="marks"),
        Index("ix_questions_topic", "primary_topic_id"),
        Index("ix_questions_source", "source_type", "verification_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    paper: Mapped[str] = mapped_column(String(4), nullable=False)
    primary_topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(12), nullable=False, default="unverified")
    exam_year: Mapped[int | None] = mapped_column(Integer)
    exam_name: Mapped[str | None] = mapped_column(String(80))
    question_ref: Mapped[str | None] = mapped_column(String(40))
    qtype: Mapped[str] = mapped_column(String(4), nullable=False)
    marks: Mapped[int] = mapped_column(Integer, nullable=False)
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    options_json: Mapped[str | None] = mapped_column(Text)
    answer_key: Mapped[str | None] = mapped_column(String(40))
    nat_low: Mapped[float | None] = mapped_column(Float)
    nat_high: Mapped[float | None] = mapped_column(Float)
    explanation: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(500))
    source_note: Mapped[str | None] = mapped_column(Text)
    ai_model: Mapped[str | None] = mapped_column(String(120))
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)

    primary_topic: Mapped[Topic] = relationship()
    topic_links: Mapped[list[QuestionTopic]] = relationship(cascade="all, delete-orphan")


class QuestionTopic(Base):
    __tablename__ = "question_topics"

    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True)


class QuestionAttempt(Base):
    __tablename__ = "question_attempts"
    __table_args__ = (
        CheckConstraint("context IN ('practice','mock')", name="context"),
        Index("ix_question_attempts_question", "question_id"),
        Index("ix_question_attempts_date", "attempt_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    attempt_date: Mapped[date] = mapped_column(Date, nullable=False)
    context: Mapped[str] = mapped_column(String(12), nullable=False)
    mock_exam_id: Mapped[int | None] = mapped_column(ForeignKey("mock_exams.id", ondelete="CASCADE"))
    response: Mapped[str | None] = mapped_column(String(200))
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    time_spent_sec: Mapped[int | None] = mapped_column(Integer)


# --------------------------------------------------------------------------- revision cards
class RevisionCard(TimestampMixin, Base):
    __tablename__ = "revision_cards"
    __table_args__ = (
        CheckConstraint("origin IN ('ai','manual')", name="origin"),
        CheckConstraint("review_status IN ('draft','reviewed')", name="review_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), unique=True, nullable=False)
    basic_idea: Mapped[str | None] = mapped_column(Text)
    formulae: Mapped[str | None] = mapped_column(Text)
    question_types: Mapped[str | None] = mapped_column(Text)
    traps: Mapped[str | None] = mapped_column(Text)
    observations: Mapped[str | None] = mapped_column(Text)
    connected_topic_codes: Mapped[str | None] = mapped_column(Text)  # JSON list of topic codes
    origin: Mapped[str] = mapped_column(String(10), nullable=False, default="manual")
    review_status: Mapped[str] = mapped_column(String(10), nullable=False, default="draft")
    bookmarked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ai_model: Mapped[str | None] = mapped_column(String(120))
    generated_at: Mapped[datetime | None] = mapped_column(DateTime)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)

    topic: Mapped[Topic] = relationship()
    versions: Mapped[list[RevisionCardVersion]] = relationship(cascade="all, delete-orphan")


class RevisionCardVersion(Base):
    __tablename__ = "revision_card_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("revision_cards.id", ondelete="CASCADE"), nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


# --------------------------------------------------------------------------- mock exams
class MockExam(Base):
    __tablename__ = "mock_exams"
    __table_args__ = (
        CheckConstraint("status IN ('in_progress','submitted')", name="status"),
        CheckConstraint("mode IN ('full','short')", name="mode"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="in_progress")
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    max_marks: Mapped[float] = mapped_column(Float, nullable=False)
    includes_ai: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    eligibility_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    blueprint_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    auto_submitted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    current_position: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    score: Mapped[float | None] = mapped_column(Float)
    correct_count: Mapped[int | None] = mapped_column(Integer)
    wrong_count: Mapped[int | None] = mapped_column(Integer)
    unanswered_count: Mapped[int | None] = mapped_column(Integer)
    negative_marks: Mapped[float | None] = mapped_column(Float)
    time_spent_sec: Mapped[int | None] = mapped_column(Integer)
    review_notes: Mapped[str | None] = mapped_column(Text)

    questions: Mapped[list[MockExamQuestion]] = relationship(
        back_populates="exam", order_by="MockExamQuestion.position", cascade="all, delete-orphan"
    )


class MockExamQuestion(Base):
    __tablename__ = "mock_exam_questions"
    __table_args__ = (
        UniqueConstraint("exam_id", "position", name="uq_mock_exam_questions_pos"),
        CheckConstraint("section IN ('GA','DA')", name="section"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("mock_exams.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    question_id: Mapped[int | None] = mapped_column(ForeignKey("questions.id", ondelete="SET NULL"))
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"))
    section: Mapped[str] = mapped_column(String(4), nullable=False)
    marks: Mapped[int] = mapped_column(Integer, nullable=False)
    qtype: Mapped[str] = mapped_column(String(4), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)

    exam: Mapped[MockExam] = relationship(back_populates="questions")
    answer: Mapped[MockAnswer | None] = relationship(
        back_populates="exam_question", uselist=False, cascade="all, delete-orphan"
    )


class MockAnswer(Base):
    __tablename__ = "mock_answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_question_id: Mapped[int] = mapped_column(
        ForeignKey("mock_exam_questions.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    response: Mapped[str | None] = mapped_column(String(200))
    marked_for_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    visited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    time_spent_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    is_correct: Mapped[bool | None] = mapped_column(Boolean)
    marks_awarded: Mapped[float | None] = mapped_column(Float)

    exam_question: Mapped[MockExamQuestion] = relationship(back_populates="answer")


# --------------------------------------------------------------------------- attention
class AttentionSession(Base):
    __tablename__ = "attention_sessions"
    __table_args__ = (
        CheckConstraint("minutes >= 1 AND minutes <= 1440", name="minutes"),
        Index("ix_attention_sessions_date", "session_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


# --------------------------------------------------------------------------- finance / research
class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("domain", "name", name="uq_projects_domain_name"),
        CheckConstraint("domain IN ('finance','research')", name="domain"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    domain: Mapped[str] = mapped_column(String(12), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class WorkLog(TimestampMixin, Base):
    __tablename__ = "work_logs"
    __table_args__ = (
        CheckConstraint("domain IN ('finance','research')", name="domain"),
        CheckConstraint("duration_minutes >= 1 AND duration_minutes <= 1440", name="duration"),
        Index("ix_work_logs_domain_date", "domain", "log_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    domain: Mapped[str] = mapped_column(String(12), nullable=False)
    log_date: Mapped[date] = mapped_column(Date, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    tags: Mapped[str | None] = mapped_column(String(200))
    what_done: Mapped[str] = mapped_column(Text, nullable=False)
    research_direction: Mapped[str | None] = mapped_column(Text)
    next_steps: Mapped[str | None] = mapped_column(Text)
    milestone: Mapped[str | None] = mapped_column(Text)
    outputs: Mapped[str | None] = mapped_column(Text)
    references_text: Mapped[str | None] = mapped_column(Text)

    project: Mapped[Project | None] = relationship()


# --------------------------------------------------------------------------- habits
class Habit(Base):
    __tablename__ = "habits"
    __table_args__ = (
        CheckConstraint("kind IN ('check','numeric')", name="kind"),
        CheckConstraint("target_value > 0", name="target"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(20))
    target_value: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class HabitEntry(TimestampMixin, Base):
    __tablename__ = "habit_entries"
    __table_args__ = (
        UniqueConstraint("habit_id", "entry_date", name="uq_habit_entries_habit_date"),
        CheckConstraint("value >= 0", name="value"),
        Index("ix_habit_entries_date", "entry_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    habit_id: Mapped[int] = mapped_column(ForeignKey("habits.id", ondelete="CASCADE"), nullable=False)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    habit: Mapped[Habit] = relationship()


# --------------------------------------------------------------------------- not-to-do
class AvoidanceRule(Base):
    __tablename__ = "avoidance_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AvoidanceEntry(TimestampMixin, Base):
    __tablename__ = "avoidance_entries"
    __table_args__ = (
        UniqueConstraint("rule_id", "entry_date", name="uq_avoidance_entries_rule_date"),
        CheckConstraint("status IN ('complied','violated')", name="status"),
        Index("ix_avoidance_entries_date", "entry_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("avoidance_rules.id", ondelete="CASCADE"), nullable=False)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    rule: Mapped[AvoidanceRule] = relationship()


# --------------------------------------------------------------------------- reflections
class Reflection(TimestampMixin, Base):
    __tablename__ = "reflections"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_date: Mapped[date] = mapped_column(Date, unique=True, nullable=False)
    went_well: Mapped[str] = mapped_column(Text, nullable=False)
    did_not_go_well: Mapped[str] = mapped_column(Text, nullable=False)
    smallest_step: Mapped[str] = mapped_column(Text, nullable=False)
    ai_suggestion: Mapped[str | None] = mapped_column(Text)


# --------------------------------------------------------------------------- gamification
class XPEvent(Base):
    __tablename__ = "xp_events"
    __table_args__ = (
        Index("ix_xp_events_date", "event_date"),
        CheckConstraint("amount >= 0", name="amount"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    rule: Mapped[str] = mapped_column(String(40), nullable=False)
    source_key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class Achievement(Base):
    __tablename__ = "achievements"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(String(240), nullable=False)
    icon: Mapped[str] = mapped_column(String(40), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class UserAchievement(Base):
    __tablename__ = "user_achievements"

    id: Mapped[int] = mapped_column(primary_key=True)
    achievement_id: Mapped[int] = mapped_column(
        ForeignKey("achievements.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    unlocked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    unlocked_on: Mapped[date] = mapped_column(Date, nullable=False)

    achievement: Mapped[Achievement] = relationship()


# --------------------------------------------------------------------------- settings & cache
class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class AICache(Base):
    __tablename__ = "ai_cache"
    __table_args__ = (CheckConstraint("kind IN ('chat','search','fetch')", name="kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cache_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    model: Mapped[str | None] = mapped_column(String(120))
    response_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)


USER_DATA_TABLES: tuple[str, ...] = (
    "topic_progress",
    "progress_audit",
    "study_logs",
    "revision_cycles",
    "revision_events",
    "questions",
    "question_topics",
    "question_attempts",
    "revision_cards",
    "revision_card_versions",
    "mock_exams",
    "mock_exam_questions",
    "mock_answers",
    "attention_sessions",
    "projects",
    "work_logs",
    "habits",
    "habit_entries",
    "avoidance_rules",
    "avoidance_entries",
    "reflections",
    "xp_events",
    "user_achievements",
    "settings",
)
"""Tables exported/restored as user data, in FK-safe insertion order."""

PRIVATE_TABLES: frozenset[str] = frozenset({"avoidance_rules", "avoidance_entries"})
"""Not-to-do data: never sent to AI; excluded from CSV export unless explicitly included."""
