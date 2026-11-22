from __future__ import annotations

from datetime import timedelta
from html import escape

import pandas as pd
import streamlit as st

from shogun.services import gamification_service as g
from shogun.ui import charts
from shogun.ui.components import html, page_header, progress_bar, quest_list, stat_row
from shogun.ui.context import get_ctx


def render() -> None:
    ctx = get_ctx()
    today = ctx.today()
    tz = ctx.tz
    page_header("XP · Rank · Badges", "Fixed, transparent rules. XP is derived from your real logs — remove a log "
                "and its XP disappears. Gamification never changes academic data.", kicker="Player profile")
    with ctx.session() as s:
        snap = g.status(s, today)
        quests = g.daily_quests(s, today, tz)
        xp_days = g.xp_by_day(s, today - timedelta(days=29), today)
        recent = [(e.event_date, e.rule, e.amount, e.description) for e in g.recent_events(s, 40)]
        badges = [(a.icon, a.name, a.description, ua.unlocked_on if ua else None) for a, ua in g.achievements_view(s)]
    lv = snap.level
    stat_row([
        ("Level", str(lv.level), f"{lv.total_xp:,} XP total"),
        ("Rank", lv.rank, "hunter rank"),
        ("Study streak", f"{snap.study_streak} d", "consecutive study days"),
        ("All-clear streak", f"{snap.clear_streak} d", "every quest completed"),
    ])
    html(progress_bar(lv.progress_pct, f"Level {lv.level} → {lv.level + 1}", f"{lv.into_level}/{lv.span} XP"))

    col_l, col_r = st.columns([1, 1])
    with col_l, st.container(border=True):
        st.markdown("##### Today's quests")
        html(quest_list(quests))
        st.caption("All applicable quests complete → +30 XP daily-clear bonus.")
    with col_r, st.container(border=True):
        st.markdown("##### XP earned (last 30 days)")
        days = [today - timedelta(days=i) for i in range(29, -1, -1)]
        st.plotly_chart(charts.bar_chart([d.strftime("%d %b") for d in days], [xp_days.get(d, 0) for d in days],
                                         y_title="XP", height=250, hover_suffix=" XP"), config=charts.CONFIG)

    st.markdown("##### Achievement badges")
    cols = st.columns(3)
    for i, (icon, name, desc, unlocked) in enumerate(badges):
        with cols[i % 3]:
            style = "" if unlocked else "opacity:.45;filter:grayscale(1)"
            state = f"Unlocked {unlocked:%d %b %Y}" if unlocked else "Locked"
            html(f'<div class="sl-card {"sl-glow" if unlocked else ""}" style="{style}">'
                 f'<div class="sl-kicker">{escape(state)}</div><h4>{escape(icon)} {escape(name)}</h4>'
                 f'<div class="sl-sub">{escape(desc)}</div></div>')

    t1, t2, t3 = st.tabs(["XP rules", "Rank ladder", "Recent XP events"])
    with t1:
        st.dataframe(pd.DataFrame([{"Rule": k, "XP": v[0], "Definition": v[1]} for k, v in g.XP_RULES.items()]),
                     hide_index=True, width="stretch")
        st.caption("No XP for not-to-do entries (private). Every XP event has a unique source key, so nothing is "
                   "ever counted twice. Level n → n+1 needs 100 + 25·(n−1) XP.")
    with t2:
        st.dataframe(pd.DataFrame([{"Rank": name, "From level": lvl, "Total XP needed": g.xp_threshold(lvl)}
                                   for lvl, name in g.RANKS]), hide_index=True, width="stretch")
    with t3:
        if recent:
            st.dataframe(pd.DataFrame(recent, columns=["Date", "Rule", "XP", "Reason"]), hide_index=True,
                         width="stretch")
        else:
            st.caption("No XP yet — log study, revisions, habits, work or a reflection.")
