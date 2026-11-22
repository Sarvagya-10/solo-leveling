"""Integrity of the bundled GATE DA PYQ bank built from official papers + official answer keys."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from shogun.config import DATA_DIR
from shogun.db.models import Question, Topic
from shogun.services import question_service, settings_service
from shogun.services.seed import seed_bundled_pyqs
from shogun.syllabus import load_official_syllabi

BANK_DIR = DATA_DIR / "pyq"
BUNDLES = sorted(BANK_DIR.glob("gate_da_*.json"))
YEARS = [2024, 2025, 2026]


def _key(year: int) -> dict:
    return json.loads((BANK_DIR / "keys" / f"gate_da_{year}_key.json").read_text(encoding="utf-8"))


def _bundle(year: int) -> list[dict]:
    return json.loads((BANK_DIR / f"gate_da_{year}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("year", YEARS)
def test_official_keys_follow_exam_pattern(year):
    key = _key(year)
    rows = key["rows"]
    assert [r["qno"] for r in rows] == list(range(1, 66))
    ga = [r for r in rows if r["section"] == "GA"]
    da = [r for r in rows if r["section"] == "DA"]
    assert (len(ga), sum(r["marks"] for r in ga)) == (10, 15)
    assert (len(da), sum(r["marks"] for r in da)) == (55, 85)
    assert key["source_url"].startswith("https://gate20")
    assert len(key["sha256"]) == 64 and len(key["paper_sha256"]) == 64


@pytest.mark.parametrize("year", YEARS)
def test_every_bundled_question_matches_the_official_key(year):
    rows = {r["qno"]: r for r in _key(year)["rows"]}
    codes = {t.code for spec in load_official_syllabi() for s in spec.sections for t in s.topics}
    bundle = _bundle(year)
    refs = [q["question_ref"] for q in bundle]
    assert len(refs) == len(set(refs)), "duplicate question numbers"
    for q in bundle:
        row = rows[int(q["question_ref"].removeprefix("Q."))]
        assert row["key"] != "MTA", "marks-to-all questions must be excluded"
        assert q["source_type"] == "official_pyq" and q["exam_year"] == year
        assert (q["qtype"], q["marks"]) == (row["qtype"], row["marks"])
        if row["qtype"] == "NAT":
            assert (q["nat_low"], q["nat_high"]) == (row["nat_low"], row["nat_high"])
            assert q["options"] == [] and q["answer_key"] is None
        else:
            assert q["answer_key"] == row["key"].replace(";", ",")
            assert len(q["options"]) == 4
        section = "GA" if row["section"] == "GA" else "DA"
        assert q["topic_codes"] and all(c in codes and c.startswith(section + ".") for c in q["topic_codes"])
        assert len(q["stem"].strip()) >= 10
        assert q["source_url"] == _key(year)["paper_url"]
        assert "transcribed" in q["source_note"] and "not official" in q["source_note"]
    # the bank must cover the large majority of each paper (figure-only questions may be excluded)
    assert len(bundle) >= 50


def test_bundled_bank_seeds_verified_idempotently_and_respects_deletions(db):
    expected = sum(len(_bundle(y)) for y in YEARS)
    added = seed_bundled_pyqs(db)
    db.flush()
    assert added == expected
    verified = db.scalar(select(func.count(Question.id)).where(
        Question.source_type == "official_pyq", Question.verification_status == "verified"))
    assert verified == expected
    assert seed_bundled_pyqs(db) == 0
    victim = db.scalars(select(Question)).first()
    question_service.delete_question(db, victim.id)
    assert seed_bundled_pyqs(db) == 0  # same bundle version: deleted question stays deleted
    assert settings_service.get_setting(db, "bundled_pyq_imported")


def test_cards_show_at_most_three_verified_pyqs_newest_first(db):
    seed_bundled_pyqs(db)
    db.flush()
    counts = question_service.topic_question_counts(db)
    tid = max(counts, key=lambda t: counts[t]["verified_pyq"])
    pyqs = question_service.verified_pyqs_for_topic(db, tid)
    assert 1 <= len(pyqs) <= 3
    primary = [q for q in pyqs if q.primary_topic_id == tid]
    assert pyqs[: len(primary)] == primary
    assert all(q.exam_year in YEARS and q.question_ref for q in pyqs)
    assert db.get(Topic, tid) is not None


def test_user_import_is_never_trusted(db):
    bundle = _bundle(2025)[:2]
    added, errors = question_service.import_questions(db, bundle)
    assert added == 2 and not errors
    statuses = set(db.scalars(select(Question.verification_status)))
    assert statuses == {"unverified"}


def test_bundle_files_present():
    assert [p.name for p in BUNDLES] == [f"gate_da_{y}.json" for y in YEARS]
    assert all(isinstance(json.loads(Path(p).read_text(encoding="utf-8")), list) for p in BUNDLES)
