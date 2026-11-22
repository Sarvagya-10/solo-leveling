from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from shogun.db.models import Habit
from shogun.services import (
    analytics_service,
    attention_service,
    avoidance_service,
    habit_service,
    reflection_service,
    settings_service,
    study_log_service,
    worklog_service,
)
from shogun.services.errors import ValidationError
from shogun.services.study_log_service import StudyEntryInput
from shogun.services.worklog_service import WorkLogInput
from tests.conftest import topic_id

D = date(2026, 11, 10)


def test_attention_no_prefill_and_separate_metrics(db):
    assert attention_service.daily_series(db) == []
    s = attention_service.summary(db)
    assert s.personal_best is None and s.baseline == 5 and s.target == 200
    attention_service.add_session(db, D, 25, None, today=D)
    attention_service.add_session(db, D, 40, None, today=D)
    attention_service.add_session(db, date(2026, 11, 12), 30, None, today=date(2026, 11, 12))
    series = attention_service.daily_series(db)
    assert [(r.day, r.longest, r.total) for r in series] == [(D, 40, 65), (date(2026, 11, 12), 30, 30)]
    assert series[1].rolling_avg == 35.0
    s = attention_service.summary(db)
    assert s.personal_best == 40 and s.progress_pct == 20.0
    with pytest.raises(ValidationError):
        attention_service.add_session(db, D, 0, None, today=D)
    with pytest.raises(ValidationError):
        attention_service.add_session(db, date(2026, 11, 13), 10, None, today=D)


def test_habits_three_states_and_numeric_water(db):
    water = db.scalar(select(Habit).where(Habit.key == "water"))
    prayer = db.scalar(select(Habit).where(Habit.key == "prayer"))
    assert water.kind == "numeric" and water.unit == "litres" and water.target_value == 3.0
    habit_service.upsert_entry(db, water.id, D, 2.5, None, today=D)
    habit_service.upsert_entry(db, prayer.id, D, 1, "fajr", today=D)
    day = habit_service.daily_summary(db, D, D)[0]
    assert (day.applicable, day.done, day.not_done, day.missing) == (8, 1, 1, 6)
    habit_service.upsert_entry(db, water.id, D, 3.2, None, today=D)
    assert habit_service.daily_summary(db, D, D)[0].done == 2
    with pytest.raises(ValidationError):
        habit_service.upsert_entry(db, prayer.id, D, 0.5, None, today=D)
    habit_service.update_habit(db, water.id, target=4.0)
    assert habit_service.daily_summary(db, D, D)[0].done == 1


def test_avoidance_missing_is_not_success(db):
    rules = avoidance_service.list_rules(db)
    assert len(rules) == 7
    avoidance_service.set_status(db, rules[0].id, D, "complied", None, today=D)
    avoidance_service.set_status(db, rules[1].id, D, "violated", None, today=D)
    day = avoidance_service.daily_compliance(db, D, D)[0]
    assert (day.complied, day.violated, day.missing) == (1, 1, 5)
    assert day.compliance_pct == round(100 / 7, 1)
    assert day.logged_compliance_pct == 50.0
    assert avoidance_service.rule_streak(db, rules[0].id, D) == 1
    assert avoidance_service.rule_streak(db, rules[2].id, D) == 0


def test_worklogs_targets_independent(db):
    worklog_service.add_log(db, WorkLogInput("finance", D, 60, "Built DCF model", project_name="Valuation"),
                            today=D)
    worklog_service.add_log(db, WorkLogInput("research", D, 30, "Read paper", references_text="arXiv:1234"),
                            today=D)
    fin = worklog_service.summary(db, "finance", D, D)
    res = worklog_service.summary(db, "research", D, D)
    assert fin.days_met == 1 and res.days_met == 0
    settings_service.set_setting(db, "research_target_minutes", 30)
    assert worklog_service.summary(db, "research", D, D).days_met == 1
    with pytest.raises(ValidationError):
        worklog_service.add_log(db, WorkLogInput("finance", D, 0, "x"), today=D)
    assert worklog_service.projects(db, "finance")[0].name == "Valuation"


def test_reflection_requires_all_prompts_and_search(db):
    with pytest.raises(ValidationError, match="did not go well"):
        reflection_service.upsert(db, D, "Studied well", "", "Sleep earlier", today=D)
    reflection_service.upsert(db, D, "Studied linear algebra", "Phone distraction", "Phone in other room", today=D)
    assert [r.entry_date for r in reflection_service.search(db, "phone")] == [D]
    assert reflection_service.search(db, "nothing-matches") == []


def test_execution_metrics_exclude_unlogged(db):
    settings_service.set_setting(db, "daily_study_target_minutes", 60)
    settings_service.set_setting(db, "daily_pyq_target", 0)
    m = analytics_service.daily_metrics(db, D, D)[0]
    # nothing logged: everything applicable, nothing completed, missing flagged
    assert m.study_applicable == 1 and m.study_completed == 0
    assert m.overall_completed == 0
    assert m.overall_applicable == 1 + 8 + 7 + 3
    assert m.missing_items == 8 + 7 + 1 + 3
    study_log_service.log_study(db, D, [StudyEntryInput(topic_id(db, "DA.2.12"), 60)], today=D)
    m = analytics_service.daily_metrics(db, D, D)[0]
    assert m.study_pct == 100.0 and m.study_logged
    # the revision scheduled for D+1 becomes an applicable study target on D+1
    m2 = analytics_service.daily_metrics(db, date(2026, 11, 11), date(2026, 11, 11))[0]
    assert m2.revisions_due == 1 and m2.study_applicable == 2
