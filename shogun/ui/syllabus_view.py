"""Shared syllabus tracker view (DA and GA)."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from shogun.services import progress_service, settings_service
from shogun.services.progress_service import STATUS_LABEL, TopicRow
from shogun.ui.components import coverage_bar, coverage_legend, html, stat_row
from shogun.ui.context import AppContext, action

STATUS_ICON = {"not_started": "○", "in_progress": "◐", "mastered": "●"}


def rev_cell(row: TopicRow, stage: int, today: date) -> str:
    cell = row.revisions.get(stage)
    if cell is None:
        return "—"
    if cell.status == "completed" and cell.completed_on:
        return f"✓ {cell.completed_on:%d %b}"
    if cell.due_date < today:
        return f"⚠ overdue {cell.due_date:%d %b}"
    if cell.due_date == today:
        return "▶ due today"
    return f"· {cell.due_date:%d %b}"


def rows_to_frame(rows: list[TopicRow], today: date, compact: bool) -> pd.DataFrame:
    records = []
    for r in rows:
        rec = {
            "Code": r.code,
            "Topic": r.name,
            "Coverage": f"{STATUS_ICON[r.coverage_status]} {STATUS_LABEL[r.coverage_status]}",
            "PYQ": f"{r.pyq_correct}/{r.pyq_target}",
            "Status": f"{STATUS_ICON[r.overall_status]} {STATUS_LABEL[r.overall_status]}"
                      + (" (override)" if r.status_override else ""),
        }
        if not compact:
            rec.update({
                "Group": r.group_label or "",
                "PYQ mastery": STATUS_LABEL[r.pyq_status] + (" (override)" if r.pyq_override is not None else ""),
                "Attempts": r.pyq_attempted,
                "Accuracy": f"{r.pyq_accuracy:.0f}%" if r.pyq_accuracy is not None else "—",
                "R1 (+1d)": rev_cell(r, 1, today), "R2 (+3d)": rev_cell(r, 2, today),
                "R3 (+7d)": rev_cell(r, 3, today), "R4 (+21d)": rev_cell(r, 4, today),
                "Minutes": r.total_minutes,
                "Last studied": r.last_studied_on.isoformat() if r.last_studied_on else "—",
                "War eligible": "Yes" if r.war_eligible else "No",
                "Notes": (r.notes or "")[:80],
                "Updated (UTC)": r.updated_at.strftime("%Y-%m-%d %H:%M") if r.updated_at else "",
            })
        records.append(rec)
    return pd.DataFrame.from_records(records)


def render_tracker(ctx: AppContext, paper: str, key: str) -> None:
    today = ctx.today()
    with ctx.session() as s:
        rows = progress_service.topic_rows(s, paper)
        rule = settings_service.get_setting(s, "war_eligibility_rule")
    summaries = progress_service.subject_summaries(rows)
    total = len(rows)
    mastered = sum(1 for r in rows if r.coverage_status == "mastered")
    started = sum(1 for r in rows if r.coverage_status != "not_started")
    pyq_m = sum(1 for r in rows if r.pyq_status == "mastered")
    eligible = sum(1 for r in rows if r.war_eligible)
    stat_row([
        ("Topics", str(total), f"{len(summaries)} official sections"),
        ("Coverage mastered", f"{mastered}", f"{100 * mastered / total:.1f}% · {started} started" if total else ""),
        ("PYQ mastery", f"{pyq_m}", "topics at PYQ target"),
        ("War-eligible", f"{eligible}", settings_service.WAR_RULES.get(str(rule), str(rule))),
    ])

    with st.container(border=True):
        st.markdown("##### Section progress")
        html(coverage_legend() + "".join(
            coverage_bar(f"{s.subject_name}", s.coverage["mastered"], s.coverage["in_progress"], s.total,
                         f" · PYQ {s.pyq_correct}/{s.pyq_attempted}")
            for s in summaries))

    st.markdown("##### Topics")
    f1, f2, f3, f4 = st.columns([2, 2, 2, 1.3])
    subjects = [s.subject_name for s in summaries]
    with f1:
        chosen = st.multiselect("Section", subjects, key=f"{key}_subj", placeholder="All sections")
    with f2:
        status_filter = st.multiselect("Coverage", list(STATUS_LABEL), format_func=STATUS_LABEL.get,
                                       key=f"{key}_status", placeholder="Any coverage")
    with f3:
        query = st.text_input("Search topics", key=f"{key}_q", placeholder="e.g. eigen, SQL, Bayes")
    with f4:
        compact = st.toggle("Compact", value=False, key=f"{key}_compact",
                            help="Fewer columns — best on phones")
    filtered = [
        r for r in rows
        if (not chosen or r.subject_name in chosen)
        and (not status_filter or r.coverage_status in status_filter)
        and (not query or query.lower() in (r.name + " " + r.code + " " + (r.group_label or "")).lower())
    ]
    st.caption(f"Showing {len(filtered)} of {total} official topics. Revision cells: ✓ done · ▶ due today · "
               "⚠ overdue · · upcoming · — not scheduled.")
    by_subject: dict[str, list[TopicRow]] = {}
    for r in filtered:
        by_subject.setdefault(r.subject_name, []).append(r)
    for summ in summaries:
        items = by_subject.get(summ.subject_name)
        if not items:
            continue
        with st.expander(f"{summ.subject_code.split('.')[-1]}. {summ.subject_name} — "
                         f"{summ.coverage['mastered']}/{summ.total} mastered", expanded=len(by_subject) == 1):
            st.dataframe(rows_to_frame(items, today, compact), hide_index=True, width="stretch",
                         height=min(38 * len(items) + 40, 520))

    render_topic_editor(ctx, rows, key)


def render_topic_editor(ctx: AppContext, rows: list[TopicRow], key: str) -> None:
    st.markdown("##### Topic detail, notes & manual override")
    labels = {r.topic_id: f"{r.code} · {r.name}" for r in rows}
    tid = st.selectbox("Topic", list(labels), format_func=labels.get, key=f"{key}_edit_topic", index=None,
                       placeholder="Choose a topic to inspect or edit")
    if tid is None:
        return
    row = next(r for r in rows if r.topic_id == tid)
    today = ctx.today()
    c1, c2 = st.columns([1.2, 1])
    with c1, st.container(border=True):
        st.markdown(f"**{row.name}** · `{row.code}`")
        st.caption(f"Official phrase: “{row.source_phrase}”" + (f" · group: {row.group_label}" if row.group_label else ""))
        st.markdown(
            f"- Coverage: **{STATUS_LABEL[row.coverage_status]}**"
            + (f" (since {row.coverage_mastered_on})" if row.coverage_mastered_on else "")
            + f"\n- PYQ: **{row.pyq_correct} correct / {row.pyq_attempted} attempted** (target {row.pyq_target}"
            + (", custom" if row.pyq_target_is_custom else "") + f") → {STATUS_LABEL[row.pyq_status]}"
            + f"\n  - from daily logs: {row.pyq_logged_attempted} attempted · in-app on verified PYQs: "
              f"{row.pyq_inapp_attempted}"
            + f"\n- Overall: **{STATUS_LABEL[row.overall_status]}**"
            + (" (manual override)" if row.status_override else "")
            + "\n- Revisions: " + " · ".join(f"R{i}: {rev_cell(row, i, today)}" for i in range(1, 5))
            + f"\n- Study time: {row.total_minutes} min · first {row.first_studied_on or '—'} · last "
              f"{row.last_studied_on or '—'}"
        )
        with st.form(f"{key}_notes_{tid}"):
            notes = st.text_area("Notes", value=row.notes or "", height=120, max_chars=5000)
            if st.form_submit_button("Save notes"):
                action(ctx, lambda s: progress_service.set_notes(s, tid, notes), success="Notes saved")
    with c2, st.container(border=True):
        st.markdown("**Manual override** — requires a reason; every change is recorded in the audit trail.")
        with st.form(f"{key}_override_{tid}"):
            what = st.selectbox("Field", ["Knowledge coverage", "PYQ mastery", "Overall status", "PYQ target"])
            cov = st.selectbox("New coverage / status", list(STATUS_LABEL), format_func=STATUS_LABEL.get)
            pyq_choice = st.selectbox("PYQ mastery override", ["Clear override (use counts)", "Force mastered",
                                                               "Force not mastered"])
            target = st.number_input("PYQ target (0 = use default)", 0, 500, value=row.pyq_target
                                     if row.pyq_target_is_custom else 0)
            reason = st.text_input("Reason (required)", max_chars=300)
            if st.form_submit_button("Apply override", type="primary"):
                def do(s, what=what, cov=cov, pyq_choice=pyq_choice, target=target, reason=reason):  # noqa: ANN001
                    if what == "Knowledge coverage":
                        progress_service.override_coverage(s, tid, cov, reason, today)
                    elif what == "Overall status":
                        progress_service.override_status(s, tid, cov, reason, today)
                    elif what == "PYQ mastery":
                        value = {"Force mastered": True, "Force not mastered": False}.get(pyq_choice)
                        progress_service.override_pyq_mastery(s, tid, value, reason, today)
                    else:
                        progress_service.set_pyq_target(s, tid, int(target) or None, reason, today)
                action(ctx, do, success=f"{what} updated for {row.name}", days=[today])
            st.caption("To remove an overall-status override, choose “Overall status” and use the "
                       "Clear button below.")
        if row.status_override and st.button("Clear overall-status override", key=f"{key}_clear_{tid}"):
            action(ctx, lambda s: progress_service.override_status(s, tid, None, "Override cleared", today),
                   success="Override cleared", days=[today])
    with st.expander("Audit trail"):
        with ctx.session() as s:
            trail = [(a.created_at, a.effective_date, a.field, a.old_value, a.new_value, a.source, a.reason)
                     for a in progress_service.audit_log(s, tid)]
        if trail:
            st.dataframe(pd.DataFrame(trail, columns=["Recorded (UTC)", "Effective date", "Field", "Old", "New",
                                                      "Source", "Reason"]), hide_index=True, width="stretch")
        else:
            st.caption("No changes recorded yet.")
