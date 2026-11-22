from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from zoneinfo import available_timezones

import streamlit as st

from shogun import APP_TITLE, __version__
from shogun.ai import workflows
from shogun.ai.errors import AIError
from shogun.db.session import run_migrations
from shogun.logging_setup import get_logger
from shogun.services import backup_service, gamification_service, settings_service
from shogun.services.errors import ShogunError
from shogun.services.seed import seed_all
from shogun.syllabus import load_official_syllabi
from shogun.ui.components import badge, flash, html, page_header
from shogun.ui.context import AppContext, action, get_ctx

log = get_logger("ui.settings")


def _targets(ctx: AppContext) -> None:
    with ctx.session() as s:
        cur = settings_service.get_all(s)
    zones = sorted(available_timezones())
    with st.form("settings_targets"):
        c1, c2 = st.columns(2)
        tz = c1.selectbox("Timezone (defines 'today')", zones, index=zones.index(cur["timezone"])
                          if cur["timezone"] in zones else 0)
        start = c2.date_input("Tracking start date", value=date.fromisoformat(cur["tracking_start_date"])
                              if cur["tracking_start_date"] else date.today())
        c1, c2, c3 = st.columns(3)
        pyq_target = c1.number_input("PYQ mastery target (correct PYQs)", 1, 500, int(cur["pyq_target_default"]))
        study_target = c2.number_input("Daily GATE study target (min, 0 = off)", 0, 1440,
                                       int(cur["daily_study_target_minutes"]), step=15)
        pyq_daily = c3.number_input("Daily PYQ target (0 = off)", 0, 500, int(cur["daily_pyq_target"]))
        c1, c2, c3, c4 = st.columns(4)
        fin = c1.number_input("Finance target (min)", 1, 1440, int(cur["finance_target_minutes"]), step=5)
        res = c2.number_input("Research target (min)", 1, 1440, int(cur["research_target_minutes"]), step=5)
        base = c3.number_input("Attention baseline (min)", 1, 1440, int(cur["attention_baseline_minutes"]))
        att = c4.number_input("Attention target (min)", 1, 1440, int(cur["attention_target_minutes"]))
        rule = st.radio("Weekend Full War eligibility", list(settings_service.WAR_RULES),
                        format_func=settings_service.WAR_RULES.get,
                        index=list(settings_service.WAR_RULES).index(cur["war_eligibility_rule"]))
        unrev = st.checkbox("Default: allow unreviewed AI questions in papers (still opt-in per paper)",
                            value=bool(cur["war_include_unreviewed_ai"]))
        priv = st.checkbox("Privacy: show only logged counts for not-to-do on the dashboard",
                           value=bool(cur["privacy_hide_not_todo"]))
        if st.form_submit_button("Save settings", type="primary"):
            values = {"timezone": tz, "tracking_start_date": start.isoformat(), "pyq_target_default": pyq_target,
                      "daily_study_target_minutes": study_target, "daily_pyq_target": pyq_daily,
                      "finance_target_minutes": fin, "research_target_minutes": res,
                      "attention_baseline_minutes": base, "attention_target_minutes": att,
                      "war_eligibility_rule": rule, "war_include_unreviewed_ai": unrev, "privacy_hide_not_todo": priv}

            def save(s):  # noqa: ANN001
                for k, v in values.items():
                    settings_service.set_setting(s, k, v)
                gamification_service.sync_all(s, tz, ctx.today())
            action(ctx, save, success="Settings saved — metrics and XP recalculated")


def _ai(ctx: AppContext) -> None:
    cfg = ctx.config
    html(f"Groq API key: {badge('configured', 'good') if cfg.groq_api_key.is_set else badge('not set', 'warning')} "
         f"&nbsp; SerpAPI key: {badge('configured', 'good') if cfg.serpapi_api_key.is_set else badge('not set', 'warning')}"
         f" &nbsp; GROQ_MODEL env: {badge(cfg.groq_model or 'auto')}")
    st.caption("Keys are read only from environment variables or the local, git-ignored `.env` file and are never "
               "displayed, logged or stored in the database. Every deterministic feature works without them.")
    if not cfg.groq_api_key.is_set or not cfg.serpapi_api_key.is_set:
        st.code("# .env (project root)\nGROQ_API_KEY=...\nSERPAPI_API_KEY=...\nGROQ_MODEL=", language="bash")
        st.caption("After editing .env, restart the app (or use 'Reload configuration' below).")
    with ctx.session() as s:
        chosen = settings_service.get_setting(s, "groq_model")
    c1, c2 = st.columns(2)
    if c1.button("Test Groq & discover models", key="ai_test_groq"):
        try:
            with ctx.session() as s:
                st.session_state["ai_models"] = workflows.test_groq(s, cfg)
        except AIError as exc:
            st.warning(f"Groq: {exc}")
    if c2.button("Test SerpAPI (no search credit used)", key="ai_test_serp"):
        try:
            info = workflows.test_serpapi(cfg)
            st.success("SerpAPI reachable. " + ", ".join(f"{k}: {v}" for k, v in info.items()))
        except AIError as exc:
            st.warning(f"SerpAPI: {exc}")
    result = st.session_state.get("ai_models")
    if result:
        st.success(f"Groq reachable — {result['explanation']}")
        models = result["models"]
        options = ["(auto: strongest available)", *models]
        idx = options.index(chosen) if chosen in options else 0
        pick = st.selectbox("Model for this app", options, index=idx, key="ai_model_pick")
        if st.button("Save model choice", key="ai_model_save"):
            value = None if pick.startswith("(auto") else pick
            action(ctx, lambda s: settings_service.set_setting(s, "groq_model", value),
                   success=f"Model set to {value or 'auto'}")
    else:
        st.caption(f"Current choice: {chosen or 'auto (strongest available model your key can access)'}")
    if st.button("Reload configuration from .env", key="ai_reload"):
        from shogun.ui.context import reset_ctx
        reset_ctx()
        flash("Configuration reloaded")
        st.rerun()


def _post_restore(ctx: AppContext) -> None:
    run_migrations(ctx.config.db_url)
    with ctx.session() as s:
        tz = str(settings_service.get_setting(s, "timezone"))
        seed_all(s, ctx.today())
        gamification_service.sync_all(s, tz, ctx.today())
        gamification_service.evaluate_achievements(s, ctx.today(), tz)


def _data(ctx: AppContext) -> None:
    cfg = ctx.config
    st.markdown("##### Backups")
    c1, c2 = st.columns([1, 2])
    if c1.button("Create backup now", type="primary", key="bk_now"):
        try:
            path = backup_service.backup_database(ctx.engine, cfg.backups_dir, "manual")
            st.success(f"Backup saved: {path.name}")
        except (ShogunError, OSError) as exc:
            st.error(f"Backup failed: {exc}")
    c2.caption(f"Backups are stored in `{cfg.backups_dir}`. Copy them somewhere safe (cloud drive) regularly.")
    backups = backup_service.list_backups(cfg.backups_dir)
    if backups:
        pick = st.selectbox("Restore from backup", backups, format_func=lambda p: p.name, key="bk_pick", index=None)
        confirm = st.text_input("Type RESTORE to confirm (a safety backup of the current data is taken first)",
                                key="bk_confirm")
        if st.button("Restore selected backup", disabled=pick is None or confirm != "RESTORE", key="bk_restore"):
            try:
                safety = backup_service.restore_backup(ctx.engine, Path(pick), cfg.backups_dir)
                _post_restore(ctx)
                flash(f"Restored {Path(pick).name}. Safety backup: {safety.name}")
                st.rerun()
            except (ShogunError, OSError) as exc:
                st.error(f"Restore failed: {exc}")

    st.markdown("##### Export")
    inc = st.checkbox("Include private not-to-do data in exports", value=False, key="exp_priv")
    with ctx.session() as s:
        json_bytes = backup_service.export_json_bytes(s, include_private=inc)
        csv_bytes = backup_service.export_csv_zip(s, include_private=inc)
    stamp = ctx.today().isoformat()
    c1, c2 = st.columns(2)
    c1.download_button("Download JSON export", json_bytes, file_name=f"shogun-export-{stamp}.json",
                       mime="application/json", key="exp_json")
    c2.download_button("Download CSV (zip)", csv_bytes, file_name=f"shogun-export-{stamp}.zip",
                       mime="application/zip", key="exp_csv")

    st.markdown("##### Import (replace all data)")
    up = st.file_uploader("Shogun JSON export", type=["json"], key="imp_file")
    confirm = st.text_input("Type IMPORT to replace current data with this file", key="imp_confirm")
    if st.button("Import", disabled=up is None or confirm != "IMPORT", key="imp_go"):
        try:
            payload = json.loads(up.getvalue().decode("utf-8"))
            safety = backup_service.backup_database(ctx.engine, cfg.backups_dir, "pre-import")
            with ctx.session() as s:
                report = backup_service.import_data(s, payload)
            _post_restore(ctx)
            flash(f"Imported {sum(report.rows.values())} rows. Safety backup: {safety.name}")
            if report.skipped:
                flash(f"{len(report.skipped)} row(s) skipped (unknown topics)", "warning")
            st.rerun()
        except (UnicodeDecodeError, json.JSONDecodeError):
            st.error("That file is not valid JSON.")
        except ShogunError as exc:
            st.error(f"Import failed: {exc}. Nothing was changed.")

    st.markdown("##### Reset")
    with st.container(border=True):
        st.error("Reset permanently deletes ALL your logs, progress, revisions, papers, XP and settings. An automatic "
                 "backup is taken first, but download an export too.")
        ok = st.checkbox("I understand this deletes all my data", key="reset_ok")
        word = st.text_input("Type RESET to confirm", key="reset_word")
        if st.button("Reset everything", disabled=not ok or word != backup_service.RESET_CONFIRMATION, key="reset_go"):
            try:
                safety = backup_service.backup_database(ctx.engine, cfg.backups_dir, "pre-reset")
                with ctx.session() as s:
                    backup_service.reset_all_data(s, word)
                _post_restore(ctx)
                flash(f"All data reset. Safety backup: {safety.name}")
                st.rerun()
            except (ShogunError, OSError) as exc:
                st.error(f"Reset failed: {exc}")


def _about() -> None:
    specs = load_official_syllabi()
    st.markdown(f"**{APP_TITLE}** v{__version__}")
    for spec in specs:
        st.markdown(f"- **{spec.paper_name}** — `{spec.syllabus_version}` · {len(spec.sections)} sections · "
                    f"{spec.topic_count} topics · source: {spec.source.get('official_url')} "
                    f"(sha256 `{spec.source.get('sha256', '')[:12]}…`)")
    st.caption("Exam pattern: gate2027.iitm.ac.in/question_paper_pattern — 65 Q, 100 marks, 180 min; −1/3 and −2/3 "
               "for wrong 1- and 2-mark MCQs; no negative marking or partial credit for MSQ/NAT.")


def render() -> None:
    ctx = get_ctx()
    page_header("Settings & Data", "Targets, AI provider, backups, export/import and reset.", kicker="Control room")
    t1, t2, t3, t4 = st.tabs(["Targets & preferences", "AI provider", "Data & backups", "About"])
    with t1:
        _targets(ctx)
    with t2:
        _ai(ctx)
    with t3:
        _data(ctx)
    with t4:
        _about()
