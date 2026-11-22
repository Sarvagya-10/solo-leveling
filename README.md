# Shogun : Phase 3 - Solo Leveling

A GATE **DA 2027** preparation and daily-execution "System", built with Streamlit,
SQLite/SQLAlchemy, Alembic and Plotly. Optional AI features use **Groq Cloud** and
**SerpAPI (DuckDuckGo engine)**. Every deterministic feature works without any API key.

> Dark, violet/royal-blue "System" interface · responsive (desktop sidebar, compact
> mobile navigation) · all data stays in a local SQLite file you control.

---

## Contents

1. [Features](#features)
2. [Quick start](#quick-start)
3. [Configuration](#configuration)
4. [Architecture](#architecture)
5. [Rules the System follows](#rules-the-system-follows)
6. [Commands](#commands)
7. [Backups, export & restore](#backups-export--restore)
8. [Deployment](#deployment)
9. [Troubleshooting](#troubleshooting)

---

## Features

| Section | What it does |
|---|---|
| **Status Window** (dashboard) | Level, rank, XP, streak, today's quests, GATE readiness, revisions due, attention, habits, not-to-do (privacy-aware), finance/research, execution trend, quick-entry forms |
| **DA Syllabus Tracker** | The complete official GATE 2027 DA syllabus — 7 sections, 119 topics — in filterable, collapsible per-section tables: coverage, PYQ mastery (attempts, accuracy, target), R1–R4, status, notes, timestamps, audited manual overrides |
| **Daily GATE Log** | Pick topics, minutes, PYQs attempted/correct, mastery status → progress updates and revisions are scheduled at **+1, +3, +7, +21 days** |
| **Revision Queue** | *To Revise Today*, overdue queue, 30-day calendar, explicit completion (with confirmation), undo |
| **General Aptitude** | Official GA syllabus (Verbal, Quantitative, Analytical, Spatial — 36 topics), daily GA entry, per-category PYQ accuracy |
| **Revision Cards** | Idea, formulae, question types & recognition patterns, traps, observations, connected DA topics, up to 3 **verified** PYQs, separately labelled AI practice; edit, bookmark, regenerate, version history, review status |
| **Question Bank & PYQs** | Bundled official GATE DA 2024–2026 PYQs (answers from official keys), add PYQs with provenance, verify/reject, practice, SerpAPI source search, AI extraction from web pages and PDFs (always unverified), AI practice generation, JSON import |
| **Weekend Full War** | Timed 180-min paper on the official 65 Q / 100 marks structure, built **only** from topics you have covered; palette, navigation, mark-for-review, clear, autosave, timer, submit confirmation, refresh-safe; post-exam analysis |
| **Attention Span** | Multiple deep-focus sessions per day; longest session vs total deep work; 7-day rolling average; personal best; progress to 200 min |
| **Finance / Research** | Independent one-hour logs (direction, next steps, projects, tags; research adds milestones, outputs, references), history, search, trends |
| **Daily Habits** | 8 default habits (water in litres), configurable targets, done / not done / missing |
| **Not-To-Do** | 7 private rules; complied / violated / missing; streaks; never sent to AI |
| **Adapt** | Three mandatory reflection prompts, searchable history, optional AI suggestion |
| **Execution Analytics** | Separate charts for study targets, habits, not-to-do, overall efficiency (with missing-data markers), cumulative syllabus coverage, section progress, PYQ mastery, CSV download |
| **XP · Rank · Badges** | Fixed XP rules, levels, ranks E→S→National Level, quests, streaks, 17 badges |
| **Settings & Data** | Targets, timezone, war eligibility rule, AI provider test/model choice, backups, restore, JSON/CSV export, import, reset |

## Quick start

Requirements: **Python 3.11+**.

```bash
git clone https://github.com/Sarvagya-10/solo-leveling.git
cd solo-leveling
python -m venv .venv
# Windows:  .venv\Scripts\activate     macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Open http://localhost:8501. On first start the app creates `var/shogun.db`, runs the
Alembic migrations and seeds the official syllabus, default habits, not-to-do rules and
badges. Nothing else is needed.

Want to look around with fake data first? Use a **separate** database:

```bash
python scripts/seed_demo.py --db var/demo.db
SHOGUN_DB_PATH=var/demo.db streamlit run app.py        # PowerShell: $env:SHOGUN_DB_PATH="var/demo.db"
```

## Configuration

Copy `.env.example` to `.env` (git-ignored) and fill in what you need:

| Variable | Purpose | Default |
|---|---|---|
| `GROQ_API_KEY` | Groq Cloud key for AI cards / practice / extraction / suggestions | unset → AI features show a configuration message |
| `GROQ_MODEL` | Preferred model id | empty → strongest model available to your key |
| `SERPAPI_API_KEY` | SerpAPI key (DuckDuckGo engine) for source search | unset → search disabled |
| `SHOGUN_DB_PATH` | SQLite database path | `var/shogun.db` |
| `SHOGUN_VAR_DIR` | Backups / exports / logs directory | `var/` |
| `SHOGUN_TIMEZONE` | Initial timezone (changeable in Settings) | `Asia/Kolkata` |
| `SHOGUN_LOG_LEVEL` | Log level | `INFO` |

**Secrets** are read only from the environment or `.env`. They are wrapped so they never
appear in `repr()`, logs (a redacting filter masks `gsk_…` keys, `api_key=` parameters
and registered secret values), exceptions, the UI or the database. Never commit `.env`.

**Model selection.** *Settings → AI provider → Test Groq & discover models* lists the
models your key can currently use (live `/models` call) and explains which one is
selected. The app prefers the strongest model from a known-good list
(`shogun/ai/groq_client.py: PREFERRED_MODELS`) and otherwise ranks by parameter count.
It never assumes a model is permanently available or free; if a configured model
disappears it falls back and tells you.

**SerpAPI test** uses the Account API, which does not consume search credits.

## Architecture

```
app.py                       Streamlit entry: page config, theme, status bar, navigation
shogun/
  config.py                  env/.env config; Secret wrapper
  logging_setup.py           rotating file + console logs with secret redaction
  timeutil.py                naive-UTC instants vs local calendar dates
  syllabus.py                versioned syllabus JSON loader + verbatim/coverage validation
  db/models.py               28 normalized tables, constraints, indexes
  db/session.py              engine (SQLite pragmas), transactional scope, Alembic runner
  services/                  ALL business logic (no Streamlit imports)
    progress_service           derived statuses, eligibility, overrides + audit, coverage timeline
    study_log_service          daily logs → progress + revision scheduling
    revision_service           +1/+3/+7/+21 scheduling, queues, ordered completion, undo
    question_service           question bank, provenance, verification, practice attempts
    scoring                    official GATE marking (exact fractions)
    exam_service               Full War blueprint, eligibility filter, assembly, autosave, scoring, analysis
    card_service               revision cards, versions, AI drafts
    attention/worklog/habit/avoidance/reflection_service
    analytics_service          execution metrics with explicit definitions
    gamification_service       derived XP ledger, levels, ranks, quests, streaks, badges
    backup_service             backups, restore, JSON/CSV export, import, reset
    seed / settings_service / defaults
  ai/
    groq_client.py             Groq REST client, retries, JSON + Pydantic validation, model ranking
    search_client.py           SerpAPI DuckDuckGo client, safe page fetching
    schemas.py                 structured-output schemas
    workflows.py               cached AI workflows + hallucination guard
  ui/
    theme.py / components.py / charts.py   design system
    context.py                 bootstrap (migrate + seed) and the action() write helper
    pages/*.py                 one module per section
data/syllabus/               official PDFs (checksums pinned) + versioned JSON
migrations/                  Alembic
scripts/seed_demo.py         demo database generator
tests/                       unit · integration · ui (AppTest)
```

**Data flow for writes.** Every UI form calls `ui.context.action()`, which runs the
service call in its own transaction, commits, re-derives XP/badges for the affected
days, queues a toast and reruns the page — so charts update immediately and survive
restarts. Expected errors (validation, conflicts, AI unavailable) are shown inline;
unexpected ones roll back, are logged (redacted) and shown generically.

**Time.** Instants are stored as naive UTC; calendar days as local dates in the
configured timezone. Scheduling is pure date arithmetic, so it is deterministic and
unaffected by DST.

## Rules the System follows

* **Syllabus integrity.** `data/syllabus/gate_da_2027.v1.json` and `gate_ga_2027.v1.json`
  hold the verbatim official text. Loading fails if any topic phrase is not a verbatim
  substring of the official text, or if any official content word is not covered by a
  topic — so nothing is invented or omitted. PDF checksums are pinned and tested.
* **Revisions.** One active R1–R4 cycle per topic (no duplicates); due dates fixed at
  scheduling; completed only by explicit confirmation, never before due, in stage order;
  overdue items stay visible.
* **PYQ mastery.** Correct PYQs ≥ target (default 10, global and per-topic); attempts and
  accuracy tracked; overrides need a reason and are audited.
* **Real PYQs are never fabricated.** The bundled bank (GATE DA 2024–2026) was built from the
  official master papers and official answer keys found via SerpAPI/DuckDuckGo search; answers
  come only from the official keys and Claude-written explanations are labelled as such (see
  `data/pyq/README.md`). Questions you add need year, question reference and source, and count as
  verified only after *you* verify them.
  AI output is always labelled and starts unverified. AI extraction from web pages is
  rejected unless the question appears verbatim in the page text.
* **Weekend Full War.** Official structure from gate2027.iitm.ac.in: 65 questions
  (GA 5×1 + 5×2 = 15 marks; DA 25×1 + 30×2 = 85 marks), 180 minutes; wrong MCQ −1/3
  (1-mark) / −2/3 (2-mark); MSQ and NAT have no negative marking and no partial credit.
  Only questions whose *every* tagged topic is war-eligible are used (eligibility rule
  configurable: coverage mastered, or coverage + PYQ target). Re-checked when the paper
  is created. If the bank is short, the shortfall is disclosed and you may take a shorter
  paper (time scaled to marks) or opt into labelled AI questions. Assembly is seeded and
  deterministic. Answers autosave; the timer derives from the stored start time.
* **Missing ≠ failed ≠ done.** Habits and not-to-do items have three states. Unlogged
  items are never counted as completed; they stay in the denominator and are flagged.
* **Gamification is derived and read-only.** XP is recomputed from source data per day
  (unique source keys → no double counting; deleting a log or undoing a revision removes
  its XP). It never modifies academic data.
* **Privacy.** Not-to-do data is never sent to AI, can be hidden on the dashboard, and is
  excluded from CSV exports unless explicitly included.

## Commands

```bash
pip install -r requirements-dev.txt     # test & lint tooling
pytest                                  # all tests (unit, integration, UI smoke)
pytest tests/unit tests/integration     # fast subset
pytest -m ui                            # Streamlit AppTest smoke tests
pytest --cov                            # coverage of shogun/ (UI excluded)
ruff check .                            # lint
mypy                                    # type check (services, db, ai)
alembic upgrade head                    # apply migrations manually (the app does this on start)
alembic revision --autogenerate -m "…"  # create a migration after changing models
python scripts/seed_demo.py --db var/demo.db
```

Tests never need network access or API keys: AI clients are tested with mocked HTTP
transports, and every test uses its own temporary SQLite database.

## Backups, export & restore

*Settings & Data → Data & backups*:

* **Create backup now** — consistent copy via SQLite's online backup API into
  `var/backups/shogun-<timestamp>-<label>.db`. Copy these off the machine regularly.
* **Restore** — type `RESTORE`; a `pre-restore` safety backup is taken first, then
  migrations, seed and XP are re-applied.
* **Export** — JSON (complete, re-importable; topics referenced by official code) or a
  CSV zip. Private not-to-do data is excluded unless you tick the box.
* **Import** — type `IMPORT`; a `pre-import` backup is taken, then all data is replaced.
* **Reset** — tick the acknowledgement and type `RESET`; a `pre-reset` backup is taken
  first.

You can also back up by copying `var/shogun.db` while the app is stopped.

## Deployment

The app is single-user by design (one SQLite file).

* **Local / home server:** `streamlit run app.py --server.port 8501 --server.address 0.0.0.0`.
  Put it behind a reverse proxy with authentication if it is reachable from a network —
  the app itself has no login.
* **Streamlit Community Cloud:** works, but its filesystem is ephemeral; data will be lost
  on restarts unless you export/import regularly. Add keys under *Secrets* as
  environment variables (`GROQ_API_KEY`, `SERPAPI_API_KEY`, `GROQ_MODEL`).
* **Docker (example):**
  ```dockerfile
  FROM python:3.11-slim
  WORKDIR /app
  COPY requirements.txt .
  RUN pip install --no-cache-dir -r requirements.txt
  COPY . .
  VOLUME /app/var
  EXPOSE 8501
  CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.headless=true"]
  ```
  Mount a volume on `/app/var` so the database and backups persist.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Groq is not configured" / "SerpAPI is not configured" | Add the key to `.env`, then *Settings → AI provider → Reload configuration* (or restart). |
| "Groq rejected the API key (401/403)" | Key revoked or mistyped; create a new key at console.groq.com. |
| "Configured model … is not available" | Use *Test Groq & discover models* and pick an available model, or clear `GROQ_MODEL`. |
| Rate limit messages | Free tiers are rate limited; wait and retry. Responses are cached, so repeats are free. |
| "Today" looks wrong | Set your timezone in *Settings → Targets & preferences*. |
| Weekend Full War says the bank is short | Only verified questions from topics you have *mastered* are used. Master more topics, add/verify PYQs, take a shorter paper or add labelled AI questions. |
| `database is locked` | Close other programs using `var/shogun.db` (e.g. DB browsers). |
| Something broke after an update | `alembic upgrade head`; check `var/logs/shogun.log`; restore a backup if needed. |
| Want a clean slate | *Settings → Data → Reset* (backup is automatic). |

Logs: `var/logs/shogun.log` (rotating, secrets redacted).

---

Syllabus sources: [GATE 2027 syllabus page](https://gate2027.iitm.ac.in/exam_papers_and_syllabus) ·
[exam pattern](https://gate2027.iitm.ac.in/question_paper_pattern). The official PDFs are in
`data/syllabus/source/`.
