"""Revision cards: one per topic, editable, bookmarkable, versioned.

AI-generated cards are stored as ``origin='ai'`` / ``review_status='draft'``
and are labelled as unreviewed until the user explicitly marks them reviewed.
Every regeneration or edit snapshots the previous content.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from shogun.ai.schemas import RevisionCardDraft
from shogun.db.models import RevisionCard, RevisionCardVersion, Subject, Topic
from shogun.services import question_service
from shogun.services.errors import ConflictError, NotFoundError, ValidationError
from shogun.timeutil import utcnow

CARD_FIELDS = ("basic_idea", "formulae", "question_types", "traps", "observations")
FIELD_LABELS = {
    "basic_idea": "Basic idea",
    "formulae": "Essential formulae",
    "question_types": "Question types & recognition patterns",
    "traps": "Common traps",
    "observations": "Extra observations",
}


def get_card(session: Session, topic_id: int) -> RevisionCard | None:
    return session.scalar(select(RevisionCard).where(RevisionCard.topic_id == topic_id))


def _snapshot(session: Session, card: RevisionCard, reason: str) -> None:
    snap = {f: getattr(card, f) for f in CARD_FIELDS}
    snap.update(connected_topic_codes=card.connected_topic_codes, origin=card.origin,
                review_status=card.review_status, ai_model=card.ai_model)
    if any(snap[f] for f in CARD_FIELDS):
        session.add(RevisionCardVersion(card_id=card.id, snapshot_json=json.dumps(snap), reason=reason))


def connected_codes(card: RevisionCard | None) -> list[str]:
    if card is None or not card.connected_topic_codes:
        return []
    try:
        return [str(c) for c in json.loads(card.connected_topic_codes)]
    except json.JSONDecodeError:
        return []


def _valid_codes(session: Session, codes: list[str], own_code: str) -> list[str]:
    existing = set(session.scalars(select(Topic.code).where(Topic.code.in_(codes))))
    return [c for c in dict.fromkeys(codes) if c in existing and c != own_code]


def save_card(session: Session, topic_id: int, fields: dict[str, str | None],
              connected: list[str] | None = None) -> RevisionCard:
    topic = session.get(Topic, topic_id)
    if topic is None:
        raise NotFoundError("Topic not found")
    if not any((fields.get(f) or "").strip() for f in CARD_FIELDS):
        raise ValidationError("A card needs at least one non-empty section")
    for f in CARD_FIELDS:
        if len(fields.get(f) or "") > 20000:
            raise ValidationError(f"{FIELD_LABELS[f]} is too long")
    card = get_card(session, topic_id)
    if card is None:
        card = RevisionCard(topic_id=topic_id, origin="manual", review_status="reviewed", reviewed_at=utcnow())
        session.add(card)
        session.flush()
    else:
        _snapshot(session, card, "edit")
    for f in CARD_FIELDS:
        setattr(card, f, (fields.get(f) or "").strip() or None)
    if connected is not None:
        card.connected_topic_codes = json.dumps(_valid_codes(session, connected, topic.code))
    session.flush()
    return card


def draft_to_fields(draft: RevisionCardDraft) -> dict[str, str]:
    def bullets(items: list[str]) -> str:
        return "\n".join(f"- {i.strip()}" for i in items if i.strip())

    formulae = "\n".join(
        f"- **{f.name.strip()}**: `{f.expression.strip()}`" + (f" — {f.note.strip()}" if f.note else "")
        for f in draft.essential_formulae
    )
    qtypes = "\n".join(f"- **{q.type.strip()}** — {q.recognition.strip()}" for q in draft.question_types)
    return {
        "basic_idea": draft.basic_idea.strip(), "formulae": formulae, "question_types": qtypes,
        "traps": bullets(draft.common_traps), "observations": bullets(draft.extra_observations),
    }


@dataclass
class DraftApplyResult:
    card: RevisionCard
    practice_added: int
    practice_skipped: int


def apply_ai_draft(session: Session, topic_id: int, draft: RevisionCardDraft, model: str) -> DraftApplyResult:
    topic = session.get(Topic, topic_id)
    if topic is None:
        raise NotFoundError("Topic not found")
    card = get_card(session, topic_id)
    if card is None:
        card = RevisionCard(topic_id=topic_id)
        session.add(card)
        session.flush()
    else:
        _snapshot(session, card, "regenerate")
    for f, v in draft_to_fields(draft).items():
        setattr(card, f, v or None)
    card.connected_topic_codes = json.dumps(_valid_codes(session, draft.connected_topic_codes, topic.code))
    card.origin, card.review_status, card.ai_model = "ai", "draft", model
    card.generated_at, card.reviewed_at = utcnow(), None
    added = skipped = 0
    for pq in draft.practice_questions:
        try:
            with session.begin_nested():
                question_service.add_question(session, question_service.QuestionInput(
                    topic_codes=[topic.code], source_type="ai_generated", qtype=pq.qtype, marks=pq.marks,
                    stem=pq.stem, options=pq.options, answer_key=pq.answer_key, nat_low=pq.nat_low,
                    nat_high=pq.nat_high, explanation=pq.explanation, ai_model=model,
                ))
            added += 1
        except (ValidationError, ConflictError):
            skipped += 1
    session.flush()
    return DraftApplyResult(card, added, skipped)


def set_reviewed(session: Session, card_id: int, reviewed: bool) -> RevisionCard:
    card = session.get(RevisionCard, card_id)
    if card is None:
        raise NotFoundError("Card not found")
    card.review_status = "reviewed" if reviewed else "draft"
    card.reviewed_at = utcnow() if reviewed else None
    session.flush()
    return card


def toggle_bookmark(session: Session, card_id: int) -> bool:
    card = session.get(RevisionCard, card_id)
    if card is None:
        raise NotFoundError("Card not found")
    card.bookmarked = not card.bookmarked
    session.flush()
    return card.bookmarked


def restore_version(session: Session, version_id: int) -> RevisionCard:
    version = session.get(RevisionCardVersion, version_id)
    if version is None:
        raise NotFoundError("Version not found")
    card = session.get(RevisionCard, version.card_id)
    assert card is not None
    snap = json.loads(version.snapshot_json)
    _snapshot(session, card, "edit")
    for f in CARD_FIELDS:
        setattr(card, f, snap.get(f))
    card.connected_topic_codes = snap.get("connected_topic_codes")
    card.origin = snap.get("origin", card.origin)
    card.review_status = snap.get("review_status", "draft")
    card.ai_model = snap.get("ai_model")
    session.flush()
    return card


def versions(session: Session, card_id: int) -> list[RevisionCardVersion]:
    return list(session.scalars(select(RevisionCardVersion).where(RevisionCardVersion.card_id == card_id)
                                .order_by(RevisionCardVersion.id.desc())))


def list_cards(session: Session, *, paper: str | None = None, bookmarked_only: bool = False) -> list[RevisionCard]:
    stmt = (select(RevisionCard).options(joinedload(RevisionCard.topic).joinedload(Topic.subject))
            .join(Topic).join(Subject).order_by(Subject.sort_order, Topic.sort_order))
    if paper:
        stmt = stmt.where(Subject.paper == paper)
    if bookmarked_only:
        stmt = stmt.where(RevisionCard.bookmarked.is_(True))
    return list(session.scalars(stmt).unique())
