from __future__ import annotations

import json

import streamlit as st
from sqlalchemy.orm import Session

from shogun.ai import workflows
from shogun.ai.errors import AIError
from shogun.services import question_service
from shogun.services.question_service import SOURCE_LABELS, VERIFICATION_LABELS, QuestionInput
from shogun.services.scoring import OPTION_KEYS
from shogun.ui.components import page_header, stat_row
from shogun.ui.context import AppContext, action, get_ctx
from shogun.ui.question_view import render_question


def _topic_labels(ctx: AppContext, paper: str) -> dict[str, str]:
    with ctx.session() as s:
        return {t.code: f"{t.code} · {t.name}" for t in question_service.topics_for_paper(s, paper)}


def _browse(ctx: AppContext) -> None:
    today = ctx.today()
    c1, c2, c3, c4 = st.columns(4)
    paper = c1.selectbox("Paper", ["Any", "DA", "GA"], key="qb_paper")
    src = c2.selectbox("Source", ["Any", *SOURCE_LABELS], format_func=lambda v: SOURCE_LABELS.get(v, v),
                       key="qb_src")
    ver = c3.selectbox("Verification", ["Any", *VERIFICATION_LABELS], format_func=lambda v: VERIFICATION_LABELS.get(v, v),
                       key="qb_ver")
    labels = _topic_labels(ctx, paper) if paper != "Any" else {**_topic_labels(ctx, "DA"), **_topic_labels(ctx, "GA")}
    code = c4.selectbox("Topic", ["Any", *labels], format_func=lambda v: labels.get(v, v), key="qb_topic")
    with ctx.session() as s:
        tid = None
        if code != "Any":
            from shogun.db.models import Topic
            tid = s.query(Topic.id).filter(Topic.code == code).scalar()
        questions = question_service.list_questions(
            s, topic_id=tid, paper=None if paper == "Any" else paper, source_type=None if src == "Any" else src,
            verification=None if ver == "Any" else ver)
        for q in questions:
            _ = (q.primary_topic.name, q.topic_links)
    st.caption(f"{len(questions)} question(s)")
    for q in questions[:100]:
        title = (f"#{q.id} · {q.primary_topic.code} · {SOURCE_LABELS[q.source_type]} · "
                 f"{VERIFICATION_LABELS[q.verification_status]} · {q.qtype} {q.marks}m")
        with st.expander(title):
            render_question(q, key="qb")
            t1, t2 = st.tabs(["Practice", "Review & manage"])
            with t1, st.form(f"qb_practice_{q.id}", clear_on_submit=True):
                if q.qtype == "MCQ":
                    opts = OPTION_KEYS[: len(question_service.options_of(q))]
                    resp = st.radio("Your answer", opts, horizontal=True, index=None)
                elif q.qtype == "MSQ":
                    opts = OPTION_KEYS[: len(question_service.options_of(q))]
                    resp = ",".join(st.multiselect("Your answer(s)", opts))
                else:
                    resp = st.text_input("Your numeric answer")
                if st.form_submit_button("Check answer"):
                    verdict = action(ctx, lambda s, qid=q.id, r=resp: question_service.record_practice_attempt(
                        s, qid, r or "", today), success=lambda ok: "Correct ✓" if ok else "Incorrect ✗ — see the answer",
                        days=[today])
                    del verdict
            with t2:
                if q.source_type == "official_pyq":
                    st.caption("Verify only after checking the question AND answer against the official GATE "
                               "question paper and official answer key.")
                ok = st.checkbox("I have checked this question against its source", key=f"qb_chk_{q.id}")
                b1, b2, b3, b4 = st.columns(4)
                if b1.button("Verify", key=f"qb_v_{q.id}", disabled=not ok or q.verification_status == "verified"):
                    action(ctx, lambda s, qid=q.id: question_service.set_verification(s, qid, "verified"),
                           success="Marked verified")
                if b2.button("Reject", key=f"qb_r_{q.id}", disabled=q.verification_status == "rejected"):
                    action(ctx, lambda s, qid=q.id: question_service.set_verification(s, qid, "rejected"),
                           success="Marked rejected (excluded from papers)")
                if b3.button("Unverify", key=f"qb_u_{q.id}", disabled=q.verification_status == "unverified"):
                    action(ctx, lambda s, qid=q.id: question_service.set_verification(s, qid, "unverified"),
                           success="Marked unverified")
                del_ok = st.checkbox("Confirm delete", key=f"qb_delok_{q.id}")
                if b4.button("Delete", key=f"qb_d_{q.id}", disabled=not del_ok):
                    action(ctx, lambda s, qid=q.id: question_service.delete_question(s, qid), success="Question deleted")
    if len(questions) > 100:
        st.caption("Showing the first 100 — narrow the filters to see more.")


def _question_form(ctx: AppContext, key: str, source_type: str) -> None:
    paper = st.segmented_control("Paper", ["DA", "GA"], default="DA", key=f"{key}_paper") or "DA"
    labels = _topic_labels(ctx, paper)
    with st.form(key, clear_on_submit=False):
        codes = st.multiselect("Syllabus topic(s) — first is primary", list(labels), format_func=labels.get)
        c1, c2, c3 = st.columns(3)
        qtype = c1.selectbox("Type", ["MCQ", "MSQ", "NAT"])
        marks = c2.selectbox("Marks", [1, 2])
        year = c3.number_input("Exam year", 2000, 2100, 2025) if source_type == "official_pyq" else None
        if source_type == "official_pyq":
            c4, c5 = st.columns(2)
            ref = c4.text_input("Question reference (e.g. Q.27)", max_chars=40)
            exam_name = c5.text_input("Exam / paper", value=f"GATE {paper}", max_chars=80)
        else:
            ref, exam_name = None, None
        stem = st.text_area("Question text (exactly as in the source)", height=150, max_chars=4000)
        st.caption("Options (MCQ/MSQ) — leave unused ones empty")
        oc = st.columns(2)
        options = [oc[i % 2].text_input(f"Option {OPTION_KEYS[i]}", key=f"{key}_opt_{i}") for i in range(4)]
        c6, c7, c8 = st.columns(3)
        answer = c6.text_input("Answer key (e.g. B or A,C)")
        nat_lo = c7.text_input("NAT answer low")
        nat_hi = c8.text_input("NAT answer high")
        explanation = st.text_area("Explanation / solution", height=100, max_chars=4000)
        source_url = st.text_input("Source URL (official paper / answer key)", max_chars=500)
        source_note = st.text_input("Source note (e.g. 'Official paper PDF, page 7')", max_chars=500)
        verified_now = False
        if source_type == "official_pyq":
            verified_now = st.checkbox("I transcribed this directly from the official paper and checked the answer "
                                       "against the official key (marks it verified)")
        if st.form_submit_button("Add question", type="primary"):
            def to_float(v: str) -> float | None:
                try:
                    return float(v) if v.strip() else None
                except ValueError:
                    return None

            data = QuestionInput(
                topic_codes=codes, source_type=source_type, qtype=qtype, marks=int(marks), stem=stem,
                options=options, answer_key=answer, nat_low=to_float(nat_lo), nat_high=to_float(nat_hi),
                explanation=explanation, exam_year=int(year) if year else None, exam_name=exam_name,
                question_ref=ref, source_url=source_url, source_note=source_note,
            )

            def do(s: Session):
                q = question_service.add_question(s, data)
                if verified_now:
                    question_service.set_verification(s, q.id, "verified")
                return q

            action(ctx, do, success=lambda q: f"Question #{q.id} added ({VERIFICATION_LABELS[q.verification_status]})")


def _sourcing(ctx: AppContext) -> None:
    st.markdown("Search the web (SerpAPI · DuckDuckGo) for official papers, answer keys and solutions. Results are "
                "**leads only** — nothing is added without your review.")
    paper = st.segmented_control("Paper", ["DA", "GA"], default="DA", key="src_paper") or "DA"
    labels = _topic_labels(ctx, paper)
    code = st.selectbox("Topic", list(labels), format_func=labels.get, key="src_topic")
    with ctx.session() as s:
        from shogun.db.models import Topic
        topic = s.query(Topic).filter(Topic.code == code).one()
        tid = topic.id
        default_q = workflows.pyq_search_query(topic)
    query = st.text_input("Search query", value=default_q, key=f"src_q_{code}")
    if st.button("Search", key="src_go"):
        try:
            with ctx.session() as s:
                st.session_state["src_results"] = [r.__dict__ for r in workflows.search_pyq_sources(
                    s, ctx.config, tid, query=query)]
        except AIError as exc:
            st.warning(f"Search unavailable: {exc}")
    results = st.session_state.get("src_results", [])
    for r in results:
        with st.container(border=True):
            st.markdown(f"**[{r['title'] or r['link']}]({r['link']})**")
            st.caption(r["snippet"])
    st.markdown("##### Extract candidate PYQs from a page (AI)")
    st.caption("The page text is sent to Groq, which may only copy questions that literally appear on the page. "
               "Every candidate is checked against the page text (hallucination guard) and saved as UNVERIFIED.")
    url = st.selectbox("Page", [r["link"] for r in results], index=None, key="src_url_pick",
                       placeholder="Pick a search result or paste a URL below") if results else None
    manual = st.text_input("…or paste a URL", key="src_url_manual")
    target = (manual or url or "").strip()
    if st.button("Extract candidates", disabled=not target, key="src_extract"):
        action(ctx, lambda s: workflows.extract_pyq_candidates(s, ctx.config, tid, target),
               success=lambda r: (f"{len(r.added)} candidate(s) saved as unverified. Rejected: "
                                  f"{r.rejected_not_in_source} not found verbatim in the page, {r.rejected_invalid} "
                                  f"invalid, {r.duplicates} duplicate(s). Verify them in Browse."))


def _generate(ctx: AppContext) -> None:
    st.markdown("Generate ORIGINAL practice questions with Groq. They are stored as **AI-generated practice**, "
                "unverified, and are never labelled as real PYQs.")
    paper = st.segmented_control("Paper", ["DA", "GA"], default="DA", key="gen_paper") or "DA"
    labels = _topic_labels(ctx, paper)
    with st.form("gen_form"):
        code = st.selectbox("Topic", list(labels), format_func=labels.get)
        c1, c2, c3 = st.columns(3)
        count = c1.number_input("How many", 1, 10, 3)
        marks = c2.selectbox("Marks", ["Any", 1, 2])
        qtype = c3.selectbox("Type", ["Any", "MCQ", "MSQ", "NAT"])
        if st.form_submit_button("Generate", type="primary"):
            def do(s: Session):
                from shogun.db.models import Topic
                tid = s.query(Topic.id).filter(Topic.code == code).scalar()
                return workflows.generate_practice_questions(
                    s, ctx.config, tid, count=int(count), marks=None if marks == "Any" else int(marks),
                    qtype=None if qtype == "Any" else qtype)
            action(ctx, do, success=lambda r: f"{len(r[0])} AI practice question(s) added (unverified); {r[1]} skipped.")


def _import(ctx: AppContext) -> None:
    st.markdown("Import questions from a JSON list (format: `data/pyq/README.md`). Everything imported starts "
                "**unverified**.")
    up = st.file_uploader("Questions JSON", type=["json"], key="qb_import")
    if up is not None and st.button("Import", key="qb_import_go"):
        try:
            payload = json.loads(up.getvalue().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            st.error("That file is not valid JSON.")
            return
        if not isinstance(payload, list):
            st.error("Expected a JSON list of questions.")
            return
        result = action(ctx, lambda s: question_service.import_questions(s, payload),
                        success=lambda r: f"Imported {r[0]} question(s); {len(r[1])} skipped.", rerun=False)
        if result and result[1]:
            st.warning("\n".join(result[1][:20]))


def render() -> None:
    ctx = get_ctx()
    page_header("Question Bank & PYQs", "Verified GATE PYQs, your own questions and labelled AI practice. Real "
                "PYQs are only ever marked verified by you.", kicker="Armoury")
    with ctx.session() as s:
        counts = question_service.bank_counts(s)
    stat_row([
        ("Verified PYQs", str(counts.get("official_pyq:verified", 0)), "usable in papers"),
        ("Unverified PYQ candidates", str(counts.get("official_pyq:unverified", 0)), "need your check"),
        ("AI practice", str(counts.get("ai_generated:unverified", 0) + counts.get("ai_generated:verified", 0)),
         f"{counts.get('ai_generated:verified', 0)} reviewed"),
        ("Your questions", str(counts.get("user_practice:unverified", 0) + counts.get("user_practice:verified", 0)),
         "user-authored"),
    ])
    tabs = st.tabs(["Browse & practice", "Add official PYQ", "Add own question", "Find sources (AI)",
                    "Generate practice (AI)", "Import JSON"])
    with tabs[0]:
        _browse(ctx)
    with tabs[1]:
        _question_form(ctx, "add_pyq", "official_pyq")
    with tabs[2]:
        _question_form(ctx, "add_own", "user_practice")
    with tabs[3]:
        _sourcing(ctx)
    with tabs[4]:
        _generate(ctx)
    with tabs[5]:
        _import(ctx)
