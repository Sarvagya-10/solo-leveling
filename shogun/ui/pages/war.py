"""Weekend Full War — timed GATE DA paper simulator UI.

All exam state (responses, marks for review, position, timer start) lives in
the database and is autosaved on every change, so a refresh or restart never
loses progress. The timer is computed from the stored start time.
"""

from __future__ import annotations

import json
import time
from datetime import datetime

import pandas as pd
import streamlit as st

from shogun.ai import workflows
from shogun.services import exam_service, settings_service
from shogun.services.exam_service import TIER_LABEL
from shogun.services.progress_service import STATUS_LABEL
from shogun.services.scoring import OPTION_KEYS, normalize_msq
from shogun.timeutil import local_date_of, utcnow
from shogun.ui import charts
from shogun.ui.components import badge, empty_state, html, page_header, stat_row
from shogun.ui.context import AppContext, action, get_ctx
from shogun.ui.question_view import answer_text, provenance_badges

PALETTE_ICON = {"not_visited": "⬜", "not_answered": "🟥", "answered": "🟩", "marked": "🟪", "answered_marked": "💜"}


# --------------------------------------------------------------------------- setup
def _setup(ctx: AppContext) -> None:
    today = ctx.today()
    with ctx.session() as s:
        report = exam_service.eligibility(s)
        include_unreviewed_default = bool(settings_service.get_setting(s, "war_include_unreviewed_ai"))
    st.markdown("#### 1 · Eligible topics (only these can appear)")
    rule_text = settings_service.WAR_RULES.get(report.rule, report.rule)
    st.caption(f"Eligibility rule: **{rule_text}** (change in Settings). Every question must have ALL its tagged "
               "topics eligible — the filter applies to verified PYQs, your questions and AI questions alike.")
    da_el, ga_el = report.eligible("DA"), report.eligible("GA")
    stat_row([
        ("DA eligible", f"{len(da_el)}/{report.total('DA')}", "topics"),
        ("GA eligible", f"{len(ga_el)}/{report.total('GA')}", "topics"),
    ], columns=2)
    with st.expander(f"View eligible topics ({len(da_el) + len(ga_el)})"):
        if not da_el and not ga_el:
            st.caption("No topics are eligible yet. Mark topics' knowledge coverage as mastered via the Daily Log.")
        for paper_rows, label in ((da_el, "DA"), (ga_el, "GA")):
            if paper_rows:
                st.dataframe(pd.DataFrame([{
                    "Paper": label, "Code": r.code, "Topic": r.name, "Section": r.subject_name,
                    "Coverage": STATUS_LABEL[r.coverage_status], "PYQ": f"{r.pyq_correct}/{r.pyq_target}",
                } for r in paper_rows]), hide_index=True, width="stretch")

    st.markdown("#### 2 · Question sources")
    c1, c2, c3 = st.columns(3)
    include_ai = c1.toggle("Include AI-generated questions", value=False, key="war_ai",
                           help="Clearly labelled in the paper and analysis. Only for eligible topics.")
    include_unrev = c2.toggle("…including unreviewed AI questions", value=include_unreviewed_default,
                              key="war_ai_unrev", disabled=not include_ai)
    seed = int(c3.number_input("Paper seed", 1, 10_000_000, value=today.toordinal() % 1_000_000,
                               help="Same seed + same bank = same paper (deterministic)."))
    with ctx.session() as s:
        plan = exam_service.plan_paper(s, seed=seed, include_ai=include_ai,
                                       include_unreviewed_ai=include_unrev and include_ai,
                                       eligible_topic_ids=report.eligible_ids)
    st.dataframe(pd.DataFrame([{
        "Section": "General Aptitude" if sp.slot.section == "GA" else "Data Science & AI",
        "Marks each": sp.slot.marks, "Required (official)": sp.slot.count, "Available": sp.available,
        "Selected": len(sp.selected), "Shortfall": sp.shortfall,
    } for sp in plan.slots]), hide_index=True, width="stretch")
    st.caption("Official GATE DA 2027 structure: 65 questions · 100 marks · 180 minutes. GA 10 Q (5×1 + 5×2 = 15 "
               "marks), DA 55 Q (25×1 + 30×2 = 85 marks). Wrong MCQ: −1/3 (1-mark), −2/3 (2-mark). MSQ & NAT: no "
               f"negative marking, no partial credit. Source priority: {', '.join(TIER_LABEL.values())}.")

    st.markdown("#### 3 · Start")
    if plan.is_full:
        st.success("The bank can fill a complete official paper from your eligible topics.")
        if st.button("⚔️ Begin full 180-minute paper", type="primary", key="war_start_full"):
            action(ctx, lambda s: exam_service.create_exam(s, exam_service.plan_paper(
                s, seed=seed, include_ai=include_ai, include_unreviewed_ai=include_unrev and include_ai),
                allow_short=False), success="Paper started — good hunting.")
    else:
        if not plan.question_ids:
            st.error("No eligible questions are available, so no paper can be generated. Add & verify PYQs for "
                     "your mastered topics, or generate labelled AI practice for them below.")
        else:
            st.warning(f"Insufficient question bank: short by **{plan.shortfall}** of 65 questions. A full paper "
                       "cannot be built without inventing questions — which this System never does.")
            ok = st.checkbox(f"Start a SHORTER paper instead: {len(plan.question_ids)} questions · {plan.max_marks} "
                             f"marks · {plan.duration_minutes} minutes (time scaled to marks)", key="war_short_ok")
            if st.button("Begin shorter paper", disabled=not ok, key="war_start_short"):
                action(ctx, lambda s: exam_service.create_exam(s, exam_service.plan_paper(
                    s, seed=seed, include_ai=include_ai, include_unreviewed_ai=include_unrev and include_ai),
                    allow_short=True), success="Shorter paper started.")
    _ai_fill(ctx, report)


def _ai_fill(ctx: AppContext, report: exam_service.EligibilityReport) -> None:
    eligible = [r for r in report.rows if r.war_eligible]
    with st.expander("Fill gaps with clearly-labelled AI practice questions (eligible topics only)"):
        if not eligible:
            st.caption("No eligible topics yet.")
            return
        labels = {r.topic_id: f"{r.code} · {r.name}" for r in eligible}
        with st.form("war_ai_gen"):
            tid = st.selectbox("Eligible topic", list(labels), format_func=labels.get)
            c1, c2, c3 = st.columns(3)
            count = c1.number_input("Questions", 1, 10, 5)
            marks = c2.selectbox("Marks", [1, 2])
            qtype = c3.selectbox("Type", ["Any", "MCQ", "MSQ", "NAT"])
            if st.form_submit_button("Generate with AI"):
                action(ctx, lambda s: workflows.generate_practice_questions(
                    s, ctx.config, tid, count=int(count), marks=int(marks), qtype=None if qtype == "Any" else qtype),
                    success=lambda r: f"{len(r[0])} AI question(s) added (unverified, labelled). Enable AI questions "
                                      "above to use them.")


# --------------------------------------------------------------------------- exam room
def _state(ans: dict) -> str:  # noqa: ANN001
    answered = bool(ans["response"])
    if ans["marked"]:
        return "answered_marked" if answered else "marked"
    if answered:
        return "answered"
    return "not_answered" if ans["visited"] else "not_visited"


def _load_exam(ctx: AppContext, exam_id: int) -> dict:
    with ctx.session() as s:
        exam = exam_service.get_exam(s, exam_id)
        qs = []
        for meq in exam.questions:
            snap = json.loads(meq.snapshot_json)
            a = meq.answer
            qs.append({"pos": meq.position, "section": meq.section, "marks": meq.marks, "qtype": meq.qtype,
                       "source_type": meq.source_type, "snap": snap,
                       "response": a.response if a else None, "marked": a.marked_for_review if a else False,
                       "visited": a.visited if a else False})
        return {"id": exam.id, "title": exam.title, "mode": exam.mode, "started_at": exam.started_at,
                "duration": exam.duration_minutes, "max_marks": exam.max_marks, "position": exam.current_position,
                "deadline": exam_service.deadline(exam), "questions": qs, "status": exam.status}


def _elapsed_for(exam_id: int, pos: int) -> int:
    key = f"war_enter_{exam_id}"
    prev = st.session_state.get(key)
    now = time.time()
    st.session_state[key] = (pos, now)
    if prev and prev[0] == pos:
        return 0
    return int(now - prev[1]) if prev else 0


def _wkey(exam_id: int, pos: int) -> str:
    """Widget-key prefix; the nonce changes whenever responses are changed programmatically."""
    nonce = st.session_state.get(f"war_nonce_{exam_id}_{pos}", 0)
    return f"war_{exam_id}_{pos}_{nonce}"


def _bump(exam_id: int, pos: int) -> None:
    key = f"war_nonce_{exam_id}_{pos}"
    st.session_state[key] = st.session_state.get(key, 0) + 1


def _current_response(exam_id: int, pos: int, qtype: str) -> str | None:
    k = _wkey(exam_id, pos)
    if qtype == "MSQ":
        return ",".join(o for o in OPTION_KEYS if st.session_state.get(f"{k}_msq_{o}")) or None
    value = st.session_state.get(f"{k}_resp")
    return str(value) if value not in (None, "") else None


def _persist(ctx: AppContext, exam_id: int, pos: int, response: str | None, marked: bool) -> None:
    try:
        with ctx.session() as s:
            exam_service.save_answer(s, exam_id, pos, response=response, marked_for_review=marked, tz=ctx.tz)
        st.session_state["war_saved_at"] = time.strftime("%H:%M:%S")
    except Exception as exc:  # surfaced on the next render
        st.session_state["war_save_error"] = str(exc)


def _autosave(ctx: AppContext, exam_id: int, pos: int, qtype: str) -> None:
    """Widget on_change callback: persist the response immediately."""
    marked = bool(st.session_state.get(f"{_wkey(exam_id, pos)}_mark", False))
    _persist(ctx, exam_id, pos, _current_response(exam_id, pos, qtype), marked)


def _goto(ctx: AppContext, exam_id: int, current: int, target: int) -> None:
    elapsed = int(time.time() - st.session_state.get(f"war_enter_{exam_id}", (current, time.time()))[1])
    with ctx.session() as s:
        exam_service.mark_visited(s, exam_id, current, elapsed_sec=elapsed)
        exam_service.mark_visited(s, exam_id, target, elapsed_sec=0)
    st.session_state[f"war_enter_{exam_id}"] = (target, time.time())
    st.session_state[f"war_pos_{exam_id}"] = target


@st.fragment(run_every=1)
def _timer(ctx: AppContext, exam_id: int, deadline_iso: str) -> None:
    remaining = max(0, int((datetime.fromisoformat(deadline_iso) - utcnow()).total_seconds()))
    h, rem = divmod(remaining, 3600)
    m, sec = divmod(rem, 60)
    color = "var(--critical)" if remaining < 300 else ("var(--warning)" if remaining < 900 else "var(--text-primary)")
    html(f'<div class="sl-card sl-glow" style="margin:0;padding:.6rem .9rem"><div class="sl-kicker">Time left</div>'
         f'<div class="sl-display" style="font-size:1.9rem;font-weight:700;color:{color}" role="timer" '
         f'aria-live="off">{h:01d}:{m:02d}:{sec:02d}</div></div>')
    if remaining == 0:
        with ctx.session() as s:
            exam = exam_service.get_exam(s, exam_id)
            if exam.status == "in_progress":
                exam_service.submit_exam(s, exam_id, auto=True, tz=str(settings_service.get_setting(s, "timezone")))
        st.rerun(scope="app")


@st.dialog("Submit paper?")
def _confirm_submit(ctx: AppContext, exam_id: int, counts: dict[str, int]) -> None:
    st.markdown(f"- Answered: **{counts['answered']}**\n- Not answered: **{counts['unanswered']}**\n"
                f"- Marked for review: **{counts['marked']}**")
    st.warning("After submission no answers can be changed.")
    c1, c2 = st.columns(2)
    if c1.button("Yes, submit", type="primary", key="war_submit_yes"):
        today = ctx.today()
        action(ctx, lambda s: exam_service.submit_exam(s, exam_id, tz=str(settings_service.get_setting(s, "timezone"))),
               success="Paper submitted — analysis ready.", days=[today])
    if c2.button("Cancel", key="war_submit_no"):
        st.rerun()


def _exam_room(ctx: AppContext, exam_id: int) -> None:
    data = _load_exam(ctx, exam_id)
    if data["status"] != "in_progress":
        st.rerun()
    qs = data["questions"]
    pos = int(st.session_state.get(f"war_pos_{exam_id}", data["position"]))
    pos = min(max(pos, 1), len(qs))
    q = next(x for x in qs if x["pos"] == pos)
    if f"war_enter_{exam_id}" not in st.session_state:
        st.session_state[f"war_enter_{exam_id}"] = (pos, time.time())
        with ctx.session() as s:
            exam_service.mark_visited(s, exam_id, pos)
        q["visited"] = True

    if err := st.session_state.pop("war_save_error", None):
        st.error(err)
        if "auto-submitted" in err:
            st.rerun()

    top_l, top_r = st.columns([3, 1])
    with top_l:
        html(f'<div class="sl-kicker">{"Full paper" if data["mode"] == "full" else "Shorter paper"} · '
             f'{len(qs)} questions · {data["max_marks"]:g} marks · {data["duration"]} min</div>'
             f'<h3 style="margin:.1rem 0">{data["title"]}</h3>')
        st.caption("Responses autosave on every change. Refreshing or closing the tab never loses your answers; "
                   "the timer keeps running from the recorded start time."
                   + (f" Last saved {st.session_state['war_saved_at']}." if st.session_state.get("war_saved_at") else ""))
    with top_r:
        _timer(ctx, exam_id, data["deadline"].isoformat())

    main, side = st.columns([2.2, 1])
    with side, st.container(border=True):
        st.markdown("**Question palette**")
        html('<div class="sl-legend">' + "".join(f"<span>{icon} {label}</span>" for icon, label in (
            ("⬜", "Not visited"), ("🟥", "Not answered"), ("🟩", "Answered"), ("🟪", "Marked"),
            ("💜", "Answered + marked"))) + "</div>")
        for section, label in (("GA", "General Aptitude"), ("DA", "Data Science & AI")):
            items = [x for x in qs if x["section"] == section]
            if not items:
                continue
            st.caption(label)
            choice = st.pills(label, [x["pos"] for x in items], selection_mode="single",
                              default=pos if q["section"] == section else None,
                              format_func=lambda p, _qs=qs: f"{PALETTE_ICON[_state(_qs[p - 1])]} {p}",
                              key=f"war_pal_{exam_id}_{section}_{pos}", label_visibility="collapsed")
            if choice is not None and choice != pos:
                _goto(ctx, exam_id, pos, int(choice))
                st.rerun()
        counts = {"answered": sum(1 for x in qs if x["response"]),
                  "unanswered": sum(1 for x in qs if not x["response"]),
                  "marked": sum(1 for x in qs if x["marked"])}
        st.caption(f"Answered {counts['answered']} · Not answered {counts['unanswered']} · Marked {counts['marked']}")
        if st.button("Submit paper", type="primary", key="war_submit", width="stretch"):
            _confirm_submit(ctx, exam_id, counts)

    with main, st.container(border=True):
        snap = q["snap"]
        neg = "−1/3" if q["marks"] == 1 else "−2/3"
        html(f'<div class="sl-kicker">Question {pos} of {len(qs)} · '
             f'{"General Aptitude" if q["section"] == "GA" else "Data Science & AI"}</div>'
             + provenance_badges(q["source_type"], snap["verification_status"], snap.get("exam_year"),
                                 snap.get("question_ref"), snap.get("exam_name"))
             + " " + badge(f'{q["qtype"]} · {q["marks"]} mark{"s" if q["marks"] > 1 else ""}', "blue")
             + " " + badge(f"Wrong: {neg}" if q["qtype"] == "MCQ" else "No negative marking", "muted"))
        st.markdown(snap["stem"])
        k = _wkey(exam_id, pos)
        if q["qtype"] == "MCQ":
            opts = list(OPTION_KEYS[: len(snap["options"])])
            if f"{k}_resp" not in st.session_state:
                st.session_state[f"{k}_resp"] = q["response"] if q["response"] in opts else None
            st.radio("Choose one option", opts, key=f"{k}_resp", format_func=lambda o, _s=snap: f"({o}) {_s['options'][OPTION_KEYS.index(o)]}",
                     on_change=_autosave, args=(ctx, exam_id, pos, "MCQ"))
        elif q["qtype"] == "MSQ":
            st.caption("Select ALL correct options (no partial credit).")
            chosen = normalize_msq(q["response"])
            for i, text in enumerate(snap["options"]):
                o = OPTION_KEYS[i]
                if f"{k}_msq_{o}" not in st.session_state:
                    st.session_state[f"{k}_msq_{o}"] = o in chosen
                st.checkbox(f"({o}) {text}", key=f"{k}_msq_{o}", on_change=_autosave, args=(ctx, exam_id, pos, "MSQ"))
        else:
            if f"{k}_resp" not in st.session_state:
                st.session_state[f"{k}_resp"] = q["response"] or ""
            st.text_input("Numeric answer (press Enter to save)", key=f"{k}_resp", on_change=_autosave,
                          args=(ctx, exam_id, pos, "NAT"))
        if f"{k}_mark" not in st.session_state:
            st.session_state[f"{k}_mark"] = q["marked"]
        st.checkbox("Mark for review", key=f"{k}_mark", on_change=_autosave, args=(ctx, exam_id, pos, q["qtype"]))

        b1, b2, b3, b4 = st.columns(4)
        if b1.button("◀ Previous", disabled=pos == 1, key=f"{k}_prev", width="stretch"):
            _goto(ctx, exam_id, pos, pos - 1)
            st.rerun()
        if b2.button("Clear response", key=f"{k}_clear", width="stretch"):
            _persist(ctx, exam_id, pos, None, bool(st.session_state.get(f"{k}_mark")))
            _bump(exam_id, pos)
            st.rerun()
        if b3.button("Mark & next", key=f"{k}_marknext", width="stretch"):
            _persist(ctx, exam_id, pos, _current_response(exam_id, pos, q["qtype"]), True)
            _bump(exam_id, pos)
            if pos < len(qs):
                _goto(ctx, exam_id, pos, pos + 1)
            st.rerun()
        if b4.button("Save & next ▶", type="primary", key=f"{k}_next", width="stretch"):
            _autosave(ctx, exam_id, pos, q["qtype"])
            if pos < len(qs):
                _goto(ctx, exam_id, pos, pos + 1)
            st.rerun()


# --------------------------------------------------------------------------- analysis
def _analysis(ctx: AppContext, exam_id: int) -> None:
    with ctx.session() as s:
        an = exam_service.analyse(s, exam_id)
        exam = an.exam
        tz = str(settings_service.get_setting(s, "timezone"))
    o = an.overall
    pct = 100 * (exam.score or 0) / exam.max_marks if exam.max_marks else 0
    st.markdown(f"### {exam.title} — analysis")
    if exam.includes_ai:
        st.caption("⚠ This paper included AI-generated practice questions (labelled per question).")
    stat_row([
        ("Score", f"{exam.score:g} / {exam.max_marks:g}", f"{pct:.1f}%"),
        ("Accuracy", f"{o.accuracy:.1f}%" if o.accuracy is not None else "—", f"{o.correct} correct · {o.wrong} wrong"),
        ("Negative marks", f"−{exam.negative_marks:g}", f"{o.unanswered} unanswered"),
        ("Time used", f"{(exam.time_spent_sec or 0) // 60} min", f"of {exam.duration_minutes} min"
         + (" · auto-submitted" if exam.auto_submitted else "")),
    ])
    sec_df = pd.DataFrame([{"Section": b.label, "Score": b.score, "Max": b.max_marks, "Correct": b.correct,
                            "Wrong": b.wrong, "Unanswered": b.unanswered, "Negative": b.negative,
                            "Accuracy %": b.accuracy, "Time (min)": round(b.time_sec / 60, 1)}
                           for b in [*an.by_section, *an.by_qtype, *an.by_marks]])
    st.dataframe(sec_df, hide_index=True, width="stretch")
    topics = an.by_topic
    if topics:
        st.plotly_chart(charts.bar_chart(
            [b.label for b in topics], [100 * b.score / b.max_marks if b.max_marks else 0 for b in topics],
            horizontal=True, percent=True, title="Topic-wise score (% of available marks, weakest first)",
            height=max(260, 28 * len(topics) + 80), hover_suffix="%"), config=charts.CONFIG)
    with st.expander("Topic-wise table"):
        st.dataframe(pd.DataFrame([{"Topic": b.label, "Questions": b.questions, "Score": b.score, "Max": b.max_marks,
                                    "Correct": b.correct, "Wrong": b.wrong, "Unanswered": b.unanswered,
                                    "Avg time (s)": round(b.time_sec / b.questions) if b.questions else 0}
                                   for b in topics]), hide_index=True, width="stretch")
    st.markdown("#### Question review")
    flt = st.segmented_control("Show", ["All", "Wrong", "Unanswered", "Marked"], default="Wrong", key=f"rev_f_{exam_id}")
    for it in an.items:
        if flt == "Wrong" and it["is_correct"] is not False:
            continue
        if flt == "Unanswered" and it["is_correct"] is not None:
            continue
        if flt == "Marked" and not it["marked_for_review"]:
            continue
        verdict = "✓" if it["is_correct"] else ("✗" if it["is_correct"] is False else "—")
        with st.expander(f"Q{it['position']} {verdict} · {it['qtype']} {it['marks']}m · {it['topic']} · "
                         f"{it['marks_awarded']:+.2f}"):
            html(provenance_badges(str(it["source_type"]), str(it["verification_status"]), it.get("exam_year"),  # type: ignore[arg-type]
                                   it.get("question_ref"), it.get("exam_name")))  # type: ignore[arg-type]
            st.markdown(str(it["stem"]))
            for kk, text in zip(OPTION_KEYS, it["options"], strict=False):  # type: ignore[arg-type]
                st.markdown(f"**({kk})** {text}")
            st.markdown(f"**Your answer:** {it['response'] or '—'} · **Correct:** "
                        f"{answer_text(str(it['qtype']), it['answer_key'], it['nat_low'], it['nat_high'])} · "  # type: ignore[arg-type]
                        f"**Time:** {it['time_sec']}s")
            if it["explanation"]:
                st.markdown(f"**Explanation:** {it['explanation']}")
    with st.form(f"review_notes_{exam_id}"):
        notes = st.text_area("Your post-exam review notes", value=exam.review_notes or "", height=120, max_chars=5000)
        if st.form_submit_button("Save review"):
            action(ctx, lambda s: exam_service.save_review_notes(s, exam_id, notes), success="Review saved")
    del tz


def _history(ctx: AppContext) -> list:
    with ctx.session() as s:
        tz = str(settings_service.get_setting(s, "timezone"))
        rows = [(e.id, e.title, e.mode, e.status, local_date_of(e.started_at, tz), e.score, e.max_marks,
                 e.correct_count, e.wrong_count, e.unanswered_count, e.time_spent_sec)
                for e in exam_service.history(s)]
    return rows


def render() -> None:
    ctx = get_ctx()
    page_header("Weekend Full War", "A timed, official-pattern GATE DA paper built ONLY from topics you have covered.",
                kicker="Raid")
    with ctx.session() as s:
        exam_service.expire_if_overdue(s, str(settings_service.get_setting(s, "timezone")))
        active = exam_service.active_exam(s)
        active_id = active.id if active else None
    if active_id is not None:
        _exam_room(ctx, active_id)
        return
    history = _history(ctx)
    submitted = [h for h in history if h[3] == "submitted"]
    tab_new, tab_review, tab_hist = st.tabs(["New paper", "Latest analysis", f"History ({len(history)})"])
    with tab_new:
        _setup(ctx)
    with tab_review:
        if not submitted:
            empty_state("No submitted papers yet", "Your post-exam analysis appears here.")
        else:
            options = {h[0]: f"{h[1]} · {h[4]} · {h[5]:g}/{h[6]:g}" for h in submitted}
            chosen = st.selectbox("Paper", list(options), format_func=options.get, key="war_review_pick")
            _analysis(ctx, chosen)
    with tab_hist:
        if not history:
            st.caption("No papers yet.")
        else:
            st.dataframe(pd.DataFrame([{
                "Paper": h[1], "Mode": h[2], "Status": h[3], "Date": h[4],
                "Score": h[5], "Max": h[6], "%": round(100 * h[5] / h[6], 1) if h[5] is not None and h[6] else None,
                "Correct": h[7], "Wrong": h[8], "Unanswered": h[9], "Minutes": (h[10] or 0) // 60,
            } for h in history]), hide_index=True, width="stretch")
            if len(submitted) >= 2:
                pts = sorted(submitted, key=lambda h: h[0])
                st.plotly_chart(charts.line_chart([h[4] for h in pts],
                                                  [("Score %", [100 * h[5] / h[6] for h in pts])],
                                                  title="Score trend", percent=True, y_range=(-10, 100)),
                                config=charts.CONFIG)
