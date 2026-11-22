"""Question bank: verified PYQs, AI-generated practice questions, user questions.

Integrity rules
---------------
* ``official_pyq`` questions must carry exam year, question reference and a
  source (URL or note). They start ``unverified``; only an explicit user
  action marks them ``verified`` after checking the official paper/answer key.
* ``ai_generated`` questions are always labelled as such and start
  ``unverified`` until the user reviews them. They can never be relabelled as
  official PYQs.
* Duplicate content is rejected via a content hash.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, joinedload

from shogun.db.models import Question, QuestionAttempt, QuestionTopic, Subject, Topic
from shogun.services.errors import ConflictError, NotFoundError, ValidationError
from shogun.services.scoring import OPTION_KEYS, check_response, normalize_msq, parse_nat
from shogun.timeutil import utcnow

SOURCE_LABELS = {
    "official_pyq": "Official GATE PYQ",
    "ai_generated": "AI-generated practice",
    "user_practice": "User-authored practice",
}
VERIFICATION_LABELS = {"verified": "Verified", "unverified": "Unverified", "rejected": "Rejected"}


@dataclass
class QuestionInput:
    topic_codes: list[str]
    source_type: str
    qtype: str
    marks: int
    stem: str
    options: list[str] = field(default_factory=list)
    answer_key: str | None = None
    nat_low: float | None = None
    nat_high: float | None = None
    explanation: str | None = None
    exam_year: int | None = None
    exam_name: str | None = None
    question_ref: str | None = None
    source_url: str | None = None
    source_note: str | None = None
    ai_model: str | None = None


def content_hash(qtype: str, stem: str, options: list[str]) -> str:
    norm = " ".join(stem.lower().split()) + "|" + qtype + "|" + "|".join(
        " ".join(o.lower().split()) for o in options
    )
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def validate_input(data: QuestionInput) -> None:
    if data.source_type not in SOURCE_LABELS:
        raise ValidationError("Unknown question source type")
    if data.qtype not in ("MCQ", "MSQ", "NAT"):
        raise ValidationError("Question type must be MCQ, MSQ or NAT")
    if data.marks not in (1, 2):
        raise ValidationError("Marks must be 1 or 2")
    if len((data.stem or "").strip()) < 10:
        raise ValidationError("Question text is too short")
    if not data.topic_codes:
        raise ValidationError("Tag at least one syllabus topic")
    if data.qtype in ("MCQ", "MSQ"):
        opts = [o for o in data.options if o.strip()]
        if len(opts) < 2 or len(opts) > len(OPTION_KEYS):
            raise ValidationError("MCQ/MSQ need between 2 and 6 options")
        valid = set(OPTION_KEYS[: len(opts)])
        keys = normalize_msq(data.answer_key)
        if not keys or not keys <= valid:
            raise ValidationError(f"Answer key must use option letters {', '.join(sorted(valid))}")
        if data.qtype == "MCQ" and len(keys) != 1:
            raise ValidationError("An MCQ has exactly one correct option")
    else:
        if data.nat_low is None or data.nat_high is None:
            raise ValidationError("NAT questions need an answer range (low and high)")
        if data.nat_low > data.nat_high:
            raise ValidationError("NAT range low must be ≤ high")
    if data.source_type == "official_pyq":
        if not data.exam_year or not (2000 <= data.exam_year <= 2100):
            raise ValidationError("Official PYQs need the exam year")
        if not (data.question_ref or "").strip():
            raise ValidationError("Official PYQs need the question reference (e.g. Q.27)")
        if not ((data.source_url or "").strip() or (data.source_note or "").strip()):
            raise ValidationError("Official PYQs need a source URL or source note")


def _topics_by_code(session: Session, codes: list[str]) -> list[Topic]:
    topics = {t.code: t for t in session.scalars(select(Topic).where(Topic.code.in_(codes)))}
    missing = [c for c in codes if c not in topics]
    if missing:
        raise ValidationError(f"Unknown topic code(s): {', '.join(missing)}")
    return [topics[c] for c in codes]


def add_question(session: Session, data: QuestionInput) -> Question:
    validate_input(data)
    topics = _topics_by_code(session, list(dict.fromkeys(data.topic_codes)))
    papers = {t.subject.paper for t in topics}
    if len(papers) != 1:
        raise ValidationError("All tagged topics must belong to the same paper (DA or GA)")
    options = [o.strip() for o in data.options if o.strip()] if data.qtype != "NAT" else []
    digest = content_hash(data.qtype, data.stem, options)
    if session.scalar(select(Question.id).where(Question.content_hash == digest)):
        raise ConflictError("This question already exists in the bank")
    answer = None
    if data.qtype == "MCQ":
        answer = (data.answer_key or "").strip().upper()
    elif data.qtype == "MSQ":
        answer = ",".join(sorted(normalize_msq(data.answer_key)))
    q = Question(
        paper=papers.pop(), primary_topic_id=topics[0].id, source_type=data.source_type,
        verification_status="unverified", exam_year=data.exam_year,
        exam_name=(data.exam_name or "").strip() or None, question_ref=(data.question_ref or "").strip() or None,
        qtype=data.qtype, marks=data.marks, stem=data.stem.strip(),
        options_json=json.dumps(options) if options else None, answer_key=answer,
        nat_low=data.nat_low if data.qtype == "NAT" else None, nat_high=data.nat_high if data.qtype == "NAT" else None,
        explanation=(data.explanation or "").strip() or None, source_url=(data.source_url or "").strip() or None,
        source_note=(data.source_note or "").strip() or None, ai_model=data.ai_model, content_hash=digest,
    )
    for t in topics:
        q.topic_links.append(QuestionTopic(topic_id=t.id))
    session.add(q)
    session.flush()
    return q


def get_question(session: Session, question_id: int) -> Question:
    q = session.get(Question, question_id)
    if q is None:
        raise NotFoundError(f"Question #{question_id} not found")
    return q


def set_verification(session: Session, question_id: int, status: str) -> Question:
    if status not in VERIFICATION_LABELS:
        raise ValidationError("Invalid verification status")
    q = get_question(session, question_id)
    q.verification_status = status
    q.reviewed_at = utcnow() if status != "unverified" else None
    session.flush()
    return q


def update_question_text(session: Session, question_id: int, *, stem: str | None = None,
                         explanation: str | None = None) -> Question:
    q = get_question(session, question_id)
    if stem is not None:
        if len(stem.strip()) < 10:
            raise ValidationError("Question text is too short")
        q.stem = stem.strip()
        q.content_hash = content_hash(q.qtype, q.stem, options_of(q))
        if q.verification_status == "verified":
            q.verification_status = "unverified"  # edited content must be re-verified
    if explanation is not None:
        q.explanation = explanation.strip() or None
    session.flush()
    return q


def delete_question(session: Session, question_id: int) -> None:
    session.delete(get_question(session, question_id))
    session.flush()


def options_of(q: Question) -> list[str]:
    return json.loads(q.options_json) if q.options_json else []


def topic_ids_of(q: Question) -> set[int]:
    return {link.topic_id for link in q.topic_links} | {q.primary_topic_id}


def list_questions(
    session: Session, *, topic_id: int | None = None, paper: str | None = None,
    source_type: str | None = None, verification: str | None = None,
) -> list[Question]:
    stmt = select(Question).options(joinedload(Question.primary_topic).joinedload(Topic.subject),
                                    joinedload(Question.topic_links))
    if topic_id is not None:
        stmt = stmt.where(Question.id.in_(select(QuestionTopic.question_id).where(QuestionTopic.topic_id == topic_id)))
    if paper:
        stmt = stmt.where(Question.paper == paper)
    if source_type:
        stmt = stmt.where(Question.source_type == source_type)
    if verification:
        stmt = stmt.where(Question.verification_status == verification)
    return list(session.scalars(stmt.order_by(Question.exam_year.desc().nulls_last(), Question.id)).unique())


def verified_pyqs_for_topic(session: Session, topic_id: int, limit: int = 3) -> list[Question]:
    return list_questions(session, topic_id=topic_id, source_type="official_pyq", verification="verified")[:limit]


def record_practice_attempt(session: Session, question_id: int, response: str, on_date: date,
                            time_spent_sec: int | None = None) -> bool:
    q = get_question(session, question_id)
    verdict = check_response(q.qtype, q.answer_key, q.nat_low, q.nat_high, response)
    if verdict is None:
        raise ValidationError("Enter an answer before checking")
    session.add(QuestionAttempt(question_id=q.id, attempt_date=on_date, context="practice",
                                response=response, is_correct=verdict, time_spent_sec=time_spent_sec))
    session.flush()
    return verdict


def bank_counts(session: Session) -> dict[str, int]:
    rows = session.execute(
        select(Question.source_type, Question.verification_status, func.count(Question.id))
        .group_by(Question.source_type, Question.verification_status)
    )
    return {f"{s}:{v}": int(n) for s, v, n in rows}


def topic_question_counts(session: Session) -> dict[int, dict[str, int]]:
    rows = session.execute(
        select(QuestionTopic.topic_id,
               func.sum(case(((Question.source_type == "official_pyq") & (Question.verification_status == "verified"), 1), else_=0)),
               func.sum(case((Question.source_type == "ai_generated", 1), else_=0)),
               func.count(Question.id))
        .join(Question, Question.id == QuestionTopic.question_id)
        .group_by(QuestionTopic.topic_id)
    )
    return {tid: {"verified_pyq": int(v or 0), "ai": int(a or 0), "total": int(n or 0)} for tid, v, a, n in rows}


def import_questions(session: Session, payload: list[dict[str, Any]]) -> tuple[int, list[str]]:
    """Import questions from a JSON list (see data/pyq/README.md). Always imported unverified."""
    added, errors = 0, []
    for idx, raw in enumerate(payload, start=1):
        try:
            data = QuestionInput(
                topic_codes=list(raw.get("topic_codes") or []), source_type=raw.get("source_type", "official_pyq"),
                qtype=raw.get("qtype", ""), marks=int(raw.get("marks", 0)), stem=raw.get("stem", ""),
                options=list(raw.get("options") or []), answer_key=raw.get("answer_key"),
                nat_low=parse_nat(str(raw["nat_low"])) if raw.get("nat_low") is not None else None,
                nat_high=parse_nat(str(raw["nat_high"])) if raw.get("nat_high") is not None else None,
                explanation=raw.get("explanation"), exam_year=raw.get("exam_year"), exam_name=raw.get("exam_name"),
                question_ref=raw.get("question_ref"), source_url=raw.get("source_url"),
                source_note=raw.get("source_note"),
            )
            with session.begin_nested():
                add_question(session, data)
            added += 1
        except (ValidationError, ConflictError, ValueError, TypeError) as exc:
            errors.append(f"Item {idx}: {exc}")
    return added, errors


def topics_for_paper(session: Session, paper: str) -> list[Topic]:
    return list(session.scalars(
        select(Topic).join(Subject).where(Subject.paper == paper, Topic.is_active.is_(True))
        .order_by(Subject.sort_order, Topic.sort_order)
    ))
