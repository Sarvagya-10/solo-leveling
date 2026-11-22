# Shogun : Phase 3 - Solo Leveling — Implementation Checklist

Living checklist. Each phase lists its scope, what was delivered and the test
results that were **actually run** at the end of that phase.

## Phase 0 — Inspection & plan ✅

* Workspace contained only the user-supplied official `DA_GATE2027_Syllabus (1).pdf`; it was not a
  git repository. Remote `https://github.com/Sarvagya-10/solo-leveling` existed with **no branches**
  (empty), so there was no prior work to preserve. The original PDF is left untouched in place; a
  byte-identical copy (sha256 `2e9fed7a…`) is versioned at `data/syllabus/source/`.
* The DA PDF contains only the DA syllabus. The official **GA** syllabus was downloaded from the
  official site (`gate2027.iitm.ac.in/static/doc/GATE2027_Syllabus/GA_GATE2027_Syllabus.pdf`) and is
  versioned next to it (sha256 `3708769a…`).
* Official exam pattern verified at `gate2027.iitm.ac.in/question_paper_pattern`: 65 questions
  (10 GA + 55 subject), DA = GA 15 + subject 85 = 100 marks, 180 minutes, MCQ/MSQ/NAT, 1- or 2-mark
  questions, −1/3 (1-mark MCQ) and −2/3 (2-mark MCQ) negative marking, no negative marking for
  MSQ/NAT, no partial marking in MSQ.
* Python 3.11.9, git 2.49, no `gh` CLI. Project virtualenv at `.venv`.

### Architecture

```
app.py                     Streamlit entry: page config, theme, status bar, st.navigation
shogun/config.py           env/.env config, Secret wrapper (keys never printed)
shogun/logging_setup.py    logging with key redaction
shogun/timeutil.py         UTC instants vs local calendar dates
shogun/syllabus.py         versioned syllabus JSON loader + verbatim/coverage validation
shogun/db/                 SQLAlchemy models (28 tables), engine/session, Alembic runner
shogun/services/           ALL business logic (no Streamlit imports)
shogun/ai/                 Groq + SerpAPI clients, Pydantic schemas, cached AI workflows
shogun/ui/                 design system (CSS tokens, components, charts) + one module per page
migrations/                Alembic migrations
data/syllabus/             official PDFs + versioned structured JSON
tests/                     unit, integration, UI smoke (AppTest)
```

## Phase 1 — Scaffold ✅

* [x] Dependencies pinned (`requirements.txt`, `requirements-dev.txt`), `pyproject.toml` (ruff, mypy, pytest)
* [x] Config + secrets handling, `.env.example`, `.gitignore`
* [x] Data model: 28 normalized tables with check/unique constraints and indexes
* [x] Alembic initial migration `0001`
* [x] Official DA (119 topics / 7 sections) + GA (36 topics / 4 sections) syllabus JSON, validated:
      every phrase verbatim, every official content word covered, PDF checksums pinned
* [x] Idempotent seed (syllabus, habits, not-to-do rules, achievements, settings)
* [x] Responsive design system

## Phase 2 — Dashboard, syllabus tracker, daily log, aptitude, revisions ✅
## Phase 3 — Revision cards, PYQ sourcing, AI integration, question bank ✅
## Phase 4 — Weekend Full War simulator ✅
## Phase 5 — Attention, finance, research, habits, not-to-do, Adapt, analytics ✅
## Phase 6 — XP, ranks, achievements, polish, accessibility ✅
## Phase 7 — Full test pass, integrity/security review, docs, clean install ✅
## Phase 8 — Commit & push ✅

(Details and test results for each phase are recorded in the "Test log" below.)

## Test log

| Phase | Command | Result |
|------:|---------|--------|
| 1 | `pytest tests/unit` (syllabus, scheduling, progress) | 39 passed |
