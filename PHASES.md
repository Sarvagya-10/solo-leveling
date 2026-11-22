# Shogun : Phase 3 - Solo Leveling — Implementation Checklist

Living checklist. Each phase lists its scope, what was delivered and the test results that
were **actually run** (see the test log at the bottom).

## Phase 0 — Inspection & plan ✅

* Workspace contained only the user-supplied official `DA_GATE2027_Syllabus (1).pdf`; it was not
  a git repository. Remote `https://github.com/Sarvagya-10/solo-leveling` existed with **no
  branches**, so there was no prior work to preserve. The original PDF is left untouched in place
  (git-ignored); a byte-identical copy (sha256 `2e9fed7a…`) is versioned in `data/syllabus/source/`.
* The DA PDF contains only the DA syllabus. The official **GA** syllabus was downloaded from
  `gate2027.iitm.ac.in/static/doc/GATE2027_Syllabus/GA_GATE2027_Syllabus.pdf` (sha256 `3708769a…`).
* Official exam pattern verified at `gate2027.iitm.ac.in/question_paper_pattern`: 65 questions
  (10 GA + 55 subject); DA = GA 15 + subject 85 = 100 marks; 180 minutes; MCQ/MSQ/NAT; 1- or
  2-mark questions; −1/3 and −2/3 for wrong 1-/2-mark MCQs; no negative marking for MSQ/NAT;
  no partial marking in MSQ. The only split satisfying both counts and marks is
  GA 5×1 + 5×2 and DA 25×1 + 30×2.
* Environment: Python 3.11.9, git 2.49, Node 24 (palette validator), no `gh`. Project venv `.venv`.

## Phase 1 — Scaffold ✅

* [x] Pinned dependencies, `pyproject.toml` (pytest, ruff, mypy, coverage)
* [x] Config with `Secret` wrapper, `.env.example`, `.gitignore`, `.gitattributes`, redacting logger
* [x] 28 normalized tables with check/unique constraints and indexes; Alembic migration `0001`
* [x] Official syllabus JSON: DA 7 sections / 119 topics, GA 4 sections / 36 topics; loader rejects
      any non-verbatim phrase or any uncovered official word; PDF checksums pinned
* [x] Idempotent seed (syllabus, 8 habits, 7 not-to-do rules, 17 badges, settings)
* [x] Design system (`shogun/ui/theme.py`, `components.py`, `charts.py`)

## Phase 2 — Dashboard, syllabus, daily log, aptitude, revisions ✅

* [x] Status Window with hero, quests, readiness, revisions, attention, habits, privacy-aware
      not-to-do, finance/research, execution trend, quick entry
* [x] DA & GA syllabus trackers: filters, compact mode, collapsible sections, R1–R4 cells,
      topic detail, notes, audited overrides (coverage, PYQ mastery, overall status, PYQ target)
* [x] Daily log → progress (forward-only coverage) → revision cycle (+1/+3/+7/+21), duplicate-free
* [x] Revision queue: today, overdue, 30-day calendar, confirmed completion, ordered stages, undo
* [x] General Aptitude: daily entry, tracker, per-category PYQ accuracy

## Phase 3 — Cards, PYQ sourcing, AI, question bank ✅

* [x] Groq client: live model discovery + ranking, retries/backoff/retry-after, timeouts, JSON mode,
      Pydantic validation with corrective retry, DB cache, typed user-safe errors
* [x] SerpAPI DuckDuckGo search; Account-API connection test (no credit used); safe page fetch
* [x] Revision cards (edit, bookmark, regenerate with versions, review status, connected topics,
      verified PYQs, separately labelled AI practice)
* [x] Question bank: provenance rules, verify/reject, practice attempts, AI extraction with a verbatim
      hallucination guard (always unverified), AI practice generation, JSON import
* [x] Live check with the user's keys (transient env vars only, never written to disk): Groq listed
      11 models, auto-selected `openai/gpt-oss-120b`; a real card generated and validated in 6.3 s;
      SerpAPI account reachable (free plan)

## Phase 4 — Weekend Full War ✅

* [x] Official blueprint; eligibility filter applied to every source; re-checked at creation
* [x] Deterministic seeded assembly with topic diversity; shortfall disclosure; shorter paper
      (time scaled to marks) or opt-in labelled AI questions
* [x] Exam room: timer from stored start, palette (pills), navigation, mark for review, clear,
      autosave on every change, resume after refresh, submit confirmation dialog, auto-submit
* [x] Analysis: score, accuracy, negative marks, time, section/type/marks/topic breakdowns,
      question review, notes; history and trend

## Phase 5 — Attention, finance, research, habits, not-to-do, Adapt, analytics ✅

* [x] Attention: multiple sessions/day, longest vs total, rolling 7-day avg, best, progress to 200
* [x] Finance / Research: independent targets, projects, research fields, search, trends
* [x] Habits: done / not done / missing, numeric water (litres), configurable targets, custom habits
* [x] Not-to-do: complied / violated / missing, streaks, never sent to AI, CSV-export opt-in
* [x] Adapt: three mandatory prompts, search, weekly trend, optional AI suggestion
* [x] Analytics: separate study / habits / not-to-do / overall charts with missing-data markers,
      metric definitions, cumulative coverage, section and PYQ-mastery progress, CSV download

## Phase 6 — Gamification, polish, accessibility ✅

* [x] Derived XP ledger (unique source keys, recomputed per day), levels, ranks, quests, streaks, badges
* [x] Level-up overlay, quest-complete toasts, all-clear overlay (disabled under reduced motion)
* [x] Responsive grid tiles, stacked columns on phones, no page-level horizontal overflow
* [x] Accessibility: AA-contrast text tokens, focus-visible outlines, ARIA labels on custom
      progress/status elements, icon + label (never colour alone), CVD-validated chart palette

## Phase 7 — Testing, integrity, security, docs, clean install ✅

* [x] Unit, integration and UI (AppTest) suites; mocked AI; temp databases; no keys needed
* [x] Responsive inspection with Playwright: 17 pages × 3 viewports (1440 / 820 / 390 px)
* [x] Secret audit of tracked files and full git history
* [x] README (setup, configuration, architecture, rules, commands, backups, deployment, troubleshooting)
* [x] Clean install from a fresh clone + new virtualenv

## Phase 8 — Commit & push ✅

See the final report / git log for the pushed commit.

## Follow-up — official PYQ bank ✅

* Keys written to the local git-ignored `.env` at the user's request (never committed).
* Official sources located with SerpAPI (DuckDuckGo engine): GATE DA 2024 (IISc paper re-hosted by
  IIT Guwahati + IISc final key), 2025 (IIT Roorkee paper + key), 2026 (IIT Guwahati paper + key).
* Answer keys parsed programmatically (`data/pyq/keys/`, checksums pinned); question text transcribed
  from the official papers; answers/types/marks always taken from the official keys.
* **188 verified PYQs** bundled (2024: 61, 2025: 63, 2026: 64; 100 MCQ / 43 MSQ / 45 NAT; 95 topics).
  Excluded: 2024 Q.59 (MTA), and 6 figure-only questions (2024 Q.2, Q.9, Q.53; 2025 Q.4, Q.8; 2026 Q.3).
* Spot-checked against the official PDFs (text layer + rendered pages), including every
  figure-to-text conversion sampled and a cross-year contamination check.
* One debatable official key (2024 Q.14) keeps the official answer with a transparent note.
* Migration 0002 (`questions.explanation_source`); explanations labelled "written by AI — not official".

## Follow-up — GATE CS 2020–2026 PYQs for shared syllabus areas ✅

* Official CS papers and keys for 2020–2026 (11 papers incl. two sets in 2021, 2024, 2025, 2026)
  located via SerpAPI/DuckDuckGo and the official archive on the GATE 2026 (IIT Guwahati) site.
* Scope: General Aptitude, Probability & Statistics, Linear Algebra, Calculus & Optimization and DBMS
  only (no AI / ML / programming / DSA); topics absent from the DA syllabus (transactions, discrete
  maths, integration, three-schema architecture, …) excluded.
* Keys parsed programmatically, except GATE 2021 (image-only keys read visually; all 34 in-scope rows
  re-checked against the key images). Keys with alternative answers ("C OR D") and MTA excluded.
* **194 CS questions** added (Prob & Stats 30, Linear Algebra 20, Calculus 10, DBMS 39, GA 95);
  bank total **382 verified official PYQs**. Cross-bundle duplicates removed deterministically.
* Figure-to-text conversions sampled and visually verified (ER diagrams, dot-tile puzzle, B+ trees).
* Badges show the source paper (e.g. "GATE 2023 CS · Q.27"); cards prefer DA-paper PYQs; Question
  Bank has a source-paper filter. Running servers re-seed automatically when bundles change.

## Test log

| Phase | Command | Result |
|------:|---------|--------|
| 1 | `pytest tests/unit` (syllabus, scheduling, progress) | 39 passed |
| 2–5 | `pytest tests/unit` (+ scoring, exam, life tracking, XP, AI clients) | 93 passed |
| 2–6 | `pytest tests/ui` (every page, empty + populated DB; entrypoint; no-key AI; daily-log form) | 37 passed |
| 7 | `pytest tests/integration` | 15 passed |
| 7 | `pytest` (full suite) | **148 passed** |
| 7 | `pytest --cov` (UI excluded) | 88 % line coverage of `shogun/` |
| 7 | `ruff check .` | no issues |
| 7 | `mypy` | no issues in 35 source files |
| 7 | Playwright layout inspection (51 page/viewport combinations) | 0 horizontal overflow, 0 exceptions |
| 7 | Secret scan (`git grep`, `git log -p --all`) | no real keys tracked or in history |
| 7 | Fresh clone → new venv → `pip install -r requirements-dev.txt` → pytest + ruff + mypy | all passed |
| PYQ | `pytest` (full suite incl. bundled-bank integrity vs official keys) | **163 passed** |
| PYQ | `ruff check .` / `mypy` | no issues |
| CS PYQ | `pytest` (full suite incl. per-bundle key integrity, scope and duplicate checks) | **191 passed** |
| CS PYQ | `ruff check .` / `mypy` | no issues |

Issues found and fixed during testing: a Dec-31 revision expectation in a test, a nested
f-string invalid on Python 3.11, a wrong-row update in the XP reconciler (caught by mypy),
sidebar icon font overridden by theme CSS, chart title/legend overlap, clipped missing-data
markers, and a cramped range selector on tablets (all caught by screenshots).
