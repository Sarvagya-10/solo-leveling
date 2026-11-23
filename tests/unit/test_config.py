from __future__ import annotations

from pathlib import Path

import pytest

from shogun.config import load_config, normalize_database_url


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, None),
        ("  ", None),
        ("postgres://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("postgresql://u:p@h/db?sslmode=require", "postgresql+psycopg://u:p@h/db?sslmode=require"),
        ('"postgresql+psycopg://u:p@h/db"', "postgresql+psycopg://u:p@h/db"),
    ],
)
def test_normalize_database_url(raw, expected):
    assert normalize_database_url(raw) == expected


def test_local_sqlite_is_permanent_locally(tmp_path: Path):
    cfg = load_config(override={"SHOGUN_DB_PATH": str(tmp_path / "x.db")})
    assert cfg.is_sqlite and not cfg.cloud_host and not cfg.storage_is_ephemeral


def test_sqlite_on_cloud_host_is_flagged_ephemeral(tmp_path: Path):
    cfg = load_config(override={"SHOGUN_DB_PATH": str(tmp_path / "x.db"), "SHOGUN_EPHEMERAL_HOST": "1"})
    assert cfg.storage_is_ephemeral and "TEMPORARY" in cfg.storage_label


def test_database_url_makes_cloud_storage_permanent_and_stays_secret():
    cfg = load_config(override={"SHOGUN_EPHEMERAL_HOST": "1", "DATABASE_URL": "postgres://u:hunter2@h/db"})
    assert not cfg.is_sqlite and not cfg.storage_is_ephemeral
    assert "hunter2" not in repr(cfg) and "hunter2" not in cfg.storage_label


def test_ephemeral_banner_shown_in_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from streamlit.testing.v1 import AppTest

    from shogun.config import PROJECT_ROOT
    from shogun.ui import context

    monkeypatch.setenv("SHOGUN_DB_PATH", str(tmp_path / "e.db"))
    monkeypatch.setenv("SHOGUN_VAR_DIR", str(tmp_path / "var"))
    monkeypatch.setenv("SHOGUN_EPHEMERAL_HOST", "1")
    monkeypatch.setenv("SHOGUN_SKIP_BUNDLED_PYQS", "1")
    context.reset_ctx()
    at = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=90)
    at.run()
    assert not at.exception
    assert any("NOT being saved permanently" in e.value for e in at.error)
    context.reset_ctx()
