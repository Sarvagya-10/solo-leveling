"""Backups, restore, JSON/CSV export, JSON import and full reset.

* Backups use SQLite's online backup API (consistent even while the app runs).
* Restoring or resetting ALWAYS takes an automatic safety backup first.
* JSON export contains every user-data table; topic and achievement foreign
  keys are exported with their stable codes so an import remaps them safely
  even if internal ids differ.
* Not-to-do data is private: excluded from CSV export unless explicitly included.
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, MetaData, Table, delete, insert, select, text
from sqlalchemy.orm import Session

from shogun import __version__
from shogun.db.models import PRIVATE_TABLES, USER_DATA_TABLES, Achievement, Topic
from shogun.logging_setup import get_logger
from shogun.services.errors import ValidationError
from shogun.timeutil import utcnow

log = get_logger("backup")
EXPORT_FORMAT = "shogun-export"
EXPORT_VERSION = 1
RESET_CONFIRMATION = "RESET"

# Columns holding topic ids / achievement ids, remapped through stable codes on import.
TOPIC_FK_COLUMNS: dict[str, tuple[str, ...]] = {
    "topic_progress": ("topic_id",),
    "progress_audit": ("topic_id",),
    "study_logs": ("topic_id",),
    "revision_cycles": ("topic_id",),
    "revision_events": ("topic_id",),
    "questions": ("primary_topic_id",),
    "question_topics": ("topic_id",),
    "revision_cards": ("topic_id",),
    "mock_exam_questions": ("topic_id",),
}


def supports_file_backups(engine: Engine) -> bool:
    return engine.dialect.name == "sqlite" and engine.url.database not in (None, "", ":memory:")


def _sqlite_path(engine: Engine) -> Path:
    if engine.dialect.name != "sqlite":
        raise ValidationError("File backups apply to the local SQLite database only. With a hosted PostgreSQL "
                              "database use the JSON export (and your provider's own backups).")
    db = engine.url.database
    if not db or db == ":memory:":
        raise ValidationError("Backups require a file-based SQLite database")
    return Path(db)


def backup_database(engine: Engine, backups_dir: Path, label: str = "manual") -> Path:
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = utcnow().strftime("%Y%m%d-%H%M%S-%f")
    safe_label = "".join(c for c in label if c.isalnum() or c in "-_")[:30] or "backup"
    dest = backups_dir / f"shogun-{stamp}-{safe_label}.db"
    src = sqlite3.connect(_sqlite_path(engine))
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    log.info("Backup written: %s", dest.name)
    return dest


def safety_snapshot(engine: Engine, backups_dir: Path, label: str) -> Path:
    """Snapshot before a destructive operation: SQLite file backup, or a full JSON export for PostgreSQL."""
    if supports_file_backups(engine):
        return backup_database(engine, backups_dir, label)
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = utcnow().strftime("%Y%m%d-%H%M%S-%f")
    dest = backups_dir / f"shogun-{stamp}-{label}.json"
    with Session(engine) as session:
        dest.write_bytes(export_json_bytes(session, include_private=True))
    return dest


def list_backups(backups_dir: Path) -> list[Path]:
    if not backups_dir.exists():
        return []
    return sorted(backups_dir.glob("shogun-*.db"), reverse=True)


def _validate_backup_file(path: Path) -> None:
    if not path.exists():
        raise ValidationError("Backup file not found")
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            con.close()
    except sqlite3.DatabaseError as exc:
        raise ValidationError("Not a valid SQLite database") from exc
    required = {"topics", "topic_progress", "study_logs", "settings"}
    if not required <= tables:
        raise ValidationError("This file is not a Shogun database backup")


def restore_backup(engine: Engine, backup_file: Path, backups_dir: Path) -> Path:
    """Replace the live database with ``backup_file``. Returns the safety backup path."""
    _validate_backup_file(backup_file)
    safety = backup_database(engine, backups_dir, "pre-restore")
    engine.dispose()
    src = sqlite3.connect(backup_file)
    try:
        dst = sqlite3.connect(_sqlite_path(engine))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    engine.dispose()
    log.info("Database restored from %s", backup_file.name)
    return safety


# --------------------------------------------------------------------------- JSON export / import
def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def _reflect(session: Session) -> MetaData:
    md = MetaData()
    md.reflect(bind=session.get_bind())
    return md


def export_data(session: Session, *, include_private: bool = True) -> dict[str, Any]:
    md = _reflect(session)
    topic_codes = dict(session.execute(select(Topic.id, Topic.code)).all())
    ach_keys = dict(session.execute(select(Achievement.id, Achievement.key)).all())
    tables: dict[str, list[dict[str, Any]]] = {}
    for name in USER_DATA_TABLES:
        if not include_private and name in PRIVATE_TABLES:
            continue
        table = md.tables[name]
        rows = []
        for row in session.execute(select(table)).mappings():
            item = {k: _jsonable(v) for k, v in row.items()}
            for col in TOPIC_FK_COLUMNS.get(name, ()):
                if item.get(col) is not None:
                    item[col] = topic_codes.get(item[col])
            if name == "user_achievements":
                item["achievement_id"] = ach_keys.get(item["achievement_id"])
            rows.append(item)
        tables[name] = rows
    return {
        "format": EXPORT_FORMAT, "format_version": EXPORT_VERSION, "app_version": __version__,
        "exported_at": utcnow().isoformat(), "includes_private": include_private,
        "topic_ref": "code", "tables": tables,
    }


def export_json_bytes(session: Session, *, include_private: bool = True) -> bytes:
    return json.dumps(export_data(session, include_private=include_private), indent=2, ensure_ascii=False).encode()


def export_csv_zip(session: Session, *, include_private: bool = False) -> bytes:
    data = export_data(session, include_private=include_private)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, rows in data["tables"].items():
            out = io.StringIO()
            if rows:
                writer = csv.DictWriter(out, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
            zf.writestr(f"{name}.csv", out.getvalue())
        zf.writestr("README.txt", "Shogun data export. Topic references use official syllabus codes.\n")
    return buf.getvalue()


def _coerce(table: Table, row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col in table.columns:
        if col.name not in row:
            continue
        value = row[col.name]
        if value is not None and isinstance(value, str):
            pytype = None
            try:
                pytype = col.type.python_type
            except NotImplementedError:  # pragma: no cover
                pass
            if pytype is datetime:
                value = datetime.fromisoformat(value)
            elif pytype is date:
                value = date.fromisoformat(value)
        out[col.name] = value
    return out


@dataclass
class ImportReport:
    rows: dict[str, int]
    skipped: list[str]


def import_data(session: Session, payload: dict[str, Any]) -> ImportReport:
    """Replace all user data with ``payload`` (from :func:`export_data`). Caller must back up first."""
    if payload.get("format") != EXPORT_FORMAT or not isinstance(payload.get("tables"), dict):
        raise ValidationError("Not a Shogun export file")
    if int(payload.get("format_version", 0)) > EXPORT_VERSION:
        raise ValidationError("Export was produced by a newer app version")
    md = _reflect(session)
    topic_ids = {code: tid for tid, code in session.execute(select(Topic.id, Topic.code)).all()}
    ach_ids = {key: aid for aid, key in session.execute(select(Achievement.id, Achievement.key)).all()}
    tables = payload["tables"]
    skipped: list[str] = []

    # Private (not-to-do) tables are only replaced when the export actually contains them.
    keep = set() if payload.get("includes_private", True) else set(PRIVATE_TABLES)
    for name in reversed(USER_DATA_TABLES):
        if name not in keep:
            session.execute(delete(md.tables[name]))
    counts: dict[str, int] = {}
    for name in USER_DATA_TABLES:
        rows = tables.get(name)
        if rows is None or name in keep:
            continue
        table = md.tables[name]
        clean_rows = []
        for raw in rows:
            row = dict(raw)
            ok = True
            for col in TOPIC_FK_COLUMNS.get(name, ()):
                if row.get(col) is not None:
                    mapped = topic_ids.get(row[col])
                    if mapped is None:
                        ok = False
                        skipped.append(f"{name}: unknown topic {row[col]}")
                    row[col] = mapped
            if name == "user_achievements":
                row["achievement_id"] = ach_ids.get(str(row.get("achievement_id")))
                ok = ok and row["achievement_id"] is not None
            if ok:
                clean_rows.append(_coerce(table, row))
        if clean_rows:
            session.execute(insert(table), clean_rows)
        counts[name] = len(clean_rows)
    session.flush()
    _reset_sequences(session, md)
    return ImportReport(rows=counts, skipped=skipped)


def _reset_sequences(session: Session, md: MetaData) -> None:
    """After inserting explicit ids, move PostgreSQL id sequences past the highest id (no-op on SQLite)."""
    if session.get_bind().dialect.name != "postgresql":
        return
    for name in USER_DATA_TABLES:
        table = md.tables[name]
        if "id" not in table.columns:
            continue
        session.execute(text(
            f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), "
            f"COALESCE((SELECT MAX(id) FROM {name}), 0) + 1, false)"
        ))


def reset_all_data(session: Session, confirmation: str) -> None:
    """Delete ALL user data. Caller must take a backup first and then re-seed."""
    if confirmation != RESET_CONFIRMATION:
        raise ValidationError(f"Type {RESET_CONFIRMATION} to confirm")
    md = _reflect(session)
    for name in reversed(USER_DATA_TABLES):
        session.execute(delete(md.tables[name]))
    session.execute(delete(md.tables["ai_cache"]))
    session.flush()
    log.warning("All user data was reset")
