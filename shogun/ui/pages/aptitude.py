from __future__ import annotations

import pandas as pd
import streamlit as st

from shogun.services import progress_service
from shogun.ui import charts
from shogun.ui.components import page_header
from shogun.ui.context import get_ctx
from shogun.ui.study_entry import render_entry_form, render_recent_logs
from shogun.ui.syllabus_view import render_tracker


def render() -> None:
    ctx = get_ctx()
    page_header("General Aptitude", "Official GATE 2027 GA syllabus: Verbal, Quantitative, Analytical and Spatial "
                "Aptitude (10 questions · 15 marks in every paper).", kicker="Common gate")
    tab_log, tab_track, tab_pyq = st.tabs(["Daily GA entry", "GA syllabus tracker", "PYQ accuracy by category"])
    with tab_log:
        with st.container(border=True):
            render_entry_form(ctx, "GA", "ga_entry")
        st.markdown("##### Recent GA entries")
        render_recent_logs(ctx, "GA", "ga_recent")
    with tab_track:
        render_tracker(ctx, "GA", "ga")
    with tab_pyq:
        with ctx.session() as s:
            rows = progress_service.topic_rows(s, "GA")
        summaries = progress_service.subject_summaries(rows)
        df = pd.DataFrame([{
            "Category": su.subject_name, "Topics": su.total, "Covered (mastered)": su.coverage["mastered"],
            "Coverage %": su.coverage_pct, "PYQ attempted": su.pyq_attempted, "PYQ correct": su.pyq_correct,
            "Accuracy %": round(100 * su.pyq_correct / su.pyq_attempted, 1) if su.pyq_attempted else None,
            "Topics at PYQ target": su.pyq_mastered,
        } for su in summaries])
        st.dataframe(df, hide_index=True, width="stretch")
        acc = [(su.subject_name, 100 * su.pyq_correct / su.pyq_attempted) for su in summaries if su.pyq_attempted]
        if acc:
            st.plotly_chart(charts.bar_chart([a for a, _ in acc], [b for _, b in acc], horizontal=True, percent=True,
                                             title="PYQ accuracy by GA category", height=240, hover_suffix="%"),
                            config=charts.CONFIG)
        else:
            st.caption("Accuracy appears once GA PYQs are logged.")
        topic_df = pd.DataFrame([{
            "Code": r.code, "Topic": r.name, "Category": r.subject_name, "Attempts": r.pyq_attempted,
            "Correct": r.pyq_correct, "Accuracy %": r.pyq_accuracy, "Target": r.pyq_target,
            "PYQ mastery": progress_service.STATUS_LABEL[r.pyq_status],
        } for r in rows])
        with st.expander("Topic-level PYQ tracking"):
            st.dataframe(topic_df, hide_index=True, width="stretch")
