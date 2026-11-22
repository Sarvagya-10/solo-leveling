"""Shogun : Phase 3 - Solo Leveling — Streamlit entry point.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

from shogun import APP_TITLE
from shogun.services import gamification_service, settings_service
from shogun.ui import nav
from shogun.ui.components import level_up_overlay, show_flash, status_bar
from shogun.ui.context import get_ctx
from shogun.ui.pages import (
    adapt,
    analytics,
    aptitude,
    attention,
    cards,
    daily_log,
    dashboard,
    habits,
    not_todo,
    question_bank,
    revisions,
    settings_page,
    syllabus,
    system,
    war,
    worklogs,
)
from shogun.ui.theme import inject_theme

st.set_page_config(page_title=APP_TITLE, page_icon="⚔️", layout="wide", initial_sidebar_state="auto",
                   menu_items={"About": f"{APP_TITLE} — GATE DA 2027 preparation System."})
inject_theme()

ctx = get_ctx()


def P(key: str, fn, title: str, icon: str, default: bool = False):  # noqa: ANN001, N802
    return nav.register(key, st.Page(fn, title=title, icon=icon, url_path=key, default=default))


pages = {
    "System": [
        P("dashboard", dashboard.render, "Status Window", ":material/dashboard:", default=True),
        P("system", system.render, "XP · Rank · Badges", ":material/military_tech:"),
    ],
    "GATE DA 2027": [
        P("syllabus", syllabus.render, "DA Syllabus Tracker", ":material/menu_book:"),
        P("daily_log", daily_log.render, "Daily GATE Log", ":material/edit_note:"),
        P("revisions", revisions.render, "Revision Queue", ":material/event_repeat:"),
        P("aptitude", aptitude.render, "General Aptitude", ":material/psychology:"),
        P("cards", cards.render, "Revision Cards", ":material/style:"),
        P("questions", question_bank.render, "Question Bank & PYQs", ":material/quiz:"),
        P("war", war.render, "Weekend Full War", ":material/swords:"),
    ],
    "Daily Execution": [
        P("attention", attention.render, "Attention Span", ":material/center_focus_strong:"),
        P("finance", worklogs.render_finance, "Finance", ":material/monitoring:"),
        P("research", worklogs.render_research, "Research", ":material/science:"),
        P("habits", habits.render, "Daily Habits", ":material/self_improvement:"),
        P("not_todo", not_todo.render, "Not-To-Do", ":material/block:"),
        P("adapt", adapt.render, "Adapt", ":material/autorenew:"),
    ],
    "Insight & Control": [
        P("analytics", analytics.render, "Execution Analytics", ":material/insights:"),
        P("settings", settings_page.render, "Settings & Data", ":material/settings:"),
    ],
}

navigation = st.navigation(pages, position="sidebar", expanded=True)

with st.sidebar:
    st.caption(f"⚔️ {APP_TITLE}")

today = ctx.today()
with ctx.session() as session:
    snapshot = gamification_service.status(session, today)
    last_level = int(settings_service.get_setting(session, "last_seen_level"))
    if snapshot.level.level > last_level:
        settings_service.set_setting(session, "last_seen_level", snapshot.level.level)
        level_up_overlay(snapshot.level.level, snapshot.level.rank)
    elif snapshot.level.level < last_level:
        settings_service.set_setting(session, "last_seen_level", snapshot.level.level)

status_bar(APP_TITLE, snapshot, today.strftime("%a %d %b %Y"))
show_flash()
navigation.run()
