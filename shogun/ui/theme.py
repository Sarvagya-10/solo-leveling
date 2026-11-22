"""Design system: tokens + global CSS for the SYSTEM interface.

Palette: charcoal-black surfaces, electric violet + royal blue accents, subtle
glow borders. Chart colours are separate (see ``charts.py``) and validated for
colour-vision deficiency against the chart surface.
"""

from __future__ import annotations

import streamlit as st

TOKENS = {
    "bg": "#0a0a0f",
    "surface_1": "#14141c",
    "surface_2": "#1b1b27",
    "border": "#2a2840",
    "violet": "#8b5cf6",
    "violet_soft": "#a78bfa",
    "blue": "#3b82f6",
    "text_primary": "#ecebf5",
    "text_secondary": "#b4b2cc",
    "text_muted": "#8f8daa",
    "good": "#0ca30c",
    "warning": "#fab219",
    "serious": "#ec835a",
    "critical": "#d03b3b",
}

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&family=Inter:wght@400;500;600&display=swap');
:root {
  --bg: %(bg)s; --surface-1: %(surface_1)s; --surface-2: %(surface_2)s; --border: %(border)s;
  --violet: %(violet)s; --violet-soft: %(violet_soft)s; --blue: %(blue)s;
  --text-primary: %(text_primary)s; --text-secondary: %(text_secondary)s; --text-muted: %(text_muted)s;
  --good: %(good)s; --warning: %(warning)s; --serious: %(serious)s; --critical: %(critical)s;
  --glow: 0 0 0 1px rgba(139,92,246,.30), 0 0 22px rgba(139,92,246,.14);
  --glow-blue: 0 0 0 1px rgba(59,130,246,.35), 0 0 22px rgba(59,130,246,.14);
  --radius: 14px;
  --font-display: 'Rajdhani', 'Segoe UI', system-ui, sans-serif;
  --font-body: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif;
}
html, body, [data-testid="stAppViewContainer"] { background: var(--bg); color: var(--text-primary); }
[data-testid="stAppViewContainer"] {
  background:
    radial-gradient(1200px 600px at 85%% -10%%, rgba(139,92,246,.10), transparent 60%%),
    radial-gradient(900px 500px at -10%% 110%%, rgba(59,130,246,.08), transparent 60%%),
    radial-gradient(rgba(167,139,250,.10) 1px, transparent 1.2px) 0 0 / 46px 46px,
    var(--bg);
  background-attachment: fixed;
}
body, p, li, label, input, textarea, [data-testid="stMarkdownContainer"] { font-family: var(--font-body); }
h1, h2, h3, h4, .sl-display { font-family: var(--font-display) !important; letter-spacing: .04em; }
h1 { font-weight: 700 !important; }
[data-testid="stHeader"] { background: rgba(10,10,15,.75); backdrop-filter: blur(6px); }
[data-testid="stSidebar"] { background: linear-gradient(180deg, #101019 0%%, #0c0c13 100%%); border-right: 1px solid var(--border); }
[data-testid="stSidebarNav"] a span:not([data-testid="stIconMaterial"]) { font-family: var(--font-display); font-size: 1.02rem; letter-spacing: .03em; }
.sl-kicker { color: var(--violet-soft); font-size: .72rem; letter-spacing: .2em; text-transform: uppercase; font-family: var(--font-display); }
.block-container { padding-top: 3.2rem; padding-bottom: 4rem; max-width: 1320px; }
a { color: var(--violet-soft); }
:focus-visible { outline: 2px solid var(--violet-soft) !important; outline-offset: 2px; }

/* Streamlit widgets */
[data-testid="stForm"], [data-testid="stExpander"] details, div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div[data-testid="stVerticalBlock"]) {
  border-color: var(--border) !important; border-radius: var(--radius) !important;
}
[data-testid="stForm"] { background: rgba(20,20,28,.72); box-shadow: var(--glow); }
[data-testid="stExpander"] details { background: rgba(20,20,28,.6); }
[data-testid="stExpander"] summary p { font-family: var(--font-display); font-size: 1.05rem; letter-spacing: .03em; }
.stButton > button, .stFormSubmitButton > button, .stDownloadButton > button {
  border-radius: 10px; border: 1px solid rgba(139,92,246,.55); background: rgba(139,92,246,.10);
  color: var(--text-primary); font-weight: 600; transition: box-shadow .15s ease, background .15s ease; min-height: 2.6rem;
}
.stButton > button:hover, .stFormSubmitButton > button:hover, .stDownloadButton > button:hover {
  box-shadow: var(--glow); background: rgba(139,92,246,.20); border-color: var(--violet-soft);
}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
  background: linear-gradient(90deg, #7c3aed, #4f46e5 60%%, #2563eb); border: none;
}
[data-testid="stMetric"] { background: var(--surface-1); border: 1px solid var(--border); border-radius: var(--radius); padding: .8rem 1rem; }
[data-testid="stMetricLabel"] p { color: var(--text-secondary) !important; font-size: .82rem; text-transform: uppercase; letter-spacing: .08em; }
[data-testid="stMetricValue"] { font-family: var(--font-display); }
[data-testid="stTabs"] button p { font-family: var(--font-display); font-size: 1.02rem; letter-spacing: .03em; }
[data-testid="stDataFrame"] { border: 1px solid var(--border); border-radius: 10px; }

/* ----- SYSTEM components ----- */
.sl-statusbar { display: flex; flex-wrap: wrap; align-items: center; gap: .6rem 1.1rem; padding: .7rem 1rem;
  background: linear-gradient(90deg, rgba(20,20,28,.95), rgba(27,27,39,.92)); border: 1px solid var(--border);
  border-radius: var(--radius); box-shadow: var(--glow); margin-bottom: 1.2rem; }
.sl-statusbar .sl-title { font-family: var(--font-display); font-weight: 700; letter-spacing: .08em; font-size: 1.05rem;
  color: var(--text-primary); text-transform: uppercase; flex: 1 1 260px; }
.sl-statusbar .sl-title small { display: block; color: var(--violet-soft); font-size: .72rem; letter-spacing: .22em; }
.sl-chip { display: inline-flex; align-items: center; gap: .35rem; padding: .25rem .65rem; border-radius: 999px;
  background: var(--surface-2); border: 1px solid var(--border); font-size: .86rem; color: var(--text-secondary); white-space: nowrap; }
.sl-chip b { color: var(--text-primary); font-family: var(--font-display); font-size: 1rem; }
.sl-rank { display: inline-grid; place-items: center; min-width: 2.2rem; height: 2.2rem; padding: 0 .45rem; border-radius: 10px;
  font-family: var(--font-display); font-weight: 700; font-size: 1.15rem; color: #fff;
  background: linear-gradient(135deg, #7c3aed, #2563eb); box-shadow: var(--glow); }
.sl-xpbar { flex: 1 1 200px; min-width: 160px; }
.sl-xpbar .sl-xpbar-label { display: flex; justify-content: space-between; font-size: .78rem; color: var(--text-secondary); margin-bottom: .2rem; }
.sl-track { height: 8px; border-radius: 999px; background: #232233; overflow: hidden; }
.sl-fill { height: 100%%; border-radius: 999px; background: linear-gradient(90deg, #8b5cf6, #3b82f6); box-shadow: 0 0 12px rgba(139,92,246,.6); }

.sl-card { background: linear-gradient(180deg, rgba(20,20,28,.92), rgba(16,16,24,.92)); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 1rem 1.1rem; margin-bottom: .9rem; position: relative; }
.sl-card.sl-glow { box-shadow: var(--glow); }
.sl-card.sl-glow-blue { box-shadow: var(--glow-blue); }
.sl-card h4 { margin: 0 0 .45rem 0; font-size: 1.1rem; color: var(--text-primary); }
.sl-card .sl-sub { color: var(--text-secondary); font-size: .88rem; }
.sl-card .sl-kicker { color: var(--violet-soft); font-size: .72rem; letter-spacing: .2em; text-transform: uppercase; font-family: var(--font-display); }

.sl-hero { padding: 1.4rem 1.4rem 1.1rem; border-radius: 18px; border: 1px solid rgba(139,92,246,.45);
  background: radial-gradient(600px 220px at 15%% 0%%, rgba(139,92,246,.22), transparent 70%%),
              radial-gradient(500px 200px at 100%% 100%%, rgba(59,130,246,.18), transparent 70%%), #12121b;
  box-shadow: var(--glow); margin-bottom: 1.1rem; }
.sl-hero .sl-hero-top { display: flex; flex-wrap: wrap; gap: 1rem 1.6rem; align-items: center; }
.sl-hero .sl-big { font-family: var(--font-display); font-size: 3.1rem; line-height: 1; font-weight: 700; color: #fff; }
.sl-hero .sl-label { color: var(--text-secondary); font-size: .78rem; letter-spacing: .16em; text-transform: uppercase; }
.sl-hero .sl-msg { font-family: var(--font-display); color: var(--violet-soft); letter-spacing: .12em; text-transform: uppercase; font-size: .9rem; margin-bottom: .6rem; }

.sl-stat-grid { display: grid; gap: .75rem; grid-template-columns: repeat(var(--cols, 4), minmax(0, 1fr)); margin: 0 0 1rem; }
.sl-stat { background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px; padding: .75rem .9rem; height: 100%%; }
.sl-stat .sl-stat-label { color: var(--text-secondary); font-size: .74rem; letter-spacing: .1em; text-transform: uppercase; }
.sl-stat .sl-stat-value { font-family: var(--font-display); font-size: 1.75rem; font-weight: 700; color: var(--text-primary); line-height: 1.15; }
.sl-stat .sl-stat-sub { color: var(--text-muted); font-size: .8rem; }

.sl-badge { display: inline-block; padding: .1rem .5rem; border-radius: 6px; font-size: .74rem; font-weight: 600; letter-spacing: .03em;
  border: 1px solid var(--border); background: var(--surface-2); color: var(--text-secondary); margin-right: .25rem; white-space: nowrap; }
.sl-badge.violet { border-color: rgba(139,92,246,.6); color: #d6ccff; background: rgba(139,92,246,.14); }
.sl-badge.blue { border-color: rgba(59,130,246,.6); color: #cfe0ff; background: rgba(59,130,246,.14); }
.sl-badge.good { border-color: rgba(12,163,12,.6); color: #b9f0b9; background: rgba(12,163,12,.14); }
.sl-badge.warning { border-color: rgba(250,178,25,.6); color: #ffe3a6; background: rgba(250,178,25,.12); }
.sl-badge.critical { border-color: rgba(208,59,59,.7); color: #ffc4c4; background: rgba(208,59,59,.14); }
.sl-badge.muted { color: var(--text-muted); }

.sl-quest { display: flex; gap: .7rem; align-items: center; padding: .55rem .2rem; border-bottom: 1px solid rgba(42,40,64,.7); }
.sl-quest:last-child { border-bottom: none; }
.sl-quest .sl-q-icon { width: 1.6rem; height: 1.6rem; border-radius: 8px; display: grid; place-items: center; font-size: .9rem;
  border: 1px solid var(--border); background: var(--surface-2); flex: 0 0 auto; }
.sl-quest.done .sl-q-icon { border-color: rgba(12,163,12,.7); background: rgba(12,163,12,.16); }
.sl-quest.na { opacity: .55; }
.sl-quest .sl-q-body { flex: 1 1 auto; min-width: 0; }
.sl-quest .sl-q-title { font-family: var(--font-display); font-size: 1.02rem; letter-spacing: .03em; color: var(--text-primary); }
.sl-quest .sl-q-detail { font-size: .8rem; color: var(--text-secondary); }

.sl-seg { display: flex; height: 10px; border-radius: 999px; overflow: hidden; background: #232233; gap: 2px; }
.sl-seg span { display: block; height: 100%%; }
.sl-progress-row { margin: .45rem 0 .8rem; }
.sl-progress-row .sl-pr-head { display: flex; justify-content: space-between; gap: .5rem; font-size: .86rem; color: var(--text-secondary); margin-bottom: .25rem; }
.sl-progress-row .sl-pr-head b { color: var(--text-primary); font-weight: 600; }
.sl-legend { display: flex; flex-wrap: wrap; gap: .4rem 1rem; font-size: .8rem; color: var(--text-secondary); margin: .2rem 0 .6rem; }
.sl-legend i { display: inline-block; width: .8rem; height: .8rem; border-radius: 3px; margin-right: .35rem; vertical-align: -1px; }

.sl-rev { display: flex; flex-wrap: wrap; gap: .3rem; }
.sl-empty { text-align: center; padding: 1.4rem 1rem; color: var(--text-secondary); border: 1px dashed var(--border); border-radius: var(--radius); }
.sl-empty .sl-empty-title { font-family: var(--font-display); color: var(--text-primary); font-size: 1.1rem; letter-spacing: .05em; }
.sl-note { font-size: .82rem; color: var(--text-muted); }
.sl-pyq { border-left: 3px solid var(--violet); padding: .4rem .8rem; margin: .5rem 0; background: rgba(139,92,246,.06); border-radius: 0 10px 10px 0; }
.sl-ai { border-left: 3px solid var(--warning); padding: .4rem .8rem; margin: .5rem 0; background: rgba(250,178,25,.06); border-radius: 0 10px 10px 0; }

/* Level-up / quest-complete overlay */
.sl-levelup { position: fixed; inset: 0; display: grid; place-items: center; pointer-events: none; z-index: 999999;
  animation: sl-fade 3.2s ease forwards; }
.sl-levelup .sl-lu-box { padding: 1.6rem 2.4rem; border-radius: 18px; text-align: center; background: rgba(10,10,15,.92);
  border: 1px solid var(--violet-soft); box-shadow: 0 0 0 1px rgba(167,139,250,.5), 0 0 60px rgba(139,92,246,.55);
  animation: sl-pop .6s cubic-bezier(.2,1.4,.4,1); }
.sl-levelup .sl-lu-kicker { font-family: var(--font-display); letter-spacing: .3em; color: var(--violet-soft); font-size: .85rem; }
.sl-levelup .sl-lu-title { font-family: var(--font-display); font-size: 2.6rem; font-weight: 700; color: #fff; letter-spacing: .12em; }
.sl-levelup .sl-lu-sub { color: var(--text-secondary); }
@keyframes sl-pop { from { transform: scale(.7); opacity: 0; } to { transform: scale(1); opacity: 1; } }
@keyframes sl-fade { 0%%, 80%% { opacity: 1; } 100%% { opacity: 0; visibility: hidden; } }
.sl-pulse { animation: sl-pulse 2.4s ease-in-out 2; }
@keyframes sl-pulse { 0%%,100%% { box-shadow: var(--glow); } 50%% { box-shadow: 0 0 0 1px rgba(167,139,250,.6), 0 0 34px rgba(139,92,246,.45); } }
@media (prefers-reduced-motion: reduce) {
  .sl-levelup, .sl-levelup .sl-lu-box, .sl-pulse { animation: none !important; }
  .sl-levelup { display: none; }
}

/* ----- Responsive ----- */
@media (max-width: 1100px) {
  .sl-stat-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 900px) {
  .block-container { padding-left: 1rem; padding-right: 1rem; padding-top: 3rem; }
  .sl-hero .sl-big { font-size: 2.4rem; }
}
@media (max-width: 640px) {
  .block-container { padding-left: .75rem; padding-right: .75rem; }
  .sl-statusbar { padding: .6rem .7rem; gap: .45rem .6rem; }
  .sl-statusbar .sl-title { flex-basis: 100%%; font-size: .95rem; }
  .sl-chip { font-size: .78rem; padding: .2rem .5rem; }
  .sl-hero { padding: 1rem; }
  .sl-hero .sl-big { font-size: 2rem; }
  .sl-stat .sl-stat-value { font-size: 1.4rem; }
  h1 { font-size: 1.7rem !important; }
  [data-testid="stMetricValue"] { font-size: 1.4rem; }
}
</style>
"""


def inject_theme() -> None:
    st.markdown(_CSS % TOKENS, unsafe_allow_html=True)
