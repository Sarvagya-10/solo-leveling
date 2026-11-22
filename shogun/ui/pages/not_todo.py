from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from shogun.services import avoidance_service, settings_service
from shogun.ui import charts
from shogun.ui.components import page_header, stat_row
from shogun.ui.context import action, get_ctx

ICON = {"complied": "✓ clean", "violated": "✗ violated", "missing": "· missing"}


def render() -> None:
    ctx = get_ctx()
    today = ctx.today()
    page_header("Daily Not-To-Do", "Private compliance log. A day you don't log is shown as missing — never assumed "
                "clean. This data is never sent to any AI service.", kicker="Discipline · private")
    day = st.date_input("Day", value=today, max_value=today, key="ntd_day")
    with ctx.session() as s:
        rules = [(r.id, r.name, r.description or "") for r in avoidance_service.list_rules(s)]
        entries = avoidance_service.entries_between(s, day, day)
        current = {rid: (entries[(rid, day)].status, entries[(rid, day)].notes or "")
                   for rid, *_ in rules if (rid, day) in entries}
        start = max(settings_service.tracking_start(s, today), today - timedelta(days=29))
        series = avoidance_service.daily_compliance(s, start, today)
        hist = avoidance_service.entries_between(s, start, today)
        streaks = {rid: avoidance_service.rule_streak(s, rid, today) for rid, *_ in rules}
        full_streak = avoidance_service.full_compliance_streak(s, today)
    t = series[-1] if series else None
    if t:
        stat_row([
            ("Clean today", f"{t.complied}/{t.applicable}", f"{t.compliance_pct:.0f}% of rules"),
            ("Violations today", str(t.violated), "logged honestly"),
            ("Missing today", str(t.missing), "not yet logged"),
            ("Full-clean streak", f"{full_streak} d", "all rules complied"),
        ])
    with st.form(f"ntd_form_{day}"):
        st.markdown(f"**Check-in for {day:%A %d %b}**")
        choices = {}
        for rid, name, desc in rules:
            status, note = current.get(rid, (None, ""))
            c1, c2 = st.columns([2.2, 1.6])
            opts = ["Not logged", "Complied", "Violated"]
            idx = 0 if status is None else (1 if status == "complied" else 2)
            pick = c1.radio(f"{name} · streak {streaks.get(rid, 0)}d", opts, index=idx, horizontal=True,
                            key=f"ntd_{rid}_{day}", help=desc)
            note_val = c2.text_input("Note", value=note, key=f"ntd_n_{rid}_{day}", label_visibility="collapsed",
                                     placeholder="note (optional, private)", max_chars=300)
            choices[rid] = (pick, note_val)
        if st.form_submit_button("Save check-in", type="primary"):
            def save(s):  # noqa: ANN001
                for rid, (pick, note) in choices.items():
                    if pick == "Not logged":
                        avoidance_service.clear_status(s, rid, day)
                    else:
                        avoidance_service.set_status(s, rid, day, pick.lower(), note, today=today)
            action(ctx, save, success=f"Check-in saved for {day:%d %b}", days=[day])

    st.markdown("##### Adherence")
    st.plotly_chart(charts.line_chart(
        [d.day for d in series],
        [("Compliance (of all rules)", [d.compliance_pct for d in series]),
         ("Compliance (of logged rules)", [d.logged_compliance_pct for d in series])],
        percent=True, y_range=(0, 105), title="Daily not-to-do compliance",
        missing_x=[d.day for d in series if d.missing], missing_y=0, height=300), config=charts.CONFIG)
    st.caption("Compliance (of all rules) counts unlogged rules as not complied. ✕ marks days with missing data.")
    with st.expander("Last 10 days by rule"):
        grid = []
        for rid, name, _ in rules:
            row = {"Rule": name, "Streak": streaks.get(rid, 0)}
            for d in series[-10:]:
                e = hist.get((rid, d.day))
                row[d.day.strftime("%d %b")] = ICON[e.status if e else "missing"]
            grid.append(row)
        st.dataframe(pd.DataFrame(grid), hide_index=True, width="stretch")
