from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from shogun.services import habit_service, settings_service
from shogun.ui import charts
from shogun.ui.components import page_header, stat_row
from shogun.ui.context import action, get_ctx

STATE_ICON = {"done": "✓ done", "not_done": "✗ not done", "missing": "· missing"}


def render() -> None:
    ctx = get_ctx()
    today = ctx.today()
    page_header("Daily Habits", "Track every habit explicitly. Unlogged habits show as missing — never as done.",
                kicker="Rituals")
    day = st.date_input("Day", value=today, max_value=today, key="hab_day")
    with ctx.session() as s:
        habits = [(h.id, h.name, h.kind, h.unit, h.target_value) for h in habit_service.list_habits(s)]
        entries = habit_service.entries_between(s, day, day)
        current = {hid: (entries[(hid, day)].value, entries[(hid, day)].notes or "")
                   for hid, *_ in habits if (hid, day) in entries}
        start = max(settings_service.tracking_start(s, today), today - timedelta(days=29))
        summary = habit_service.daily_summary(s, start, today)
        hist_entries = habit_service.entries_between(s, start, today)
        habit_objs = habit_service.list_habits(s)
        streaks = {h.id: habit_service.habit_streak(s, h, today) for h in habit_objs}
    today_summary = next((d for d in summary if d.day == today), None)
    if today_summary:
        stat_row([
            ("Done today", f"{today_summary.done}/{today_summary.applicable}", f"{today_summary.completion_pct:.0f}%"),
            ("Not done", str(today_summary.not_done), "explicitly logged"),
            ("Missing", str(today_summary.missing), "not logged yet"),
            ("Perfect days (30d)", str(sum(1 for d in summary if d.applicable and d.done == d.applicable)), ""),
        ])
    with st.form(f"hab_form_{day}"):
        st.markdown(f"**Log habits for {day:%A %d %b}** — every field you save is recorded explicitly.")
        values: dict[int, tuple[object, str, bool]] = {}
        for hid, name, kind, unit, target in habits:
            val, note = current.get(hid, (None, ""))
            c1, c2, c3 = st.columns([2, 1.2, 2])
            if kind == "check":
                choice = c1.radio(name, ["Not logged", "Done", "Not done"], horizontal=True,
                                  index=0 if val is None else (1 if val >= 1 else 2), key=f"hab_{hid}_{day}")
                values[hid] = (choice, "", True)
                c2.caption(f"streak {streaks.get(hid, 0)}d")
            else:
                logged = c1.checkbox(f"{name} — log value", value=val is not None, key=f"hab_l_{hid}_{day}")
                amount = c2.number_input(f"{unit or 'value'} (target {target:g})", 0.0, 10000.0,
                                         float(val or 0.0), step=0.25 if unit == "litres" else 5.0,
                                         key=f"hab_v_{hid}_{day}")
                values[hid] = (amount if logged else "Not logged", "", False)
            note_val = c3.text_input("Note", value=note, key=f"hab_n_{hid}_{day}", max_chars=300,
                                     label_visibility="collapsed", placeholder="note (optional)")
            values[hid] = (values[hid][0], note_val, values[hid][2])
        if st.form_submit_button("Save habits", type="primary"):
            def save(s):  # noqa: ANN001
                for hid, (val, note, is_check) in values.items():
                    if val == "Not logged":
                        habit_service.clear_entry(s, hid, day)
                    elif is_check:
                        habit_service.upsert_entry(s, hid, day, 1.0 if val == "Done" else 0.0, note, today=today)
                    else:
                        habit_service.upsert_entry(s, hid, day, float(val), note, today=today)  # type: ignore[arg-type]
            action(ctx, save, success=f"Habits saved for {day:%d %b}", days=[day])

    st.markdown("##### Trends")
    st.plotly_chart(charts.line_chart([d.day for d in summary], [("Habit completion", [d.completion_pct for d in summary])],
                                      percent=True, y_range=(0, 105), title="Daily habit completion",
                                      missing_x=[d.day for d in summary if d.missing], missing_y=0, height=280),
                    config=charts.CONFIG)
    st.caption("✕ = at least one habit not logged that day. Completion = habits meeting target ÷ active habits.")
    grid = []
    for h in habit_objs:
        row = {"Habit": h.name + (f" (≥{h.target_value:g} {h.unit})" if h.kind == "numeric" else "")}
        for d in summary[-10:]:
            row[d.day.strftime("%d %b")] = STATE_ICON[habit_service.entry_state(h, hist_entries.get((h.id, d.day)))]
        grid.append(row)
    with st.expander("Last 10 days by habit", expanded=False):
        st.dataframe(pd.DataFrame(grid), hide_index=True, width="stretch")

    with st.expander("Configure habits & targets"):
        for h in habit_objs:
            with st.form(f"hab_cfg_{h.id}"):
                c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
                name = c1.text_input("Name", value=h.name, max_chars=80)
                target = c2.number_input("Target", 0.01, 10000.0, float(h.target_value), disabled=h.kind == "check")
                unit = c3.text_input("Unit", value=h.unit or "", disabled=h.kind == "check", max_chars=20)
                active = c4.checkbox("Active", value=h.active)
                if st.form_submit_button(f"Save {h.name}"):
                    action(ctx, lambda s, h=h, name=name, target=target, unit=unit, active=active:
                           habit_service.update_habit(s, h.id, name=name, target=target, unit=unit, active=active),
                           success="Habit updated", days=[today])
        with st.form("hab_new"):
            st.markdown("**Add a habit**")
            c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
            name = c1.text_input("Name", max_chars=80)
            kind = c2.selectbox("Kind", ["check", "numeric"])
            target = c3.number_input("Target", 0.01, 10000.0, 1.0)
            unit = c4.text_input("Unit", max_chars=20)
            if st.form_submit_button("Add habit"):
                action(ctx, lambda s: habit_service.add_habit(s, name, kind, float(target), unit),
                       success=f"Habit '{name}' added")
