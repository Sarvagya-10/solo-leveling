"""Question rendering helpers (provenance labels are always visible)."""

from __future__ import annotations

from html import escape

import streamlit as st

from shogun.db.models import Question
from shogun.services.question_service import SOURCE_LABELS, VERIFICATION_LABELS, options_of
from shogun.services.scoring import OPTION_KEYS
from shogun.ui.components import badge, html


def provenance_badges(source_type: str, verification: str, year: int | None = None, ref: str | None = None) -> str:
    kind = {"official_pyq": "violet", "ai_generated": "warning", "user_practice": "blue"}.get(source_type, "")
    vkind = {"verified": "good", "unverified": "muted", "rejected": "critical"}.get(verification, "")
    parts = [badge(SOURCE_LABELS.get(source_type, source_type), kind),
             badge(VERIFICATION_LABELS.get(verification, verification), vkind)]
    if year:
        parts.append(badge(f"GATE {year}" + (f" · {ref}" if ref else ""), "blue"))
    if source_type == "official_pyq" and verification != "verified":
        parts.append(badge("Not yet verified — do not trust as a real PYQ", "warning"))
    if source_type == "ai_generated":
        parts.append(badge("Not a real GATE question", "warning"))
    return " ".join(parts)


def answer_text(qtype: str, answer_key: str | None, nat_low: float | None, nat_high: float | None) -> str:
    if qtype == "NAT":
        if nat_low is None:
            return "—"
        return f"{nat_low:g}" if nat_low == nat_high else f"{nat_low:g} to {nat_high:g}"
    return answer_key or "—"


def render_question(q: Question, *, show_answer: bool = False, key: str = "") -> None:
    cls = "sl-pyq" if q.source_type == "official_pyq" else "sl-ai"
    marks_label = f"{q.qtype} · {q.marks} mark" + ("s" if q.marks > 1 else "")
    html(f'<div class="{cls}">{provenance_badges(q.source_type, q.verification_status, q.exam_year, q.question_ref)}'
         f' {badge(marks_label)}</div>')
    st.markdown(q.stem)
    for k, text in zip(OPTION_KEYS, options_of(q), strict=False):
        st.markdown(f"**({k})** {text}")
    if show_answer or st.toggle("Show answer & explanation", key=f"ans_{key}_{q.id}"):
        official = q.source_type == "official_pyq" and q.verification_status == "verified"
        st.markdown(f"**Answer{' (official key)' if official else ''}:** "
                    f"{escape(answer_text(q.qtype, q.answer_key, q.nat_low, q.nat_high))}")
        if q.explanation:
            label = {"official": "Explanation (official)",
                     "ai_authored": "Explanation (written by AI — not official; review it)",
                     "user": "Explanation (yours)"}.get(q.explanation_source or "", "Explanation")
            st.markdown(f"**{label}:** {q.explanation}")
    if q.source_url:
        st.caption(f"Source: {q.source_url}")
    if q.source_note:
        st.caption(f"Provenance: {q.source_note[:600]}")
