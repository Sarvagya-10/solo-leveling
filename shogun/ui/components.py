"""Reusable presentational components. All user text is HTML-escaped."""

from __future__ import annotations

from collections.abc import Iterable
from html import escape

import streamlit as st

from shogun.services.gamification_service import Quest, StatusSnapshot

STATUS_BADGE = {"not_started": ("Not started", "muted"), "in_progress": ("In progress", "blue"),
                "mastered": ("Mastered", "violet")}


def html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def page_header(title: str, subtitle: str | None = None, kicker: str | None = None) -> None:
    k = f'<div class="sl-kicker">{escape(kicker)}</div>' if kicker else ""
    s = f'<p class="sl-sub" style="color:var(--text-secondary);margin:.1rem 0 1rem">{escape(subtitle)}</p>' if subtitle else ""
    html(f'{k}<h1 style="margin:0">{escape(title)}</h1>{s}')


def status_bar(title: str, snap: StatusSnapshot, today_label: str) -> None:
    lv = snap.level
    html(f"""
<div class="sl-statusbar" role="status" aria-label="Player status">
  <div class="sl-title"><small>THE SYSTEM</small>{escape(title)}</div>
  <span class="sl-rank" title="Hunter rank" aria-label="Rank {escape(lv.rank)}">{escape(lv.rank if len(lv.rank) <= 2 else 'NL')}</span>
  <span class="sl-chip">Level <b>{lv.level}</b></span>
  <div class="sl-xpbar" aria-label="Experience {lv.into_level} of {lv.span}">
    <div class="sl-xpbar-label"><span>XP {lv.total_xp:,}</span><span>{lv.into_level}/{lv.span} to Lv {lv.level + 1}</span></div>
    <div class="sl-track"><div class="sl-fill" style="width:{lv.progress_pct}%"></div></div>
  </div>
  <span class="sl-chip">🔥 Streak <b>{snap.study_streak}</b>d</span>
  <span class="sl-chip">+<b>{snap.today_xp}</b> XP today</span>
  <span class="sl-chip">{escape(today_label)}</span>
</div>""")


def stat(label: str, value: str, sub: str | None = None) -> str:
    sub_html = f'<div class="sl-stat-sub">{escape(sub)}</div>' if sub else ""
    return (f'<div class="sl-stat"><div class="sl-stat-label">{escape(label)}</div>'
            f'<div class="sl-stat-value">{escape(value)}</div>{sub_html}</div>')


def stat_row(items: list[tuple[str, str, str | None]], columns: int = 4) -> None:
    """A responsive row of stat tiles (columns stack on phones)."""
    for start in range(0, len(items), columns):
        cols = st.columns(columns)
        for col, item in zip(cols, items[start : start + columns], strict=False):
            with col:
                html(stat(*item))


def badge(text: str, kind: str = "") -> str:
    return f'<span class="sl-badge {escape(kind)}">{escape(text)}</span>'


def status_badge(status: str) -> str:
    label, kind = STATUS_BADGE.get(status, (status, ""))
    return badge(label, kind)


def card(title: str, body_html: str, *, kicker: str | None = None, glow: str = "") -> None:
    k = f'<div class="sl-kicker">{escape(kicker)}</div>' if kicker else ""
    cls = {"violet": "sl-glow", "blue": "sl-glow-blue"}.get(glow, "")
    html(f'<div class="sl-card {cls}">{k}<h4>{escape(title)}</h4>{body_html}</div>')


def empty_state(title: str, body: str) -> None:
    html(f'<div class="sl-empty"><div class="sl-empty-title">{escape(title)}</div><div>{escape(body)}</div></div>')


def quest_list(quests: Iterable[Quest]) -> str:
    rows = []
    for q in quests:
        cls = "done" if q.done else ("na" if not q.applicable else "")
        icon = "✓" if q.done else ("–" if not q.applicable else "◇")
        detail = q.detail if q.applicable else f"{q.detail} · not applicable today"
        state = "completed" if q.done else ("not applicable" if not q.applicable else "pending")
        rows.append(
            f'<div class="sl-quest {cls}" aria-label="{escape(q.title)}: {state}"><div class="sl-q-icon">{icon}</div>'
            f'<div class="sl-q-body"><div class="sl-q-title">{escape(q.title)}</div>'
            f'<div class="sl-q-detail">{escape(detail)}</div>'
            f'<div class="sl-track" style="height:4px;margin-top:.3rem"><div class="sl-fill" '
            f'style="width:{int(q.progress * 100)}%"></div></div></div></div>'
        )
    return "".join(rows)


SEG_COLORS = {"mastered": "#9085e9", "in_progress": "#5a50b8"}


def coverage_bar(label: str, mastered: int, in_progress: int, total: int, extra: str = "") -> str:
    m = 100.0 * mastered / total if total else 0
    p = 100.0 * in_progress / total if total else 0
    return (
        f'<div class="sl-progress-row"><div class="sl-pr-head"><span><b>{escape(label)}</b></span>'
        f'<span>{mastered}/{total} mastered · {in_progress} in progress{escape(extra)}</span></div>'
        f'<div class="sl-seg" role="img" aria-label="{escape(label)}: {mastered} of {total} mastered, '
        f'{in_progress} in progress">'
        f'<span style="width:{m:.2f}%;background:{SEG_COLORS["mastered"]}"></span>'
        f'<span style="width:{p:.2f}%;background:{SEG_COLORS["in_progress"]}"></span></div></div>'
    )


def coverage_legend() -> str:
    return (f'<div class="sl-legend"><span><i style="background:{SEG_COLORS["mastered"]}"></i>Mastered</span>'
            f'<span><i style="background:{SEG_COLORS["in_progress"]}"></i>In progress</span>'
            f'<span><i style="background:#232233;border:1px solid #2a2840"></i>Not started</span></div>')


def progress_bar(pct: float, label: str, right: str = "") -> str:
    pct = max(0.0, min(100.0, pct))
    return (f'<div class="sl-progress-row"><div class="sl-pr-head"><span><b>{escape(label)}</b></span>'
            f'<span>{escape(right)}</span></div><div class="sl-track" role="progressbar" aria-valuenow="{pct:.0f}" '
            f'aria-valuemin="0" aria-valuemax="100" aria-label="{escape(label)}"><div class="sl-fill" '
            f'style="width:{pct:.1f}%"></div></div></div>')


def level_up_overlay(level: int, rank: str) -> None:
    html(f'<div class="sl-levelup" aria-live="polite"><div class="sl-lu-box"><div class="sl-lu-kicker">'
         f'SYSTEM MESSAGE</div><div class="sl-lu-title">LEVEL UP</div><div class="sl-lu-sub">You reached '
         f'level {level} · Rank {escape(rank)}</div></div></div>')


def flash(message: str, kind: str = "success") -> None:
    st.session_state.setdefault("_flash", []).append((kind, message))


def quest_clear_overlay() -> None:
    html('<div class="sl-levelup" aria-live="polite"><div class="sl-lu-box"><div class="sl-lu-kicker">'
         'SYSTEM MESSAGE</div><div class="sl-lu-title">QUESTS CLEARED</div><div class="sl-lu-sub">'
         'Every daily quest is complete · +30 XP</div></div></div>')


def show_flash() -> None:
    if st.session_state.pop("_quest_clear_fx", False):
        quest_clear_overlay()
    for kind, message in st.session_state.pop("_flash", []):
        icon = {"success": "✅", "info": "ℹ️", "warning": "⚠️", "badge": "🏅", "error": "❌",
                "quest": "⚔️"}.get(kind, "ℹ️")
        st.toast(message, icon=icon)
        if kind in ("warning", "error"):
            (st.warning if kind == "warning" else st.error)(message)
