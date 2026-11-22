"""Weekend Full War — GATE DA 2027 full-paper simulator.

Official structure (gate2027.iitm.ac.in/question_paper_pattern):
65 questions / 100 marks / 180 minutes; GA 10 questions = 15 marks and DA 55
questions = 85 marks. The only 1-/2-mark split satisfying both counts and
marks is GA 5×1 + 5×2 and DA 25×1 + 30×2.

Strict eligibility: a question is usable only if EVERY syllabus topic it is
tagged with is war-eligible for the user (see progress_service). The filter is
applied identically to official PYQs, user questions and AI-generated ones.
Official PYQs must be user-verified. AI questions are opt-in and always
labelled.

Paper assembly is deterministic for a given seed and question bank.
"""

from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from fractions import Fraction

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from shogun.db.models import MockAnswer, MockExam, MockExamQuestion, Question, QuestionAttempt
from shogun.services import progress_service, settings_service
from shogun.services.errors import ConflictError, NotFoundError, ValidationError
from shogun.services.question_service import options_of, topic_ids_of
from shogun.services.scoring import encode_msq, normalize_msq, parse_nat, round_marks, score_response
from shogun.timeutil import local_date_of, utcnow


@dataclass(frozen=True)
class Slot:
    section: str
    marks: int
    count: int


FULL_BLUEPRINT: tuple[Slot, ...] = (
    Slot("GA", 1, 5), Slot("GA", 2, 5), Slot("DA", 1, 25), Slot("DA", 2, 30),
)
FULL_DURATION_MIN = 180
FULL_QUESTIONS = sum(s.count for s in FULL_BLUEPRINT)  # 65
FULL_MARKS = sum(s.count * s.marks for s in FULL_BLUEPRINT)  # 100
assert FULL_QUESTIONS == 65 and FULL_MARKS == 100

_TIER = {("official_pyq", "verified"): 0, ("user_practice", "verified"): 1, ("user_practice", "unverified"): 1,
         ("ai_generated", "verified"): 2, ("ai_generated", "unverified"): 3}
TIER_LABEL = {0: "Verified official PYQ", 1: "User-authored", 2: "AI-generated (reviewed)",
              3: "AI-generated (unreviewed)"}


# --------------------------------------------------------------------------- eligibility
@dataclass
class EligibilityReport:
    rule: str
    rows: list[progress_service.TopicRow]

    @property
    def eligible_ids(self) -> set[int]:
        return {r.topic_id for r in self.rows if r.war_eligible}

    def eligible(self, paper: str) -> list[progress_service.TopicRow]:
        return [r for r in self.rows if r.paper == paper and r.war_eligible]

    def total(self, paper: str) -> int:
        return sum(1 for r in self.rows if r.paper == paper)


def eligibility(session: Session) -> EligibilityReport:
    rule = str(settings_service.get_setting(session, "war_eligibility_rule"))
    return EligibilityReport(rule=rule, rows=progress_service.topic_rows(session))


def question_tier(q: Question) -> int | None:
    return _TIER.get((q.source_type, q.verification_status))


def eligible_questions(
    session: Session, eligible_topic_ids: set[int], *, include_ai: bool, include_unreviewed_ai: bool
) -> list[Question]:
    """Questions whose every tagged topic is eligible and whose provenance is allowed."""
    out = []
    stmt = select(Question).options(joinedload(Question.topic_links)).order_by(Question.id)
    for q in session.scalars(stmt).unique():
        tier = question_tier(q)
        if tier is None:
            continue  # rejected, or unverified official PYQ
        if q.source_type == "ai_generated" and (not include_ai or (tier == 3 and not include_unreviewed_ai)):
            continue
        if not topic_ids_of(q) <= eligible_topic_ids:
            continue
        out.append(q)
    return out


# --------------------------------------------------------------------------- planning
@dataclass
class SlotPlan:
    slot: Slot
    available: int
    selected: list[int] = field(default_factory=list)

    @property
    def shortfall(self) -> int:
        return max(0, self.slot.count - len(self.selected))


@dataclass
class PaperPlan:
    seed: int
    slots: list[SlotPlan]
    include_ai: bool
    include_unreviewed_ai: bool

    @property
    def shortfall(self) -> int:
        return sum(s.shortfall for s in self.slots)

    @property
    def is_full(self) -> bool:
        return self.shortfall == 0

    @property
    def question_ids(self) -> list[int]:
        return [qid for s in self.slots for qid in s.selected]

    @property
    def max_marks(self) -> int:
        return sum(len(s.selected) * s.slot.marks for s in self.slots)

    @property
    def duration_minutes(self) -> int:
        if self.is_full:
            return FULL_DURATION_MIN
        return max(10, math.ceil(FULL_DURATION_MIN * self.max_marks / FULL_MARKS))


def _diverse_pick(candidates: list[Question], count: int, rng: random.Random) -> list[int]:
    """Pick by provenance tier, round-robin across topics inside a tier for coverage."""
    picked: list[int] = []
    by_tier: dict[int, list[Question]] = defaultdict(list)
    for q in sorted(candidates, key=lambda x: x.id):
        by_tier[question_tier(q) or 0].append(q)
    for tier in sorted(by_tier):
        by_topic: dict[int, list[Question]] = defaultdict(list)
        for q in by_tier[tier]:
            by_topic[q.primary_topic_id].append(q)
        topic_order = sorted(by_topic)
        rng.shuffle(topic_order)
        for tid in topic_order:
            rng.shuffle(by_topic[tid])
        while len(picked) < count and any(by_topic[t] for t in topic_order):
            for tid in topic_order:
                if by_topic[tid] and len(picked) < count:
                    picked.append(by_topic[tid].pop().id)
        if len(picked) >= count:
            break
    return picked


def plan_paper(
    session: Session, *, seed: int, include_ai: bool = False, include_unreviewed_ai: bool = False,
    eligible_topic_ids: set[int] | None = None,
) -> PaperPlan:
    if eligible_topic_ids is None:
        eligible_topic_ids = eligibility(session).eligible_ids
    pool = eligible_questions(session, eligible_topic_ids, include_ai=include_ai,
                              include_unreviewed_ai=include_unreviewed_ai)
    rng = random.Random(seed)
    slots = []
    for slot in FULL_BLUEPRINT:
        cands = [q for q in pool if q.paper == slot.section and q.marks == slot.marks]
        plan = SlotPlan(slot=slot, available=len(cands))
        plan.selected = _diverse_pick(cands, slot.count, rng)
        slots.append(plan)
    return PaperPlan(seed=seed, slots=slots, include_ai=include_ai, include_unreviewed_ai=include_unreviewed_ai)


# --------------------------------------------------------------------------- lifecycle
def active_exam(session: Session) -> MockExam | None:
    return session.scalars(select(MockExam).where(MockExam.status == "in_progress").order_by(MockExam.id.desc())).first()


def _snapshot(q: Question) -> str:
    return json.dumps({
        "stem": q.stem, "options": options_of(q), "answer_key": q.answer_key, "nat_low": q.nat_low,
        "nat_high": q.nat_high, "explanation": q.explanation, "source_type": q.source_type,
        "verification_status": q.verification_status, "exam_year": q.exam_year, "exam_name": q.exam_name,
        "question_ref": q.question_ref, "source_url": q.source_url, "ai_model": q.ai_model,
        "topic_code": q.primary_topic.code, "topic_name": q.primary_topic.name,
        "subject_name": q.primary_topic.subject.name,
    })


def create_exam(session: Session, plan: PaperPlan, *, allow_short: bool, now: datetime | None = None) -> MockExam:
    if active_exam(session) is not None:
        raise ConflictError("A paper is already in progress — resume and submit it first")
    if not plan.question_ids:
        raise ValidationError("No eligible questions are available for a paper")
    if not plan.is_full and not allow_short:
        raise ValidationError(f"Question bank is short by {plan.shortfall} questions; choose a shorter paper")
    report = eligibility(session)
    planned = [session.get(Question, qid) for qid in plan.question_ids]
    # Defence in depth: re-check eligibility at creation time, never trust a stale plan.
    for q in planned:
        if q is None or question_tier(q) is None or not topic_ids_of(q) <= report.eligible_ids:
            raise ConflictError("The question bank or topic eligibility changed — rebuild the paper")
    mode = "full" if plan.is_full else "short"
    n = (session.scalar(select(func.count(MockExam.id))) or 0) + 1
    exam = MockExam(
        title=f"{'Full' if plan.is_full else 'Short'} War #{n}", mode=mode, seed=plan.seed,
        duration_minutes=plan.duration_minutes, max_marks=float(plan.max_marks),
        includes_ai=any(q is not None and q.source_type == "ai_generated" for q in planned),
        eligibility_snapshot=json.dumps({
            "rule": report.rule,
            "eligible_topic_codes": sorted(r.code for r in report.rows if r.war_eligible),
        }),
        blueprint_json=json.dumps([
            {"section": s.slot.section, "marks": s.slot.marks, "required": s.slot.count, "selected": len(s.selected)}
            for s in plan.slots
        ]),
        started_at=now or utcnow(),
    )
    position = 0
    for slot_plan in plan.slots:
        for qid in slot_plan.selected:
            q = session.get(Question, qid)
            assert q is not None
            position += 1
            meq = MockExamQuestion(
                position=position, question_id=q.id, topic_id=q.primary_topic_id, section=slot_plan.slot.section,
                marks=q.marks, qtype=q.qtype, source_type=q.source_type, snapshot_json=_snapshot(q),
            )
            meq.answer = MockAnswer()
            exam.questions.append(meq)
    session.add(exam)
    session.flush()
    return exam


def get_exam(session: Session, exam_id: int) -> MockExam:
    exam = session.get(MockExam, exam_id)
    if exam is None:
        raise NotFoundError(f"Paper #{exam_id} not found")
    return exam


def deadline(exam: MockExam) -> datetime:
    return exam.started_at + timedelta(minutes=exam.duration_minutes)


def remaining_seconds(exam: MockExam, now: datetime | None = None) -> int:
    return max(0, int((deadline(exam) - (now or utcnow())).total_seconds()))


def normalize_response(qtype: str, response: str | None) -> str | None:
    if response is None or not str(response).strip():
        return None
    if qtype == "MCQ":
        value = str(response).strip().upper()
        if len(value) != 1 or not value.isalpha():
            raise ValidationError("Choose one option")
        return value
    if qtype == "MSQ":
        return encode_msq(normalize_msq(str(response))) or None
    number = parse_nat(str(response))
    if number is None:
        raise ValidationError("Enter a valid number")
    return str(response).strip()


def save_answer(
    session: Session, exam_id: int, position: int, *, response: str | None, marked_for_review: bool = False,
    elapsed_sec: int = 0, now: datetime | None = None, tz: str = "UTC",
) -> MockAnswer:
    """Autosave a response. Raises ConflictError (after auto-submitting) if time is over."""
    now = now or utcnow()
    exam = get_exam(session, exam_id)
    if exam.status != "in_progress":
        raise ConflictError("This paper has already been submitted")
    if now >= deadline(exam):
        submit_exam(session, exam_id, now=now, auto=True, tz=tz)
        raise ConflictError("Time is up — the paper was auto-submitted")
    meq = next((q for q in exam.questions if q.position == position), None)
    if meq is None:
        raise NotFoundError(f"Question {position} not found in this paper")
    answer = meq.answer or MockAnswer()
    meq.answer = answer
    answer.response = normalize_response(meq.qtype, response)
    answer.marked_for_review = bool(marked_for_review)
    answer.visited = True
    answer.time_spent_sec = (answer.time_spent_sec or 0) + max(0, min(int(elapsed_sec), exam.duration_minutes * 60))
    exam.current_position = position
    session.flush()
    return answer


def mark_visited(session: Session, exam_id: int, position: int, elapsed_sec: int = 0) -> None:
    exam = get_exam(session, exam_id)
    if exam.status != "in_progress":
        return
    for meq in exam.questions:
        if meq.position == position and meq.answer is not None:
            meq.answer.visited = True
            meq.answer.time_spent_sec += max(0, min(int(elapsed_sec), exam.duration_minutes * 60))
    exam.current_position = position
    session.flush()


def submit_exam(session: Session, exam_id: int, *, now: datetime | None = None, auto: bool = False,
                tz: str = "UTC") -> MockExam:
    now = now or utcnow()
    exam = get_exam(session, exam_id)
    if exam.status == "submitted":
        raise ConflictError("This paper has already been submitted")
    total = Fraction(0)
    negative = Fraction(0)
    correct = wrong = unanswered = 0
    attempt_date = local_date_of(now, tz)
    for meq in exam.questions:
        snap = json.loads(meq.snapshot_json)
        answer = meq.answer or MockAnswer()
        meq.answer = answer
        scored = score_response(meq.qtype, meq.marks, snap["answer_key"], snap["nat_low"], snap["nat_high"],
                                answer.response)
        answer.is_correct = scored.is_correct
        answer.marks_awarded = float(scored.marks)
        total += scored.marks
        if scored.is_correct is None:
            unanswered += 1
        elif scored.is_correct:
            correct += 1
        else:
            wrong += 1
            negative += -scored.marks if scored.marks < 0 else 0
        if scored.answered and meq.question_id is not None:
            session.add(QuestionAttempt(
                question_id=meq.question_id, attempt_date=attempt_date, context="mock", mock_exam_id=exam.id,
                response=answer.response, is_correct=bool(scored.is_correct), time_spent_sec=answer.time_spent_sec,
            ))
    exam.status = "submitted"
    exam.submitted_at = min(now, deadline(exam)) if auto else now
    exam.auto_submitted = auto
    exam.score = round_marks(total)
    exam.negative_marks = round_marks(negative)
    exam.correct_count, exam.wrong_count, exam.unanswered_count = correct, wrong, unanswered
    exam.time_spent_sec = int(min((exam.submitted_at - exam.started_at).total_seconds(), exam.duration_minutes * 60))
    session.flush()
    return exam


def expire_if_overdue(session: Session, tz: str, now: datetime | None = None) -> MockExam | None:
    """Auto-submit an in-progress paper whose time has run out (e.g. after a restart)."""
    exam = active_exam(session)
    if exam is not None and (now or utcnow()) >= deadline(exam):
        return submit_exam(session, exam.id, now=now, auto=True, tz=tz)
    return None


def history(session: Session) -> list[MockExam]:
    return list(session.scalars(select(MockExam).order_by(MockExam.id.desc())))


def submitted_on(exam: MockExam, tz: str) -> date | None:
    return local_date_of(exam.submitted_at, tz) if exam.submitted_at else None


# --------------------------------------------------------------------------- analysis
@dataclass
class Bucket:
    label: str
    questions: int = 0
    correct: int = 0
    wrong: int = 0
    unanswered: int = 0
    score: float = 0.0
    max_marks: float = 0.0
    negative: float = 0.0
    time_sec: int = 0

    @property
    def accuracy(self) -> float | None:
        attempted = self.correct + self.wrong
        return round(100.0 * self.correct / attempted, 1) if attempted else None


@dataclass
class ExamAnalysis:
    exam: MockExam
    overall: Bucket
    by_section: list[Bucket]
    by_topic: list[Bucket]
    by_qtype: list[Bucket]
    by_marks: list[Bucket]
    items: list[dict[str, object]]


def _add(bucket: Bucket, meq: MockExamQuestion) -> None:
    a = meq.answer
    bucket.questions += 1
    bucket.max_marks += meq.marks
    bucket.time_sec += a.time_spent_sec if a else 0
    if a is None or a.is_correct is None:
        bucket.unanswered += 1
        return
    bucket.score += a.marks_awarded or 0.0
    if a.is_correct:
        bucket.correct += 1
    else:
        bucket.wrong += 1
        bucket.negative += -(a.marks_awarded or 0.0)


def analyse(session: Session, exam_id: int) -> ExamAnalysis:
    exam = get_exam(session, exam_id)
    if exam.status != "submitted":
        raise ConflictError("Analysis is available after submission")
    overall = Bucket("Overall")
    groups: dict[str, dict[str, Bucket]] = {"section": {}, "topic": {}, "qtype": {}, "marks": {}}
    items = []
    for meq in exam.questions:
        snap = json.loads(meq.snapshot_json)
        _add(overall, meq)
        keys = {
            "section": "General Aptitude" if meq.section == "GA" else "Data Science & AI",
            "topic": f"{snap['topic_code']} · {snap['topic_name']}",
            "qtype": meq.qtype,
            "marks": f"{meq.marks}-mark",
        }
        for kind, label in keys.items():
            _add(groups[kind].setdefault(label, Bucket(label)), meq)
        a = meq.answer
        items.append({
            "position": meq.position, "section": meq.section, "qtype": meq.qtype, "marks": meq.marks,
            "source_type": meq.source_type, "topic": keys["topic"], "subject": snap.get("subject_name"),
            "stem": snap["stem"], "options": snap["options"], "answer_key": snap["answer_key"],
            "nat_low": snap["nat_low"], "nat_high": snap["nat_high"], "explanation": snap["explanation"],
            "exam_year": snap["exam_year"], "question_ref": snap["question_ref"],
            "verification_status": snap["verification_status"],
            "response": a.response if a else None, "is_correct": a.is_correct if a else None,
            "marks_awarded": a.marks_awarded if a else 0.0, "time_sec": a.time_spent_sec if a else 0,
            "marked_for_review": a.marked_for_review if a else False,
        })
    for b in [overall, *[b for g in groups.values() for b in g.values()]]:
        b.score, b.negative = round(b.score, 2), round(b.negative, 2)
    return ExamAnalysis(
        exam=exam, overall=overall, by_section=list(groups["section"].values()),
        by_topic=sorted(groups["topic"].values(), key=lambda b: (b.score - b.max_marks)),
        by_qtype=list(groups["qtype"].values()), by_marks=list(groups["marks"].values()), items=items,
    )


def save_review_notes(session: Session, exam_id: int, notes: str) -> None:
    exam = get_exam(session, exam_id)
    exam.review_notes = notes.strip() or None
    session.flush()
