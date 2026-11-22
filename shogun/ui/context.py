"""Per-process app context and the action helper used by every page.

``action()`` runs a write in its own transaction, commits it, re-syncs XP and
achievements for the affected days, queues a success message and reruns the
script so every chart reflects the new data immediately. Expected errors are
shown inline; unexpected ones are logged (redacted) and shown generically.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from typing import Any

import streamlit as st
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from shogun.ai.errors import AIError
from shogun.config import AppConfig, load_config
from shogun.db.session import get_engine, run_migrations, session_scope
from shogun.logging_setup import configure_logging, get_logger, register_secret
from shogun.services import exam_service, gamification_service, settings_service
from shogun.services.errors import ShogunError
from shogun.services.seed import seed_all
from shogun.timeutil import local_today
from shogun.ui.components import flash

log = get_logger("ui")


@dataclass
class AppContext:
    config: AppConfig
    engine: Engine

    @contextmanager
    def session(self) -> Iterator[Session]:
        with session_scope(self.engine) as s:
            yield s

    @property
    def tz(self) -> str:
        with self.session() as s:
            return str(settings_service.get_setting(s, "timezone"))

    def today(self) -> date:
        return local_today(self.tz)


@st.cache_resource(show_spinner="Opening the gate…")
def _bootstrap() -> AppContext:
    config = load_config()
    configure_logging(config.log_level, config.logs_dir)
    register_secret(config.groq_api_key.get())
    register_secret(config.serpapi_api_key.get())
    run_migrations(config.db_url)
    engine = get_engine(config.db_url)
    with session_scope(engine) as s:
        if settings_service.get_setting(s, "timezone") == settings_service.DEFAULTS["timezone"] \
                and config.timezone != settings_service.DEFAULTS["timezone"]:
            settings_service.set_setting(s, "timezone", config.timezone)
        tz = str(settings_service.get_setting(s, "timezone"))
        today = local_today(tz)
        seed_all(s, today)
        exam_service.expire_if_overdue(s, tz)
        gamification_service.sync_all(s, tz, today)
        gamification_service.evaluate_achievements(s, today, tz)
    log.info("Application bootstrapped")
    return AppContext(config=config, engine=engine)


def get_ctx() -> AppContext:
    return _bootstrap()


def reset_ctx() -> None:
    _bootstrap.clear()


def action(
    ctx: AppContext,
    fn: Callable[[Session], Any],
    *,
    success: str | Callable[[Any], str],
    days: Iterable[date] | Callable[[Any], Iterable[date]] = (),
    rerun: bool = True,
) -> Any:
    """Run a write; on success commit, sync XP, flash and rerun. Returns the result or None on error."""
    try:
        with ctx.session() as s:
            result = fn(s)
            tz = str(settings_service.get_setting(s, "timezone"))
            today = local_today(tz)
            affected = set(days(result) if callable(days) else days)
            new_badges = gamification_service.after_change(s, affected, today, tz)
    except ShogunError as exc:
        st.error(str(exc))
        return None
    except AIError as exc:
        st.warning(f"AI unavailable: {exc}")
        return None
    except Exception:
        log.exception("Unexpected error while saving")
        st.error("Something went wrong while saving. Nothing was changed. Details are in var/logs/shogun.log.")
        return None
    flash(success(result) if callable(success) else success)
    for badge in new_badges:
        flash(f"Achievement unlocked: {badge.icon} {badge.name}", "badge")
    if rerun:
        st.rerun()
    return result
