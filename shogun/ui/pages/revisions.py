from __future__ import annotations

from collections import Counter
from datetime import timedelta

import pandas as pd
import streamlit as st

from shogun.services import revision_service
from shogun.ui import charts
from shogun.ui.components import empty_state, page_header, stat_row
from shogun.ui.context import AppContext, action, get_ctx


def _event_label(ev) -> str:  # noqa: ANN001
    return f"R{ev.stage} · {ev.topic.code} {ev.topic.name}"


def _complete_form(ctx: AppContext, ev, prefix: str) -> None:  # noqa: ANN001
    today = ctx.today()
    late = (today - ev.due_date).days
    with st.container(border=True):
        st.markdown(f"**{_event_label(ev)}**  \n"
                    f"<span class='sl-note'>{ev.topic.subject.name} · due {ev.due_date:%a %d %b}"
                    f"{f' · {late} day(s) overdue' if late > 0 else ''} · revision {ev.stage} of 4 "
                    f"(+{ev.offset_days}d)</span>", unsafe_allow_html=True)
        with st.form(f"{prefix}_{ev.id}"):
            c1, c2 = st.columns(2)
            minutes = c1.number_input("Minutes spent", 0, 600, 20, step=5, key=f"{prefix}_m_{ev.id}")
            confidence = c2.select_slider("Confidence", options=[1, 2, 3, 4, 5], value=3, key=f"{prefix}_c_{ev.id}")
            notes = st.text_input("Notes (optional)", key=f"{prefix}_n_{ev.id}", max_chars=500)
            confirm = st.checkbox("I actually completed this revision", key=f"{prefix}_ok_{ev.id}")
            if st.form_submit_button(f"Complete R{ev.stage}", type="primary"):
                if not confirm:
                    st.error("Tick the confirmation box — revisions are never marked complete automatically.")
                else:
                    action(ctx, lambda s: revision_service.complete_revision(
                        s, ev.id, today, minutes=int(minutes), confidence=int(confidence), notes=notes),
                        success=f"R{ev.stage} completed for {ev.topic.name} (+15 XP)", days=[today])


def render() -> None:
    ctx = get_ctx()
    today = ctx.today()
    page_header("Revision Queue", "Spaced revisions at +1, +3, +7 and +21 days. Nothing is ever completed "
                "silently — confirm each one.", kicker="Memory dungeon")
    with ctx.session() as s:
        due = revision_service.due_today(s, today)
        over = revision_service.overdue(s, today)
        upcoming = revision_service.upcoming(s, today, days=30)
        done_recent = revision_service.completed_between(s, today - timedelta(days=14), today)
        for ev in [*due, *over, *upcoming, *done_recent]:
            _ = ev.topic.subject.name  # load before session closes
    stat_row([
        ("To revise today", str(len(due)), "due today"),
        ("Overdue", str(len(over)), "pending past due date"),
        ("Next 30 days", str(len(upcoming)), "scheduled"),
        ("Completed (14d)", str(len(done_recent)), "revisions"),
    ])
    tab_today, tab_over, tab_cal, tab_done = st.tabs([f"To Revise Today ({len(due)})", f"Overdue ({len(over)})",
                                                      "Upcoming calendar", "Completed"])
    with tab_today:
        if not due:
            empty_state("Queue clear for today", "No revisions are due today. Log study to schedule new ones.")
        cols = st.columns(2)
        for i, ev in enumerate(due):
            with cols[i % 2]:
                _complete_form(ctx, ev, "due")
    with tab_over:
        if not over:
            empty_state("No overdue revisions", "Everything scheduled before today has been completed.")
        else:
            st.warning("Overdue revisions stay pending until you complete them. Complete earlier stages first.")
        cols = st.columns(2)
        for i, ev in enumerate(over):
            with cols[i % 2]:
                _complete_form(ctx, ev, "over")
    with tab_cal:
        if not upcoming:
            empty_state("Nothing scheduled", "Upcoming revisions appear here after you log study.")
        else:
            counts = Counter(ev.due_date for ev in upcoming)
            days = [today + timedelta(days=i) for i in range(1, 31)]
            st.plotly_chart(charts.bar_chart([d.strftime("%d %b") for d in days], [counts.get(d, 0) for d in days],
                                             title="Revisions due per day (next 30 days)", y_title="Revisions",
                                             height=260), config=charts.CONFIG)
            for day in sorted(counts):
                with st.expander(f"{day:%a %d %b} — {counts[day]} revision(s)", expanded=day == min(counts)):
                    for ev in [e for e in upcoming if e.due_date == day]:
                        st.markdown(f"- {_event_label(ev)} · <span class='sl-note'>{ev.topic.subject.name}</span>",
                                    unsafe_allow_html=True)
    with tab_done:
        if not done_recent:
            st.caption("No revisions completed in the last 14 days.")
        else:
            st.dataframe(pd.DataFrame([(ev.completed_on, f"R{ev.stage}", ev.topic.code, ev.topic.name, ev.minutes,
                                        ev.confidence, ev.notes or "") for ev in done_recent],
                                      columns=["Completed", "Stage", "Code", "Topic", "Minutes", "Confidence",
                                               "Notes"]), hide_index=True, width="stretch")
            with st.expander("Undo a mistaken completion"):
                options = {ev.id: f"{ev.completed_on} · {_event_label(ev)}" for ev in done_recent}
                eid = st.selectbox("Completed revision", list(options), format_func=options.get, index=None,
                                   key="rev_undo")
                if st.button("Undo completion", disabled=eid is None, key="rev_undo_btn"):
                    action(ctx, lambda s: revision_service.undo_revision(s, eid), success="Completion undone",
                           days=lambda d: [d])
