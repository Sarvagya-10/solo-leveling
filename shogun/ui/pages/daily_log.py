from __future__ import annotations

import streamlit as st

from shogun.services import revision_service, study_log_service
from shogun.ui import nav
from shogun.ui.components import page_header, stat_row
from shogun.ui.context import get_ctx
from shogun.ui.study_entry import render_entry_form, render_recent_logs


def render() -> None:
    ctx = get_ctx()
    today = ctx.today()
    page_header("Daily GATE Log", "Log what you studied today. Progress updates automatically and revisions are "
                "scheduled for +1, +3, +7 and +21 days.", kicker="Training record")
    with ctx.session() as s:
        totals = study_log_service.daily_totals(s, today, today).get(today, {"minutes": 0, "pyq_attempted": 0,
                                                                              "pyq_correct": 0, "topics": 0})
        due = len(revision_service.due_today(s, today))
        over = len(revision_service.overdue(s, today))
    stat_row([
        ("Today", f"{totals['minutes']} min", f"{totals['topics']} topic(s)"),
        ("PYQs today", f"{totals['pyq_correct']}/{totals['pyq_attempted']}", "correct / attempted"),
        ("To revise today", str(due), "scheduled revisions"),
        ("Overdue", str(over), "still pending"),
    ])
    if due or over:
        nav.link("revisions", f"Open the revision queue ({due + over} pending)", icon="🔁")
    paper = st.segmented_control("Paper", ["DA", "GA"], default="DA", key="dl_paper",
                                 format_func=lambda p: "Data Science & AI" if p == "DA" else "General Aptitude")
    paper = paper or "DA"
    with st.container(border=True):
        render_entry_form(ctx, paper, f"dl_{paper}")
    st.markdown("##### Recent entries")
    render_recent_logs(ctx, paper, f"dl_recent_{paper}")
