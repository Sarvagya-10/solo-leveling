"""Idempotent seeding: official syllabus, default habits/rules/badges, settings.

Running the seed repeatedly never duplicates rows and never touches user data
(progress, logs, notes). Topics removed from a newer syllabus version are
marked inactive rather than deleted, so history is preserved.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from shogun.config import DATA_DIR
from shogun.db.models import Achievement, AvoidanceRule, Habit, Subject, Topic, TopicProgress
from shogun.logging_setup import get_logger
from shogun.services import question_service, settings_service
from shogun.services.defaults import ACHIEVEMENTS, DEFAULT_AVOIDANCE_RULES, DEFAULT_HABITS
from shogun.syllabus import SyllabusSpec, load_official_syllabi

log = get_logger("seed")


@dataclass
class SeedReport:
    subjects_added: int = 0
    topics_added: int = 0
    topics_updated: int = 0
    topics_deactivated: int = 0
    progress_rows_added: int = 0


def seed_syllabus(session: Session, specs: list[SyllabusSpec]) -> SeedReport:
    report = SeedReport()
    subjects = {s.code: s for s in session.scalars(select(Subject))}
    topics = {t.code: t for t in session.scalars(select(Topic))}
    seen_codes: set[str] = set()
    order = 0
    for spec in specs:
        for section in spec.sections:
            order += 1
            subject = subjects.get(section.code)
            if subject is None:
                subject = Subject(code=section.code)
                session.add(subject)
                subjects[section.code] = subject
                report.subjects_added += 1
            subject.paper = spec.paper_code
            subject.section_number = section.number
            subject.name = section.name
            subject.official_text = section.official_text
            subject.sort_order = order
            subject.syllabus_version = spec.syllabus_version
            session.flush()
            for idx, tspec in enumerate(section.topics, start=1):
                seen_codes.add(tspec.code)
                topic = topics.get(tspec.code)
                if topic is None:
                    topic = Topic(code=tspec.code)
                    session.add(topic)
                    topics[tspec.code] = topic
                    report.topics_added += 1
                else:
                    report.topics_updated += 1
                topic.subject_id = subject.id
                topic.name = tspec.name
                topic.source_phrase = tspec.source_phrase
                topic.group_label = tspec.group
                topic.context = tspec.context
                topic.sort_order = idx
                topic.is_active = True
                topic.syllabus_version = spec.syllabus_version
    for code, topic in topics.items():
        if code not in seen_codes and topic.is_active:
            topic.is_active = False
            report.topics_deactivated += 1
    session.flush()

    have_progress = set(session.scalars(select(TopicProgress.topic_id)))
    for topic in topics.values():
        if topic.id not in have_progress:
            session.add(TopicProgress(topic_id=topic.id))
            report.progress_rows_added += 1
    session.flush()
    return report


def seed_habits(session: Session) -> int:
    existing = set(session.scalars(select(Habit.key)))
    added = 0
    for order, h in enumerate(DEFAULT_HABITS, start=1):
        if h.key not in existing:
            session.add(Habit(key=h.key, name=h.name, kind=h.kind, unit=h.unit, target_value=h.target,
                              sort_order=order, active=True))
            added += 1
    session.flush()
    return added


def seed_avoidance_rules(session: Session) -> int:
    existing = set(session.scalars(select(AvoidanceRule.key)))
    added = 0
    for order, r in enumerate(DEFAULT_AVOIDANCE_RULES, start=1):
        if r.key not in existing:
            session.add(AvoidanceRule(key=r.key, name=r.name, description=r.description, sort_order=order))
            added += 1
    session.flush()
    return added


def seed_achievements(session: Session) -> int:
    existing = {a.key: a for a in session.scalars(select(Achievement))}
    added = 0
    for order, a in enumerate(ACHIEVEMENTS, start=1):
        row = existing.get(a.key)
        if row is None:
            session.add(Achievement(key=a.key, name=a.name, description=a.description, icon=a.icon,
                                    sort_order=order))
            added += 1
        else:
            row.name, row.description, row.icon, row.sort_order = a.name, a.description, a.icon, order
    session.flush()
    return added


BUNDLED_PYQ_DIR = DATA_DIR / "pyq"


def seed_bundled_pyqs(session: Session, directory: Path | None = None) -> int:
    """Import the bundled official PYQ bank (``data/pyq/gate_*.json``).

    Each bundle file is imported once per content version (sha256 recorded in settings), so
    questions you delete are not resurrected on every start; duplicates are skipped by content hash.
    """
    directory = directory or BUNDLED_PYQ_DIR
    imported = dict(settings_service.get_setting(session, "bundled_pyq_imported") or {})
    added = 0
    for path in sorted(directory.glob("gate_*.json")):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if imported.get(path.name) == digest:
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        n, errors = question_service.import_questions(session, payload, trusted=True)
        added += n
        for err in errors:
            if "already exists" not in err:
                log.warning("Bundled PYQ %s: %s", path.name, err)
        imported[path.name] = digest
        log.info("Bundled PYQ bank %s: %d new question(s)", path.name, n)
    settings_service.set_setting(session, "bundled_pyq_imported", imported)
    return added


def seed_all(session: Session, today: date, specs: list[SyllabusSpec] | None = None,
             *, bundled_pyqs: bool = True) -> SeedReport:
    report = seed_syllabus(session, specs if specs is not None else load_official_syllabi())
    seed_habits(session)
    seed_avoidance_rules(session)
    seed_achievements(session)
    if bundled_pyqs:
        seed_bundled_pyqs(session)
    if settings_service.get_setting(session, "tracking_start_date") is None:
        settings_service.set_setting(session, "tracking_start_date", today.isoformat())
    log.info(
        "Seed complete: +%d subjects, +%d topics, %d deactivated",
        report.subjects_added, report.topics_added, report.topics_deactivated,
    )
    return report
