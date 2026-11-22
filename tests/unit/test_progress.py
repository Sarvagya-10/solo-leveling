from __future__ import annotations

from datetime import date

import pytest

from shogun.services import progress_service, settings_service, study_log_service
from shogun.services.errors import ValidationError
from shogun.services.progress_service import derive_overall, derive_pyq_status, is_war_eligible
from shogun.services.study_log_service import StudyEntryInput
from tests.conftest import topic_id

D = date(2026, 11, 10)


@pytest.mark.parametrize(
    "attempted,correct,target,override,expected",
    [
        (0, 0, 10, None, "not_started"),
        (5, 3, 10, None, "in_progress"),
        (12, 10, 10, None, "mastered"),
        (12, 9, 10, None, "in_progress"),
        (0, 0, 10, True, "mastered"),
        (20, 15, 10, False, "in_progress"),
    ],
)
def test_pyq_status(attempted, correct, target, override, expected):
    assert derive_pyq_status(attempted, correct, target, override) == expected


def test_overall_status():
    assert derive_overall("mastered", "mastered") == "mastered"
    assert derive_overall("mastered", "in_progress") == "in_progress"
    assert derive_overall("not_started", "not_started") == "not_started"
    assert derive_overall("not_started", "not_started", "mastered") == "mastered"


def test_eligibility_rules():
    assert is_war_eligible("mastered", "not_started", "coverage_mastered")
    assert not is_war_eligible("in_progress", "mastered", "coverage_mastered")
    assert not is_war_eligible("mastered", "in_progress", "coverage_and_pyq")
    assert is_war_eligible("mastered", "mastered", "coverage_and_pyq")


def _row(db, code):
    return next(r for r in progress_service.topic_rows(db) if r.code == code)


def test_log_updates_coverage_pyq_and_never_downgrades(db):
    tid = topic_id(db, "DA.6.05")
    study_log_service.log_study(db, D, [StudyEntryInput(tid, 90, 6, 4, "mastered")], today=D)
    study_log_service.log_study(db, date(2026, 11, 11), [StudyEntryInput(tid, 30, 6, 6, "in_progress")],
                                today=date(2026, 11, 11))
    row = _row(db, "DA.6.05")
    assert row.coverage_status == "mastered"
    assert (row.pyq_attempted, row.pyq_correct, row.pyq_status) == (12, 10, "mastered")
    assert row.pyq_accuracy == pytest.approx(83.3)
    assert row.overall_status == "mastered"
    assert row.total_minutes == 120
    assert row.first_studied_on == D and row.last_studied_on == date(2026, 11, 11)


def test_configurable_pyq_target(db):
    tid = topic_id(db, "DA.6.05")
    study_log_service.log_study(db, D, [StudyEntryInput(tid, 30, 5, 5, "in_progress")], today=D)
    assert _row(db, "DA.6.05").pyq_status == "in_progress"
    settings_service.set_setting(db, "pyq_target_default", 5)
    assert _row(db, "DA.6.05").pyq_status == "mastered"
    progress_service.set_pyq_target(db, tid, 8, "harder topic", D)
    assert _row(db, "DA.6.05").pyq_status == "in_progress"


def test_overrides_require_reason_and_are_audited(db):
    tid = topic_id(db, "DA.7.01")
    with pytest.raises(ValidationError, match="reason"):
        progress_service.override_coverage(db, tid, "mastered", "", D)
    progress_service.override_coverage(db, tid, "mastered", "Covered in coaching", D)
    progress_service.override_pyq_mastery(db, tid, True, "Solved offline", D)
    trail = progress_service.audit_log(db, tid)
    fields = {(a.field, a.source, a.new_value) for a in trail}
    assert ("coverage_status", "override", "mastered") in fields
    assert ("pyq_mastery_override", "override", "True") in fields
    assert _row(db, "DA.7.01").overall_status == "mastered"


def test_eligibility_uses_setting(db):
    tid = topic_id(db, "DA.7.01")
    progress_service.override_coverage(db, tid, "mastered", "done", D)
    assert _row(db, "DA.7.01").war_eligible
    settings_service.set_setting(db, "war_eligibility_rule", "coverage_and_pyq")
    assert not _row(db, "DA.7.01").war_eligible


def test_coverage_timeline_and_subject_summary(db):
    a, b = topic_id(db, "DA.2.01"), topic_id(db, "DA.2.02")
    study_log_service.log_study(db, D, [StudyEntryInput(a, 60, status="mastered")], today=D)
    study_log_service.log_study(db, date(2026, 11, 12), [StudyEntryInput(b, 60, status="in_progress")],
                                today=date(2026, 11, 12))
    tl = progress_service.coverage_timeline(db, date(2026, 11, 9), date(2026, 11, 12))
    assert [(p["started"], p["mastered"]) for p in tl] == [(0, 0), (1, 1), (1, 1), (2, 1)]
    summ = {s.subject_code: s for s in progress_service.subject_summaries(progress_service.topic_rows(db, "DA"))}
    assert summ["DA.2"].coverage == {"not_started": 16, "in_progress": 1, "mastered": 1}
    assert summ["DA.2"].total == 18
