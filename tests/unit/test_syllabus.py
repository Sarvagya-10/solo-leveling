from __future__ import annotations

import hashlib
import json

import pytest
from sqlalchemy import func, select

from shogun.config import PROJECT_ROOT
from shogun.db.models import Subject, Topic, TopicProgress
from shogun.services.seed import seed_all
from shogun.syllabus import (
    DA_FILE,
    GA_FILE,
    SyllabusSpec,
    load_official_syllabi,
    load_syllabus,
    uncovered_words,
)
from tests.conftest import SEED_DAY

EXPECTED_DA_SECTIONS = [
    "Probability and Statistics",
    "Linear Algebra",
    "Calculus and Optimization",
    "Programming, Data Structures and Algorithms",
    "Database Management and Warehousing",
    "Machine Learning",
    "Artificial Intelligence",
]
EXPECTED_GA_SECTIONS = ["Verbal Aptitude", "Quantitative Aptitude", "Analytical Aptitude", "Spatial Aptitude"]


def test_da_has_all_seven_official_sections():
    spec = load_syllabus(DA_FILE)
    assert [s.name for s in spec.sections] == EXPECTED_DA_SECTIONS
    assert spec.topic_count == 119


def test_ga_has_exactly_the_official_sections():
    spec = load_syllabus(GA_FILE)
    assert [s.name for s in spec.sections] == EXPECTED_GA_SECTIONS
    assert spec.topic_count == 36


@pytest.mark.parametrize("path", [DA_FILE, GA_FILE])
def test_every_phrase_is_verbatim_and_every_word_is_covered(path):
    spec = load_syllabus(path)
    for section in spec.sections:
        assert uncovered_words(section) == set()
        for t in section.topics:
            assert t.source_phrase in section.official_text
            if t.group:
                assert t.group in section.official_text


@pytest.mark.parametrize("path", [DA_FILE, GA_FILE])
def test_source_pdf_checksum_matches(path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    pdf = PROJECT_ROOT / raw["source"]["local_file"]
    assert hashlib.sha256(pdf.read_bytes()).hexdigest() == raw["source"]["sha256"]


def test_invented_topic_is_rejected():
    raw = json.loads(DA_FILE.read_text(encoding="utf-8"))
    raw["sections"][0]["topics"].append(
        {"code": "DA.1.99", "name": "Markov chains", "source_phrase": "Markov chains"}
    )
    with pytest.raises(ValueError, match="not verbatim"):
        SyllabusSpec.model_validate(raw)


def test_omitted_topic_is_rejected():
    raw = json.loads(DA_FILE.read_text(encoding="utf-8"))
    raw["sections"][1]["topics"] = [t for t in raw["sections"][1]["topics"] if t["source_phrase"] != "nullity"]
    with pytest.raises(ValueError, match="nullity"):
        SyllabusSpec.model_validate(raw)


def test_seed_is_idempotent(db):
    n_topics = db.scalar(select(func.count(Topic.id)))
    seed_all(db, today=SEED_DAY)
    seed_all(db, today=SEED_DAY)
    assert db.scalar(select(func.count(Topic.id))) == n_topics == 155
    assert db.scalar(select(func.count(Subject.id))) == 11
    assert db.scalar(select(func.count(TopicProgress.id))) == 155


def test_reseed_preserves_progress_and_deactivates_removed_topics(db):
    prog = db.scalar(select(TopicProgress).join(Topic).where(Topic.code == "DA.2.15"))
    prog.notes = "keep me"
    db.flush()
    specs = load_official_syllabi()
    specs[0].sections[1].topics = [t for t in specs[0].sections[1].topics if t.code != "DA.2.15"]
    report = seed_all(db, today=SEED_DAY, specs=specs)
    assert report.topics_deactivated == 1
    topic = db.scalar(select(Topic).where(Topic.code == "DA.2.15"))
    assert topic.is_active is False
    assert topic.progress.notes == "keep me"
