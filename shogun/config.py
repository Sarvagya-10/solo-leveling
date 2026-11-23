"""Application configuration.

Credentials are read ONLY from the process environment or a local, git-ignored
``.env`` file. They are wrapped in :class:`Secret` so they never appear in
``repr()``, logs, tracebacks or the UI.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
SYLLABUS_DIR = DATA_DIR / "syllabus"
DEFAULT_TIMEZONE = "Asia/Kolkata"


class Secret:
    """Opaque holder for a credential. ``str()``/``repr()`` never reveal it."""

    __slots__ = ("_value",)

    def __init__(self, value: str | None) -> None:
        cleaned = (value or "").strip()
        self._value = cleaned or None

    def get(self) -> str | None:
        return self._value

    @property
    def is_set(self) -> bool:
        return bool(self._value) and not _looks_like_placeholder(self._value or "")

    def __repr__(self) -> str:
        return "Secret(set)" if self.is_set else "Secret(unset)"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:  # pragma: no cover - trivial
        return isinstance(other, Secret) and other._value == self._value

    def __hash__(self) -> int:  # pragma: no cover - trivial
        return hash(self._value)


def _looks_like_placeholder(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith("your-") or lowered in {"changeme", "placeholder", "xxx"}


@dataclass(frozen=True)
class AppConfig:
    db_path: Path
    timezone: str
    log_level: str
    var_dir: Path
    groq_api_key: Secret = field(repr=True)
    serpapi_api_key: Secret = field(repr=True)
    groq_model: str | None = None
    database_url: Secret = field(default_factory=lambda: Secret(None))
    cloud_host: bool = False

    @property
    def db_url(self) -> str:
        """SQLAlchemy URL: the external database if configured, else the local SQLite file."""
        external = self.database_url.get() if self.database_url.is_set else None
        return external or f"sqlite:///{self.db_path.as_posix()}"

    @property
    def is_sqlite(self) -> bool:
        return self.db_url.startswith("sqlite")

    @property
    def storage_is_ephemeral(self) -> bool:
        """True when data would be lost on restart (local SQLite file on a cloud host such as Streamlit Cloud)."""
        return self.cloud_host and self.is_sqlite

    @property
    def storage_label(self) -> str:
        if not self.is_sqlite:
            return "External PostgreSQL database (permanent)"
        return f"Local SQLite file {self.db_path}" + (" — TEMPORARY on this cloud host" if self.cloud_host else "")

    @property
    def backups_dir(self) -> Path:
        return self.var_dir / "backups"

    @property
    def exports_dir(self) -> Path:
        return self.var_dir / "exports"

    @property
    def logs_dir(self) -> Path:
        return self.var_dir / "logs"


def normalize_database_url(url: str | None) -> str | None:
    """Accept Neon/Supabase/Heroku style URLs and select the psycopg (v3) driver."""
    cleaned = (url or "").strip().strip('"').strip("'")
    if not cleaned:
        return None
    for prefix in ("postgres://", "postgresql://"):
        if cleaned.startswith(prefix):
            return "postgresql+psycopg://" + cleaned[len(prefix):]
    return cleaned


def detect_cloud_host(env: dict[str, str]) -> bool:
    """Streamlit Community Cloud runs apps from /mount/src; allow an explicit override for other hosts."""
    if env.get("SHOGUN_EPHEMERAL_HOST", "").lower() in ("1", "true", "yes"):
        return True
    return PROJECT_ROOT.as_posix().startswith("/mount/src") or env.get("HOSTNAME", "") == "streamlit"


def validate_timezone(name: str) -> str:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Unknown timezone: {name!r}") from exc
    return name


def load_config(env_file: Path | None = None, *, override: dict[str, str] | None = None) -> AppConfig:
    """Build configuration from environment (+ optional ``.env``).

    ``override`` is used by tests to inject values without touching os.environ.
    """
    if env_file is None:
        env_file = PROJECT_ROOT / ".env"
    if env_file.exists() and not os.environ.get("SHOGUN_DISABLE_DOTENV"):
        load_dotenv(env_file, override=False)

    env = dict(os.environ)
    if override:
        env.update(override)

    var_dir = Path(env.get("SHOGUN_VAR_DIR") or (PROJECT_ROOT / "var"))
    db_path = Path(env.get("SHOGUN_DB_PATH") or (var_dir / "shogun.db"))
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    if not var_dir.is_absolute():
        var_dir = PROJECT_ROOT / var_dir

    tz = env.get("SHOGUN_TIMEZONE") or DEFAULT_TIMEZONE
    try:
        tz = validate_timezone(tz)
    except ValueError:
        tz = DEFAULT_TIMEZONE

    model = (env.get("GROQ_MODEL") or "").strip() or None

    return AppConfig(
        db_path=db_path,
        timezone=tz,
        log_level=(env.get("SHOGUN_LOG_LEVEL") or "INFO").upper(),
        var_dir=var_dir,
        groq_api_key=Secret(env.get("GROQ_API_KEY")),
        serpapi_api_key=Secret(env.get("SERPAPI_API_KEY")),
        groq_model=model,
        database_url=Secret(normalize_database_url(env.get("SHOGUN_DATABASE_URL") or env.get("DATABASE_URL"))),
        cloud_host=detect_cloud_host(env),
    )
