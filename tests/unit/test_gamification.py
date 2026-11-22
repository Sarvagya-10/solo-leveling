from __future__ import annotations

from datetime import date

from sqlalchemy import func, select

from shogun.db.models import Habit, RevisionEvent, TopicProgress, XPEvent
from shogun.services import gamification_service as g
from shogun.services import habit_service, revision_service, study_log_service
from shogun.services.study_log_service import StudyEntryInput
from tests.conftest import topic_id

D = date(2026, 11, 10)
TZ = "Asia/Kolkata"


def test_level_curve_and_ranks():
    assert g.xp_threshold(1) == 0
    assert g.xp_threshold(2) == 100
    assert g.xp_threshold(3) == 225
    assert g.level_for_xp(0).level == 1
    assert g.level_for_xp(99).level == 1
    assert g.level_for_xp(100).level == 2
    info = g.level_for_xp(150)
    assert (info.into_level, info.span) == (50, 125)
    assert g.rank_for_level(1) == "E" and g.rank_for_level(10) == "C" and g.rank_for_level(60) == "National Level"


def test_study_xp_rules_and_idempotent_sync(db):
    study_log_service.log_study(db, D, [StudyEntryInput(topic_id(db, "DA.2.12"), 95, 6, 5)], today=D)
    g.sync_day(db, D, TZ)
    g.sync_day(db, D, TZ)  # repeated sync must not double count
    rules = dict(db.execute(select(XPEvent.rule, XPEvent.amount)).all())
    assert rules == {"study_topic": 10, "study_time": 15, "pyq_correct": 5}
    assert g.total_xp(db) == 30


def test_xp_revoked_when_source_removed(db):
    res = study_log_service.log_study(db, D, [StudyEntryInput(topic_id(db, "DA.2.12"), 60)], today=D)
    g.sync_day(db, D, TZ)
    assert g.total_xp(db) > 0
    study_log_service.delete_study_log(db, res.log_ids[0])
    g.sync_day(db, D, TZ)
    assert g.total_xp(db) == 0


def test_revision_xp_follows_completion_and_undo(db):
    study_log_service.log_study(db, D, [StudyEntryInput(topic_id(db, "DA.2.12"), 10)], today=D)
    r1 = db.scalar(select(RevisionEvent).where(RevisionEvent.stage == 1))
    revision_service.complete_revision(db, r1.id, date(2026, 11, 11))
    g.sync_day(db, date(2026, 11, 11), TZ)
    assert db.scalar(select(XPEvent.amount).where(XPEvent.rule == "revision")) == 15
    undone = revision_service.undo_revision(db, r1.id)
    g.sync_day(db, undone, TZ)
    assert db.scalar(select(func.count(XPEvent.id)).where(XPEvent.rule == "revision")) == 0


def test_habit_not_met_gives_no_xp(db):
    water = db.scalar(select(Habit).where(Habit.key == "water"))
    habit_service.upsert_entry(db, water.id, D, 1.0, None, today=D)
    g.sync_day(db, D, TZ)
    assert g.total_xp(db) == 0
    habit_service.upsert_entry(db, water.id, D, 3.0, None, today=D)
    g.sync_day(db, D, TZ)
    assert g.total_xp(db) == 5


def test_gamification_never_modifies_academic_data(db):
    study_log_service.log_study(db, D, [StudyEntryInput(topic_id(db, "DA.2.12"), 60, status="in_progress")],
                                today=D)
    before = [(p.topic_id, p.coverage_status, p.total_minutes, p.revision_stage)
              for p in db.scalars(select(TopicProgress).order_by(TopicProgress.topic_id))]
    g.sync_all(db, TZ, D)
    g.evaluate_achievements(db, D, TZ)
    g.daily_quests(db, D, TZ)
    after = [(p.topic_id, p.coverage_status, p.total_minutes, p.revision_stage)
             for p in db.scalars(select(TopicProgress).order_by(TopicProgress.topic_id))]
    assert before == after


def test_achievement_unlock_and_revoke(db):
    res = study_log_service.log_study(db, D, [StudyEntryInput(topic_id(db, "DA.2.12"), 30)], today=D)
    new = g.evaluate_achievements(db, D, TZ)
    assert "first_log" in {a.key for a in new}
    study_log_service.delete_study_log(db, res.log_ids[0])
    g.evaluate_achievements(db, D, TZ)
    unlocked = {a.key for a, ua in g.achievements_view(db) if ua is not None}
    assert "first_log" not in unlocked


def test_streaks(db):
    tid = topic_id(db, "DA.2.12")
    for day in (8, 9, 10):
        d = date(2026, 11, day)
        study_log_service.log_study(db, d, [StudyEntryInput(tid, 30)], today=d)
    assert g.study_streak(db, date(2026, 11, 10)) == 3
    assert g.study_streak(db, date(2026, 11, 11)) == 3  # today not yet logged keeps streak
    assert g.study_streak(db, date(2026, 11, 12)) == 0


def test_daily_quests_shape(db):
    quests = g.daily_quests(db, D, TZ)
    keys = [q.key for q in quests]
    assert keys == ["study", "pyq", "revision", "habits", "finance", "research", "attention", "adapt"]
    rev = next(q for q in quests if q.key == "revision")
    assert rev.applicable is False  # nothing due
