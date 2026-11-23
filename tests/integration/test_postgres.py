"""PostgreSQL persistence tests (the permanent-storage option for cloud deployments).

Runs against a real embedded PostgreSQL server (``pgserver``); skipped if it is unavailable.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import func, select

from shogun.db.base import Base
from shogun.db.models import AttentionSession, Question, RevisionEvent, StudyLog
from shogun.db.session import make_engine, run_migrations, session_scope
from shogun.services import (
    analytics_service,
    attention_service,
    backup_service,
    exam_service,
    gamification_service,
    habit_service,
    progress_service,
    reflection_service,
    revision_service,
    study_log_service,
    worklog_service,
)
from shogun.services.seed import seed_all
from shogun.services.study_log_service import StudyEntryInput
from shogun.services.worklog_service import WorkLogInput
from tests.conftest import topic_id

pgserver = pytest.importorskip("pgserver")
psycopg = pytest.importorskip("psycopg")

D = date(2026, 11, 22)
TZ = "Asia/Kolkata"


@pytest.fixture(scope="session")
def pg_server(tmp_path_factory: pytest.TempPathFactory):
    server = pgserver.get_server(str(tmp_path_factory.mktemp("pgdata")), cleanup_mode="stop")
    yield server
    server.cleanup()


@pytest.fixture
def pg_url(pg_server) -> Iterator[str]:
    base = pg_server.get_uri()  # postgresql://postgres:@127.0.0.1:PORT/postgres
    name = "shogun_" + uuid.uuid4().hex[:10]
    with psycopg.connect(base, autocommit=True) as conn:
        conn.execute(f"CREATE DATABASE {name}")
    yield "postgresql+psycopg://" + base.removeprefix("postgresql://").rsplit("/", 1)[0] + "/" + name
    with psycopg.connect(base, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


def test_migrations_match_models_on_postgres(pg_url):
    run_migrations(pg_url)
    engine = make_engine(pg_url)
    with engine.connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
    engine.dispose()


def test_every_write_persists_across_reconnects(pg_url):
    run_migrations(pg_url)
    engine = make_engine(pg_url)
    with session_scope(engine) as s:
        seed_all(s, D)
        tid = topic_id(s, "DA.1.02")
        study_log_service.log_study(s, D, [StudyEntryInput(tid, 60, 4, 3, "in_progress")], today=D)
        attention_service.add_session(s, D, 5, None, today=D)
        attention_service.add_session(s, D, 6, None, today=D)
        worklog_service.add_log(s, WorkLogInput("finance", D, 60, "APE backtest"), today=D)
        water = next(h for h in habit_service.list_habits(s) if h.key == "water")
        habit_service.upsert_entry(s, water.id, D, 3.0, None, today=D)
        reflection_service.upsert(s, D, "good", "late start", "start earlier", today=D)
        gamification_service.after_change(s, {D}, D, TZ)
    with session_scope(engine) as s:
        r1 = s.scalar(select(RevisionEvent).where(RevisionEvent.stage == 1))
        revision_service.complete_revision(s, r1.id, D + timedelta(days=1))
        exam = exam_service.create_exam(s, exam_service.plan_paper(s, seed=1, include_ai=False),
                                        allow_short=True, now=datetime(2026, 11, 22, 5, 0)) \
            if exam_service.plan_paper(s, seed=1).question_ids else None
        if exam is not None:
            exam_service.submit_exam(s, exam.id, now=datetime(2026, 11, 22, 5, 30), tz=TZ)
    engine.dispose()  # simulate an app restart

    engine = make_engine(pg_url)
    with session_scope(engine) as s:
        assert [x.minutes for x in attention_service.sessions_on(s, D)] == [5, 6]
        series = attention_service.daily_series(s)
        assert (series[0].longest, series[0].total) == (6, 11)
        row = next(r for r in progress_service.topic_rows(s) if r.code == "DA.1.02")
        assert (row.coverage_status, row.total_minutes, row.revision_stage) == ("in_progress", 60, 1)
        assert analytics_service.daily_metrics(s, D, D)[0].study_minutes == 60
        assert gamification_service.total_xp(s) > 0
        assert s.scalar(select(func.count(Question.id))) > 300  # bundled official PYQs seeded on Postgres
    engine.dispose()


def test_copy_local_sqlite_into_postgres_and_keep_writing(tmp_path: Path, pg_url):
    src_url = f"sqlite:///{(tmp_path / 'local.db').as_posix()}"
    run_migrations(src_url)
    src = make_engine(src_url)
    with session_scope(src) as s:
        seed_all(s, D, bundled_pyqs=False)
        study_log_service.log_study(s, D, [StudyEntryInput(topic_id(s, "DA.1.02"), 60)], today=D)
        attention_service.add_session(s, D, 5, None, today=D)
        payload = backup_service.export_data(s, include_private=True)
    src.dispose()

    run_migrations(pg_url)
    dst = make_engine(pg_url)
    with session_scope(dst) as t:
        seed_all(t, D, bundled_pyqs=False)
    with session_scope(dst) as t:
        backup_service.import_data(t, payload)
    with session_scope(dst) as t:
        # sequences were moved past imported ids, so new rows don't collide
        attention_service.add_session(t, D, 6, None, today=D)
        study_log_service.log_study(t, D, [StudyEntryInput(topic_id(t, "DA.2.12"), 30)], today=D)
    with session_scope(dst) as t:
        assert sorted(x.minutes for x in t.scalars(select(AttentionSession))) == [5, 6]
        assert t.scalar(select(func.count(StudyLog.id))) == 2
        snapshot = backup_service.safety_snapshot(dst, tmp_path / "backups", "pre-test")
        assert snapshot.suffix == ".json" and snapshot.stat().st_size > 1000
        assert not backup_service.supports_file_backups(dst)
    dst.dispose()


def test_app_saves_into_postgres_via_ui(pg_url, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from streamlit.testing.v1 import AppTest

    from shogun.ui import context

    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setenv("SHOGUN_VAR_DIR", str(tmp_path / "var"))
    monkeypatch.setenv("SHOGUN_SKIP_BUNDLED_PYQS", "1")
    context.reset_ctx()

    def page() -> None:
        from shogun.ui.pages import attention

        attention.render()

    at = AppTest.from_function(page, default_timeout=90)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    at.number_input[0].set_value(5)
    at.button(key="FormSubmitter:att_form-Log session").click().run()
    assert not at.exception and not at.error, [e.value for e in at.error]
    context.reset_ctx()
    engine = make_engine(pg_url)
    with session_scope(engine) as s:
        assert [x.minutes for x in s.scalars(select(AttentionSession))] == [5]
    engine.dispose()
    context.reset_ctx()
