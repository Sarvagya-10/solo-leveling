from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from shogun.services import analytics_service, progress_service, settings_service
from shogun.ui import charts
from shogun.ui.components import page_header, stat_row
from shogun.ui.context import get_ctx


def render() -> None:
    ctx = get_ctx()
    today = ctx.today()
    page_header("Execution Analytics", "Transparent daily metrics. Unlogged items are never counted as completed.",
                kicker="Battle log")
    with ctx.session() as s:
        tracking_start = settings_service.tracking_start(s, today)
    span = st.segmented_control("Range", ["7 days", "14 days", "30 days", "90 days", "All"], default="30 days",
                                key="an_range") or "30 days"
    days = {"7 days": 7, "14 days": 14, "30 days": 30, "90 days": 90}.get(span)
    start = tracking_start if days is None else max(tracking_start, today - timedelta(days=days - 1))
    st.caption(f"Tracking since {tracking_start:%d %b %Y}. Days before that are not applicable.")

    with ctx.session() as s:
        metrics = analytics_service.daily_metrics(s, start, today)
        coverage = progress_service.coverage_timeline(s, start, today, "DA")
        rows = progress_service.topic_rows(s, "DA")
    if not metrics:
        st.info("No applicable days in this range yet.")
        return
    avg = analytics_service.averages(metrics)
    stat_row([
        ("Avg execution", f"{avg['overall']:.0f}%" if avg["overall"] is not None else "—", "daily efficiency"),
        ("Avg study targets", f"{avg['study']:.0f}%" if avg["study"] is not None else "—", ""),
        ("Avg habits", f"{avg['habits']:.0f}%" if avg["habits"] is not None else "—", ""),
        ("Days with missing data", f"{int(avg['missing_days'] or 0)}/{len(metrics)}", "see ✕ markers"),
    ])
    with st.expander("Metric definitions (how every number is calculated)"):
        for name, text in analytics_service.METRIC_DEFINITIONS.items():
            st.markdown(f"**{name}** — {text}")

    x = [m.day for m in metrics]
    tab1, tab2, tab3 = st.tabs(["Daily execution", "GATE syllabus", "Data table"])
    with tab1:
        st.plotly_chart(charts.line_chart(x, [("Daily execution efficiency", [m.overall_pct for m in metrics])],
                                          percent=True, y_range=(0, 105), title="Daily execution efficiency",
                                          missing_x=[m.day for m in metrics if m.missing_items], missing_y=0,
                                          height=300), config=charts.CONFIG)
        col_l, col_r = st.columns(2)
        with col_l:
            st.plotly_chart(charts.line_chart(x, [("Study targets", [m.study_pct for m in metrics])], percent=True,
                                              y_range=(0, 105), title="Study targets",
                                              missing_x=[m.day for m in metrics if not m.study_logged], missing_y=0,
                                              height=280), config=charts.CONFIG)
            st.caption("✕ = no study logged that day.")
        with col_r:
            st.plotly_chart(charts.line_chart(x, [("Habits / to-dos", [m.habits_pct for m in metrics])], percent=True,
                                              y_range=(0, 105), title="Habits & to-dos",
                                              missing_x=[m.day for m in metrics if m.habits_missing], missing_y=0,
                                              height=280), config=charts.CONFIG)
            st.caption("✕ = at least one habit not logged.")
        col_l, col_r = st.columns(2)
        with col_l:
            st.plotly_chart(charts.line_chart(x, [("Not-to-do compliance", [m.avoid_pct for m in metrics])],
                                              percent=True, y_range=(0, 105), title="Not-to-do compliance",
                                              missing_x=[m.day for m in metrics if m.avoid_missing], missing_y=0,
                                              height=280), config=charts.CONFIG)
            st.caption("✕ = at least one rule not logged (counted as not complied).")
        with col_r:
            completed = [m.overall_completed for m in metrics]
            st.plotly_chart(charts.bar_chart([d.strftime("%d %b") for d in x], completed,
                                             title="Completed targets per day", y_title="targets", height=280),
                            config=charts.CONFIG)
        cumulative, total = [], 0
        for m in metrics:
            total += m.overall_completed
            cumulative.append(total)
        st.plotly_chart(charts.line_chart(x, [("Cumulative completed targets", cumulative)],
                                          title="Cumulative completed targets", y_title="targets", height=260,
                                          markers=False), config=charts.CONFIG)
    with tab2:
        st.plotly_chart(charts.line_chart(
            [c["date"] for c in coverage],
            [("Topics mastered", [c["mastered"] for c in coverage]), ("Topics started", [c["started"] for c in coverage])],
            title=f"Cumulative DA syllabus coverage (of {coverage[0]['total'] if coverage else 119} topics)",
            y_title="topics", height=320, markers=False), config=charts.CONFIG)
        summaries = progress_service.subject_summaries(rows)
        col_l, col_r = st.columns(2)
        with col_l:
            st.plotly_chart(charts.bar_chart([su.subject_name for su in summaries], [su.coverage_pct for su in summaries],
                                             horizontal=True, percent=True, title="Coverage mastered by section",
                                             height=320, hover_suffix="%"), config=charts.CONFIG)
        with col_r:
            st.plotly_chart(charts.bar_chart([su.subject_name for su in summaries],
                                             [100 * su.pyq_mastered / su.total if su.total else 0 for su in summaries],
                                             horizontal=True, percent=True, title="Topics at PYQ-mastery target",
                                             height=320, hover_suffix="%"), config=charts.CONFIG)
        st.dataframe(pd.DataFrame([{
            "Section": su.subject_name, "Topics": su.total, "Mastered": su.coverage["mastered"],
            "In progress": su.coverage["in_progress"], "Not started": su.coverage["not_started"],
            "PYQ mastery": su.pyq_mastered, "PYQ attempted": su.pyq_attempted, "PYQ correct": su.pyq_correct,
            "Accuracy %": round(100 * su.pyq_correct / su.pyq_attempted, 1) if su.pyq_attempted else None,
            "Study hours": round(su.minutes / 60, 1),
        } for su in summaries]), hide_index=True, width="stretch")
    with tab3:
        df = pd.DataFrame([{
            "Date": m.day, "Study min": m.study_minutes, "Study target": m.study_target, "PYQs": m.pyq_attempted,
            "Revisions due": m.revisions_due, "Revisions done": m.revisions_done,
            "Study %": m.study_pct, "Habits done": m.habits_done, "Habits missing": m.habits_missing,
            "Habits %": m.habits_pct, "Not-to-do complied": m.avoid_complied, "Violated": m.avoid_violated,
            "Not logged": m.avoid_missing, "Compliance %": m.avoid_pct, "Finance min": m.finance_minutes,
            "Research min": m.research_minutes, "Reflection": "yes" if m.reflection_done else "no",
            "Completed": m.overall_completed, "Applicable": m.overall_applicable, "Execution %": m.overall_pct,
            "Missing items": m.missing_items,
        } for m in reversed(metrics)])
        st.dataframe(df, hide_index=True, width="stretch")
        st.download_button("Download CSV", df.to_csv(index=False).encode(), file_name="execution_metrics.csv",
                           mime="text/csv")
