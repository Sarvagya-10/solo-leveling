from __future__ import annotations

import streamlit as st

from shogun.ui.components import page_header
from shogun.ui.context import get_ctx
from shogun.ui.syllabus_view import render_tracker


def render() -> None:
    ctx = get_ctx()
    page_header("GATE DA 2027 Syllabus", "Complete official syllabus (IIT Madras, GATE 2027) — 7 sections, "
                "119 trackable topics, each tied verbatim to the official text.", kicker="Dungeon map")
    with st.expander("How progress is measured"):
        st.markdown(
            "- **Knowledge coverage** — not started → in progress → mastered. Raised by daily logs, never "
            "silently lowered; manual changes need a reason and are audited.\n"
            "- **PYQ mastery** — mastered when correct PYQs reach the target (default 10, configurable globally "
            "and per topic). Counts = PYQs you log daily + in-app attempts on verified PYQs.\n"
            "- **Revisions R1–R4** — scheduled automatically at +1, +3, +7 and +21 days after study.\n"
            "- **Overall status** — mastered only when coverage *and* PYQ mastery are mastered.\n"
            "- Source: `data/syllabus/gate_da_2027.v1.json` (official PDF checksum pinned)."
        )
    render_tracker(ctx, "DA", "da")
