"""UI smoke tests: every page renders without exceptions (empty DB and populated DB), no API keys."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

PAGES = [
    ("shogun.ui.pages.dashboard", "render"),
    ("shogun.ui.pages.system", "render"),
    ("shogun.ui.pages.syllabus", "render"),
    ("shogun.ui.pages.daily_log", "render"),
    ("shogun.ui.pages.revisions", "render"),
    ("shogun.ui.pages.aptitude", "render"),
    ("shogun.ui.pages.cards", "render"),
    ("shogun.ui.pages.question_bank", "render"),
    ("shogun.ui.pages.war", "render"),
    ("shogun.ui.pages.attention", "render"),
    ("shogun.ui.pages.worklogs", "render_finance"),
    ("shogun.ui.pages.worklogs", "render_research"),
    ("shogun.ui.pages.habits", "render"),
    ("shogun.ui.pages.not_todo", "render"),
    ("shogun.ui.pages.adapt", "render"),
    ("shogun.ui.pages.analytics", "render"),
    ("shogun.ui.pages.settings_page", "render"),
]

pytestmark = pytest.mark.ui


def _page_script(module_name: str, func_name: str) -> None:
    import importlib

    from shogun.ui.theme import inject_theme

    inject_theme()
    getattr(importlib.import_module(module_name), func_name)()


@pytest.fixture
def app_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SHOGUN_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv("SHOGUN_VAR_DIR", str(tmp_path / "var"))
    for var in ("GROQ_API_KEY", "SERPAPI_API_KEY", "GROQ_MODEL"):
        monkeypatch.delenv(var, raising=False)
    from shogun.ui import context

    context.reset_ctx()
    yield tmp_path
    context.reset_ctx()


def _populate() -> None:
    from sqlalchemy import select

    from shogun.db.models import Habit, Topic
    from shogun.services import (
        attention_service,
        avoidance_service,
        card_service,
        exam_service,
        habit_service,
        progress_service,
        question_service,
        reflection_service,
        revision_service,
        study_log_service,
        worklog_service,
    )
    from shogun.services.question_service import QuestionInput
    from shogun.services.study_log_service import StudyEntryInput
    from shogun.services.worklog_service import WorkLogInput
    from shogun.ui.context import get_ctx

    ctx = get_ctx()
    today = ctx.today()
    with ctx.session() as s:
        tid = s.scalar(select(Topic.id).where(Topic.code == "DA.2.12"))
        ga = s.scalar(select(Topic.id).where(Topic.code == "GA.2.05"))
        d0 = today - timedelta(days=3)
        study_log_service.log_study(s, d0, [StudyEntryInput(tid, 90, 8, 6, "mastered")], today=today)
        study_log_service.log_study(s, today, [StudyEntryInput(ga, 30, 4, 3, "in_progress")], today=today)
        progress_service.override_coverage(s, ga, "mastered", "covered", today)
        ev = revision_service.due_today(s, d0 + timedelta(days=1)) or revision_service.overdue(s, today)
        if ev:
            revision_service.complete_revision(s, ev[0].id, today)
        attention_service.add_session(s, today, 45, "deep work", today=today)
        worklog_service.add_log(s, WorkLogInput("finance", today, 60, "Valuation work", project_name="DCF"), today=today)
        worklog_service.add_log(s, WorkLogInput("research", today, 40, "Paper reading", milestone="M1"), today=today)
        water = s.scalar(select(Habit.id).where(Habit.key == "water"))
        habit_service.upsert_entry(s, water, today, 2.0, None, today=today)
        rules = avoidance_service.list_rules(s)
        avoidance_service.set_status(s, rules[0].id, today, "complied", None, today=today)
        reflection_service.upsert(s, today, "Good focus", "Late start", "Start at 7", today=today)
        card_service.save_card(s, tid, {"basic_idea": "Av = λv", "formulae": "- det(A-λI)=0"}, ["DA.2.13"])
        for i, (code, marks, qtype) in enumerate([("DA.2.12", 1, "MCQ"), ("DA.2.12", 2, "NAT"),
                                                  ("GA.2.05", 1, "MSQ")]):
            q = question_service.add_question(s, QuestionInput(
                topic_codes=[code], source_type="official_pyq", qtype=qtype, marks=marks,
                stem=f"Sample verified question number {i} for smoke testing purposes",
                options=["a", "b", "c", "d"] if qtype != "NAT" else [], answer_key="A" if qtype != "NAT" else None,
                nat_low=1.0 if qtype == "NAT" else None, nat_high=2.0 if qtype == "NAT" else None,
                exam_year=2025, question_ref=f"Q.{i}", source_url="https://example.org"))
            question_service.set_verification(s, q.id, "verified")
        exam = exam_service.create_exam(s, exam_service.plan_paper(s, seed=5), allow_short=True)
        exam_service.save_answer(s, exam.id, 1, response="A")
        exam_service.submit_exam(s, exam.id, tz=ctx.tz)


def _run(module: str, func: str) -> AppTest:
    at = AppTest.from_function(_page_script, args=(module, func), default_timeout=60)
    at.run()
    return at


@pytest.mark.parametrize("module,func", PAGES)
def test_page_renders_on_empty_database(app_env, module, func):
    at = _run(module, func)
    assert not at.exception, [e.value for e in at.exception]


@pytest.mark.parametrize("module,func", PAGES)
def test_page_renders_with_data(app_env, module, func):
    _populate()
    at = _run(module, func)
    assert not at.exception, [e.value for e in at.exception]


def test_full_app_entrypoint_runs(app_env):
    at = AppTest.from_file(str(Path(__file__).resolve().parents[2] / "app.py"), default_timeout=60)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    html = " ".join(m.value for m in at.markdown)
    assert "Shogun : Phase 3 - Solo Leveling" in html


def test_no_api_key_ai_actions_degrade_gracefully(app_env):
    """Generating a card without keys must show a configuration message, not crash."""
    at = _run("shogun.ui.pages.cards", "render")
    gen = [b for b in at.button if b.key == "card_gen"]
    assert gen, "generate button present"
    gen[0].click().run()
    assert not at.exception
    assert any("GROQ_API_KEY" in w.value for w in at.warning)


def test_daily_log_form_schedules_revisions(app_env):
    at = _run("shogun.ui.pages.daily_log", "render")
    from sqlalchemy import select

    from shogun.db.models import Topic
    from shogun.ui.context import get_ctx

    with get_ctx().session() as s:
        tid = s.scalar(select(Topic.id).where(Topic.code == "DA.1.08"))
    at.multiselect(key="dl_DA_topics").select(tid).run()
    at.number_input(key=f"dl_DA_m_{tid}").set_value(75).run()
    at.button(key="FormSubmitter:dl_DA_form-Save study log & schedule revisions").click().run()
    assert not at.exception
    assert not at.error, [e.value for e in at.error]
    from shogun.services import revision_service

    with get_ctx().session() as s:
        today = get_ctx().today()
        assert len(revision_service.upcoming(s, today, days=30)) == 4


def test_exam_room_answer_autosave_navigation_and_resume(app_env):
    from sqlalchemy import select

    from shogun.db.models import MockAnswer, Topic
    from shogun.services import exam_service, progress_service, question_service
    from shogun.services.question_service import QuestionInput
    from shogun.ui.context import get_ctx

    ctx = get_ctx()
    today = ctx.today()
    with ctx.session() as s:
        tid = s.scalar(select(Topic.id).where(Topic.code == "DA.2.12"))
        progress_service.override_coverage(s, tid, "mastered", "covered", today)
        for i in range(3):
            q = question_service.add_question(s, QuestionInput(
                topic_codes=["DA.2.12"], source_type="official_pyq", qtype="MCQ", marks=1,
                stem=f"Exam room question number {i} about eigenvalues", options=["p", "q", "r", "s"],
                answer_key="B", exam_year=2025, question_ref=f"Q.{i}", source_url="https://example.org"))
            question_service.set_verification(s, q.id, "verified")
        exam = exam_service.create_exam(s, exam_service.plan_paper(s, seed=1), allow_short=True)
        exam_id = exam.id

    at = _run("shogun.ui.pages.war", "render")
    assert not at.exception, [e.value for e in at.exception]
    radios = [r for r in at.radio if r.key and r.key.endswith("_resp")]
    assert radios, "MCQ options rendered"
    radios[0].set_value("B").run()  # on_change autosave
    assert not at.exception
    with ctx.session() as s:
        answers = s.scalars(select(MockAnswer)).all()
        assert sum(1 for a in answers if a.response == "B") == 1
    nxt = [b for b in at.button if b.key and b.key.endswith("_next")]
    nxt[0].click().run()
    assert not at.exception
    mark = [b for b in at.button if b.key and b.key.endswith("_marknext")]
    mark[0].click().run()
    assert not at.exception
    with ctx.session() as s:
        exam = exam_service.get_exam(s, exam_id)
        assert exam.status == "in_progress" and exam.current_position == 3
        assert sum(1 for q in exam.questions if q.answer.marked_for_review) == 1
    # a fresh session (e.g. browser refresh) resumes the same paper and position from the database
    at2 = _run("shogun.ui.pages.war", "render")
    assert not at2.exception
    assert any("Question 3 of 3" in m.value for m in at2.markdown)
