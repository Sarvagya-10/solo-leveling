from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

# Make sure no real credentials leak into tests, regardless of the developer's shell.
for _var in ("GROQ_API_KEY", "SERPAPI_API_KEY", "GROQ_MODEL"):
    os.environ.pop(_var, None)
os.environ["SHOGUN_DISABLE_DOTENV"] = "1"

from shogun.db.base import Base  # noqa: E402
from shogun.db.models import Topic  # noqa: E402
from shogun.db.session import make_engine, session_factory  # noqa: E402
from shogun.services.seed import seed_all  # noqa: E402

SEED_DAY = date(2026, 11, 1)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    eng = make_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    session = session_factory(engine)()
    seed_all(session, today=SEED_DAY, bundled_pyqs=False)
    session.commit()
    yield session
    session.close()


def topic_id(session: Session, code: str) -> int:
    tid = session.scalar(select(Topic.id).where(Topic.code == code))
    assert tid is not None, code
    return tid
