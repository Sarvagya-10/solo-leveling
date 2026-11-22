from __future__ import annotations

from collections import Counter
from datetime import timedelta

import streamlit as st

from shogun.ai import workflows
from shogun.services import reflection_service
from shogun.services.reflection_service import PROMPTS
from shogun.ui import charts
from shogun.ui.components import page_header, stat_row
from shogun.ui.context import action, get_ctx


def render() -> None:
    ctx = get_ctx()
    today = ctx.today()
    page_header("Adapt", "Three questions, every day. Small honest steps compound.", kicker="Reflection")
    day = st.date_input("Reflection date", value=today, max_value=today, key="adapt_day")
    with ctx.session() as s:
        row = reflection_service.get(s, day)
        existing = (row.went_well, row.did_not_go_well, row.smallest_step, row.ai_suggestion, row.id) if row else None
        total = reflection_service.count(s)
        streak = reflection_service.streak(s, today)
        all_dates = reflection_service.dates(s)
    stat_row([("Reflections", str(total), "written"), ("Streak", f"{streak} d", "consecutive days"),
              ("Last 7 days", str(sum(1 for d in all_dates if d > today - timedelta(days=7))), "of 7")], columns=3)

    with st.form(f"adapt_form_{day}"):
        st.markdown(f"**{day:%A %d %b}** — all three prompts are required.")
        a = st.text_area(PROMPTS["went_well"], value=existing[0] if existing else "", height=100, max_chars=5000)
        b = st.text_area(PROMPTS["did_not_go_well"], value=existing[1] if existing else "", height=100, max_chars=5000)
        c = st.text_area(PROMPTS["smallest_step"], value=existing[2] if existing else "", height=80, max_chars=5000)
        if st.form_submit_button("Save reflection", type="primary"):
            action(ctx, lambda s: reflection_service.upsert(s, day, a, b, c, today=today),
                   success="Reflection saved (+15 XP)", days=[day])

    if existing:
        with st.container(border=True):
            st.markdown("**Optional AI suggestion** (Groq). Only this reflection's three answers are sent.")
            if existing[3]:
                st.markdown(existing[3])
            if st.button("Get suggestion" if not existing[3] else "Refresh suggestion", key="adapt_ai"):
                rid = existing[4]

                def do(s):  # noqa: ANN001
                    text = workflows.reflection_advice(s, ctx.config, rid, force=bool(existing[3]))
                    reflection_service.save_ai_suggestion(s, rid, text)
                action(ctx, do, success="Suggestion added")

    st.markdown("##### History")
    if all_dates:
        start = max(min(all_dates), today - timedelta(days=83))
        weeks = Counter((d - timedelta(days=d.weekday())) for d in all_dates if d >= start)
        week_starts = sorted({start - timedelta(days=start.weekday()) + timedelta(weeks=i)
                              for i in range(((today - start).days // 7) + 1)})
        st.plotly_chart(charts.bar_chart([w.strftime("%d %b") for w in week_starts],
                                         [weeks.get(w, 0) for w in week_starts], title="Reflections per week",
                                         y_title="days", height=220), config=charts.CONFIG)
    q = st.text_input("Search reflections", placeholder="e.g. sleep, phone, linear algebra", key="adapt_q")
    with ctx.session() as s:
        results = [(r.entry_date, r.went_well, r.did_not_go_well, r.smallest_step, r.ai_suggestion)
                   for r in reflection_service.search(s, q or None)]
    if not results:
        st.caption("No reflections found.")
    for d, a, b, c, ai in results[:60]:
        with st.expander(f"{d:%a %d %b %Y}"):
            st.markdown(f"**Went well:** {a}\n\n**Did not go well:** {b}\n\n**Smallest step:** {c}")
            if ai:
                st.caption("AI suggestion")
                st.markdown(ai)
