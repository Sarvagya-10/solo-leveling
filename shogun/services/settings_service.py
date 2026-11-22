"""Typed, validated key/value settings persisted in the ``settings`` table."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from shogun.config import DEFAULT_TIMEZONE, validate_timezone
from shogun.db.models import Setting
from shogun.services.errors import ValidationError

DEFAULTS: dict[str, Any] = {
    "timezone": DEFAULT_TIMEZONE,
    "tracking_start_date": None,  # ISO date; set on first bootstrap
    "pyq_target_default": 10,
    "daily_study_target_minutes": 240,
    "daily_pyq_target": 10,
    "finance_target_minutes": 60,
    "research_target_minutes": 60,
    "attention_baseline_minutes": 5,
    "attention_target_minutes": 200,
    "war_eligibility_rule": "coverage_mastered",
    "war_include_unreviewed_ai": False,
    "groq_model": None,
    "privacy_hide_not_todo": True,
    "last_seen_level": 1,
    "bundled_pyq_imported": {},  # {bundle filename: sha256} — each bundle version is imported once
}

_INT_RANGES: dict[str, tuple[int, int]] = {
    "pyq_target_default": (1, 500),
    "daily_study_target_minutes": (0, 1440),
    "daily_pyq_target": (0, 500),
    "finance_target_minutes": (1, 1440),
    "research_target_minutes": (1, 1440),
    "attention_baseline_minutes": (1, 1440),
    "attention_target_minutes": (1, 1440),
    "last_seen_level": (1, 100000),
}
WAR_RULES = {
    "coverage_mastered": "Knowledge coverage marked mastered",
    "coverage_and_pyq": "Coverage mastered AND PYQ mastery target met",
}


def _validate(key: str, value: Any) -> Any:
    if key not in DEFAULTS:
        raise ValidationError(f"Unknown setting: {key}")
    if key in _INT_RANGES:
        lo, hi = _INT_RANGES[key]
        try:
            ivalue = int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{key} must be a whole number") from exc
        if not lo <= ivalue <= hi:
            raise ValidationError(f"{key} must be between {lo} and {hi}")
        return ivalue
    if key == "timezone":
        try:
            return validate_timezone(str(value))
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
    if key == "tracking_start_date":
        if value is None:
            return None
        return date.fromisoformat(str(value)).isoformat()
    if key == "war_eligibility_rule":
        if value not in WAR_RULES:
            raise ValidationError(f"war_eligibility_rule must be one of {sorted(WAR_RULES)}")
        return value
    if key in {"war_include_unreviewed_ai", "privacy_hide_not_todo"}:
        return bool(value)
    if key == "groq_model":
        return (str(value).strip() or None) if value is not None else None
    return value


def get_setting(session: Session, key: str) -> Any:
    if key not in DEFAULTS:
        raise ValidationError(f"Unknown setting: {key}")
    row = session.get(Setting, key)
    if row is None:
        return DEFAULTS[key]
    return json.loads(row.value_json)


def set_setting(session: Session, key: str, value: Any) -> Any:
    clean = _validate(key, value)
    row = session.get(Setting, key)
    payload = json.dumps(clean)
    if row is None:
        session.add(Setting(key=key, value_json=payload))
    else:
        row.value_json = payload
    session.flush()
    return clean


def get_all(session: Session) -> dict[str, Any]:
    values = dict(DEFAULTS)
    for row in session.scalars(select(Setting)):
        if row.key in values:
            values[row.key] = json.loads(row.value_json)
    return values


def tracking_start(session: Session, fallback: date) -> date:
    raw = get_setting(session, "tracking_start_date")
    return date.fromisoformat(raw) if raw else fallback
