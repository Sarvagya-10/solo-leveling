from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from shogun.services import exam_service, progress_service, question_service
from shogun.services.errors import ConflictError, ValidationError
from shogun.services.question_service import QuestionInput
from tests.conftest import topic_id

D = date(2026, 11, 10)


def make_q(db, code, marks=1, qtype="MCQ", source="official_pyq", verify=True, extra_codes=(), n=0):
    data = QuestionInput(
        topic_codes=[code, *extra_codes], source_type=source, qtype=qtype, marks=marks,
        stem=f"Question {n} on {code} with marks {marks} type {qtype} — compute the value",
        options=["one", "two", "three", "four"] if qtype != "NAT" else [],
        answer_key={"MCQ": "A", "MSQ": "A,B"}.get(qtype), nat_low=1.0 if qtype == "NAT" else None,
        nat_high=1.5 if qtype == "NAT" else None, exam_year=2025 if source == "official_pyq" else None,
        question_ref=f"Q.{n}" if source == "official_pyq" else None,
        source_url="https://example.org/paper" if source == "official_pyq" else None,
    )
    q = question_service.add_question(db, data)
    if verify:
        question_service.set_verification(db, q.id, "verified")
    return q


def master(db, code):
    progress_service.override_coverage(db, topic_id(db, code), "mastered", "covered", D)


def test_blueprint_is_official():
    assert exam_service.FULL_QUESTIONS == 65
    assert exam_service.FULL_MARKS == 100
    ga = [s for s in exam_service.FULL_BLUEPRINT if s.section == "GA"]
    da = [s for s in exam_service.FULL_BLUEPRINT if s.section == "DA"]
    assert sum(s.count for s in ga) == 10 and sum(s.count * s.marks for s in ga) == 15
    assert sum(s.count for s in da) == 55 and sum(s.count * s.marks for s in da) == 85


def test_only_eligible_topics_are_used(db):
    master(db, "DA.2.12")
    ok = make_q(db, "DA.2.12", n=1)
    not_covered = make_q(db, "DA.2.13", n=2)
    mixed = make_q(db, "DA.2.12", extra_codes=("DA.2.13",), n=3)
    unverified = make_q(db, "DA.2.12", verify=False, n=4)
    ai = make_q(db, "DA.2.12", source="ai_generated", verify=False, n=5)
    report = exam_service.eligibility(db)
    pool = exam_service.eligible_questions(db, report.eligible_ids, include_ai=False, include_unreviewed_ai=False)
    assert [q.id for q in pool] == [ok.id]
    pool_ai = exam_service.eligible_questions(db, report.eligible_ids, include_ai=True, include_unreviewed_ai=True)
    assert {q.id for q in pool_ai} == {ok.id, ai.id}
    assert not_covered.id not in {q.id for q in pool_ai}
    assert mixed.id not in {q.id for q in pool_ai} and unverified.id not in {q.id for q in pool_ai}


def test_ai_questions_also_filtered_by_eligibility(db):
    ai = make_q(db, "DA.2.13", source="ai_generated", verify=True, n=6)
    pool = exam_service.eligible_questions(db, exam_service.eligibility(db).eligible_ids, include_ai=True,
                                           include_unreviewed_ai=True)
    assert ai.id not in {q.id for q in pool}


def test_insufficient_bank_discloses_shortfall_and_short_paper(db):
    master(db, "DA.2.12")
    master(db, "GA.2.05")
    for i in range(3):
        make_q(db, "DA.2.12", marks=1, n=10 + i)
    make_q(db, "DA.2.12", marks=2, qtype="NAT", n=20)
    make_q(db, "GA.2.05", marks=1, n=30)
    plan = exam_service.plan_paper(db, seed=7)
    assert not plan.is_full
    assert plan.shortfall == 65 - 5
    assert plan.max_marks == 3 + 2 + 1
    assert plan.duration_minutes == max(10, -(-180 * 6 // 100))
    with pytest.raises(ValidationError, match="short by"):
        exam_service.create_exam(db, plan, allow_short=False)
    exam = exam_service.create_exam(db, plan, allow_short=True, now=datetime(2026, 11, 10, 4, 0))
    assert exam.mode == "short" and len(exam.questions) == 5
    assert [q.section for q in exam.questions][0] == "GA"


def test_plan_is_deterministic_for_seed(db):
    master(db, "DA.2.12")
    master(db, "DA.2.11")
    for i in range(12):
        make_q(db, "DA.2.12" if i % 2 else "DA.2.11", n=100 + i)
    a = exam_service.plan_paper(db, seed=42).question_ids
    b = exam_service.plan_paper(db, seed=42).question_ids
    assert a == b


def test_full_lifecycle_scoring_and_analysis(db):
    master(db, "DA.2.12")
    master(db, "GA.2.05")
    q1 = make_q(db, "DA.2.12", marks=1, n=200)  # MCQ key A
    q2 = make_q(db, "DA.2.12", marks=2, n=201)  # MCQ key A
    q3 = make_q(db, "DA.2.12", marks=2, qtype="MSQ", n=202)  # key A,B
    q4 = make_q(db, "DA.2.12", marks=1, qtype="NAT", n=203)  # 1..1.5
    make_q(db, "GA.2.05", marks=1, n=204)
    start = datetime(2026, 11, 10, 4, 0)
    plan = exam_service.plan_paper(db, seed=1)
    exam = exam_service.create_exam(db, plan, allow_short=True, now=start)
    with pytest.raises(ConflictError, match="in progress"):
        exam_service.create_exam(db, plan, allow_short=True, now=start)
    pos = {q.question_id: q.position for q in exam.questions}
    t = start + timedelta(minutes=1)
    exam_service.save_answer(db, exam.id, pos[q1.id], response="B", now=t, elapsed_sec=30)  # -1/3
    exam_service.save_answer(db, exam.id, pos[q2.id], response="A", now=t, elapsed_sec=40)  # +2
    exam_service.save_answer(db, exam.id, pos[q3.id], response="A", marked_for_review=True, now=t)  # 0
    exam_service.save_answer(db, exam.id, pos[q4.id], response="1.2", now=t)  # +1
    with pytest.raises(ValidationError):
        exam_service.save_answer(db, exam.id, pos[q4.id], response="x", now=t)
    exam = exam_service.submit_exam(db, exam.id, now=t + timedelta(minutes=5))
    assert exam.score == pytest.approx(2 + 1 - 1 / 3, abs=0.01)
    assert exam.negative_marks == pytest.approx(0.33, abs=0.01)
    assert (exam.correct_count, exam.wrong_count, exam.unanswered_count) == (2, 2, 1)
    analysis = exam_service.analyse(db, exam.id)
    assert analysis.overall.questions == 5
    assert {b.label for b in analysis.by_section} == {"General Aptitude", "Data Science & AI"}
    assert analysis.overall.accuracy == 50.0
    with pytest.raises(ConflictError):
        exam_service.save_answer(db, exam.id, 1, response="A", now=t)


def test_timeout_auto_submits(db):
    master(db, "DA.2.12")
    make_q(db, "DA.2.12", n=300)
    start = datetime(2026, 11, 10, 4, 0)
    exam = exam_service.create_exam(db, exam_service.plan_paper(db, seed=3), allow_short=True, now=start)
    late = start + timedelta(minutes=exam.duration_minutes + 1)
    with pytest.raises(ConflictError, match="auto-submitted"):
        exam_service.save_answer(db, exam.id, 1, response="A", now=late)
    assert exam.status == "submitted" and exam.auto_submitted
    assert exam.time_spent_sec == exam.duration_minutes * 60
    assert exam_service.remaining_seconds(exam, late) == 0


def test_official_pyq_requires_provenance(db):
    with pytest.raises(ValidationError, match="year"):
        question_service.add_question(db, QuestionInput(
            topic_codes=["DA.2.12"], source_type="official_pyq", qtype="MCQ", marks=1,
            stem="A question without provenance details", options=["a", "b"], answer_key="A"))
