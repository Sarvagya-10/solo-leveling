"""Integrity of the bundled GATE PYQ bank built from official papers + official answer keys.

Bundles: GATE DA 2024-2026 (all areas) and GATE CS 2020-2026 restricted to GA, Probability &
Statistics, Linear Algebra, Calculus & Optimization and DBMS (areas shared with the DA syllabus).
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select

from shogun.config import DATA_DIR
from shogun.db.models import Question, Topic
from shogun.services import question_service, settings_service
from shogun.services.question_service import content_hash
from shogun.services.seed import seed_bundled_pyqs
from shogun.syllabus import load_official_syllabi

BANK_DIR = DATA_DIR / "pyq"
BUNDLE_IDS = sorted(p.stem.removeprefix("gate_") for p in BANK_DIR.glob("gate_*.json"))
DA_BUNDLES = ["da_2024", "da_2025", "da_2026"]
CS_SCOPE = ("GA.", "DA.1.", "DA.2.", "DA.3.", "DA.5.")


def _key(bid: str) -> dict:
    return json.loads((BANK_DIR / "keys" / f"gate_{bid}_key.json").read_text(encoding="utf-8"))


def _bundle(bid: str) -> list[dict]:
    return json.loads((BANK_DIR / f"gate_{bid}.json").read_text(encoding="utf-8"))


def test_expected_bundles_present():
    assert set(DA_BUNDLES) <= set(BUNDLE_IDS)
    assert any(b.startswith("cs_") for b in BUNDLE_IDS)
    for bid in BUNDLE_IDS:
        assert (BANK_DIR / "keys" / f"gate_{bid}_key.json").exists(), bid


@pytest.mark.parametrize("bid", BUNDLE_IDS)
def test_official_keys_follow_exam_pattern(bid):
    key = _key(bid)
    rows = key["rows"]
    assert [r["index"] for r in rows] == list(range(1, 66))
    ga = [r for r in rows if r["section"] == "GA"]
    sub = [r for r in rows if r["section"] != "GA"]
    assert (len(ga), sum(r["marks"] for r in ga)) == (10, 15)
    assert (len(sub), sum(r["marks"] for r in sub)) == (55, 85)
    assert key["source_url"].startswith("https://gate20")
    assert len(key["sha256"]) == 64 and len(key["paper_sha256"]) == 64


@pytest.mark.parametrize("bid", BUNDLE_IDS)
def test_every_bundled_question_matches_the_official_key(bid):
    key = _key(bid)
    rows = {r["index"]: r for r in key["rows"]}
    codes = {t.code for spec in load_official_syllabi() for s in spec.sections for t in s.topics}
    bundle = _bundle(bid)
    refs = [q["question_ref"] for q in bundle]
    assert len(refs) == len(set(refs)), "duplicate question references"
    scope = CS_SCOPE if bid.startswith("cs_") else ("GA.", "DA.")
    for q in bundle:
        row = rows[q["key_row"]]
        assert q["question_ref"] == row["ref"]
        assert row["key"] != "MTA" and not row["alternatives"], "MTA / alternative-answer keys must be excluded"
        assert q["source_type"] == "official_pyq" and q["verification_status"] == "verified"
        assert q["exam_name"] == key["exam"]
        assert (q["qtype"], q["marks"]) == (row["qtype"], row["marks"])
        if row["qtype"] == "NAT":
            assert (q["nat_low"], q["nat_high"]) == (row["nat_low"], row["nat_high"])
            assert q["options"] == [] and q["answer_key"] is None
        else:
            assert q["answer_key"] == row["key"].replace(";", ",")
            assert len(q["options"]) == 4
        section_prefix = "GA." if row["section"] == "GA" else "DA."
        assert q["topic_codes"] and all(c in codes for c in q["topic_codes"])
        assert all(c.startswith(section_prefix) and c.startswith(scope) for c in q["topic_codes"])
        assert len(q["stem"].strip()) >= 10
        assert q["source_url"] == key["paper_url"]
        assert "transcribed" in q["source_note"] and "not official" in q["source_note"]
    if bid in DA_BUNDLES:
        assert len(bundle) >= 50  # DA papers: everything except MTA / figure-only questions


def test_no_question_appears_in_two_bundles():
    seen: dict[str, str] = {}
    for bid in BUNDLE_IDS:
        for q in _bundle(bid):
            digest = content_hash(q["qtype"], q["stem"], q["options"])
            assert digest not in seen, f"{bid} {q['question_ref']} duplicates {seen[digest]}"
            seen[digest] = f"{bid} {q['question_ref']}"


def test_bundled_bank_seeds_verified_idempotently_and_respects_deletions(db):
    expected = sum(len(_bundle(b)) for b in BUNDLE_IDS)
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


def test_cards_prefer_da_paper_pyqs_then_newest(db):
    seed_bundled_pyqs(db)
    db.flush()
    counts = question_service.topic_question_counts(db)
    tid = max(counts, key=lambda t: counts[t]["verified_pyq"])
    pyqs = question_service.verified_pyqs_for_topic(db, tid)
    assert 1 <= len(pyqs) <= 3
    primary = [q for q in pyqs if q.primary_topic_id == tid]
    assert pyqs[: len(primary)] == primary
    assert all(q.exam_year and q.question_ref and q.exam_name for q in pyqs)
    assert db.get(Topic, tid) is not None


def test_cs_questions_never_land_on_excluded_sections(db):
    seed_bundled_pyqs(db)
    db.flush()
    cs = db.scalars(select(Question).where(Question.exam_name.like("% CS%"))).all()
    assert cs, "CS bundle questions imported"
    for q in cs:
        assert q.primary_topic.code.startswith(CS_SCOPE), q.primary_topic.code


def test_user_import_is_never_trusted(db):
    bundle = _bundle("da_2025")[:2]
    added, errors = question_service.import_questions(db, bundle)
    assert added == 2 and not errors
    statuses = set(db.scalars(select(Question.verification_status)))
    assert statuses == {"unverified"}
