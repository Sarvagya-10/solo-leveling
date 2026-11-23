"""Copy all Shogun data from one database to another (e.g. local SQLite -> hosted PostgreSQL).

Usage (PowerShell):
    $env:TARGET_DATABASE_URL = "postgresql://user:password@host/dbname?sslmode=require"
    python scripts/copy_data.py                       # from var/shogun.db to TARGET_DATABASE_URL
    python scripts/copy_data.py --source sqlite:///path/to/other.db

The target is migrated and seeded first. Refuses to overwrite a target that already contains
user entries unless --force is given. The database URL (and its password) is never printed.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from shogun.config import load_config, normalize_database_url  # noqa: E402
from shogun.db.models import AttentionSession, HabitEntry, Reflection, StudyLog, WorkLog  # noqa: E402
from shogun.db.session import make_engine, run_migrations, session_scope  # noqa: E402
from shogun.logging_setup import register_secret  # noqa: E402
from shogun.services import backup_service, gamification_service, settings_service  # noqa: E402
from shogun.services.seed import seed_all  # noqa: E402
from shogun.timeutil import local_today  # noqa: E402

USER_ENTRY_MODELS = (StudyLog, AttentionSession, WorkLog, HabitEntry, Reflection)


def entry_count(session) -> int:  # noqa: ANN001
    return sum(int(session.scalar(select(func.count()).select_from(m)) or 0) for m in USER_ENTRY_MODELS)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", help="Source SQLAlchemy URL (default: the local var/shogun.db)")
    parser.add_argument("--force", action="store_true", help="Overwrite a target that already has entries")
    args = parser.parse_args()

    cfg = load_config()
    source_url = normalize_database_url(args.source) or f"sqlite:///{cfg.db_path.as_posix()}"
    target_url = normalize_database_url(os.environ.get("TARGET_DATABASE_URL"))
    if not target_url:
        raise SystemExit("Set TARGET_DATABASE_URL to the destination database URL first.")
    if target_url == source_url:
        raise SystemExit("Source and target are the same database.")
    register_secret(target_url)

    source, target = make_engine(source_url), make_engine(target_url)
    with session_scope(source) as s:
        payload = backup_service.export_data(s, include_private=True)
        print(f"Source: {entry_count(s)} entries")
    run_migrations(target_url)
    with session_scope(target) as t:
        tz = str(settings_service.get_setting(t, "timezone"))
        seed_all(t, local_today(tz))
        existing = entry_count(t)
    if existing and not args.force:
        raise SystemExit(f"Target already has {existing} entries; refusing to overwrite (use --force).")
    with session_scope(target) as t:
        report = backup_service.import_data(t, payload)
    with session_scope(target) as t:
        tz = str(settings_service.get_setting(t, "timezone"))
        today = local_today(tz)
        seed_all(t, today)
        gamification_service.sync_all(t, tz, today)
        gamification_service.evaluate_achievements(t, today, tz)
        print(f"Copied {sum(report.rows.values())} rows; target now has {entry_count(t)} entries.")
    source.dispose()
    target.dispose()


if __name__ == "__main__":
    main()
