"""Shared daily study-entry form (used by Daily GATE Log and General Aptitude)."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from shogun.services import progress_service, study_log_service
from shogun.services.progress_service import STATUS_LABEL
from shogun.services.study_log_service import StudyEntryInput
from shogun.ui.context import AppContext, action


def _summary(result: study_log_service.LogResult) -> str:
    parts = [f"Logged {len(result.log_ids)} topic(s)."]
    for info in result.scheduled:
        parts.append(f"{info.topic_name}: revisions on " + ", ".join(d.strftime("%d %b") for d in info.due_dates))
    if result.already_scheduled:
        parts.append("Already in an active revision cycle (no duplicates): " + ", ".join(result.already_scheduled))
    return " ".join(parts)


def render_entry_form(ctx: AppContext, paper: str, key: str) -> None:
    today = ctx.today()
    with ctx.session() as s:
        rows = progress_service.topic_rows(s, paper)
    labels = {r.topic_id: f"{r.code} · {r.name}" for r in rows}
    current = {r.topic_id: r for r in rows}

    log_date = st.date_input("Study date", value=today, max_value=today, key=f"{key}_date",
                             help="Backdate if you forgot to log; future dates are not allowed.")
    selected = st.multiselect("Topics studied", list(labels), format_func=labels.get, key=f"{key}_topics",
                              placeholder="Search and select every topic you studied")
    if not selected:
        st.caption("Select one or more topics to enter minutes, PYQs and mastery status.")
        return
    with st.form(f"{key}_form", clear_on_submit=False):
        entries_raw = []
        for tid in selected:
            row = current[tid]
            st.markdown(f"**{labels[tid]}** · current coverage: {STATUS_LABEL[row.coverage_status]}")
            c1, c2, c3, c4 = st.columns([1, 1, 1, 1.4])
            minutes = c1.number_input("Minutes", 0, 1440, 60, step=5, key=f"{key}_m_{tid}")
            attempted = c2.number_input("PYQs attempted", 0, 500, 0, key=f"{key}_a_{tid}")
            correct = c3.number_input("PYQs correct", 0, 500, 0, key=f"{key}_c_{tid}")
            default_status = row.coverage_status if row.coverage_status != "not_started" else "in_progress"
            status = c4.selectbox("Mastery status", list(STATUS_LABEL), index=list(STATUS_LABEL).index(default_status),
                                  format_func=STATUS_LABEL.get, key=f"{key}_s_{tid}")
            notes = st.text_input("Notes (optional)", key=f"{key}_n_{tid}", max_chars=1000)
            entries_raw.append((tid, int(minutes), int(attempted), int(correct), status, notes))
        submitted = st.form_submit_button("Save study log & schedule revisions", type="primary")
    if submitted:
        entries = [StudyEntryInput(tid, m, a, c, st_, n) for tid, m, a, c, st_, n in entries_raw]
        action(ctx, lambda s: study_log_service.log_study(s, log_date, entries, today=today),
               success=_summary, days=[log_date])


def render_recent_logs(ctx: AppContext, paper: str, key: str, days: int = 14) -> None:
    today = ctx.today()
    with ctx.session() as s:
        logs = [(lg.id, lg.log_date, lg.topic.code, lg.topic.name, lg.minutes, lg.pyq_attempted, lg.pyq_correct,
                 STATUS_LABEL[lg.reported_status], lg.notes or "")
                for lg in study_log_service.logs_between(s, today - timedelta(days=days), today, paper)]
    if not logs:
        st.caption(f"No {paper} study logged in the last {days} days.")
        return
    df = pd.DataFrame(logs, columns=["id", "Date", "Code", "Topic", "Minutes", "PYQ att.", "PYQ correct",
                                     "Reported status", "Notes"])
    st.dataframe(df.drop(columns=["id"]), hide_index=True, width="stretch")
    with st.expander("Delete a mistaken entry"):
        options = {lid: f"{d} · {code} {name} · {m} min" for lid, d, code, name, m, *_ in logs}
        lid = st.selectbox("Entry", list(options), format_func=options.get, key=f"{key}_del_sel", index=None)
        confirm = st.checkbox("I understand this removes the entry (revisions it created are removed only if "
                              "none were completed).", key=f"{key}_del_ok")
        if st.button("Delete entry", key=f"{key}_del_btn", disabled=lid is None or not confirm):
            action(ctx, lambda s: study_log_service.delete_study_log(s, lid), success="Entry deleted",
                   days=lambda d: [d])
