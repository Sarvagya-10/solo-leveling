"""End-to-end service flows on real temporary SQLite databases."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import func, select

from shogun.db.base import Base
from shogun.db.models import (
    AvoidanceEntry,
    QuestionAttempt,
    RevisionEvent,
    StudyLog,
    Topic,
    TopicProgress,
    XPEvent,
)
from shogun.db.session import make_engine, run_migrations, session_factory, session_scope
from shogun.services import (
    analytics_service,
    avoidance_service,
    backup_service,
    exam_service,
    gamification_service,
    progress_service,
    question_service,
    reflection_service,
    revision_service,
    study_log_service,
)
from shogun.services.errors import ValidationError
from shogun.services.question_service import QuestionInput
from shogun.services.seed import seed_all
from shogun.services.study_log_service import StudyEntryInput
from shogun.timeutil import local_date_of, local_today
from tests.conftest import topic_id

TZ = "Asia/Kolkata"
D = date(2026, 11, 10)


def test_migrations_match_models(tmp_path: Path):
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    run_migrations(url)
    engine = make_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    assert diff == [], diff


def test_study_entry_schedules_revisions_and_awards_xp(db):
    tid = topic_id(db, "DA.4.12")
    result = study_log_service.log_study(db, D, [StudyEntryInput(tid, 90, 5, 4, "mastered")], today=D)
    gamification_service.after_change(db, {D}, D, TZ)
    assert [d for d in result.scheduled[0].due_dates] == [D + timedelta(days=n) for n in (1, 3, 7, 21)]
    row = next(r for r in progress_service.topic_rows(db) if r.topic_id == tid)
    assert row.coverage_status == "mastered" and row.revisions[4].due_date == D + timedelta(days=21)
    assert gamification_service.total_xp(db) == 10 + 15 + 4  # topic + 90min + 4 correct


def test_revision_completion_updates_topic_progress(db):
    tid = topic_id(db, "DA.4.12")
    study_log_service.log_study(db, D, [StudyEntryInput(tid, 30)], today=D)
    events = sorted(db.scalars(select(RevisionEvent).where(RevisionEvent.topic_id == tid)), key=lambda e: e.stage)
    for e in events[:3]:
        revision_service.complete_revision(db, e.id, e.due_date, minutes=15, confidence=4)
    row = next(r for r in progress_service.topic_rows(db) if r.topic_id == tid)
    assert row.revision_stage == 3
    assert [row.revisions[i].status for i in range(1, 5)] == ["completed"] * 3 + ["pending"]
    audit = [a for a in progress_service.audit_log(db, tid) if a.field == "revision_stage"]
    assert len(audit) == 3


def _verified(db, code, marks, qtype="MCQ", n=0):
    q = question_service.add_question(db, QuestionInput(
        topic_codes=[code], source_type="official_pyq", qtype=qtype, marks=marks,
        stem=f"Integration question {n} for {code} worth {marks}", options=["w", "x", "y", "z"],
        answer_key="C", exam_year=2024, question_ref=f"Q.{n}", source_url="https://example.org/da2024"))
    question_service.set_verification(db, q.id, "verified")
    return q


def test_mock_exam_creation_submission_analytics(db):
    progress_service.override_coverage(db, topic_id(db, "DA.4.12"), "mastered", "covered", D)
    progress_service.override_coverage(db, topic_id(db, "GA.1.01"), "mastered", "covered", D)
    for i in range(3):
        _verified(db, "DA.4.12", 1 + i % 2, n=i)
    _verified(db, "GA.1.01", 1, n=10)
    _verified(db, "DA.4.13", 1, n=11)  # NOT eligible
    start = datetime(2026, 11, 14, 3, 30)
    plan = exam_service.plan_paper(db, seed=99)
    exam = exam_service.create_exam(db, plan, allow_short=True, now=start)
    codes = {json.loads(q.snapshot_json)["topic_code"] for q in exam.questions}
    assert codes == {"DA.4.12", "GA.1.01"}
    for q in exam.questions:
        exam_service.save_answer(db, exam.id, q.position, response="C" if q.position % 2 else "A",
                                 now=start + timedelta(minutes=q.position), elapsed_sec=60)
    exam = exam_service.submit_exam(db, exam.id, now=start + timedelta(minutes=20), tz=TZ)
    an = exam_service.analyse(db, exam.id)
    assert an.overall.questions == 4 and an.overall.correct + an.overall.wrong == 4
    assert exam.score == pytest.approx(sum(i["marks_awarded"] for i in an.items))
    # in-app attempts on verified PYQs feed topic PYQ mastery counts
    assert db.scalar(select(func.count(QuestionAttempt.id)).where(QuestionAttempt.context == "mock")) == 4
    row = next(r for r in progress_service.topic_rows(db) if r.code == "DA.4.12")
    assert row.pyq_inapp_attempted == 3
    gamification_service.after_change(db, {local_date_of(exam.submitted_at, TZ)}, D, TZ)
    assert db.scalar(select(XPEvent.amount).where(XPEvent.rule == "mock_short")) == 25


def _populate(db):
    tid = topic_id(db, "DA.6.05")
    study_log_service.log_study(db, D, [StudyEntryInput(tid, 60, 3, 2, "in_progress", "note")], today=D)
    rule = avoidance_service.list_rules(db)[0]
    avoidance_service.set_status(db, rule.id, D, "violated", "private", today=D)
    reflection_service.upsert(db, D, "went well", "not well", "small step", today=D)
    _verified(db, "DA.6.05", 2, n=50)
    gamification_service.after_change(db, {D}, D, TZ)
    db.commit()


def _snapshot(db):
    return {
        "logs": db.scalar(select(func.count(StudyLog.id))),
        "events": db.scalar(select(func.count(RevisionEvent.id))),
        "avoid": db.scalar(select(func.count(AvoidanceEntry.id))),
        "xp": gamification_service.total_xp(db),
        "minutes": db.scalar(select(TopicProgress.total_minutes).join(Topic).where(Topic.code == "DA.6.05")),
    }


def test_export_import_roundtrip(db, engine):
    _populate(db)
    before = _snapshot(db)
    payload = json.loads(backup_service.export_json_bytes(db, include_private=True))
    assert payload["tables"]["study_logs"][0]["topic_id"] == "DA.6.05"  # stable code, not internal id
    backup_service.reset_all_data(db, "RESET")
    seed_all(db, D, bundled_pyqs=False)
    db.commit()
    assert _snapshot(db)["logs"] == 0
    backup_service.import_data(db, payload)
    seed_all(db, D, bundled_pyqs=False)
    db.commit()
    assert _snapshot(db) == before


def test_export_without_private_keeps_private_tables_on_import(db):
    _populate(db)
    payload = json.loads(backup_service.export_json_bytes(db, include_private=False))
    assert "avoidance_entries" not in payload["tables"]
    backup_service.import_data(db, payload)
    db.commit()
    assert db.scalar(select(func.count(AvoidanceEntry.id))) == 1


def test_csv_export_excludes_private_by_default(db):
    import io
    import zipfile

    _populate(db)
    names = zipfile.ZipFile(io.BytesIO(backup_service.export_csv_zip(db))).namelist()
    assert "study_logs.csv" in names and "avoidance_entries.csv" not in names


def test_import_rejects_garbage(db):
    with pytest.raises(ValidationError):
        backup_service.import_data(db, {"format": "nope"})


def test_backup_and_restore_roundtrip(tmp_path: Path):
    url = f"sqlite:///{(tmp_path / 'live.db').as_posix()}"
    run_migrations(url)
    engine = make_engine(url)
    with session_scope(engine) as s:
        seed_all(s, D, bundled_pyqs=False)
        study_log_service.log_study(s, D, [StudyEntryInput(topic_id(s, "DA.1.08"), 45)], today=D)
    backup = backup_service.backup_database(engine, tmp_path / "backups", "test")
    with session_scope(engine) as s:
        backup_service.reset_all_data(s, "RESET")
    with session_scope(engine) as s:
        assert s.scalar(select(func.count(StudyLog.id))) == 0
    safety = backup_service.restore_backup(engine, backup, tmp_path / "backups")
    assert safety.exists()
    with session_scope(engine) as s:
        assert s.scalar(select(func.count(StudyLog.id))) == 1
    with pytest.raises(ValidationError):
        backup_service.restore_backup(engine, tmp_path / "missing.db", tmp_path / "backups")
    engine.dispose()


def test_reset_requires_confirmation(db):
    with pytest.raises(ValidationError):
        backup_service.reset_all_data(db, "reset")


def test_data_persists_across_engine_restart(tmp_path: Path):
    url = f"sqlite:///{(tmp_path / 'p.db').as_posix()}"
    run_migrations(url)
    engine = make_engine(url)
    with session_scope(engine) as s:
        seed_all(s, D, bundled_pyqs=False)
        study_log_service.log_study(s, D, [StudyEntryInput(topic_id(s, "DA.2.01"), 50, status="mastered")], today=D)
    engine.dispose()
    engine2 = make_engine(url)
    session = session_factory(engine2)()
    row = next(r for r in progress_service.topic_rows(session) if r.code == "DA.2.01")
    assert row.coverage_status == "mastered" and row.total_minutes == 50
    m = analytics_service.daily_metrics(session, D, D)[0]
    assert m.study_minutes == 50
    session.close()
    engine2.dispose()


@pytest.mark.parametrize(
    "utc,tz,expected",
    [
        (datetime(2026, 11, 22, 18, 29), "Asia/Kolkata", date(2026, 11, 22)),  # 23:59 IST
        (datetime(2026, 11, 22, 18, 30), "Asia/Kolkata", date(2026, 11, 23)),  # 00:00 IST next day
        (datetime(2026, 12, 31, 20, 0), "Asia/Kolkata", date(2027, 1, 1)),
        (datetime(2027, 3, 14, 6, 59), "America/New_York", date(2027, 3, 14)),  # DST change day
    ],
)
def test_local_date_boundaries(utc, tz, expected):
    assert local_today(tz, now_utc=utc) == expected
    assert local_date_of(utc, tz) == expected
