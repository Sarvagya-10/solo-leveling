from __future__ import annotations

import pandas as pd
import streamlit as st

from shogun.services import attention_service
from shogun.ui import charts
from shogun.ui.components import empty_state, html, page_header, progress_bar, stat_row
from shogun.ui.context import action, get_ctx


def render() -> None:
    ctx = get_ctx()
    today = ctx.today()
    page_header("Attention Span", "Log your longest continuous deep-focus session each day. Nothing is prefilled "
                "or assumed — only what you log is plotted.", kicker="Focus stat")
    with ctx.session() as s:
        summ = attention_service.summary(s)
        series = attention_service.daily_series(s)
        todays = [(x.id, x.minutes, x.notes or "") for x in attention_service.sessions_on(s, today)]
    stat_row([
        ("Latest longest", f"{summ.latest_longest} min" if summ.latest_longest else "—",
         f"on {summ.latest_day:%d %b}" if summ.latest_day else "no sessions yet"),
        ("Personal best", f"{summ.personal_best} min" if summ.personal_best else "—",
         f"on {summ.personal_best_on:%d %b}" if summ.personal_best_on else ""),
        ("7-day average", f"{summ.rolling_avg:.0f} min" if summ.rolling_avg is not None else "—",
         "of daily longest (logged days)"),
        ("Total deep work", f"{summ.total_minutes} min", f"{summ.days_logged} day(s) logged"),
    ])
    html(progress_bar(summ.progress_pct, f"Progress toward {summ.target} min",
                      f"best {summ.personal_best or 0} / {summ.target} min · baseline {summ.baseline} min"))

    left, right = st.columns([1, 1.6])
    with left:
        with st.form("att_form", clear_on_submit=True):
            st.markdown("**Log a deep-focus session**")
            day = st.date_input("Date", value=today, max_value=today)
            minutes = st.number_input("Continuous deep-focus minutes", 1, 1440, 25, step=5)
            notes = st.text_input("What were you doing? (optional)", max_chars=500)
            if st.form_submit_button("Log session", type="primary"):
                action(ctx, lambda s: attention_service.add_session(s, day, int(minutes), notes, today=today),
                       success=f"{int(minutes)}-minute session logged", days=[day])
        st.caption("Log several sessions per day — the chart shows the longest session and total deep work "
                   "separately.")
        if todays:
            st.markdown("**Today's sessions**")
            for sid, mins, note in todays:
                c1, c2 = st.columns([3, 1])
                c1.markdown(f"{mins} min" + (f" · {note}" if note else ""))
                if c2.button("Delete", key=f"att_del_{sid}"):
                    action(ctx, lambda s, sid=sid: attention_service.delete_session(s, sid),
                           success="Session deleted", days=lambda d: [d])
    with right:
        if not series:
            empty_state("No sessions logged yet", f"Your starting baseline is {summ.baseline} minutes. Log today's "
                        "longest focus session to start the graph.")
        else:
            x = [r.day for r in series]
            st.plotly_chart(charts.line_chart(
                x, [("Longest session", [r.longest for r in series]),
                    ("7-day rolling average", [r.rolling_avg for r in series])],
                title="Longest continuous deep-focus session", y_title="minutes",
                ref_lines=[(summ.target, f"Target {summ.target} min"), (summ.baseline, f"Baseline {summ.baseline} min")],
                height=340), config=charts.CONFIG)
            st.plotly_chart(charts.bar_chart([r.day.strftime("%d %b") for r in series], [r.total for r in series],
                                             title="Total deep-work minutes per day", y_title="minutes", height=240,
                                             hover_suffix=" min"), config=charts.CONFIG)
    if series:
        with st.expander("Daily values"):
            st.dataframe(pd.DataFrame([{"Date": r.day, "Longest (min)": r.longest, "Total (min)": r.total,
                                        "Sessions": r.sessions, "7-day avg": r.rolling_avg} for r in reversed(series)]),
                         hide_index=True, width="stretch")
