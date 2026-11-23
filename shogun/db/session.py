"""Engine/session management and schema bootstrap (Alembic)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from shogun.config import PROJECT_ROOT
from shogun.logging_setup import get_logger

log = get_logger("db")
_engines: dict[str, Engine] = {}


def _set_sqlite_pragmas(dbapi_connection, _record) -> None:  # type: ignore[no-untyped-def]
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def make_engine(db_url: str) -> Engine:
    if not db_url.startswith("sqlite"):
        # External server database (PostgreSQL): resilient to dropped idle connections on free tiers.
        return create_engine(db_url, future=True, pool_pre_ping=True, pool_recycle=300, pool_size=3,
                             max_overflow=2)
    if db_url.startswith("sqlite:///") and db_url != "sqlite:///:memory:":
        Path(db_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(db_url, future=True, connect_args={"check_same_thread": False})
    event.listen(engine, "connect", _set_sqlite_pragmas)
    return engine


def get_engine(db_url: str) -> Engine:
    """Process-wide cached engine per URL."""
    engine = _engines.get(db_url)
    if engine is None:
        engine = make_engine(db_url)
        _engines[db_url] = engine
    return engine


def dispose_engine(db_url: str) -> None:
    engine = _engines.pop(db_url, None)
    if engine is not None:
        engine.dispose()


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Transactional scope: commit on success, rollback on any error."""
    session = session_factory(engine)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def run_migrations(db_url: str) -> None:
    """Upgrade the database to the latest Alembic revision."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))  # configparser escaping
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")
    log.info("Database schema is at the latest migration")
