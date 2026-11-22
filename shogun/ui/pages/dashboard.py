from __future__ import annotations

from datetime import timedelta
from html import escape

import streamlit as st

from shogun.services import (
    analytics_service,
    attention_service,
    avoidance_service,
    gamification_service,
    habit_service,
    progress_service,
    revision_service,
    settings_service,
    worklog_service,
)
from shogun.services.worklog_service import WorkLogInput
from shogun.ui import charts, nav
from shogun.ui.components import coverage_bar, coverage_legend, html, quest_list, stat
from shogun.ui.context import AppContext, action, get_ctx


def _hero(snap: gamification_service.StatusSnapshot, quests_done: int, quests_total: int) -> None:
    lv = snap.level
    message = ("All daily quests cleared. The System acknowledges you." if quests_total and quests_done == quests_total
               else "Daily quests have arrived. Failure to complete them will be recorded.")
    html(f"""
<div class="sl-hero {'sl-pulse' if quests_total and quests_done == quests_total else ''}">
  <div class="sl-msg">⟡ System message — {escape(message)}</div>
  <div class="sl-hero-top">
    <div><div class="sl-label">Level</div><div class="sl-big">{lv.level}</div></div>
    <div><div class="sl-label">Rank</div><div class="sl-big">{escape(lv.rank)}</div></div>
    <div style="flex:1 1 240px;min-width:220px">
      <div class="sl-label">Experience · {lv.total_xp:,} XP</div>
      <div class="sl-track" style="height:12px;margin:.45rem 0 .3rem"><div class="sl-fill" style="width:{lv.progress_pct}%"></div></div>
      <div class="sl-note">{lv.into_level} / {lv.span} XP to level {lv.level + 1}</div>
    </div>
    <div><div class="sl-label">Quests</div><div class="sl-big">{quests_done}/{quests_total}</div></div>
    <div><div class="sl-label">Study streak</div><div class="sl-big">{snap.study_streak}d</div></div>
  </div>
</div>""")


def _quick_entry(ctx: AppContext) -> None:
    today = ctx.today()
    with st.expander("⚡ Quick entry", expanded=False):
        t1, t2, t3, t4 = st.tabs(["Deep focus", "Habits", "Finance / Research", "More"])
        with t1, st.form("qe_attention", clear_on_submit=True):
            minutes = st.number_input("Longest continuous deep-focus session (minutes)", 1, 1440, 25)
            if st.form_submit_button("Log session", type="primary"):
                action(ctx, lambda s: attention_service.add_session(s, today, int(minutes), None, today=today),
                       success=f"Deep-focus session of {int(minutes)} min logged", days=[today])
        with t2:
            with ctx.session() as s:
                habits = [(h.id, h.name, h.kind, h.unit, h.target_value) for h in habit_service.list_habits(s)]
                entries = habit_service.entries_between(s, today, today)
                values = {hid: entries[(hid, today)].value for hid, *_ in habits if (hid, today) in entries}
            with st.form("qe_habits"):
                inputs = {}
                cols = st.columns(2)
                for i, (hid, name, kind, unit, target) in enumerate(habits):
                    with cols[i % 2]:
                        if kind == "check":
                            inputs[hid] = st.checkbox(name, value=values.get(hid, 0) >= 1, key=f"qe_h_{hid}")
                        else:
                            inputs[hid] = st.number_input(f"{name} ({unit or ''}, target {target:g})", 0.0, 10000.0,
                                                          float(values.get(hid, 0.0)), step=0.5 if unit == "litres" else 5.0,
                                                          key=f"qe_h_{hid}")
                st.caption("Saving logs every habit for today (unchecked = explicitly not done).")
                if st.form_submit_button("Save today's habits", type="primary"):
                    def save(s):  # noqa: ANN001
                        for hid, val in inputs.items():
                            habit_service.upsert_entry(s, hid, today, float(val), None, today=today)
                    action(ctx, save, success="Habits saved", days=[today])
        with t3, st.form("qe_work", clear_on_submit=True):
            domain = st.radio("Domain", ["finance", "research"], horizontal=True, format_func=str.title)
            dur = st.number_input("Duration (minutes)", 1, 1440, 60, step=5)
            what = st.text_area("What was done", max_chars=3000, height=90)
            nxt = st.text_input("Next steps (optional)", max_chars=1000)
            if st.form_submit_button("Save work log", type="primary"):
                action(ctx, lambda s: worklog_service.add_log(
                    s, WorkLogInput(domain, today, int(dur), what, next_steps=nxt), today=today),
                    success=f"{domain.title()} log saved", days=[today])
        with t4:
            c1, c2, c3 = st.columns(3)
            with c1:
                nav.link("daily_log", "Log GATE study", icon="📘")
                nav.link("revisions", "Revision queue", icon="🔁")
            with c2:
                nav.link("not_todo", "Not-to-do check-in", icon="🚫")
                nav.link("adapt", "Write reflection", icon="🪞")
            with c3:
                nav.link("war", "Weekend Full War", icon="⚔️")
                nav.link("analytics", "Execution analytics", icon="📈")


def render() -> None:
    ctx = get_ctx()
    today = ctx.today()
    tz = ctx.tz
    with ctx.session() as s:
        snap = gamification_service.status(s, today)
        quests = gamification_service.daily_quests(s, today, tz)
        rows = progress_service.topic_rows(s, "DA")
        due = revision_service.due_today(s, today)
        over = revision_service.overdue(s, today)
        due_view = [(e.stage, e.topic.code, e.topic.name, e.due_date) for e in [*over, *due]][:8]
        att = attention_service.summary(s)
        metrics = analytics_service.daily_metrics(
            s, max(settings_service.tracking_start(s, today), today - timedelta(days=13)), today)
        fin = worklog_service.summary(s, "finance", today - timedelta(days=6), today)
        res = worklog_service.summary(s, "research", today - timedelta(days=6), today)
        fin_today = worklog_service.daily_minutes(s, "finance", today, today).get(today, 0)
        res_today = worklog_service.daily_minutes(s, "research", today, today).get(today, 0)
        habit_today = habit_service.daily_summary(s, today, today)[0]
        avoid_today = avoidance_service.daily_compliance(s, today, today)[0]
        hide_private = bool(settings_service.get_setting(s, "privacy_hide_not_todo"))
    applicable = [q for q in quests if q.applicable]
    done = sum(1 for q in applicable if q.done)
    _hero(snap, done, len(applicable))

    mastered = sum(1 for r in rows if r.coverage_status == "mastered")
    started = sum(1 for r in rows if r.coverage_status != "not_started")
    eligible = sum(1 for r in rows if r.war_eligible)
    today_m = metrics[-1] if metrics else None
    cols = st.columns(4)
    tiles = [
        stat("GATE readiness", f"{100 * mastered / len(rows):.0f}%", f"{mastered}/{len(rows)} DA topics mastered · "
             f"{started} started · {eligible} war-eligible"),
        stat("Revisions", f"{len(due)} today", f"{len(over)} overdue"),
        stat("Attention span", f"{att.latest_longest or 0} min" if att.latest_longest else "Not logged",
             f"best {att.personal_best or 0} · target {att.target} min"),
        stat("Today's execution", f"{today_m.overall_pct:.0f}%" if today_m and today_m.overall_pct is not None else "—",
             f"{today_m.missing_items} item(s) not logged yet" if today_m else ""),
    ]
    for col, tile in zip(cols, tiles, strict=True):
        with col:
            html(tile)
    cols = st.columns(4)
    tiles = [
        stat("Habits today", f"{habit_today.done}/{habit_today.applicable}", f"{habit_today.missing} not logged"),
        stat("Not-to-do", f"{avoid_today.complied + avoid_today.violated}/{avoid_today.applicable} logged"
             if hide_private else f"{avoid_today.complied}/{avoid_today.applicable} clean",
             "details hidden (privacy)" if hide_private else f"{avoid_today.violated} violation(s)"),
        stat("Finance", f"{fin_today} min today", f"target met {fin.days_met}/7 days"),
        stat("Research", f"{res_today} min today", f"target met {res.days_met}/7 days"),
    ]
    for col, tile in zip(cols, tiles, strict=True):
        with col:
            html(tile)
    st.write("")
    _quick_entry(ctx)

    left, right = st.columns([1.05, 1])
    with left, st.container(border=True):
        st.markdown("##### Today's quests")
        html(quest_list(quests))
    with right, st.container(border=True):
        st.markdown("##### To revise today")
        if not due_view:
            st.caption("No revisions due. Study a topic to schedule its R1–R4 cycle.")
        for stage, code, name, due_date in due_view:
            tag = "overdue" if due_date < today else "today"
            html(f'<div class="sl-quest"><div class="sl-q-icon">R{stage}</div><div class="sl-q-body">'
                 f'<div class="sl-q-title">{escape(name)}</div><div class="sl-q-detail">{escape(code)} · '
                 f'{"⚠ overdue since " + due_date.strftime("%d %b") if tag == "overdue" else "due today"}</div>'
                 f'</div></div>')
        nav.link("revisions", "Open revision queue", icon="🔁")

    left, right = st.columns([1.3, 1])
    with left, st.container(border=True):
        st.markdown("##### Execution trend (last 14 days)")
        if metrics:
            st.plotly_chart(charts.line_chart(
                [m.day for m in metrics],
                [("Daily execution", [m.overall_pct for m in metrics]), ("Study targets", [m.study_pct for m in metrics])],
                percent=True, y_range=(0, 105), height=280,
                missing_x=[m.day for m in metrics if m.missing_items], missing_y=0),
                config=charts.CONFIG)
            st.caption("✕ marks days with at least one unlogged item (unlogged items are never counted as done).")
    with right, st.container(border=True):
        st.markdown("##### GATE DA readiness by section")
        summaries = progress_service.subject_summaries(rows)
        html(coverage_legend() + "".join(coverage_bar(su.subject_name, su.coverage["mastered"],
                                                      su.coverage["in_progress"], su.total) for su in summaries))
        nav.link("syllabus", "Open syllabus tracker", icon="📚")
