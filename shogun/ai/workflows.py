"""High-level AI workflows used by the UI.

Every workflow:
* fails with a typed :class:`AIError` (shown as a friendly message) when keys
  are missing or the provider is unavailable — deterministic features never
  depend on it;
* caches responses in the ``ai_cache`` table (cost-aware; ``force=True``
  bypasses the cache for explicit regeneration);
* never sends private not-to-do data to a provider.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from shogun.ai.errors import AINotConfiguredError, AIResponseError
from shogun.ai.groq_client import GroqClient, ModelInfo, choose_model
from shogun.ai.schemas import PracticeSet, PYQCandidateList, ReflectionAdvice, RevisionCardDraft
from shogun.ai.search_client import SearchResult, SerpApiClient, fetch_page_text
from shogun.config import AppConfig
from shogun.db.models import AICache, Question, Reflection, Subject, Topic
from shogun.logging_setup import get_logger
from shogun.services import question_service, settings_service
from shogun.services.errors import ConflictError, NotFoundError, ValidationError
from shogun.timeutil import utcnow

log = get_logger("ai.workflows")
T = TypeVar("T", bound=BaseModel)
_MODELS_TTL = 6 * 3600
_models_cache: dict[str, tuple[float, list[ModelInfo]]] = {}


# --------------------------------------------------------------------------- plumbing
def groq_client(cfg: AppConfig, **kw: Any) -> GroqClient:
    return GroqClient(cfg.groq_api_key, **kw)


def serp_client(cfg: AppConfig, **kw: Any) -> SerpApiClient:
    return SerpApiClient(cfg.serpapi_api_key, **kw)


def available_models(client: GroqClient, *, refresh: bool = False) -> list[ModelInfo]:
    key = "groq"
    hit = _models_cache.get(key)
    if hit and not refresh and time.time() - hit[0] < _MODELS_TTL:
        return hit[1]
    models = client.list_models()
    _models_cache[key] = (time.time(), models)
    return models


def resolve_model(session: Session, cfg: AppConfig, client: GroqClient) -> str:
    configured = settings_service.get_setting(session, "groq_model") or cfg.groq_model
    model, why = choose_model(available_models(client), configured)
    if model is None:
        raise AINotConfiguredError(why)
    return model


def _cache_key(kind: str, model: str | None, payload: Any) -> str:
    raw = json.dumps({"k": kind, "m": model, "p": payload}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _cache_get(session: Session, key: str) -> str | None:
    row = session.scalar(select(AICache).where(AICache.cache_key == key))
    if row is None:
        return None
    if row.expires_at is not None and row.expires_at < utcnow():
        session.delete(row)
        return None
    return row.response_json


def _cache_put(session: Session, key: str, kind: str, model: str | None, value: str,
               ttl: timedelta | None = None) -> None:
    row = session.scalar(select(AICache).where(AICache.cache_key == key))
    expires = utcnow() + ttl if ttl else None
    if row is None:
        session.add(AICache(cache_key=key, kind=kind, model=model, response_json=value, expires_at=expires))
    else:
        row.response_json, row.expires_at, row.created_at = value, expires, utcnow()
    session.flush()


def cached_chat_json(session: Session, client: GroqClient, model: str, messages: list[dict[str, str]],
                     schema: type[T], *, force: bool = False, max_tokens: int = 3000,
                     temperature: float = 0.2) -> tuple[T, bool]:
    key = _cache_key("chat:" + schema.__name__, model, messages)
    if not force:
        hit = _cache_get(session, key)
        if hit is not None:
            try:
                return schema.model_validate_json(hit), True
            except ValueError:
                pass
    obj, _raw = client.chat_json(model, messages, schema, max_tokens=max_tokens, temperature=temperature)
    _cache_put(session, key, "chat", model, obj.model_dump_json())
    return obj, False


def _topic(session: Session, topic_id: int) -> Topic:
    topic = session.get(Topic, topic_id)
    if topic is None:
        raise NotFoundError("Topic not found")
    return topic


def _topic_context(topic: Topic) -> str:
    parts = [f"Topic code: {topic.code}", f"Topic: {topic.name}", f"Section: {topic.subject.name}",
             f"Paper: GATE 2027 {'Data Science and AI (DA)' if topic.subject.paper == 'DA' else 'General Aptitude (GA)'}"]
    if topic.group_label:
        parts.append(f"Official group: {topic.group_label}")
    parts.append(f"Official section syllabus text: {topic.subject.official_text}")
    return "\n".join(parts)


# --------------------------------------------------------------------------- revision cards
CARD_SYSTEM = (
    "You are an expert GATE Data Science & AI tutor writing concise, exam-focused revision cards. "
    "Be technically precise. Use plain text or simple LaTeX-free notation. "
    "Output ONLY a JSON object with keys: basic_idea (string), essential_formulae (list of "
    "{name, expression, note}), question_types (list of {type, recognition}), common_traps (list of "
    "strings), extra_observations (list of strings), connected_topic_codes (list of topic codes chosen "
    "ONLY from the provided list), practice_questions (exactly 3 ORIGINAL practice questions, each "
    "{qtype: MCQ|MSQ|NAT, marks: 1|2, stem, options (4 strings for MCQ/MSQ, [] for NAT), answer_key "
    "(e.g. 'B' or 'A,C'; null for NAT), nat_low, nat_high (numbers for NAT, else null), explanation}). "
    "The practice questions must be your own original questions. NEVER present them as real GATE "
    "questions and never claim a year or paper for them."
)


def generate_card_draft(session: Session, cfg: AppConfig, topic_id: int, *, force: bool = False,
                        client: GroqClient | None = None) -> tuple[RevisionCardDraft, str, bool]:
    topic = _topic(session, topic_id)
    client = client or groq_client(cfg)
    model = resolve_model(session, cfg, client)
    catalogue = "\n".join(
        f"{code}: {name}" for code, name in session.execute(
            select(Topic.code, Topic.name).join(Subject).where(Subject.paper == "DA", Topic.is_active.is_(True))
            .order_by(Subject.sort_order, Topic.sort_order))
    )
    messages = [
        {"role": "system", "content": CARD_SYSTEM},
        {"role": "user", "content": f"{_topic_context(topic)}\n\nAllowed connected DA topic codes:\n{catalogue}\n\n"
                                    "Write the revision card JSON now."},
    ]
    draft, cached = cached_chat_json(session, client, model, messages, RevisionCardDraft, force=force,
                                     max_tokens=3500)
    return draft, model, cached


# --------------------------------------------------------------------------- practice questions
PRACTICE_SYSTEM = (
    "You write ORIGINAL GATE-style practice questions. Output ONLY JSON: {\"questions\": [ {qtype: "
    "MCQ|MSQ|NAT, marks: 1|2, stem, options (4 strings for MCQ/MSQ, [] for NAT), answer_key ('B' or "
    "'A,C'; null for NAT), nat_low, nat_high (numbers for NAT else null), explanation} ]}. Questions must "
    "be self-contained, unambiguous, solvable without figures, and have a single verified answer. "
    "Never claim they are real GATE questions."
)


def generate_practice_questions(session: Session, cfg: AppConfig, topic_id: int, *, count: int = 3,
                                marks: int | None = None, qtype: str | None = None, force: bool = False,
                                client: GroqClient | None = None) -> tuple[list[Question], int]:
    """Generate and store AI practice questions (unverified). Returns (added, skipped_duplicates)."""
    if not 1 <= count <= 10:
        raise ValidationError("Generate between 1 and 10 questions at a time")
    topic = _topic(session, topic_id)
    client = client or groq_client(cfg)
    model = resolve_model(session, cfg, client)
    constraints = []
    if marks:
        constraints.append(f"every question carries {marks} mark(s)")
    if qtype:
        constraints.append(f"every question is of type {qtype}")
    messages = [
        {"role": "system", "content": PRACTICE_SYSTEM},
        {"role": "user", "content": f"{_topic_context(topic)}\n\nWrite {count} practice questions strictly on "
                                    f"this topic{' where ' + ' and '.join(constraints) if constraints else ''}."},
    ]
    result, _cached = cached_chat_json(session, client, model, messages, PracticeSet, force=force,
                                       max_tokens=3500, temperature=0.4)
    added: list[Question] = []
    skipped = 0
    for pq in result.questions[:count]:
        if (marks and pq.marks != marks) or (qtype and pq.qtype != qtype):
            skipped += 1
            continue
        try:
            with session.begin_nested():
                added.append(question_service.add_question(session, question_service.QuestionInput(
                    topic_codes=[topic.code], source_type="ai_generated", qtype=pq.qtype, marks=pq.marks,
                    stem=pq.stem, options=pq.options, answer_key=pq.answer_key, nat_low=pq.nat_low,
                    nat_high=pq.nat_high, explanation=pq.explanation, ai_model=model,
                )))
        except (ValidationError, ConflictError):
            skipped += 1
    return added, skipped


# --------------------------------------------------------------------------- PYQ sourcing
def pyq_search_query(topic: Topic, year: int | None = None) -> str:
    paper = "GATE DA" if topic.subject.paper == "DA" else "GATE General Aptitude"
    return f"{paper} {year or ''} previous year question {topic.name} solution".replace("  ", " ")


def search_pyq_sources(session: Session, cfg: AppConfig, topic_id: int, *, year: int | None = None,
                       query: str | None = None, force: bool = False,
                       client: SerpApiClient | None = None) -> list[SearchResult]:
    topic = _topic(session, topic_id)
    q = (query or pyq_search_query(topic, year)).strip()
    key = _cache_key("search", "duckduckgo", q)
    if not force:
        hit = _cache_get(session, key)
        if hit is not None:
            return [SearchResult(**r) for r in json.loads(hit)]
    client = client or serp_client(cfg)
    results = client.search(q)
    _cache_put(session, key, "search", "duckduckgo", json.dumps([r.__dict__ for r in results]),
               ttl=timedelta(days=7))
    return results


_NORM = re.compile(r"[^a-z0-9]+")


def _shingles(text: str, n: int = 4) -> set[tuple[str, ...]]:
    words = _NORM.sub(" ", text.lower()).split()
    if len(words) < n:
        return {tuple(words)} if words else set()
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def appears_in(source_text: str, excerpt: str, threshold: float = 0.7) -> bool:
    """Hallucination guard: does ``excerpt`` substantially occur in ``source_text``?"""
    ex = _shingles(excerpt)
    if not ex:
        return False
    src = _shingles(source_text)
    return len(ex & src) / len(ex) >= threshold


EXTRACT_SYSTEM = (
    "You extract GATE previous-year questions from the supplied web page text. Only extract questions "
    "that appear VERBATIM in the text and that the text explicitly attributes to a specific GATE exam "
    "year. Copy the question stem and options exactly. Include the answer only if the page states it. "
    "Never invent, paraphrase or complete questions. Output ONLY JSON: {\"candidates\": [ {exam_year, "
    "question_ref, qtype: MCQ|MSQ|NAT, marks: 1|2, stem, options, answer_key, nat_low, nat_high, "
    "explanation, evidence} ]} where evidence is a verbatim excerpt of the page containing the question. "
    "Return {\"candidates\": []} if none qualify."
)


@dataclass
class ExtractionResult:
    added: list[Question]
    rejected_not_in_source: int
    rejected_invalid: int
    duplicates: int


def extract_pyq_candidates(session: Session, cfg: AppConfig, topic_id: int, url: str, *,
                           client: GroqClient | None = None, page_text: str | None = None) -> ExtractionResult:
    """Extract candidate PYQs from a page. They are stored UNVERIFIED and must be checked by the user."""
    topic = _topic(session, topic_id)
    text = page_text if page_text is not None else fetch_page_text(url)
    if len(text) < 200:
        raise AIResponseError("The page has too little readable text to extract questions from")
    text = text[:24000]
    client = client or groq_client(cfg)
    model = resolve_model(session, cfg, client)
    messages = [
        {"role": "system", "content": EXTRACT_SYSTEM},
        {"role": "user", "content": f"Target syllabus topic: {topic.name} ({topic.subject.name}).\n"
                                    f"Source URL: {url}\n\nPAGE TEXT:\n{text}"},
    ]
    result, _ = cached_chat_json(session, client, model, messages, PYQCandidateList, max_tokens=4000,
                                 temperature=0.0)
    added: list[Question] = []
    not_in_source = invalid = dupes = 0
    for cand in result.candidates:
        if not (appears_in(text, cand.stem) and appears_in(text, cand.evidence, 0.6)):
            not_in_source += 1
            continue
        try:
            with session.begin_nested():
                added.append(question_service.add_question(session, question_service.QuestionInput(
                    topic_codes=[topic.code], source_type="official_pyq", qtype=cand.qtype, marks=cand.marks,
                    stem=cand.stem, options=cand.options, answer_key=cand.answer_key, nat_low=cand.nat_low,
                    nat_high=cand.nat_high, explanation=cand.explanation, exam_year=cand.exam_year,
                    exam_name=f"GATE {cand.exam_year}", question_ref=cand.question_ref, source_url=url,
                    source_note=f"Extracted by {model}; evidence: {cand.evidence[:400]}", ai_model=model,
                )))
        except ConflictError:
            dupes += 1
        except ValidationError:
            invalid += 1
    return ExtractionResult(added, not_in_source, invalid, dupes)


# --------------------------------------------------------------------------- reflection
ADAPT_SYSTEM = (
    "You are a supportive, practical performance coach for a student preparing for GATE. Read the "
    "reflection and respond ONLY with JSON {observations: [up to 3 short strings], next_smallest_step: "
    "string, encouragement: string}. Keep the next step tiny, concrete and doable tomorrow."
)


def reflection_advice(session: Session, cfg: AppConfig, reflection_id: int, *, force: bool = False,
                      client: GroqClient | None = None) -> str:
    row = session.get(Reflection, reflection_id)
    if row is None:
        raise NotFoundError("Reflection not found")
    client = client or groq_client(cfg)
    model = resolve_model(session, cfg, client)
    messages = [
        {"role": "system", "content": ADAPT_SYSTEM},
        {"role": "user", "content": f"What went well: {row.went_well}\nWhat did not go well: {row.did_not_go_well}\n"
                                    f"My smallest step: {row.smallest_step}"},
    ]
    advice, _ = cached_chat_json(session, client, model, messages, ReflectionAdvice, force=force,
                                 max_tokens=800, temperature=0.5)
    lines = [f"- {o}" for o in advice.observations]
    lines.append(f"\n**Next smallest step:** {advice.next_smallest_step}")
    lines.append(f"\n_{advice.encouragement}_")
    return "\n".join(lines)


# --------------------------------------------------------------------------- diagnostics
def test_groq(session: Session, cfg: AppConfig, client: GroqClient | None = None) -> dict[str, Any]:
    client = client or groq_client(cfg)
    models = available_models(client, refresh=True)
    configured = settings_service.get_setting(session, "groq_model") or cfg.groq_model
    model, why = choose_model(models, configured)
    return {"models": [m.id for m in models], "selected": model, "explanation": why}


def test_serpapi(cfg: AppConfig, client: SerpApiClient | None = None) -> dict[str, Any]:
    client = client or serp_client(cfg)
    return client.account()
