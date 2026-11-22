from __future__ import annotations

import json

import pandas as pd
import streamlit as st
from sqlalchemy.orm import Session

from shogun.ai import workflows
from shogun.db.models import Topic
from shogun.services import card_service, question_service
from shogun.services.card_service import CARD_FIELDS, FIELD_LABELS
from shogun.ui import nav
from shogun.ui.components import badge, empty_state, html, page_header
from shogun.ui.context import AppContext, action, get_ctx
from shogun.ui.question_view import render_question


def _generate(ctx: AppContext, topic_id: int, force: bool) -> None:
    def do(s: Session):
        draft, model, cached = workflows.generate_card_draft(s, ctx.config, topic_id, force=force)
        result = card_service.apply_ai_draft(s, topic_id, draft, model)
        return result, model, cached

    action(ctx, do, success=lambda r: f"Card {'loaded from cache' if r[2] else 'generated'} with {r[1]} — "
                                      f"{r[0].practice_added} AI practice question(s) added. Review before trusting it.")


def render() -> None:
    ctx = get_ctx()
    page_header("Revision Cards", "One card per topic: idea, formulae, recognition patterns, traps, connected topics, "
                "verified PYQs and separately-labelled AI practice.", kicker="Grimoire")
    c1, c2, c3 = st.columns([1, 2, 1])
    paper = c1.segmented_control("Paper", ["DA", "GA"], default="DA", key="cards_paper") or "DA"
    with ctx.session() as s:
        topics = question_service.topics_for_paper(s, paper)
        labels = {t.id: f"{t.code} · {t.name}" for t in topics}
        cards = {c.topic_id: c for c in card_service.list_cards(s, paper=paper)}
        counts = question_service.topic_question_counts(s)
    bookmarked_only = c3.toggle("Bookmarked only", key="cards_bm")
    choices = [tid for tid in labels if not bookmarked_only or (tid in cards and cards[tid].bookmarked)]
    if not choices:
        empty_state("No cards here yet", "Bookmark cards to see them in this filter.")
        return
    tid = c2.selectbox("Topic", choices, format_func=lambda t: ("★ " if t in cards and cards[t].bookmarked else "")
                       + labels[t] + (" ✓card" if t in cards else ""), key="cards_topic")

    with st.expander(f"Card overview — {len(cards)}/{len(topics)} topics have cards"):
        st.dataframe(pd.DataFrame([{
            "Topic": labels[t], "Card": "Yes" if t in cards else "—",
            "Review": ("Reviewed" if cards[t].review_status == "reviewed" else "AI draft — unreviewed") if t in cards else "",
            "Bookmarked": "★" if t in cards and cards[t].bookmarked else "",
            "Verified PYQs": counts.get(t, {}).get("verified_pyq", 0),
            "AI practice": counts.get(t, {}).get("ai", 0),
        } for t in labels]), hide_index=True, width="stretch")

    with ctx.session() as s:
        topic = s.get(Topic, tid)
        topic_name = topic.name
        card = card_service.get_card(s, tid)
        connected = []
        if card:
            codes = card_service.connected_codes(card)
            connected = [(t.code, t.name) for t in s.query(Topic).filter(Topic.code.in_(codes)).all()]
        pyqs = question_service.verified_pyqs_for_topic(s, tid, limit=3)
        ai_qs = question_service.list_questions(s, topic_id=tid, source_type="ai_generated")
        versions = card_service.versions(s, card.id) if card else []
        for q in [*pyqs, *ai_qs]:
            _ = q.topic_links

    st.markdown(f"### {topic_name}")
    if card is None:
        empty_state("No card for this topic yet", "Generate a draft with AI (requires GROQ_API_KEY) or write one.")
    else:
        status = (badge("Reviewed", "good") if card.review_status == "reviewed"
                  else badge("AI draft — not reviewed yet", "warning"))
        origin = badge(f"AI · {card.ai_model}" if card.origin == "ai" else "Written by you", "blue")
        html(f"{status} {origin} {badge('★ Bookmarked', 'violet') if card.bookmarked else ''}")
        for f in CARD_FIELDS:
            value = getattr(card, f)
            if value:
                with st.container(border=True):
                    st.markdown(f"**{FIELD_LABELS[f]}**")
                    st.markdown(value)
        if connected:
            with st.container(border=True):
                st.markdown("**Connected DA syllabus topics**")
                st.markdown("\n".join(f"- `{c}` {n}" for c, n in connected))

    a1, a2, a3, a4 = st.columns(4)
    if card is None:
        if a1.button("✨ Generate with AI", type="primary", key="card_gen"):
            _generate(ctx, tid, force=False)
    else:
        if a1.button("★ Unbookmark" if card.bookmarked else "☆ Bookmark", key="card_bm"):
            action(ctx, lambda s: card_service.toggle_bookmark(s, card.id),
                   success=lambda on: "Bookmarked" if on else "Bookmark removed")
        if card.review_status == "draft":
            if a2.button("✓ Mark reviewed", key="card_rev", help="Confirm you checked the content for accuracy"):
                action(ctx, lambda s: card_service.set_reviewed(s, card.id, True), success="Card marked reviewed")
        elif a2.button("Mark as draft", key="card_unrev"):
            action(ctx, lambda s: card_service.set_reviewed(s, card.id, False), success="Card marked as draft")
        regen_ok = a4.checkbox("Confirm regenerate", key="card_regen_ok",
                               help="Regenerating replaces the card (the old version is kept in history)")
        if a3.button("↻ Regenerate", key="card_regen", disabled=not regen_ok):
            _generate(ctx, tid, force=True)

    with st.expander("✏️ Write / edit card"):
        with st.form(f"card_edit_{tid}"):
            values = {f: st.text_area(FIELD_LABELS[f], value=(getattr(card, f) or "") if card else "",
                                      height=140 if f != "basic_idea" else 110, max_chars=20000) for f in CARD_FIELDS}
            conn = st.text_input("Connected topic codes (comma separated, e.g. DA.2.12, DA.6.24)",
                                 value=", ".join(card_service.connected_codes(card)) if card else "")
            if st.form_submit_button("Save card", type="primary"):
                action(ctx, lambda s: card_service.save_card(s, tid, values, [c.strip() for c in conn.split(",")
                                                                               if c.strip()]),
                       success="Card saved")

    st.markdown("#### Genuine GATE PYQs (verified)")
    if not pyqs:
        st.info("No verified GATE PYQs are available for this topic yet. Real PYQs are never fabricated — "
                "add them from the official papers in the Question Bank and verify them there.")
    else:
        if len(pyqs) < 3:
            st.caption(f"Only {len(pyqs)} verified PYQ(s) available for this topic.")
        for q in pyqs:
            with st.container(border=True):
                render_question(q, key="card_pyq")
    nav.link("questions", "Add or verify PYQs in the Question Bank", icon="🧾")

    st.markdown("#### AI-generated practice questions")
    st.caption("Clearly labelled AI practice — NOT real GATE questions. Review them before relying on them.")
    if not ai_qs:
        st.caption("None yet. Generating a card creates three.")
    for q in ai_qs[:6]:
        with st.container(border=True):
            render_question(q, key="card_ai")

    if versions:
        with st.expander(f"Version history ({len(versions)})"):
            for v in versions[:10]:
                snap = json.loads(v.snapshot_json)
                st.markdown(f"**{v.created_at:%Y-%m-%d %H:%M} UTC** · {v.reason} · {snap.get('origin')} · "
                            f"{snap.get('review_status')}")
                st.caption((snap.get("basic_idea") or "")[:240])
                if st.button("Restore this version", key=f"card_restore_{v.id}"):
                    action(ctx, lambda s, vid=v.id: card_service.restore_version(s, vid), success="Version restored")

