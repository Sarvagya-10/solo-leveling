"""Finance and Research pages (same structure, independently tracked)."""

from __future__ import annotations

from datetime import timedelta
from html import escape

import pandas as pd
import streamlit as st

from shogun.services import settings_service, worklog_service
from shogun.services.defaults import FINANCE_PROJECT
from shogun.services.worklog_service import WorkLogInput
from shogun.timeutil import date_range
from shogun.ui import charts
from shogun.ui.components import empty_state, html, page_header, stat_row
from shogun.ui.context import action, get_ctx


def _render(domain: str) -> None:
    ctx = get_ctx()
    today = ctx.today()
    research = domain == "research"
    page_header("Research" if research else "Finance",
                "Daily one-hour research block: direction, milestones, outputs, references." if research else
                "Daily one-hour finance block: what you did, direction and next steps.",
                kicker="Side quest")
    with ctx.session() as s:
        start = max(settings_service.tracking_start(s, today), today - timedelta(days=29))
        summ = worklog_service.summary(s, domain, start, today)
        minutes = worklog_service.daily_minutes(s, domain, start, today)
        projects = [p.name for p in worklog_service.projects(s, domain)]
        target_label = str(settings_service.get_setting(s, "finance_target_label"))
    if not research:
        html(f'<div class="sl-hero" role="banner" aria-label="Finance target {escape(target_label)}">'
             f'<div class="sl-label">Project · {escape(FINANCE_PROJECT)}</div>'
             f'<div class="sl-big" style="font-size:clamp(2.6rem,7vw,4.4rem)">TARGET {escape(target_label)}</div>'
             f'</div>')
    stat_row([
        ("Today", f"{minutes.get(today, 0)} min", f"target {summ.target} min"),
        ("Target streak", f"{summ.current_streak} d", "consecutive days met"),
        ("Days met (30d)", f"{summ.days_met}", f"{summ.completion_pct:.0f}% of days"),
        ("Total (30d)", f"{summ.total_minutes / 60:.1f} h", f"{summ.days_logged} day(s) logged"),
    ])
    left, right = st.columns([1, 1.4])
    with left, st.form(f"{domain}_form", clear_on_submit=True):
        st.markdown("**New log**")
        c1, c2 = st.columns(2)
        day = c1.date_input("Date", value=today, max_value=today)
        dur = c2.number_input("Duration (min)", 1, 1440, summ.target, step=5)
        if research:
            project = st.selectbox("Project", ["(none)", *projects, "+ New project…"], key=f"{domain}_proj")
            new_project = st.text_input("New project name (if adding one)", max_chars=120)
        else:
            st.markdown(f"Project: **{FINANCE_PROJECT}**")
            project, new_project = FINANCE_PROJECT, ""
        what = st.text_area("What was done *", height=90, max_chars=5000)
        direction = st.text_area("Research direction", height=70, max_chars=5000)
        milestone = st.text_input("Milestone", max_chars=500) if research else None
        outputs = st.text_area("Outputs (papers, code, notes)", height=60, max_chars=5000) if research else None
        refs = st.text_area("References (one per line)", height=60, max_chars=5000) if research else None
        nxt = st.text_area("Next steps", height=70, max_chars=5000)
        tags = st.text_input("Tags (comma separated)", max_chars=200) if research else None
        if st.form_submit_button("Save log", type="primary"):
            proj = new_project if project == "+ New project…" else (None if project == "(none)" else project)
            data = WorkLogInput(domain, day, int(dur), what, research_direction=direction, next_steps=nxt,
                                project_name=proj, tags=tags, milestone=milestone, outputs=outputs,
                                references_text=refs)
            action(ctx, lambda s: worklog_service.add_log(s, data, today=today),
                   success=f"{domain.title()} log saved ({int(dur)} min)", days=[day])
    with right:
        days = list(date_range(start, today))
        st.plotly_chart(charts.bar_chart([d.strftime("%d %b") for d in days], [minutes.get(d, 0) for d in days],
                                         title="Minutes per day (last 30 days)", y_title="minutes", height=260,
                                         hover_suffix=" min"), config=charts.CONFIG)
        met = []
        running = 0
        for i, d in enumerate(days, start=1):
            running += 1 if minutes.get(d, 0) >= summ.target else 0
            met.append(100 * running / i)
        st.plotly_chart(charts.line_chart(days, [("Days on target (cumulative %)", met)], percent=True,
                                          y_range=(0, 105), height=220, title="Completion trend"),
                        config=charts.CONFIG)
    st.markdown("##### History")
    if research:
        c1, c2 = st.columns([2, 1])
        q = c1.text_input("Search logs", key=f"{domain}_search", placeholder="keyword in any field")
        pf = c2.selectbox("Project", ["All", *projects], key=f"{domain}_pf")
    else:
        q = st.text_input("Search logs", key=f"{domain}_search", placeholder="keyword in any field")
        pf = "All"
    with ctx.session() as s:
        pid = None
        if pf != "All":
            pid = next((p.id for p in worklog_service.projects(s, domain) if p.name == pf), None)
        logs = [(lg.id, lg.log_date, lg.duration_minutes, lg.project.name if lg.project else "", lg.what_done,
                 lg.research_direction or "", lg.milestone or "", lg.outputs or "", lg.next_steps or "",
                 lg.references_text or "", lg.tags or "")
                for lg in worklog_service.list_logs(s, domain, search=q or None, project_id=pid)]
    if not logs:
        empty_state("No logs yet", "Your entries will appear here.")
        return
    cols = ["id", "Date", "Minutes", "Project", "What was done", "Direction", "Milestone", "Outputs", "Next steps",
            "References", "Tags"]
    df = pd.DataFrame(logs, columns=cols)
    if not research:
        df = df.drop(columns=["Milestone", "Outputs", "References", "Tags"])
    st.dataframe(df.drop(columns=["id"]), hide_index=True, width="stretch")
    with st.expander("Delete an entry"):
        opts = {row[0]: f"{row[1]} · {row[2]} min · {row[4][:50]}" for row in logs}
        lid = st.selectbox("Entry", list(opts), format_func=opts.get, index=None, key=f"{domain}_del")
        if st.button("Delete", disabled=lid is None, key=f"{domain}_del_btn"):
            action(ctx, lambda s: worklog_service.delete_log(s, lid), success="Entry deleted", days=lambda d: [d])


def render_finance() -> None:
    _render("finance")


def render_research() -> None:
    _render("research")
